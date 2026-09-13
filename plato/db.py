"""SQLite storage: linked accounts, preferences, reminder bookkeeping."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_id         INTEGER PRIMARY KEY,
    moodle_userid INTEGER,
    username      TEXT,
    fullname      TEXT,
    token_enc     TEXT,
    linked_at     INTEGER
);
CREATE TABLE IF NOT EXISTS prefs (
    tg_id          INTEGER PRIMARY KEY,
    reminders      INTEGER NOT NULL DEFAULT 1,
    leads          TEXT    NOT NULL DEFAULT '1440,180,60',
    digest_hour    INTEGER,
    notify_moodle  INTEGER NOT NULL DEFAULT 0,
    last_notif_id  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sent (
    tg_id    INTEGER NOT NULL,
    key      TEXT    NOT NULL,
    sent_at  INTEGER NOT NULL,
    PRIMARY KEY (tg_id, key)
);
"""


class Storage:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def open(self) -> None:
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Storage.open() was never awaited")
        return self._db

    # --- users --------------------------------------------------------
    async def get_user(self, tg_id: int) -> dict | None:
        async with self.db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,)) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def link_user(
        self, tg_id: int, moodle_userid: int, username: str, fullname: str, token_enc: str
    ) -> None:
        async with self._lock:
            await self.db.execute(
                """INSERT INTO users (tg_id, moodle_userid, username, fullname, token_enc, linked_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(tg_id) DO UPDATE SET
                       moodle_userid = excluded.moodle_userid,
                       username      = excluded.username,
                       fullname      = excluded.fullname,
                       token_enc     = excluded.token_enc,
                       linked_at     = excluded.linked_at""",
                (tg_id, moodle_userid, username, fullname, token_enc, int(time.time())),
            )
            await self.db.execute(
                "INSERT OR IGNORE INTO prefs (tg_id) VALUES (?)", (tg_id,)
            )
            await self.db.commit()

    async def drop_token(self, tg_id: int) -> None:
        async with self._lock:
            await self.db.execute(
                "UPDATE users SET token_enc = NULL WHERE tg_id = ?", (tg_id,)
            )
            await self.db.commit()

    async def forget(self, tg_id: int) -> None:
        async with self._lock:
            for table in ("users", "prefs", "sent"):
                await self.db.execute(f"DELETE FROM {table} WHERE tg_id = ?", (tg_id,))
            await self.db.commit()

    async def linked_users(self) -> list[dict]:
        async with self.db.execute(
            """SELECT u.*, p.reminders, p.leads, p.digest_hour, p.notify_moodle, p.last_notif_id
               FROM users u JOIN prefs p USING (tg_id)
               WHERE u.token_enc IS NOT NULL"""
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    # --- prefs --------------------------------------------------------
    async def get_prefs(self, tg_id: int) -> dict:
        async with self.db.execute("SELECT * FROM prefs WHERE tg_id = ?", (tg_id,)) as cur:
            row = await cur.fetchone()
        if row:
            return dict(row)
        async with self._lock:
            await self.db.execute("INSERT OR IGNORE INTO prefs (tg_id) VALUES (?)", (tg_id,))
            await self.db.commit()
        return await self.get_prefs(tg_id)

    async def set_prefs(self, tg_id: int, **fields: Any) -> None:
        if not fields:
            return
        await self.get_prefs(tg_id)
        assignments = ", ".join(f"{k} = ?" for k in fields)
        async with self._lock:
            await self.db.execute(
                f"UPDATE prefs SET {assignments} WHERE tg_id = ?",
                (*fields.values(), tg_id),
            )
            await self.db.commit()

    # --- reminder bookkeeping ----------------------------------------
    async def already_sent(self, tg_id: int, key: str) -> bool:
        async with self.db.execute(
            "SELECT 1 FROM sent WHERE tg_id = ? AND key = ?", (tg_id, key)
        ) as cur:
            return await cur.fetchone() is not None

    async def mark_sent(self, tg_id: int, key: str) -> None:
        async with self._lock:
            await self.db.execute(
                "INSERT OR REPLACE INTO sent (tg_id, key, sent_at) VALUES (?, ?, ?)",
                (tg_id, key, int(time.time())),
            )
            await self.db.commit()

    async def prune_sent(self, older_than_days: int = 30) -> None:
        cutoff = int(time.time()) - older_than_days * 86400
        async with self._lock:
            await self.db.execute("DELETE FROM sent WHERE sent_at < ?", (cutoff,))
            await self.db.commit()
