"""Linking a Telegram account to a PLATO account."""
from __future__ import annotations

import logging

import httpx
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from ..formatting import esc
from ..keyboards import (
    BTN_ASSIGNMENTS,
    BTN_COURSES,
    BTN_DEADLINES,
    BTN_GRADES,
    BTN_SETTINGS,
    login_prompt,
    main_menu,
)
from ..moodle import InvalidLogin, MoodleClient, MoodleError, fetch_token
from ..services import Services
from .common import message_of

log = logging.getLogger(__name__)
router = Router(name="auth")
MENU_TEXTS = {BTN_COURSES, BTN_ASSIGNMENTS, BTN_DEADLINES, BTN_GRADES, BTN_SETTINGS}

WELCOME = (
    "<b>PLATO assistant</b> \U0001f9d1‍\U0001f393\n\n"
    "I keep your Pusan National University coursework in one place:\n"
    "• ⏰ upcoming deadlines with reminders\n"
    "• \U0001f4dd assignments and what is still unsubmitted\n"
    "• \U0001f4da courses, contents and \U0001f4ca grades\n"
    "• \U0001f4e8 PLATO notifications forwarded to Telegram\n"
    "• \U0001f4e2 course announcements the moment they are posted\n\n"
    "Send /login to connect your PLATO account."
)
HELP = (
    "<b>Commands</b>\n"
    "/login — connect your PLATO account\n"
    "/deadlines [days] — what is due (default 14 days)\n"
    "/assignments — assignments with submission status\n"
    "/courses — your active courses\n"
    "/grades — course totals and item grades\n"
    "/settings — reminders, daily digest, notifications\n"
    "/sync — drop the cache and refetch\n"
    "/whoami — the linked PLATO account\n"
    "/logout — delete your token and data"
)
PASSWORD_PROMPT = (
    "Now send your <b>PLATO password</b>.\n\n"
    "\U0001f512 I delete the message immediately, exchange it for a web-service "
    "token, and never store the password itself."
)


class Login(StatesGroup):
    username = State()
    password = State()


@router.message(CommandStart())
async def start(message: Message, services: Services) -> None:
    user = await services.storage.get_user(message.from_user.id)
    if user and user.get("token_enc"):
        await message.answer(
            f"Welcome back, <b>{esc(user['fullname'])}</b>.\n\n{HELP}",
            reply_markup=main_menu(),
        )
    else:
        await message.answer(WELCOME, reply_markup=login_prompt())


@router.message(Command("help"))
async def help_cmd(message: Message) -> None:
    await message.answer(HELP, reply_markup=main_menu())


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Cancelled.", reply_markup=main_menu())


@router.message(Command("login"))
async def login_cmd(message: Message, state: FSMContext) -> None:
    await state.set_state(Login.username)
    await message.answer(
        "Send your <b>PLATO ID</b> (the student number you use on "
        "plato.pusan.ac.kr).\n\n/cancel to stop.",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.callback_query(F.data == "login")
async def login_button(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await login_cmd(message_of(call), state)


@router.message(Login.username)
async def got_username(message: Message, state: FSMContext) -> None:
    candidate = (message.text or "").strip()
    if not candidate or candidate.startswith("/") or candidate in MENU_TEXTS:
        await message.answer("That does not look like a PLATO ID. Send it, or /cancel.")
        return
    await state.update_data(username=candidate)
    await state.set_state(Login.password)
    await message.answer(PASSWORD_PROMPT)


@router.message(Login.password)
async def got_password(message: Message, state: FSMContext, services: Services) -> None:
    password = message.text or ""
    try:  # the password must not linger in the chat history
        await message.delete()
    except TelegramBadRequest:
        pass

    data = await state.get_data()
    await state.clear()
    username = data.get("username", "")
    status = await message.answer("Signing in to PLATO…")

    try:
        token = await fetch_token(services.cfg.plato_url, username, password, services.http)
    except InvalidLogin:
        await status.edit_text(
            "❌ PLATO rejected that ID or password.\n\n"
            "Check them on the website, then try /login again.",
            reply_markup=login_prompt(),
        )
        return
    except MoodleError as exc:
        await status.edit_text(
            f"❌ PLATO refused the login: <i>{esc(exc.message)}</i>\n\n"
            "If your account needs a password change or agreement on the website, "
            "do that first, then /login again.",
            reply_markup=login_prompt(),
        )
        return
    except httpx.HTTPError as exc:
        log.warning("token request failed: %s", exc)
        await status.edit_text("⚠️ PLATO is not responding. Try /login again later.")
        return

    client = MoodleClient(services.cfg.plato_url, token, services.http)
    try:
        info = await client.site_info()
    except MoodleError as exc:
        await status.edit_text(f"❌ Could not read your profile ({esc(exc.code)}).")
        return

    await services.storage.link_user(
        tg_id=message.from_user.id,
        moodle_userid=int(info.get("userid", 0)),
        username=info.get("username", username),
        fullname=info.get("fullname", username),
        token_enc=services.vault.encrypt(token),
    )
    await services.storage.set_prefs(
        message.from_user.id, leads=",".join(str(m) for m in services.cfg.default_leads)
    )
    services.forget_client(message.from_user.id)

    await status.edit_text(
        f"✅ Linked as <b>{esc(info.get('fullname'))}</b>.\n\n"
        "Deadline reminders are on. Use the menu below or /help."
    )
    await message.answer("Ready.", reply_markup=main_menu())


@router.message(Command("whoami"))
async def whoami(message: Message, services: Services) -> None:
    user = await services.storage.get_user(message.from_user.id)
    if not user or not user.get("token_enc"):
        await message.answer("Not linked. Send /login.", reply_markup=login_prompt())
        return
    prefs = await services.storage.get_prefs(message.from_user.id)
    await message.answer(
        f"\U0001f9d1‍\U0001f393 <b>{esc(user['fullname'])}</b>\n"
        f"PLATO ID: <code>{esc(user['username'])}</code>\n"
        f"Site: {esc(services.cfg.plato_url)}\n"
        f"Reminders: {'on' if prefs['reminders'] else 'off'} "
        f"({esc(prefs['leads'])} min before)"
    )


@router.message(Command("logout"))
async def logout(message: Message, services: Services) -> None:
    await services.storage.forget(message.from_user.id)
    services.forget_client(message.from_user.id)
    await message.answer(
        "\U0001f6aa Logged out. Your token, preferences and reminder history are deleted.",
        reply_markup=ReplyKeyboardRemove(),
    )
