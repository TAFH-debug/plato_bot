"""Message rendering helpers."""
from __future__ import annotations

import html
import time
from datetime import datetime
from zoneinfo import ZoneInfo

MODULE_ICON = {
    "assign": "📝",
    "quiz": "🧪",
    "forum": "💬",
    "workshop": "🛠",
    "lesson": "📖",
    "feedback": "🗳",
    "choice": "✅",
    "vod": "🎬",
    "attendance": "🙋",
    "zoom": "🎥",
    "ubboard": "📋",
}
STATE_ICON = {"todo": "⬜", "submitted": "✅", "graded": "🏆", "closed": "🔒"}


def esc(text: object) -> str:
    return html.escape(str(text or ""), quote=False)


def dt(ts: int, tz: ZoneInfo) -> str:
    if not ts:
        return "no due date"
    return datetime.fromtimestamp(ts, tz).strftime("%a %d %b, %H:%M")


def left(seconds: int) -> str:
    if seconds < 0:
        seconds = -seconds
        suffix = " overdue"
    else:
        suffix = " left"
    days, rem = divmod(int(seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h{suffix}"
    if hours:
        return f"{hours}h {minutes}m{suffix}"
    return f"{minutes}m{suffix}"


def urgency(seconds_left: int) -> str:
    if seconds_left < 0:
        return "⛔"
    if seconds_left < 24 * 3600:
        return "🔴"
    if seconds_left < 72 * 3600:
        return "🟠"
    return "🟢"


def icon(modulename: str) -> str:
    return MODULE_ICON.get(modulename, "📌")


def short_course(name: str, limit: int = 34) -> str:
    name = " ".join(str(name).split())
    return name if len(name) <= limit else name[: limit - 1] + "…"


def event_line(event: dict, tz: ZoneInfo) -> str:
    ts = int(event.get("timesort") or event.get("timestart") or 0)
    remaining = ts - int(time.time())
    course = (event.get("course") or {}).get("fullname", "")
    url = event.get("url") or (event.get("action") or {}).get("url") or ""
    title = esc(event.get("name", "untitled"))
    head = f'<a href="{esc(url)}">{title}</a>' if url else f"<b>{title}</b>"
    return (
        f"{urgency(remaining)} {icon(event.get('modulename', ''))} {head}\n"
        f"   <i>{esc(short_course(course))}</i>\n"
        f"   🗓 {dt(ts, tz)} · <b>{left(remaining)}</b>"
    )


def assignment_line(item: dict, tz: ZoneInfo) -> str:
    due = int(item.get("duedate") or 0)
    remaining = due - int(time.time())
    state = item.get("state", "todo")
    mark = STATE_ICON.get(state, "⬜")
    title = esc(item.get("name", "assignment"))
    url = item.get("url", "")
    head = f'<a href="{esc(url)}">{title}</a>' if url else f"<b>{title}</b>"
    when = f"🗓 {dt(due, tz)}" if due else "🗓 no due date"
    tail = f" · <b>{left(remaining)}</b>" if due and state == "todo" else ""
    return f"{mark} {head}\n   {when}{tail} · {esc(item.get('state_label', state))}"
