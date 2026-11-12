"""Lưu cấu hình từng server + danh sách thông báo đã gửi (chống gửi trùng) bằng SQLite."""
from __future__ import annotations

import os
import time
from typing import Iterable, Optional

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS guilds (
    guild_id   INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL,
    role_id    INTEGER,
    digest     INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS subs (
    guild_id   INTEGER NOT NULL,
    league_key TEXT    NOT NULL,
    PRIMARY KEY (guild_id, league_key)
);
CREATE TABLE IF NOT EXISTS sent (
    key     TEXT PRIMARY KEY,
    sent_at INTEGER NOT NULL
);
"""


class Database:
    def __init__(self, path: str):
        self.path = path
        self.conn: Optional[aiosqlite.Connection] = None

    async def init(self) -> None:
        folder = os.path.dirname(self.path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()

    # ---- cấu hình server ---------------------------------------------------
    async def upsert_guild(
        self, guild_id: int, channel_id: int, role_id: Optional[int], digest: bool
    ) -> None:
        await self.conn.execute(
            """INSERT INTO guilds(guild_id, channel_id, role_id, digest) VALUES(?,?,?,?)
               ON CONFLICT(guild_id) DO UPDATE SET
                 channel_id=excluded.channel_id, role_id=excluded.role_id, digest=excluded.digest""",
            (guild_id, channel_id, role_id, int(digest)),
        )
        await self.conn.commit()

    async def get_guild(self, guild_id: int) -> Optional[dict]:
        async with self.conn.execute("SELECT * FROM guilds WHERE guild_id=?", (guild_id,)) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def all_guilds(self) -> list[dict]:
        async with self.conn.execute("SELECT * FROM guilds") as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def delete_guild(self, guild_id: int) -> None:
        await self.conn.execute("DELETE FROM guilds WHERE guild_id=?", (guild_id,))
        await self.conn.execute("DELETE FROM subs WHERE guild_id=?", (guild_id,))
        await self.conn.commit()

    # ---- đăng ký giải ------------------------------------------------------
    async def get_subs(self, guild_id: int) -> set[str]:
        async with self.conn.execute(
            "SELECT league_key FROM subs WHERE guild_id=?", (guild_id,)
        ) as cur:
            return {r["league_key"] for r in await cur.fetchall()}

    async def add_subs(self, guild_id: int, keys: Iterable[str]) -> None:
        await self.conn.executemany(
            "INSERT OR IGNORE INTO subs(guild_id, league_key) VALUES(?,?)",
            [(guild_id, k) for k in keys],
        )
        await self.conn.commit()

    async def remove_subs(self, guild_id: int, keys: Iterable[str]) -> None:
        await self.conn.executemany(
            "DELETE FROM subs WHERE guild_id=? AND league_key=?",
            [(guild_id, k) for k in keys],
        )
        await self.conn.commit()

    # ---- chống gửi trùng ---------------------------------------------------
    async def claim(self, key: str) -> bool:
        """Đánh dấu 'đã gửi'. Trả True nếu đây là lần đầu (được phép gửi), False nếu đã gửi rồi."""
        cur = await self.conn.execute(
            "INSERT OR IGNORE INTO sent(key, sent_at) VALUES(?,?)", (key, int(time.time()))
        )
        await self.conn.commit()
        return cur.rowcount == 1

    async def cleanup(self, older_than_ts: int) -> None:
        await self.conn.execute("DELETE FROM sent WHERE sent_at < ?", (older_than_ts,))
        await self.conn.commit()
