"""Dựng embed Discord: thông báo từng trận/phiên, bản tin ngày, danh sách lịch."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

import discord

from config import League
from models import Event

WEEKDAYS = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
PROVIDER_LABEL = {
    "espn": "ESPN",
    "tsdb": "TheSportsDB",
    "sportstimes": "f1calendar.com",
}

EMBED_TOTAL_LIMIT = 5500   # giới hạn Discord là 6000 ký tự / embed
FIELD_VALUE_LIMIT = 1000   # giới hạn Discord là 1024 ký tự / field


# --------------------------------------------------------------------------- #
# Định dạng thời gian
# --------------------------------------------------------------------------- #
def tz_label(tz: ZoneInfo, at: datetime) -> str:
    offset = at.astimezone(tz).utcoffset()
    minutes = int(offset.total_seconds() // 60) if offset else 0
    sign = "+" if minutes >= 0 else "-"
    h, m = divmod(abs(minutes), 60)
    return f"UTC{sign}{h}" + (f":{m:02d}" if m else "")


def fmt_full(dt: datetime, tz: ZoneInfo) -> str:
    local = dt.astimezone(tz)
    return f"{WEEKDAYS[local.weekday()]}, {local:%d/%m/%Y} · **{local:%H:%M}**"


def fmt_day(dt: datetime, tz: ZoneInfo) -> str:
    local = dt.astimezone(tz)
    return f"{WEEKDAYS[local.weekday()]} {local:%d/%m}"


# --------------------------------------------------------------------------- #
# Thông báo 1 trận / 1 phiên đua
# --------------------------------------------------------------------------- #
def notification_embed(
    ev: Event, league: League, minutes_before: int, tz: ZoneInfo
) -> discord.Embed:
    if ev.home and ev.away:
        title = f"{league.emoji} {ev.home} vs {ev.away}"
    else:
        title = f"{league.emoji} {ev.title}"

    if minutes_before > 0:
        desc = f"⏳ **Còn {minutes_before} phút nữa** là bắt đầu · <t:{ev.ts}:R>"
    else:
        desc = "🔴 **Bắt đầu ngay bây giờ!**"

    embed = discord.Embed(
        title=title[:256], description=desc, color=league.color, timestamp=ev.start
    )
    embed.set_author(name=league.name, icon_url=ev.logo)
    embed.add_field(
        name=f"⏰ Giờ {tz_label(tz, ev.start)}", value=fmt_full(ev.start, tz), inline=True
    )
    # Thẻ <t:..:F> Discord tự đổi theo múi giờ của từng người xem.
    embed.add_field(name="🌍 Giờ của bạn", value=f"<t:{ev.ts}:F>", inline=True)
    if ev.round:
        embed.add_field(name="🔢 Vòng/Chặng", value=ev.round, inline=True)
    if ev.venue:
        label = "🏟️ Sân" if league.kind == "football" else "📍 Địa điểm"
        embed.add_field(name=label, value=ev.venue, inline=True)
    if ev.logo:
        embed.set_thumbnail(url=ev.logo)
    return embed


# --------------------------------------------------------------------------- #
# Danh sách lịch (bản tin ngày, /schedule, /today)
# --------------------------------------------------------------------------- #
def _chunk(lines: list[str], limit: int = FIELD_VALUE_LIMIT) -> list[str]:
    chunks: list[str] = []
    cur: list[str] = []
    size = 0
    for line in lines:
        add = len(line) + 1
        if cur and size + add > limit:
            chunks.append("\n".join(cur))
            cur, size = [], 0
        cur.append(line)
        size += add
    if cur:
        chunks.append("\n".join(cur))
    return chunks


def _league_lines(events: Iterable[Event], tz: ZoneInfo, date_headers: bool) -> list[str]:
    lines: list[str] = []
    last_date = None
    for ev in sorted(events, key=lambda e: e.start):
        local = ev.start.astimezone(tz)
        if date_headers and local.date() != last_date:
            lines.append(f"**{fmt_day(ev.start, tz)}**")
            last_date = local.date()
        lines.append(f"`{local:%H:%M}` {ev.line_text}")
    return lines


def grouped_embeds(
    title: str,
    groups: list[tuple[League, list[Event]]],
    tz: ZoneInfo,
    *,
    color: int = 0x5865F2,
    description: Optional[str] = None,
    footer: Optional[str] = None,
    max_embeds: int = 10,
) -> list[discord.Embed]:
    """Mỗi giải = 1 field (tự chia nhỏ nếu dài). Tự tách thành nhiều embed khi vượt giới hạn."""
    all_dates = {
        ev.start.astimezone(tz).date() for _, evs in groups for ev in evs
    }
    date_headers = len(all_dates) > 1

    # Chuẩn bị danh sách field (tên, giá trị)
    fields: list[tuple[str, str]] = []
    for league, evs in groups:
        chunks = _chunk(_league_lines(evs, tz, date_headers))
        for i, chunk in enumerate(chunks):
            name = f"{league.emoji} {league.name}" if i == 0 else "\u200b"
            fields.append((name, chunk))

    embeds: list[discord.Embed] = []

    def new_embed(first: bool) -> tuple[discord.Embed, int]:
        e = discord.Embed(color=color)
        size = 0
        if first:
            e.title = title
            size += len(title)
            if description:
                e.description = description
                size += len(description)
        return e, size

    embed, size = new_embed(True)
    count = 0
    for name, value in fields:
        need = len(name) + len(value)
        if count >= 24 or size + need > EMBED_TOTAL_LIMIT:
            embeds.append(embed)
            embed, size = new_embed(False)
            count = 0
        embed.add_field(name=name, value=value, inline=False)
        size += need
        count += 1
    embeds.append(embed)

    truncated = len(embeds) > max_embeds
    embeds = embeds[:max_embeds]
    last_footer = footer or ""
    if truncated:
        last_footer = (last_footer + " • " if last_footer else "") + "Còn nữa – dùng /schedule với từng giải để xem đủ"
    if last_footer:
        embeds[-1].set_footer(text=last_footer)
    return embeds
