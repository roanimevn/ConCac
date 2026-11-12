"""TheSportsDB (key miễn phí) – dùng cho V.League 1 và V.League 2.

Bản miễn phí chỉ trả về ~15 sự kiện sắp tới mỗi giải (đủ cho ~2 vòng đấu), và dữ liệu do
cộng đồng cập nhật nên có thể chậm hơn nguồn chính thức. Muốn đầy đủ hơn: dùng key trả phí
(TSDB_API_KEY) hoặc đổi sang nguồn ICS/API khác.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiohttp

import config
from config import League
from models import Event
from .base import get_json, parse_utc

log = logging.getLogger("sportsbot.tsdb")

_BAD_STATUS = {"postponed", "cancelled", "canceled", "abandoned", "suspended"}
_id_cache: dict[str, str] = {}


def _base() -> str:
    return f"https://www.thesportsdb.com/api/v1/json/{config.TSDB_API_KEY}"


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


async def resolve_league_id(http: aiohttp.ClientSession, league: League) -> str:
    """source = "4803" (ID sẵn) hoặc "name:<Quốc gia>|<Tên giải>" (tự dò ID)."""
    if not league.source.startswith("name:"):
        return league.source
    if league.source in _id_cache:
        return _id_cache[league.source]

    country, _, wanted = league.source[5:].partition("|")
    data = await get_json(
        http, f"{_base()}/search_all_leagues.php", params={"c": country, "s": "Soccer"}
    )
    rows = (data or {}).get("countries") or (data or {}).get("leagues") or []
    target = _norm(wanted)
    for row in rows:
        if target in _norm(row.get("strLeague") or ""):
            _id_cache[league.source] = str(row["idLeague"])
            log.info("Đã dò được ID %s cho %s", row["idLeague"], league.name)
            return _id_cache[league.source]

    names = ", ".join(r.get("strLeague", "?") for r in rows) or "(trống)"
    raise RuntimeError(
        f"Không tìm thấy giải '{wanted}' trên TheSportsDB. Các giải của {country}: {names}. "
        f"Hãy đặt SOURCE_{league.key.upper()}=<idLeague> trong .env."
    )


def _start_of(ev: dict) -> Optional[datetime]:
    # strTimestamp là UTC, dạng "2026-09-10T12:15:00".
    start = parse_utc(ev.get("strTimestamp"))
    if start:
        return start
    date, time = ev.get("dateEvent"), ev.get("strTime")
    if date and time:
        return parse_utc(f"{date}T{time}")
    return None  # không rõ giờ -> bỏ qua


def parse_events(data: dict, league: League) -> list[Event]:
    out: list[Event] = []
    for ev in (data or {}).get("events") or []:
        status = (ev.get("strStatus") or "").strip().lower()
        if status in _BAD_STATUS or (ev.get("strPostponed") or "").lower() == "yes":
            continue
        start = _start_of(ev)
        if start is None:
            continue

        home, away = ev.get("strHomeTeam"), ev.get("strAwayTeam")
        if not (home and away) and " vs " in (ev.get("strEvent") or ""):
            home, _, away = ev["strEvent"].partition(" vs ")
        if not (home and away):
            continue

        rnd = ev.get("intRound")
        out.append(
            Event(
                uid=f"{league.key}:{ev['idEvent']}",
                league_key=league.key,
                start=start,
                title=f"{home} vs {away}",
                home=home,
                away=away,
                venue=ev.get("strVenue") or None,
                round=f"Vòng {rnd}" if rnd not in (None, "", "0") else None,
            )
        )
    return out


async def fetch(http: aiohttp.ClientSession, league: League, days_ahead: int) -> list[Event]:
    league_id = await resolve_league_id(http, league)
    data = await get_json(http, f"{_base()}/eventsnextleague.php", params={"id": league_id})
    limit = datetime.now(timezone.utc) + timedelta(days=days_ahead)
    return [e for e in parse_events(data, league) if e.start <= limit]
