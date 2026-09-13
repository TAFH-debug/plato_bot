"""Shared helpers for handlers."""
from __future__ import annotations

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from ..keyboards import login_prompt
from ..moodle import MoodleClient
from ..services import Services

NOT_LINKED = (
    "You are not linked to PLATO yet.\n\n"
    "Send /login and I will ask for your PLATO ID and password."
)
LIMIT = 3800


def chunks(text: str) -> list[str]:
    """Split a long message on blank lines, staying under Telegram's limit."""
    if len(text) <= LIMIT:
        return [text]
    out, current = [], ""
    for block in text.split("\n\n"):
        if len(current) + len(block) + 2 > LIMIT:
            if current:
                out.append(current)
            while len(block) > LIMIT:
                out.append(block[:LIMIT])
                block = block[LIMIT:]
            current = block
        else:
            current = f"{current}\n\n{block}" if current else block
    if current:
        out.append(current)
    return out


def message_of(target: Message | CallbackQuery) -> Message:
    return target if isinstance(target, Message) else target.message


async def show(
    target: Message | CallbackQuery,
    text: str,
    keyboard: InlineKeyboardMarkup | None = None,
) -> None:
    """Render text, editing in place when it came from a button press."""
    parts = chunks(text)
    if isinstance(target, CallbackQuery) and len(parts) == 1 and target.message:
        try:
            await target.message.edit_text(
                parts[0], reply_markup=keyboard, disable_web_page_preview=True
            )
            return
        except TelegramBadRequest:
            pass
    msg = message_of(target)
    for index, part in enumerate(parts):
        await msg.answer(
            part,
            reply_markup=keyboard if index == len(parts) - 1 else None,
            disable_web_page_preview=True,
        )


async def require_client(
    target: Message | CallbackQuery, services: Services
) -> tuple[MoodleClient, dict] | None:
    """Return (client, user row) or prompt the user to log in first."""
    tg_id = target.from_user.id
    client = await services.client_for(tg_id)
    if client is None:
        await message_of(target).answer(NOT_LINKED, reply_markup=login_prompt())
        return None
    user = await services.storage.get_user(tg_id)
    return client, (user or {})


async def busy(target: Message | CallbackQuery, note: str = "Loading…") -> None:
    if isinstance(target, CallbackQuery):
        await target.answer(note)
    else:
        await target.bot.send_chat_action(target.chat.id, "typing")
