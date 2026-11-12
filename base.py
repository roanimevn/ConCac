"""Hàm dùng chung cho các provider."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import aiohttp

log = logging.getLogger("sportsbot.providers")


class SourceNotFound(Exception):
    """HTTP 404 – slug/ID/file không tồn tại."""


async def get_json(
    http: aiohttp.ClientSession,
    url: str,
    *,
    params: Optional[dict] = None,
    retries: int = 3,
) -> Any:
    last: Optional[Exception] = None
    for attempt in range(retries):
        try:
            async with http.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                if resp.status == 404:
                    raise SourceNotFound(url)
                resp.raise_for_status()
                return await resp.json(content_type=None)
        except SourceNotFound:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            last = exc
            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)
    assert last is not None
    raise last


def parse_utc(value: Optional[str]) -> Optional[datetime]:
    """Chuyển chuỗi ISO-8601 thành datetime UTC (chấp nhận 'Z' và chuỗi không có múi giờ)."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
