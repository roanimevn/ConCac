"""Mô hình dữ liệu dùng chung cho mọi nguồn."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class Event:
    """Một trận đấu (bóng đá) hoặc một phiên đua (F1/F2/F3)."""

    uid: str                      # duy nhất toàn hệ thống: "<league>:<id nguồn>"
    league_key: str
    start: datetime               # timezone-aware, UTC
    title: str                    # "Arsenal vs Chelsea" hoặc "Monaco GP — Qualifying"
    home: Optional[str] = None
    away: Optional[str] = None
    venue: Optional[str] = None   # sân / địa điểm
    round: Optional[str] = None   # vòng đấu / chặng
    logo: Optional[str] = None    # logo giải (nếu nguồn cung cấp)
    important: bool = True        # False -> không báo (vd: buổi tập tự do)

    @property
    def ts(self) -> int:
        """Unix timestamp (giây) – dùng cho thẻ <t:...> của Discord."""
        return int(self.start.timestamp())

    @property
    def line_text(self) -> str:
        if self.home and self.away:
            return f"{self.home} vs {self.away}"
        return self.title
