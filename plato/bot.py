"""Bot assembly and lifecycle."""
from __future__ import annotations

import asyncio
import logging

import httpx
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, ErrorEvent

from .config import Config
from .handlers import build_router
from .keyboards import login_prompt
from .moodle import MoodleError, TokenExpired
from .reminders import Jobs
from .services import Services

log = logging.getLogger(__name__)

COMMANDS = [
    BotCommand(command="deadlines", description="What is due soon"),
    BotCommand(command="assignments", description="Assignments and submission status"),
    BotCommand(command="courses", description="Your active courses"),
    BotCommand(command="grades", description="Grades"),
    BotCommand(command="settings", description="Reminders and notifications"),
    BotCommand(command="sync", description="Refetch from PLATO"),
    BotCommand(command="login", description="Connect your PLATO account"),
    BotCommand(command="logout", description="Delete your data"),
    BotCommand(command="help", description="All commands"),
]


def _chat_id(event: ErrorEvent) -> int | None:
    update = event.update
    if update.message:
        return update.message.chat.id
    if update.callback_query and update.callback_query.message:
        return update.callback_query.message.chat.id
    return None


def build_dispatcher(services: Services) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp["services"] = services
    dp.include_router(build_router())

    @dp.errors()
    async def on_error(event: ErrorEvent) -> bool:
        chat_id = _chat_id(event)
        exc = event.exception

        if isinstance(exc, TokenExpired):
            tg_id = None
            if event.update.message:
                tg_id = event.update.message.from_user.id
            elif event.update.callback_query:
                tg_id = event.update.callback_query.from_user.id
            if tg_id:
                await services.invalidate_token(tg_id)
            if chat_id:
                await event.bot.send_message(
                    chat_id,
                    "\U0001f513 Your PLATO session expired. Send /login to reconnect.",
                    reply_markup=login_prompt(),
                )
            return True

        if isinstance(exc, MoodleError):
            log.warning("moodle error: %s", exc)
            if chat_id:
                await event.bot.send_message(
                    chat_id, f"⚠️ PLATO said: <i>{exc.message or exc.code}</i>"
                )
            return True

        if isinstance(exc, httpx.HTTPError):
            log.warning("network error: %s", exc)
            if chat_id:
                await event.bot.send_message(
                    chat_id, "⚠️ PLATO is slow or unreachable. Try again in a moment."
                )
            return True

        log.exception("unhandled error", exc_info=exc)
        if chat_id:
            await event.bot.send_message(chat_id, "⚠️ Something broke. Try again.")
        return True

    return dp


async def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)

    cfg = Config.load()
    services = Services(cfg)
    await services.start()

    bot = Bot(
        cfg.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )
    dp = build_dispatcher(services)
    jobs = Jobs(bot, services)

    try:
        await bot.set_my_commands(COMMANDS)
        jobs.start()
        await bot.delete_webhook(drop_pending_updates=True)
        log.info("polling as @%s", (await bot.me()).username)
        await dp.start_polling(bot, handle_signals=True)
    finally:
        jobs.stop()
        await services.stop()
        await bot.session.close()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
