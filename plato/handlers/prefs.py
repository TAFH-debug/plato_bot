"""Reminder / digest / notification preferences."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from .. import keyboards as kb
from ..services import Services
from .common import show

router = Router(name="prefs")


def parse_leads(raw: str) -> set[int]:
    return {int(x) for x in str(raw or "").split(",") if x.strip().isdigit()}


def summary(prefs: dict, tz_name: str) -> str:
    leads = sorted(parse_leads(prefs["leads"]), reverse=True)
    pretty = ", ".join(kb.lead_label(m) for m in leads) or "none"
    digest = (
        f"{prefs['digest_hour']:02d}:00 {tz_name}"
        if prefs["digest_hour"] is not None
        else "off"
    )
    return (
        "<b>⚙️ Settings</b>\n\n"
        f"\U0001f514 Deadline reminders: <b>{'on' if prefs['reminders'] else 'off'}</b>\n"
        f"⏱ Sent before: <b>{pretty}</b>\n"
        f"\U0001f4f0 Daily digest: <b>{digest}</b>\n"
        f"\U0001f4e8 PLATO notifications: <b>"
        f"{'forwarded' if prefs['notify_moodle'] else 'off'}</b>"
    )


async def render(target: Message | CallbackQuery, services: Services) -> None:
    prefs = await services.storage.get_prefs(target.from_user.id)
    await show(target, summary(prefs, str(services.cfg.tz)), kb.settings_menu(prefs))


@router.message(Command("settings"))
@router.message(F.text == kb.BTN_SETTINGS)
async def settings_cmd(message: Message, services: Services) -> None:
    await render(message, services)


@router.callback_query(F.data == "set:back")
async def back_cb(call: CallbackQuery, services: Services) -> None:
    await call.answer()
    await render(call, services)


@router.callback_query(F.data == "set:toggle_rem")
async def toggle_reminders(call: CallbackQuery, services: Services) -> None:
    prefs = await services.storage.get_prefs(call.from_user.id)
    new = 0 if prefs["reminders"] else 1
    await services.storage.set_prefs(call.from_user.id, reminders=new)
    await call.answer("Reminders on" if new else "Reminders off")
    await render(call, services)


@router.callback_query(F.data == "set:toggle_notif")
async def toggle_notifications(call: CallbackQuery, services: Services) -> None:
    prefs = await services.storage.get_prefs(call.from_user.id)
    new = 0 if prefs["notify_moodle"] else 1
    await services.storage.set_prefs(call.from_user.id, notify_moodle=new)
    await call.answer("Forwarding PLATO notifications" if new else "Forwarding off")
    await render(call, services)


@router.callback_query(F.data == "set:leads")
async def leads_menu(call: CallbackQuery, services: Services) -> None:
    prefs = await services.storage.get_prefs(call.from_user.id)
    await call.answer()
    await show(
        call,
        "<b>⏱ Remind me before a deadline</b>\n\nTap to switch each one on or off.",
        kb.leads_menu(parse_leads(prefs["leads"])),
    )


@router.callback_query(F.data.startswith("lead:"))
async def toggle_lead(call: CallbackQuery, services: Services) -> None:
    minutes = int(call.data.split(":", 1)[1])
    prefs = await services.storage.get_prefs(call.from_user.id)
    leads = parse_leads(prefs["leads"])
    leads.symmetric_difference_update({minutes})
    await services.storage.set_prefs(
        call.from_user.id, leads=",".join(str(m) for m in sorted(leads, reverse=True))
    )
    await call.answer("Added" if minutes in leads else "Removed")
    await show(
        call,
        "<b>⏱ Remind me before a deadline</b>\n\nTap to switch each one on or off.",
        kb.leads_menu(leads),
    )


@router.callback_query(F.data == "set:digest")
async def digest_menu(call: CallbackQuery, services: Services) -> None:
    prefs = await services.storage.get_prefs(call.from_user.id)
    await call.answer()
    await show(
        call,
        f"<b>\U0001f4f0 Daily digest</b>\n\nOne summary of the next 3 days, "
        f"sent at the chosen hour ({services.cfg.tz}).",
        kb.digest_menu(prefs["digest_hour"]),
    )


@router.callback_query(F.data.startswith("dig:"))
async def set_digest(call: CallbackQuery, services: Services) -> None:
    raw = call.data.split(":", 1)[1]
    hour = None if raw == "off" else int(raw)
    await services.storage.set_prefs(call.from_user.id, digest_hour=hour)
    await call.answer("Digest off" if hour is None else f"Digest at {hour:02d}:00")
    await render(call, services)


@router.callback_query(F.data == "set:logout")
async def logout_cb(call: CallbackQuery, services: Services) -> None:
    await services.storage.forget(call.from_user.id)
    services.forget_client(call.from_user.id)
    await call.answer("Logged out")
    await show(call, "\U0001f6aa Logged out. Everything stored about you is deleted.")
    await call.message.answer("Send /login to connect again.", reply_markup=ReplyKeyboardRemove())
