"""ESPN (API công khai, không cần key) – dùng cho Premier League, LaLiga, Bundesliga,
Serie A, C1/C2/C3 và AFC Champions League Elite/Two.

Lưu ý: đây là API *không chính thức* của ESPN, có thể đổi định dạng mà không báo trước.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import aiohttp

from config import League
from models import Event
from .base import get_json, parse_utc

log = logging.getLogger("sportsbot.espn")

BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"

# Trạng thái không còn là "sắp diễn ra"
SKIP_STATUS = {
    "STATUS_POSTPONED",
    "STATUS_CANCELED",
    "STATUS_CANCELLED",
    "STATUS_ABANDONED",
    "STATUS_SUSPENDED",
    "STATUS_FORFEIT",
}


def parse_scoreboard(data: dict, league: League) -> list[Event]:
    """Tách riêng để dễ test: JSON scoreboard -> list[Event]."""
    logo = None
    try:
        logo = data["leagues"][0]["logos"][0]["href"]
    except (KeyError, IndexError, TypeError):
        pass

    events: list[Event] = []
    for ev in data.get("events") or []:
        status = (ev.get("status") or {}).get("type") or {}
        if status.get("state") == "post" or status.get("completed"):
            continue
        if status.get("name") in SKIP_STATUS:
            continue

        comp = (ev.get("competitions") or [{}])[0]
        if comp.get("timeValid") is False:  # chưa chốt giờ thi đấu
            continue

        start = parse_utc(ev.get("date"))
        if start is None:
            continue

        home = away = None
        for c in comp.get("competitors") or []:
            team = c.get("team") or {}
            name = team.get("displayName") or team.get("shortDisplayName")
            if c.get("homeAway") == "home":
                home = name
            elif c.get("homeAway") == "away":
                away = name
        if not (home and away):
            continue

        venue = (comp.get("venue") or {}).get("fullName")
        notes = comp.get("notes") or ev.get("notes") or []
        round_ = notes[0].get("headline") if notes and isinstance(notes[0], dict) else None

        events.append(
            Event(
                uid=f"{league.key}:{ev['id']}",
                league_key=league.key,
                start=start,
                title=f"{home} vs {away}",
                home=home,
                away=away,
                venue=venue,
                round=round_,
                logo=logo,
            )
        )
    return events


async def fetch(http: aiohttp.ClientSession, league: League, days_ahead: int) -> list[Event]:
    today = datetime.now(timezone.utc).date()
    # Nới ±1 ngày vì ESPN quy ngày theo múi giờ Mỹ.
    start = today - timedelta(days=1)
    end = today + timedelta(days=days_ahead + 1)
    params = {"dates": f"{start:%Y%m%d}-{end:%Y%m%d}", "limit": 500}
    data = await get_json(http, f"{BASE}/{league.source}/scoreboard", params=params)

    limit = datetime.now(timezone.utc) + timedelta(days=days_ahead)
    return [e for e in parse_scoreboard(data, league) if e.start <= limit]
