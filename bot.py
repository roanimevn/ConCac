"""Discord bot thông báo lịch thi đấu (embed, đúng giờ).

Chạy:  python bot.py
"""
import asyncio
import logging
import math
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

import config
from config import LEAGUE_BY_KEY, LEAGUES, League
from db import Database
from embeds import PROVIDER_LABEL, grouped_embeds, notification_embed, tz_label
from models import Event
from providers import fetch_league

log = logging.getLogger("sportsbot")
UTC = timezone.utc
MAX_SLEEP = 30.0  # tối đa ngủ 30s giữa 2 lần kiểm tra -> độ trễ thông báo << 30s


def utcnow() -> datetime:
    return datetime.now(UTC)


def build_presence() -> tuple[discord.Status, Optional[discord.BaseActivity]]:
    """Chấm trạng thái ở avatar + dòng hoạt động hiển thị dưới tên bot."""
    statuses = {
        "online": discord.Status.online,
        "idle": discord.Status.idle,          # 🌙 Chờ
        "dnd": discord.Status.dnd,
        "invisible": discord.Status.invisible,
    }
    status = statuses.get(config.BOT_STATUS, discord.Status.online)
    name, detail = config.BOT_ACTIVITY, config.BOT_ACTIVITY_DETAIL
    if not name and not detail:
        return status, None

    if config.BOT_ACTIVITY_TYPE == "custom":
        # Bot không gắn được emoji cho custom status -> gộp chữ vào 1 dòng (Discord sẽ tự thêm 🤔).
        text = " · ".join(x for x in (name, detail) if x)
        return status, discord.CustomActivity(name=text)

    kinds = {
        "playing": discord.ActivityType.playing,
        "watching": discord.ActivityType.watching,
        "listening": discord.ActivityType.listening,
        "competing": discord.ActivityType.competing,
    }
    kind = kinds.get(config.BOT_ACTIVITY_TYPE, discord.ActivityType.playing)
    kwargs = {"type": kind, "name": name or detail}
    if name and detail:
        kwargs["state"] = detail  # dòng phụ trong hồ sơ bot
    return status, discord.Activity(**kwargs)


LEAGUE_CHOICES = [
    app_commands.Choice(name=f"{lg.emoji} {lg.name}", value=lg.key) for lg in LEAGUES
]
LEAGUE_CHOICES_WITH_ALL = [app_commands.Choice(name="Tất cả các giải", value="all")] + LEAGUE_CHOICES


# =========================================================================== #
# Bot
# =========================================================================== #
class SportsBot(commands.Bot):
    def __init__(self) -> None:
        status, activity = build_presence()
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=discord.Intents.default(),
            help_command=None,
            status=status,
            activity=activity,
        )
        self.db = Database(config.DB_PATH)
        self.http_session: Optional[aiohttp.ClientSession] = None
        self.events_cache: dict[str, list[Event]] = {}
        self.refresh_status: dict[str, tuple[int, Optional[str]]] = {}
        self.last_refresh: Optional[datetime] = None
        self.boot_ts = time.time()
        self._bg: list[asyncio.Task] = []

    # ---- vòng đời ----------------------------------------------------------
    async def setup_hook(self) -> None:
        await self.db.init()
        self.http_session = aiohttp.ClientSession(
            headers={"User-Agent": "DiscordSportsBot/1.0 (+schedule notifier)"}
        )
        await self.add_cog(SportsCog(self))

        if config.DEV_GUILD_ID:
            guild = discord.Object(id=config.DEV_GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

        await self.refresh_all()
        self._bg = [
            asyncio.create_task(self.scheduler_loop(), name="scheduler"),
            asyncio.create_task(self.refresh_loop(), name="refresh"),
        ]
        if config.SELF_PING_URL:
            self._bg.append(asyncio.create_task(self.self_ping_loop(), name="self-ping"))

    async def close(self) -> None:
        for task in self._bg:
            task.cancel()
        if self.http_session:
            await self.http_session.close()
        await self.db.close()
        await super().close()

    async def on_ready(self) -> None:
        log.info("Đã đăng nhập: %s (%d server)", self.user, len(self.guilds))

    async def on_guild_remove(self, guild: discord.Guild) -> None:
        await self.db.delete_guild(guild.id)

    # ---- trạng thái cho /health (Flask) -----------------------------------
    def health(self) -> dict:
        ready = self.is_ready() and not self.is_closed()
        latency = self.latency if ready else float("nan")
        return {
            "ok": ready,
            "ready": ready,
            "latency_ms": round(latency * 1000) if math.isfinite(latency) else None,
            "guilds": len(self.guilds),
            "events_cached": sum(len(v) for v in self.events_cache.values()),
            "last_refresh": self.last_refresh.isoformat() if self.last_refresh else None,
            "uptime_s": int(time.time() - self.boot_ts),
        }

    async def self_ping_loop(self) -> None:
        """Gọi /health qua URL công khai để Render thấy có 'inbound traffic' và không cho ngủ."""
        url = config.SELF_PING_URL.rstrip("/") + "/health"
        log.info("Self-ping bật: %s mỗi %d phút", url, config.SELF_PING_MINUTES)
        while True:
            await asyncio.sleep(config.SELF_PING_MINUTES * 60)
            try:
                async with self.http_session.get(
                    url, timeout=aiohttp.ClientTimeout(total=20)
                ) as resp:
                    log.debug("self-ping -> HTTP %s", resp.status)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("self-ping lỗi: %s", exc)

    # ---- nạp cấu hình từ biến môi trường ----------------------------------
    async def seed_from_env(self) -> None:
        """Khi filesystem bị xoá (Render Free), dựng lại cấu hình từ CHANNEL_ID/ROLE_ID/SEED_LEAGUES.

        Chỉ nạp khi DB chưa có cấu hình cho server đó, nên không đè lên /setup của bạn
        nếu có dùng ổ đĩa bền.
        """
        if not config.CHANNEL_ID:
            return
        try:
            channel = await self.fetch_channel(config.CHANNEL_ID)
        except discord.HTTPException as exc:
            log.error("CHANNEL_ID=%s không truy cập được (%s). Kiểm tra ID và quyền của bot.",
                      config.CHANNEL_ID, exc)
            return
        guild = getattr(channel, "guild", None)
        if guild is None:
            log.error("CHANNEL_ID phải là một kênh văn bản trong server.")
            return

        gid = guild.id
        if await self.db.get_guild(gid):
            log.info("Server %s đã có cấu hình trong DB – bỏ qua CHANNEL_ID.", gid)
            return

        raw = [x.strip().lower() for x in config.SEED_LEAGUES.split(",") if x.strip()]
        if not raw or "all" in raw:
            keys = [lg.key for lg in LEAGUES]
        else:
            keys = [k for k in raw if k in LEAGUE_BY_KEY]
            for bad in (k for k in raw if k not in LEAGUE_BY_KEY):
                log.warning("SEED_LEAGUES: bỏ qua key không hợp lệ %r (hợp lệ: %s)",
                            bad, ", ".join(LEAGUE_BY_KEY))
        await self.db.upsert_guild(gid, config.CHANNEL_ID, config.ROLE_ID, config.SEED_DIGEST)
        await self.db.add_subs(gid, keys)
        log.info("Đã nạp cấu hình từ env cho server %s: kênh %s, %d giải",
                 gid, config.CHANNEL_ID, len(keys))

    # ---- cập nhật lịch từ nguồn -------------------------------------------
    async def refresh_all(self) -> None:
        async def one(league: League) -> None:
            try:
                events = await fetch_league(self.http_session, league, config.DAYS_AHEAD)
                self.events_cache[league.key] = sorted(events, key=lambda e: e.start)
                self.refresh_status[league.key] = (len(events), None)
            except Exception as exc:  # noqa: BLE001 – giữ cache cũ nếu nguồn lỗi
                log.warning("Lỗi cập nhật %s: %s", league.name, exc)
                count = len(self.events_cache.get(league.key, []))
                self.refresh_status[league.key] = (count, f"{type(exc).__name__}: {exc}")

        await asyncio.gather(*(one(lg) for lg in LEAGUES))
        self.last_refresh = utcnow()
        total = sum(len(v) for v in self.events_cache.values())
        log.info("Đã cập nhật lịch: %d sự kiện / %d giải", total, len(LEAGUES))

    async def refresh_loop(self) -> None:
        while True:
            await asyncio.sleep(config.REFRESH_MINUTES * 60)
            try:
                await self.refresh_all()
                await self.db.cleanup(int(time.time()) - 7 * 86400)
            except Exception:  # noqa: BLE001
                log.exception("refresh_loop lỗi")

    # ---- lập lịch thông báo ------------------------------------------------
    def due_notifications(self, now: datetime) -> list[tuple[Event, int]]:
        """Các (sự kiện, số phút báo trước) đang nằm trong cửa sổ [t, t + grace)."""
        grace = timedelta(seconds=config.LATE_GRACE_SECONDS)
        due: list[tuple[Event, int]] = []
        for events in self.events_cache.values():
            for ev in events:
                if not ev.important:
                    continue
                for off in config.NOTIFY_OFFSETS:
                    t = ev.start - timedelta(minutes=off)
                    if t <= now < t + grace:
                        due.append((ev, off))
        due.sort(key=lambda p: (p[0].start, p[0].league_key, -p[1]))
        return due

    def seconds_until_next(self, now: datetime) -> float:
        nxt: Optional[datetime] = None
        for events in self.events_cache.values():
            for ev in events:
                if not ev.important:
                    continue
                for off in config.NOTIFY_OFFSETS:
                    t = ev.start - timedelta(minutes=off)
                    if t > now and (nxt is None or t < nxt):
                        nxt = t
        if nxt is None:
            return MAX_SLEEP
        return min(max((nxt - now).total_seconds(), 0.5), MAX_SLEEP)

    async def scheduler_loop(self) -> None:
        await self.wait_until_ready()
        try:
            await self.seed_from_env()
        except Exception:  # noqa: BLE001
            log.exception("seed_from_env lỗi")
        log.info("Scheduler chạy. Báo trước (phút): %s", config.NOTIFY_OFFSETS)
        while not self.is_closed():
            delay = 10.0
            try:
                now = utcnow()
                await self.process_due(now)
                await self.process_digest(now)
                delay = self.seconds_until_next(utcnow())
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("scheduler lỗi")
            await asyncio.sleep(delay)

    async def process_due(self, now: datetime) -> None:
        due = self.due_notifications(now)
        if not due:
            return
        for guild_cfg in await self.db.all_guilds():
            gid = guild_cfg["guild_id"]
            subs = await self.db.get_subs(gid)
            batch: list[discord.Embed] = []
            for ev, off in due:
                if ev.league_key not in subs:
                    continue
                # Khoá gồm cả giờ bắt đầu: nếu trận bị dời giờ, sẽ được báo lại theo giờ mới.
                key = f"n:{ev.uid}:{ev.ts}:{off}:{gid}"
                if not await self.db.claim(key):
                    continue
                batch.append(
                    notification_embed(ev, LEAGUE_BY_KEY[ev.league_key], off, config.TIMEZONE)
                )
            # Nhiều trận cùng giờ -> gom chung 1 tin nhắn (tối đa 10 embed / tin).
            for i in range(0, len(batch), 10):
                await self.send_to_guild(guild_cfg, batch[i : i + 10], mention=True)

    async def process_digest(self, now: datetime) -> None:
        if config.DAILY_DIGEST_HOUR < 0:
            return
        local = now.astimezone(config.TIMEZONE)
        if local.hour != config.DAILY_DIGEST_HOUR:
            return
        until = now + timedelta(hours=24)
        for guild_cfg in await self.db.all_guilds():
            if not guild_cfg["digest"]:
                continue
            gid = guild_cfg["guild_id"]
            if not await self.db.claim(f"d:{gid}:{local:%Y%m%d}"):
                continue
            subs = await self.db.get_subs(gid)
            groups = self.upcoming(subs, until=until)
            if not groups:
                continue
            embeds = grouped_embeds(
                "📅 Lịch thi đấu 24 giờ tới",
                groups,
                config.TIMEZONE,
                color=0x5865F2,
                description=f"Giờ hiển thị: **{tz_label(config.TIMEZONE, now)}**",
            )
            await self.send_to_guild(guild_cfg, embeds, mention=False)

    # ---- tiện ích ----------------------------------------------------------
    def upcoming(
        self, keys: set[str], *, until: datetime
    ) -> list[tuple[League, list[Event]]]:
        now = utcnow()
        out: list[tuple[League, list[Event]]] = []
        for lg in LEAGUES:
            if lg.key not in keys:
                continue
            evs = [e for e in self.events_cache.get(lg.key, []) if now <= e.start <= until]
            if evs:
                out.append((lg, evs))
        return out

    async def send_to_guild(
        self, guild_cfg: dict, embeds: list[discord.Embed], *, mention: bool
    ) -> bool:
        channel = self.get_channel(guild_cfg["channel_id"])
        if channel is None:
            try:
                channel = await self.fetch_channel(guild_cfg["channel_id"])
            except (discord.NotFound, discord.Forbidden):
                log.warning("Server %s: không truy cập được kênh %s",
                            guild_cfg["guild_id"], guild_cfg["channel_id"])
                return False
        content = None
        if mention and guild_cfg.get("role_id"):
            content = f"<@&{guild_cfg['role_id']}>"
        try:
            await channel.send(
                content=content,
                embeds=embeds,
                allowed_mentions=discord.AllowedMentions(roles=True, everyone=False, users=False),
            )
            return True
        except discord.HTTPException as exc:
            log.warning("Server %s: gửi thất bại (%s)", guild_cfg["guild_id"], exc)
            return False


# =========================================================================== #
# Lệnh slash
# =========================================================================== #
class SportsCog(commands.Cog):
    def __init__(self, bot: SportsBot) -> None:
        self.bot = bot

    async def _keys_for(self, guild_id: Optional[int]) -> set[str]:
        """Giải mà server đang đăng ký; chưa setup thì coi như tất cả."""
        if guild_id is not None and await self.bot.db.get_guild(guild_id):
            return await self.bot.db.get_subs(guild_id)
        return {lg.key for lg in LEAGUES}

    # ---- /setup ------------------------------------------------------------
    @app_commands.command(name="setup", description="Chọn kênh nhận thông báo lịch thi đấu")
    @app_commands.describe(
        channel="Kênh để bot gửi thông báo",
        role="(Tuỳ chọn) Role sẽ được nhắc tên mỗi lần có thông báo",
        digest="Gửi bản tin 'lịch 24 giờ tới' mỗi sáng (mặc định: bật)",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def setup_cmd(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        role: Optional[discord.Role] = None,
        digest: bool = True,
    ) -> None:
        perms = channel.permissions_for(interaction.guild.me)
        missing = [
            label
            for label, ok in (
                ("Xem kênh", perms.view_channel),
                ("Gửi tin nhắn", perms.send_messages),
                ("Nhúng liên kết (Embed Links)", perms.embed_links),
            )
            if not ok
        ]
        if missing:
            await interaction.response.send_message(
                f"❌ Bot thiếu quyền ở {channel.mention}: **{', '.join(missing)}**.", ephemeral=True
            )
            return

        gid = interaction.guild_id
        first_time = await self.bot.db.get_guild(gid) is None
        await self.bot.db.upsert_guild(gid, channel.id, role.id if role else None, digest)
        if first_time:
            await self.bot.db.add_subs(gid, [lg.key for lg in LEAGUES])

        offsets = ", ".join(f"{m} phút" if m else "đúng giờ" for m in config.NOTIFY_OFFSETS)
        await interaction.response.send_message(
            f"✅ Đã thiết lập! Thông báo sẽ gửi tới {channel.mention}"
            + (f", nhắc {role.mention}" if role else "")
            + f".\n⏰ Báo: **{offsets}** trước giờ thi đấu"
            + (f" · 📅 Bản tin lúc **{config.DAILY_DIGEST_HOUR:02d}:00** mỗi ngày" if digest and config.DAILY_DIGEST_HOUR >= 0 else "")
            + "\nDùng `/leagues` để chọn giải, `/testnotify` để thử.",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    # ---- /subscribe, /unsubscribe -----------------------------------------
    async def _change_subs(self, interaction: discord.Interaction, league: str, add: bool) -> None:
        gid = interaction.guild_id
        if not await self.bot.db.get_guild(gid):
            await interaction.response.send_message(
                "⚠️ Hãy chạy `/setup` trước để chọn kênh thông báo.", ephemeral=True
            )
            return
        keys = [lg.key for lg in LEAGUES] if league == "all" else [league]
        if add:
            await self.bot.db.add_subs(gid, keys)
        else:
            await self.bot.db.remove_subs(gid, keys)
        names = "tất cả các giải" if league == "all" else LEAGUE_BY_KEY[league].name
        verb = "Đã bật" if add else "Đã tắt"
        await interaction.response.send_message(f"✅ {verb} thông báo cho **{names}**.", ephemeral=True)

    @app_commands.command(name="subscribe", description="Bật thông báo cho một giải đấu")
    @app_commands.describe(league="Giải đấu")
    @app_commands.choices(league=LEAGUE_CHOICES_WITH_ALL)
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def subscribe(self, interaction: discord.Interaction, league: str) -> None:
        await self._change_subs(interaction, league, add=True)

    @app_commands.command(name="unsubscribe", description="Tắt thông báo cho một giải đấu")
    @app_commands.describe(league="Giải đấu")
    @app_commands.choices(league=LEAGUE_CHOICES_WITH_ALL)
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def unsubscribe(self, interaction: discord.Interaction, league: str) -> None:
        await self._change_subs(interaction, league, add=False)

    # ---- /leagues ----------------------------------------------------------
    @app_commands.command(name="leagues", description="Xem danh sách giải đấu và trạng thái thông báo")
    @app_commands.guild_only()
    async def leagues(self, interaction: discord.Interaction) -> None:
        keys = await self._keys_for(interaction.guild_id)
        configured = await self.bot.db.get_guild(interaction.guild_id) is not None
        lines = []
        for lg in LEAGUES:
            mark = "✅" if lg.key in keys else "⬜"
            n = len(self.bot.events_cache.get(lg.key, []))
            lines.append(f"{mark} {lg.emoji} **{lg.name}** · {n} lịch sắp tới")
        embed = discord.Embed(
            title="Danh sách giải đấu", description="\n".join(lines), color=0x5865F2
        )
        if not configured:
            embed.set_footer(text="Server chưa /setup nên chưa có thông báo tự động.")
        await interaction.response.send_message(embed=embed)

    # ---- /schedule, /today -------------------------------------------------
    @app_commands.command(name="schedule", description="Xem lịch thi đấu sắp tới")
    @app_commands.describe(league="Giải đấu (bỏ trống = các giải đang bật)", days="Số ngày tới (1–14)")
    @app_commands.choices(league=LEAGUE_CHOICES)
    @app_commands.guild_only()
    async def schedule(
        self,
        interaction: discord.Interaction,
        league: Optional[str] = None,
        days: app_commands.Range[int, 1, 14] = 3,
    ) -> None:
        keys = {league} if league else await self._keys_for(interaction.guild_id)
        await self._reply_schedule(interaction, keys, timedelta(days=days), f"📅 Lịch thi đấu {days} ngày tới")

    @app_commands.command(name="today", description="Lịch thi đấu trong 24 giờ tới")
    @app_commands.guild_only()
    async def today(self, interaction: discord.Interaction) -> None:
        keys = await self._keys_for(interaction.guild_id)
        await self._reply_schedule(interaction, keys, timedelta(hours=24), "📅 Lịch thi đấu 24 giờ tới")

    async def _reply_schedule(
        self, interaction: discord.Interaction, keys: set[str], span: timedelta, title: str
    ) -> None:
        now = utcnow()
        groups = self.bot.upcoming(keys, until=now + span)
        if not groups:
            await interaction.response.send_message(
                "Không có trận/phiên nào trong khoảng thời gian này "
                "(hoặc nguồn dữ liệu chưa cập nhật lịch).",
                ephemeral=True,
            )
            return
        embeds = grouped_embeds(
            title,
            groups,
            config.TIMEZONE,
            description=f"Giờ hiển thị: **{tz_label(config.TIMEZONE, now)}**",
        )
        await interaction.response.send_message(embeds=embeds)

    # ---- /testnotify -------------------------------------------------------
    @app_commands.command(name="testnotify", description="Gửi thử một thông báo vào kênh đã cài")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def testnotify(self, interaction: discord.Interaction) -> None:
        guild_cfg = await self.bot.db.get_guild(interaction.guild_id)
        if not guild_cfg:
            await interaction.response.send_message("⚠️ Hãy chạy `/setup` trước.", ephemeral=True)
            return

        subs = await self._keys_for(interaction.guild_id)
        groups = self.bot.upcoming(subs, until=utcnow() + timedelta(days=config.DAYS_AHEAD))
        if groups:
            league, evs = groups[0]
            ev = evs[0]
        else:  # chưa có lịch nào -> dùng dữ liệu mẫu
            league = LEAGUES[0]
            ev = Event("demo", league.key, utcnow() + timedelta(minutes=15),
                       "Arsenal vs Chelsea", "Arsenal", "Chelsea", "Emirates Stadium", "Vòng 12")
        embed = notification_embed(ev, league, config.NOTIFY_OFFSETS[0] if config.NOTIFY_OFFSETS else 0,
                                   config.TIMEZONE)
        embed.set_footer(text="🧪 Thông báo thử nghiệm")
        ok = await self.bot.send_to_guild(guild_cfg, [embed], mention=False)
        await interaction.response.send_message(
            "✅ Đã gửi thử." if ok else "❌ Gửi thất bại – kiểm tra quyền của bot ở kênh đã chọn.",
            ephemeral=True,
        )

    # ---- /status -----------------------------------------------------------
    @app_commands.command(name="status", description="Tình trạng nguồn dữ liệu của bot")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def status(self, interaction: discord.Interaction) -> None:
        lines = []
        for lg in LEAGUES:
            count, err = self.bot.refresh_status.get(lg.key, (0, "chưa cập nhật"))
            src = PROVIDER_LABEL[lg.provider]
            lines.append(
                f"{'❌' if err else '✅'} **{lg.name}** · {count} lịch · {src}"
                + (f"\n　└ `{err[:150]}`" if err else "")
            )
        embed = discord.Embed(title="Tình trạng nguồn dữ liệu", description="\n".join(lines), color=0x5865F2)
        if self.bot.last_refresh:
            embed.add_field(name="Cập nhật lần cuối", value=f"<t:{int(self.bot.last_refresh.timestamp())}:R>")
        embed.add_field(name="Chu kỳ", value=f"mỗi {config.REFRESH_MINUTES} phút", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)


# =========================================================================== #
def _retry_after(exc: discord.HTTPException) -> Optional[int]:
    """Đọc header Retry-After nếu Discord/Cloudflare có gửi (giây)."""
    try:
        value = exc.response.headers.get("Retry-After")
        return min(max(int(float(value)), 30), 3600) if value else None
    except Exception:  # noqa: BLE001
        return None


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    )
    if not config.DISCORD_TOKEN:
        sys.exit("Thiếu DISCORD_TOKEN – hãy tạo file .env (xem env.example).")

    current: dict[str, Optional[SportsBot]] = {"bot": None}

    def health() -> dict:
        bot = current["bot"]
        if bot is None:
            return {"ok": False, "ready": False}
        return bot.health()

    if config.KEEP_ALIVE:
        import keep_alive  # import muộn: chạy local không cần cài Flask

        # Flask luôn chạy -> Render thấy service "sống", không restart liên tục khi chờ đăng nhập lại.
        keep_alive.start(health, config.PORT or 8080)

    wait = config.LOGIN_RETRY_MINUTES * 60
    while True:
        bot = SportsBot()
        current["bot"] = bot
        try:
            bot.run(config.DISCORD_TOKEN, log_handler=None)
            return  # thoát bình thường (Ctrl+C / tắt service)
        except discord.LoginFailure:
            sys.exit("DISCORD_TOKEN sai hoặc đã bị reset – lấy token mới ở Developer Portal → Bot.")
        except discord.HTTPException as exc:
            if exc.status != 429:
                raise
            sleep_for = _retry_after(exc) or wait
            log.error(
                "Discord/Cloudflare đang chặn IP của host này (HTTP 429, lỗi 1015). "
                "Không phải lỗi token. Thử lại sau %d phút.", sleep_for // 60
            )
            time.sleep(sleep_for)
            wait = min(wait * 2, 30 * 60)


if __name__ == "__main__":
    main()
