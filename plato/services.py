"""Shared runtime objects handed to every handler."""
from __future__ import annotations

import httpx

from .config import Config
from .crypto import Vault
from .db import Storage
from .moodle import MoodleClient


class Services:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.storage = Storage(cfg.db_path)
        self.vault = Vault(cfg.fernet_key)
        self.http = httpx.AsyncClient(
            timeout=httpx.Timeout(25.0),
            headers={"User-Agent": "plato-telegram-bot/1.0"},
            follow_redirects=True,
        )
        self._clients: dict[int, MoodleClient] = {}

    async def start(self) -> None:
        await self.storage.open()

    async def stop(self) -> None:
        await self.http.aclose()
        await self.storage.close()

    async def client_for(self, tg_id: int) -> MoodleClient | None:
        """Return a ready client for a linked user, or None if not linked."""
        if client := self._clients.get(tg_id):
            return client
        user = await self.storage.get_user(tg_id)
        if not user or not user.get("token_enc"):
            return None
        token = self.vault.decrypt(user["token_enc"])
        if not token:
            await self.storage.drop_token(tg_id)
            return None
        client = MoodleClient(self.cfg.plato_url, token, self.http)
        self._clients[tg_id] = client
        return client

    def forget_client(self, tg_id: int) -> None:
        self._clients.pop(tg_id, None)

    async def invalidate_token(self, tg_id: int) -> None:
        self.forget_client(tg_id)
        await self.storage.drop_token(tg_id)
