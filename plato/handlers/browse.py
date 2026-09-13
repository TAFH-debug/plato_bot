"""Courses, assignments, deadlines, grades."""
from __future__ import annotations

import re

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from .. import keyboards as kb
from ..services import Services
from ..views import (
    assignments_text,
    course_contents_text,
    course_grades_text,
    courses_text,
    grades_overview_text,
    upcoming_text,
)
from .common import busy, require_client, show

router = Router(name="browse")

Target = Message | CallbackQuery


async def _courses(target: Target, services: Services) -> None:
    ctx = await require_client(target, services)
    if not ctx:
        return
    client, user = ctx
    await busy(target)
    courses = await client.courses(user.get("moodle_userid", 0))
    await show(target, courses_text(courses), kb.course_list(courses, "course"))


@router.message(Command("courses"))
@router.message(F.text == kb.BTN_COURSES)
async def courses_cmd(message: Message, services: Services) -> None:
    await _courses(message, services)


@router.callback_query(F.data == "courses")
async def courses_cb(call: CallbackQuery, services: Services) -> None:
    await _courses(call, services)


@router.callback_query(F.data.startswith("course:"))
async def course_menu(call: CallbackQuery, services: Services) -> None:
    ctx = await require_client(call, services)
    if not ctx:
        return
    client, user = ctx
    courseid = int(call.data.split(":", 1)[1])
    await call.answer()
    courses = await client.courses(user.get("moodle_userid", 0))
    name = next(
        (c.get("fullname", "") for c in courses if int(c["id"]) == courseid), "Course"
    )
    await show(
        call,
        f"<b>{name}</b>\n\nWhat do you need?",
        kb.course_menu(courseid, services.cfg.plato_url),
    )


async def _assignments(target: Target, services: Services, courseid: int | None) -> None:
    ctx = await require_client(target, services)
    if not ctx:
        return
    client, user = ctx
    await busy(target, "Checking submissions…")
    courses = await client.courses(user.get("moodle_userid", 0))
    text = await assignments_text(client, courses, services.cfg.tz, courseid)
    keyboard = (
        kb.course_menu(courseid, services.cfg.plato_url) if courseid else kb.refresh("assign")
    )
    await show(target, text, keyboard)


@router.message(Command("assignments"))
@router.message(F.text == kb.BTN_ASSIGNMENTS)
async def assignments_cmd(message: Message, services: Services) -> None:
    await _assignments(message, services, None)


@router.callback_query(F.data == "assign")
async def assignments_cb(call: CallbackQuery, services: Services) -> None:
    await _assignments(call, services, None)


@router.callback_query(F.data.startswith("ca:"))
async def course_assignments_cb(call: CallbackQuery, services: Services) -> None:
    await _assignments(call, services, int(call.data.split(":", 1)[1]))


async def _deadlines(target: Target, services: Services, days: int) -> None:
    ctx = await require_client(target, services)
    if not ctx:
        return
    client, _ = ctx
    await busy(target)
    text = await upcoming_text(client, services.cfg.tz, days=days)
    await show(target, text, kb.refresh("dl"))


@router.message(Command("deadlines", "due", "upcoming"))
async def deadlines_cmd(
    message: Message, command: CommandObject, services: Services
) -> None:
    days = 14
    if command.args and (match := re.search(r"\d+", command.args)):
        days = max(1, min(90, int(match.group())))
    await _deadlines(message, services, days)


@router.message(F.text == kb.BTN_DEADLINES)
async def deadlines_button(message: Message, services: Services) -> None:
    await _deadlines(message, services, 14)


@router.callback_query(F.data == "dl")
async def deadlines_cb(call: CallbackQuery, services: Services) -> None:
    await _deadlines(call, services, 14)


async def _grades(target: Target, services: Services) -> None:
    ctx = await require_client(target, services)
    if not ctx:
        return
    client, user = ctx
    await busy(target)
    courses = await client.courses(user.get("moodle_userid", 0))
    text = await grades_overview_text(client, user.get("moodle_userid", 0), courses)
    await show(target, text, kb.course_list(courses, "cg"))


@router.message(Command("grades"))
@router.message(F.text == kb.BTN_GRADES)
async def grades_cmd(message: Message, services: Services) -> None:
    await _grades(message, services)


@router.callback_query(F.data == "grades")
async def grades_cb(call: CallbackQuery, services: Services) -> None:
    await _grades(call, services)


@router.callback_query(F.data.startswith("cg:"))
async def course_grades_cb(call: CallbackQuery, services: Services) -> None:
    ctx = await require_client(call, services)
    if not ctx:
        return
    client, user = ctx
    courseid = int(call.data.split(":", 1)[1])
    await call.answer()
    text = await course_grades_text(client, courseid, user.get("moodle_userid", 0))
    await show(call, text, kb.course_menu(courseid, services.cfg.plato_url))


@router.callback_query(F.data.startswith("cc:"))
async def course_contents_cb(call: CallbackQuery, services: Services) -> None:
    ctx = await require_client(call, services)
    if not ctx:
        return
    client, _ = ctx
    courseid = int(call.data.split(":", 1)[1])
    await call.answer()
    text = await course_contents_text(client, courseid)
    await show(call, text, kb.course_menu(courseid, services.cfg.plato_url))


@router.message(Command("sync"))
async def sync_cmd(message: Message, services: Services) -> None:
    ctx = await require_client(message, services)
    if not ctx:
        return
    client, _ = ctx
    client.invalidate()
    await message.answer("\U0001f504 Cache cleared. Next request refetches from PLATO.")
