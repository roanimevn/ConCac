"""Cấu hình bot và danh sách giải đấu.

Mọi thứ chỉnh được qua file .env (xem env.example). Nếu một nguồn dữ liệu sai
slug/ID, bạn có thể ghi đè bằng biến SOURCE_<KEY> mà không cần sửa code,
ví dụ: SOURCE_ACLT=afc.cup
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _int_list(name: str, default: str) -> list[int]:
    raw = os.getenv(name, default).replace(" ", "")
    return [int(x) for x in raw.split(",") if x]


# --------------------------------------------------------------------------- #
# Cài đặt chung
# --------------------------------------------------------------------------- #
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
DEV_GUILD_ID = int(os.getenv("DEV_GUILD_ID") or 0) or None  # sync lệnh tức thì cho 1 server

TIMEZONE_NAME = os.getenv("TIMEZONE", "Asia/Ho_Chi_Minh")
TIMEZONE = ZoneInfo(TIMEZONE_NAME)

# Báo trước bao nhiêu phút. 0 = báo đúng giờ bắt đầu. Mặc định: trước 15 phút + đúng giờ.
NOTIFY_OFFSETS: list[int] = sorted(
    {m for m in _int_list("NOTIFY_OFFSETS", "15,0") if m >= 0}, reverse=True
)

# Giờ gửi bản tin "lịch 24 giờ tới" mỗi ngày (theo TIMEZONE). Đặt -1 để tắt.
DAILY_DIGEST_HOUR = int(os.getenv("DAILY_DIGEST_HOUR", "7"))

REFRESH_MINUTES = int(os.getenv("REFRESH_MINUTES", "120"))  # tần suất cập nhật lịch từ nguồn
DAYS_AHEAD = int(os.getenv("DAYS_AHEAD", "14"))             # lấy lịch bao nhiêu ngày tới
LATE_GRACE_SECONDS = int(os.getenv("LATE_GRACE_SECONDS", "120"))  # trễ tối đa vẫn còn gửi

# F1/F2/F3: có báo cả buổi tập (Free Practice) không? Mặc định chỉ báo Qualifying/Sprint/Race.
NOTIFY_PRACTICE = _bool("NOTIFY_PRACTICE", False)

TSDB_API_KEY = os.getenv("TSDB_API_KEY", "123")  # key miễn phí của TheSportsDB

# Trạng thái hiển thị của bot trên Discord.
#  - BOT_STATUS: chấm tròn ở avatar -> online | idle (🌙 Chờ) | dnd | invisible
#  - BOT_ACTIVITY: dòng chữ hiện ngay dưới tên bot
#  - BOT_ACTIVITY_DETAIL: dòng phụ trong hồ sơ bot (để trống = không dùng)
#  - BOT_ACTIVITY_TYPE: playing | watching | listening | competing | custom
#    (custom bị Discord tự chèn 🤔 phía trước chữ, nên mặc định dùng playing)
BOT_STATUS = os.getenv("BOT_STATUS", "idle").strip().lower()
BOT_ACTIVITY = os.getenv("BOT_ACTIVITY", "Đang cập nhật giải đấu...").strip()
BOT_ACTIVITY_DETAIL = os.getenv("BOT_ACTIVITY_DETAIL", "").strip()
BOT_ACTIVITY_TYPE = os.getenv("BOT_ACTIVITY_TYPE", "playing").strip().lower()
DB_PATH = os.getenv("DB_PATH", "data/bot.db")

# Nếu Discord/Cloudflare chặn IP của host (HTTP 429, lỗi 1015) lúc đăng nhập: chờ rồi thử lại thay vì
# sập (Render sẽ tự khởi động lại liên tục và làm lệnh chặn kéo dài). Mỗi lần thất bại chờ gấp đôi, tối đa 30 phút.
LOGIN_RETRY_MINUTES = max(1, int(os.getenv("LOGIN_RETRY_MINUTES", "5")))

# --------------------------------------------------------------------------- #
# Chạy trên Render Web Service (hoặc host nào đó bắt buộc mở cổng HTTP)
# --------------------------------------------------------------------------- #
# Render tự đặt PORT -> tự bật Flask keep-alive. Chạy local thì mặc định tắt (KEEP_ALIVE=true để bật).
PORT = int(os.getenv("PORT") or 0) or None
KEEP_ALIVE = _bool("KEEP_ALIVE", PORT is not None)

# Bot tự gọi /health của chính nó (qua URL công khai) mỗi N phút để không bị Render cho ngủ.
# Render tự cấp RENDER_EXTERNAL_URL; host khác thì đặt SELF_PING_URL. Để trống = tắt.
SELF_PING_URL = (os.getenv("SELF_PING_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").strip()
SELF_PING_MINUTES = max(1, int(os.getenv("SELF_PING_MINUTES", "5")))

# Render Free có filesystem tạm (SQLite mất khi restart) -> cho phép khai báo cấu hình bằng biến
# môi trường; mỗi lần khởi động bot sẽ tự nạp lại nếu DB chưa có cấu hình cho server đó.
CHANNEL_ID = int(os.getenv("CHANNEL_ID") or 0) or None   # kênh nhận thông báo
ROLE_ID = int(os.getenv("ROLE_ID") or 0) or None         # (tuỳ chọn) role được nhắc tên
SEED_LEAGUES = os.getenv("SEED_LEAGUES", "all")          # "all" hoặc "epl,laliga,c1,vl1,f1"
SEED_DIGEST = _bool("SEED_DIGEST", True)                 # bật bản tin sáng


# --------------------------------------------------------------------------- #
# Danh sách giải đấu
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class League:
    key: str       # định danh ngắn, dùng trong lệnh và DB
    name: str      # tên hiển thị
    emoji: str
    color: int     # màu viền embed
    provider: str  # "espn" | "tsdb" | "sportstimes"
    source: str    # slug / ID tuỳ provider
    kind: str      # "football" | "racing"


def _league(key, name, emoji, color, provider, source, kind="football") -> League:
    source = os.getenv(f"SOURCE_{key.upper()}", source)
    return League(key, name, emoji, color, provider, source, kind)


LEAGUES: list[League] = [
    # --- Bóng đá châu Âu (ESPN) ---
    _league("epl", "Premier League", "⚽", 0x3D195B, "espn", "eng.1"),
    _league("laliga", "LaLiga", "⚽", 0xEE2523, "espn", "esp.1"),
    _league("bundesliga", "Bundesliga", "⚽", 0xD20515, "espn", "ger.1"),
    _league("seriea", "Serie A", "⚽", 0x008FD7, "espn", "ita.1"),
    _league("c1", "Champions League (C1)", "🏆", 0x1F3A93, "espn", "uefa.champions"),
    _league("c2", "Europa League (C2)", "🏆", 0xF68E1F, "espn", "uefa.europa"),
    _league("c3", "Conference League (C3)", "🏆", 0x2ECC71, "espn", "uefa.europa.conf"),
    # --- Châu Á (ESPN) ---
    _league("acle", "AFC Champions League Elite", "🌏", 0x1565C0, "espn", "afc.champions"),
    # Slug của ACL Two chưa xác minh được từ sandbox -> chạy `python check_sources.py`
    # để kiểm tra; nếu sai, đặt SOURCE_ACLT=<slug đúng> trong .env.
    _league("aclt", "AFC Champions League Two", "🌏", 0x00897B, "espn", "afc.cup"),
    # --- Việt Nam (TheSportsDB) ---
    _league("vl1", "V.League 1", "🇻🇳", 0xDA251D, "tsdb", "4803"),
    # V.League 2: tự dò ID theo tên lúc khởi động (hoặc đặt SOURCE_VL2=<id>).
    _league("vl2", "V.League 2", "🇻🇳", 0xFFCD00, "tsdb", "name:Vietnam|V.League 2"),
    # --- Đua xe (dataset f1calendar.com / sportstimes) ---
    _league("f1", "Formula 1", "🏎️", 0xE10600, "sportstimes", "f1", "racing"),
    _league("f2", "Formula 2", "🏎️", 0x0090FF, "sportstimes", "f2", "racing"),
    _league("f3", "Formula 3", "🏎️", 0xFF7A00, "sportstimes", "f3", "racing"),
]

LEAGUE_BY_KEY: dict[str, League] = {lg.key: lg for lg in LEAGUES}
