"""Background jobs: deadline reminders, daily digest, PLATO notifications."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime

import httpx
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .keyboards import login_prompt
from .moodle import MoodleClient, MoodleError, TokenExpired
from .services import Services
from .views import (
    announcement_items,
    announcement_text,
    digest_text,
    notification_text,
    reminder_text,
)

log = logging.getLogger(__name__)

RELINK = (
    "\U0001f513 Your PLATO session expired, so reminders are paused.\n"
    "Send /login to reconnect."
)


class Jobs:
    """Owns the scheduler and the per-user polling loops."""

    def __init__(self, bot: Bot, services: Services) -> None:
        self.bot = bot
        self.services = services
        self.scheduler = AsyncIOScheduler(timezone=services.cfg.tz)

    def start(self) -> None:
        every = self.services.cfg.check_interval_min
        self.scheduler.add_job(
            self.check_deadlines, IntervalTrigger(minutes=every), id="deadlines"
        )
        self.scheduler.add_job(
            self.poll_notifications, IntervalTrigger(minutes=max(5, every)), id="notifs"
        )
        self.scheduler.add_job(
            self.poll_announcements, IntervalTrigger(minutes=max(15, every)), id="forums"
        )
        self.scheduler.add_job(
            self.send_digests, CronTrigger(minute=5), id="digests"
        )
        self.scheduler.add_job(
            self.services.storage.prune_sent, CronTrigger(hour=4, minute=30), id="prune"
        )
        self.scheduler.start()
        log.info("scheduler started (deadline check every %s min)", every)

    def stop(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    # --- delivery -----------------------------------------------------
    async def send(self, tg_id: int, text: str, **kwargs) -> bool:
        try:
            await self.bot.send_message(
                tg_id, text, disable_web_page_preview=True, **kwargs
            )
            return True
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after + 1)
            return await self.send(tg_id, text, **kwargs)
        except TelegramForbiddenError:
            log.info("user %s blocked the bot; disabling reminders", tg_id)
            await self.services.storage.set_prefs(tg_id, reminders=0, notify_moodle=0)
            return False
        except Exception as exc:  # network hiccup, malformed html, ...
            log.warning("send to %s failed: %s", tg_id, exc)
            return False

    async def _client(self, user: dict) -> MoodleClient | None:
        return await self.services.client_for(user["tg_id"])

    async def _handle_expiry(self, tg_id: int) -> None:
        await self.services.invalidate_token(tg_id)
        await self.send(tg_id, RELINK, reply_markup=login_prompt())

    async def _for_each(self, users: list[dict], coro_factory) -> None:
        for user in users:
            try:
                await coro_factory(user)
            except TokenExpired:
                await self._handle_expiry(user["tg_id"])
            except (MoodleError, httpx.HTTPError) as exc:
                log.warning("job failed for %s: %s", user["tg_id"], exc)
            await asyncio.sleep(0.2)  # stay friendly to PLATO and to Telegram

    # --- jobs ---------------------------------------------------------
    async def check_deadlines(self) -> None:
        users = [u for u in await self.services.storage.linked_users() if u["reminders"]]
        if not users:
            return

        async def one(user: dict) -> None:
            leads = sorted(
                {int(x) for x in str(user["leads"]).split(",") if x.strip().isdigit()}
            )
            if not leads:
                return
            client = await self._client(user)
            if client is None:
                return
            window_days = max(1, (leads[-1] // 1440) + 1)
            events = await client.upcoming(days=window_days)
            now = int(time.time())
            for event in events:
                due = int(event.get("timesort") or event.get("timestart") or 0)
                remaining = due - now
                if remaining <= 0:
                    continue
                matching = [m for m in leads if remaining <= m * 60]
                if not matching:
                    continue
                lead = matching[0]
                key = f"{event.get('id')}:{lead}"
                if await self.services.storage.already_sent(user["tg_id"], key):
                    continue
                sent = await self.send(
                    user["tg_id"], reminder_text(event, self.services.cfg.tz)
                )
                if not sent:
                    return
                # never backfill the wider windows for the same event
                for wider in matching:
                    await self.services.storage.mark_sent(
                        user["tg_id"], f"{event.get('id')}:{wider}"
                    )

        await self._for_each(users, one)

    async def send_digests(self) -> None:
        hour = datetime.now(self.services.cfg.tz).hour
        users = [
            u
            for u in await self.services.storage.linked_users()
            if u["digest_hour"] is not None and int(u["digest_hour"]) == hour
        ]
        if not users:
            return

        async def one(user: dict) -> None:
            client = await self._client(user)
            if client is None:
                return
            events = await client.upcoming(days=3)
            await self.send(user["tg_id"], digest_text(events, self.services.cfg.tz))

        await self._for_each(users, one)

    async def poll_notifications(self) -> None:
        users = [
            u for u in await self.services.storage.linked_users() if u["notify_moodle"]
        ]
        if not users:
            return

        async def one(user: dict) -> None:
            client = await self._client(user)
            if client is None:
                return
            items = await client.notifications(user["moodle_userid"], limit=10)
            if not items:
                return
            newest = max(int(i.get("id", 0)) for i in items)
            last_seen = int(user["last_notif_id"])
            if last_seen == 0:  # first run: take a baseline, do not flood
                await self.services.storage.set_prefs(user["tg_id"], last_notif_id=newest)
                return
            fresh = [i for i in items if int(i.get("id", 0)) > last_seen]
            for item in sorted(fresh, key=lambda i: int(i.get("id", 0))):
                await self.send(
                    user["tg_id"], notification_text(item, self.services.cfg.tz)
                )
                await asyncio.sleep(0.1)
            if fresh:
                await self.services.storage.set_prefs(user["tg_id"], last_notif_id=newest)

        await self._for_each(users, one)

    async def poll_announcements(self) -> None:
        users = [
            u for u in await self.services.storage.linked_users() if u["notify_forums"]
        ]
        if not users:
            return

        async def one(user: dict) -> None:
            client = await self._client(user)
            if client is None:
                return
            courses = await client.courses(user["moodle_userid"])
            items = await announcement_items(client, courses)
            if not items:
                return
            newest = max(i["disc_id"] for i in items)
            last_seen = int(user["last_forum_disc"])
            if last_seen == 0:  # first run: baseline, do not replay old posts
                await self.services.storage.set_prefs(
                    user["tg_id"], last_forum_disc=newest
                )
                return
            fresh = [i for i in items if i["disc_id"] > last_seen]
            for item in sorted(fresh, key=lambda i: i["disc_id"]):
                await self.send(
                    user["tg_id"], announcement_text(item, self.services.cfg.tz)
                )
                await asyncio.sleep(0.1)
            if fresh:
                await self.services.storage.set_prefs(
                    user["tg_id"], last_forum_disc=newest
                )

        await self._for_each(users, one)
