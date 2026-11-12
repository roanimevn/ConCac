"""Dataset mở của f1calendar.com (repo GitHub sportstimes/f1, giấy phép MIT).

Mỗi series có 1 file JSON theo năm: _db/<f1|f2|f3>/<năm>.json
  {"races": [{"name": "Monaco", "round": 8, "location": "Monte Carlo",
              "sessions": {"fp1": "2026-06-05T11:30:00Z", ..., "gp": "..."}}]}
Parser bên dưới viết khá "dễ tính" với tên session để chịu được thay đổi nhỏ.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

import aiohttp

import config
from config import League
from models import Event
from .base import SourceNotFound, get_json, parse_utc

log = logging.getLogger("sportsbot.sportstimes")

BASE = "https://raw.githubusercontent.com/sportstimes/f1/main/_db"

# key (đã chuẩn hoá: chữ thường, bỏ ký tự lạ) -> (nhãn hiển thị, có phải buổi tập không)
SESSIONS: dict[str, tuple[str, bool]] = {
    "fp1": ("Free Practice 1", True),
    "fp2": ("Free Practice 2", True),
    "fp3": ("Free Practice 3", True),
    "practice": ("Free Practice", True),
    "sprintqualifying": ("Sprint Qualifying", False),
    "sprintshootout": ("Sprint Shootout", False),
    "qualifying": ("Qualifying", False),
    "sprint": ("Sprint Race", False),
    "feature": ("Feature Race", False),
    "gp": ("Grand Prix (Race)", False),
    "race": ("Race", False),
}


def describe_session(key: str) -> tuple[str, bool]:
    """Trả về (nhãn, is_practice)."""
    norm = re.sub(r"[^a-z0-9]", "", key.lower())
    if norm in SESSIONS:
        return SESSIONS[norm]
    return key.replace("_", " ").title(), False


def parse_season(data: dict, league: League) -> list[Event]:
    out: list[Event] = []
    for race in (data or {}).get("races") or []:
        if race.get("canceled") or race.get("cancelled"):
            continue
        name = race.get("name") or race.get("slug") or "?"
        gp = f"{name} GP" if league.key == "f1" and "gp" not in name.lower() else name
        rnd = race.get("round")
        slug = race.get("slug") or re.sub(r"[^a-z0-9]", "", name.lower())

        for key, iso in (race.get("sessions") or {}).items():
            start = parse_utc(iso)
            if start is None:
                continue
            label, is_practice = describe_session(key)
            out.append(
                Event(
                    uid=f"{league.key}:{rnd or slug}:{re.sub(r'[^a-z0-9]', '', key.lower())}",
                    league_key=league.key,
                    start=start,
                    title=f"{gp} — {label}",
                    venue=race.get("location"),
                    round=f"Chặng {rnd}" if rnd else None,
                    important=(not is_practice) or config.NOTIFY_PRACTICE,
                )
            )
    return out


async def fetch(http: aiohttp.ClientSession, league: League, days_ahead: int) -> list[Event]:
    now = datetime.now(timezone.utc)
    events: list[Event] = []
    found = 0
    # Lấy cả năm sau để không bị hụt lịch vào cuối năm.
    for year in (now.year, now.year + 1):
        try:
            data = await get_json(http, f"{BASE}/{league.source}/{year}.json")
        except SourceNotFound:
            continue
        found += 1
        events += parse_season(data, league)
    if not found:
        raise RuntimeError(f"Không tìm thấy file lịch {league.source} cho năm {now.year}")

    lo, hi = now - timedelta(hours=6), now + timedelta(days=days_ahead)
    return [e for e in events if lo <= e.start <= hi]
