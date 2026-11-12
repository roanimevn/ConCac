"""Kiểm tra từng nguồn dữ liệu có trả lịch hay không – KHÔNG cần token Discord.

    python check_sources.py                 # kiểm tra tất cả giải
    python check_sources.py --slug afc.cup  # thử 1 slug ESPN bất kỳ (để dò slug đúng)
"""
import argparse
import asyncio
from datetime import datetime, timedelta, timezone

import aiohttp

import config
from embeds import fmt_full
from providers import espn, fetch_league
from providers.base import get_json


async def check_slug(http: aiohttp.ClientSession, slug: str) -> None:
    today = datetime.now(timezone.utc).date()
    params = {"dates": f"{today:%Y%m%d}-{today + timedelta(days=30):%Y%m%d}", "limit": 500}
    data = await get_json(http, f"{espn.BASE}/{slug}/scoreboard", params=params)
    name = (data.get("leagues") or [{}])[0].get("name", "?")
    print(f"slug '{slug}' -> {name!r}, {len(data.get('events') or [])} trận trong 30 ngày tới")


async def main(args: argparse.Namespace) -> None:
    async with aiohttp.ClientSession(headers={"User-Agent": "DiscordSportsBot/1.0"}) as http:
        if args.slug:
            await check_slug(http, args.slug)
            return

        bad = 0
        for lg in config.LEAGUES:
            try:
                events = await fetch_league(http, lg, config.DAYS_AHEAD)
            except Exception as exc:  # noqa: BLE001
                bad += 1
                print(f"❌ {lg.name:<30} [{lg.provider}:{lg.source}] {type(exc).__name__}: {exc}")
                continue
            events.sort(key=lambda e: e.start)
            print(f"✅ {lg.name:<30} [{lg.provider}:{lg.source}] {len(events)} lịch")
            for ev in events[:2]:
                print(f"     {fmt_full(ev.start, config.TIMEZONE).replace('**', '')}  {ev.line_text}")
        print(f"\nXong: {len(config.LEAGUES) - bad}/{len(config.LEAGUES)} nguồn hoạt động.")
        print("Giải trả về 0 lịch có thể do đang nghỉ hè/nghỉ giữa mùa – không nhất thiết là lỗi.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", help="thử một slug ESPN (vd: afc.cup)")
    asyncio.run(main(parser.parse_args()))
