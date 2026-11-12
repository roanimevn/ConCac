"""Điều phối: chọn provider phù hợp cho từng giải."""
from __future__ import annotations

import aiohttp

from config import League
from models import Event
from . import espn, sportstimes, thesportsdb

_PROVIDERS = {
    "espn": espn,
    "tsdb": thesportsdb,
    "sportstimes": sportstimes,
}


async def fetch_league(http: aiohttp.ClientSession, league: League, days_ahead: int) -> list[Event]:
    return await _PROVIDERS[league.provider].fetch(http, league, days_ahead)
