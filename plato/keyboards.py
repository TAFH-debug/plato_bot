"""Inline and reply keyboards."""
from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from .config import LEAD_CHOICES
from .formatting import short_course

BTN_COURSES = "📚 Courses"
BTN_ASSIGNMENTS = "📝 Assignments"
BTN_DEADLINES = "⏰ Deadlines"
BTN_GRADES = "📊 Grades"
BTN_SETTINGS = "⚙️ Settings"


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_DEADLINES), KeyboardButton(text=BTN_ASSIGNMENTS)],
            [KeyboardButton(text=BTN_COURSES), KeyboardButton(text=BTN_GRADES)],
            [KeyboardButton(text=BTN_SETTINGS)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def course_list(courses: list[dict], action: str) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=short_course(c.get("fullname") or c.get("shortname", "course"), 40),
                callback_data=f"{action}:{c['id']}",
            )
        ]
        for c in courses[:40]
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def course_menu(courseid: int, site_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📝 Assignments", callback_data=f"ca:{courseid}"),
                InlineKeyboardButton(text="📊 Grades", callback_data=f"cg:{courseid}"),
            ],
            [
                InlineKeyboardButton(text="🗂 Contents", callback_data=f"cc:{courseid}"),
                InlineKeyboardButton(
                    text="🌐 Open in PLATO",
                    url=f"{site_url}/course/view.php?id={courseid}",
                ),
            ],
            [InlineKeyboardButton(text="⬅️ Courses", callback_data="courses")],
        ]
    )


def refresh(action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔄 Refresh", callback_data=action)]]
    )


def settings_menu(prefs: dict) -> InlineKeyboardMarkup:
    on = "🔔 Reminders: ON" if prefs["reminders"] else "🔕 Reminders: OFF"
    digest = (
        f"📰 Daily digest: {prefs['digest_hour']:02d}:00"
        if prefs["digest_hour"] is not None
        else "📰 Daily digest: off"
    )
    notif = "📨 PLATO notifications: ON" if prefs["notify_moodle"] else "📨 PLATO notifications: OFF"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=on, callback_data="set:toggle_rem")],
            [InlineKeyboardButton(text="⏱ Reminder times", callback_data="set:leads")],
            [InlineKeyboardButton(text=digest, callback_data="set:digest")],
            [InlineKeyboardButton(text=notif, callback_data="set:toggle_notif")],
            [InlineKeyboardButton(text="🚪 Log out", callback_data="set:logout")],
        ]
    )


def lead_label(minutes: int) -> str:
    if minutes % 1440 == 0:
        return f"{minutes // 1440}d"
    if minutes % 60 == 0:
        return f"{minutes // 60}h"
    return f"{minutes}m"


def leads_menu(active: set[int]) -> InlineKeyboardMarkup:
    rows, row = [], []
    for minutes in LEAD_CHOICES:
        mark = "✅" if minutes in active else "▫️"
        row.append(
            InlineKeyboardButton(
                text=f"{mark} {lead_label(minutes)}", callback_data=f"lead:{minutes}"
            )
        )
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="⬅️ Back", callback_data="set:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def digest_menu(current: int | None) -> InlineKeyboardMarkup:
    rows, row = [], []
    for hour in (7, 8, 9, 12, 18, 20, 21, 22):
        mark = "✅" if current == hour else "▫️"
        row.append(
            InlineKeyboardButton(text=f"{mark} {hour:02d}:00", callback_data=f"dig:{hour}")
        )
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [
            InlineKeyboardButton(text="🚫 Off", callback_data="dig:off"),
            InlineKeyboardButton(text="⬅️ Back", callback_data="set:back"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def login_prompt() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔐 Log in", callback_data="login")]]
    )
