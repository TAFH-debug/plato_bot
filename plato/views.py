"""Fetch + render: everything the handlers and the scheduler show."""
from __future__ import annotations

import asyncio
import time
from zoneinfo import ZoneInfo

from .formatting import assignment_line, dt, esc, event_line, icon, short_course
from .moodle import MoodleClient, MoodleError, assignment_state

STATUS_BUDGET = 30  # max submission-status lookups per request


async def _attach_status(client: MoodleClient, items: list[dict]) -> None:
    async def one(item: dict) -> None:
        try:
            status = await client.submission_status(item["id"])
        except MoodleError:
            return
        state, label = assignment_state(status)
        item["state"], item["state_label"] = state, label

    await asyncio.gather(*(one(i) for i in items[:STATUS_BUDGET]))


async def assignment_items(
    client: MoodleClient,
    courseids: list[int],
    with_status: bool = True,
    stale_days: int = 14,
) -> list[dict]:
    """Assignments across courses, soonest first, with submission state."""
    if not courseids:
        return []
    now = time.time()
    items: list[dict] = []
    for course in await client.assignments(courseids):
        for a in course.get("assignments", []):
            due = int(a.get("duedate") or 0)
            if due and due < now - stale_days * 86400:
                continue
            items.append(
                {
                    "id": a["id"],
                    "cmid": a.get("cmid"),
                    "name": a.get("name", "assignment"),
                    "courseid": course.get("id"),
                    "course": course.get("fullname") or course.get("shortname", ""),
                    "duedate": due,
                    "cutoffdate": int(a.get("cutoffdate") or 0),
                    "url": f"{client.base_url}/mod/assign/view.php?id={a.get('cmid')}",
                    "state": "todo",
                    "state_label": "not submitted",
                }
            )
    items.sort(key=lambda i: (i["duedate"] == 0, i["duedate"]))
    if with_status:
        await _attach_status(client, items)
    return items


def course_ids(courses: list[dict]) -> list[int]:
    return [int(c["id"]) for c in courses if c.get("id")]


def course_names(courses: list[dict]) -> dict[int, str]:
    return {
        int(c["id"]): c.get("fullname") or c.get("shortname", "course")
        for c in courses
        if c.get("id")
    }


# --- renderers --------------------------------------------------------
async def upcoming_text(client: MoodleClient, tz: ZoneInfo, days: int = 14) -> str:
    events = await client.upcoming(days=days)
    if not events:
        return f"Nothing due in the next {days} days. \U0001f389"
    head = f"<b>⏰ Due within {days} days</b> · {len(events)} item(s)\n"
    body = "\n\n".join(event_line(e, tz) for e in events[:25])
    return head + "\n" + body


async def assignments_text(
    client: MoodleClient, courses: list[dict], tz: ZoneInfo, courseid: int | None = None
) -> str:
    ids = [courseid] if courseid else course_ids(courses)
    items = await assignment_items(client, ids)
    if not items:
        return "No assignments found for the selected course(s)."

    pending = [i for i in items if i["state"] == "todo"]
    done = [i for i in items if i["state"] != "todo"]

    lines = [f"<b>\U0001f4dd Assignments</b> · {len(pending)} open / {len(items)} total"]
    if courseid:
        names = course_names(courses)
        lines[0] += f"\n<i>{esc(short_course(names.get(courseid, ''), 60))}</i>"

    if pending:
        lines.append("\n<b>Open</b>")
        for item in pending[:20]:
            prefix = "" if courseid else f"<i>{esc(short_course(item['course'], 30))}</i>\n"
            lines.append(prefix + assignment_line(item, tz))
    if done:
        lines.append("\n<b>Submitted / graded</b>")
        for item in done[:12]:
            lines.append(assignment_line(item, tz))
    return "\n".join(lines)


def courses_text(courses: list[dict]) -> str:
    if not courses:
        return "No active courses found."
    lines = [f"<b>\U0001f4da Active courses</b> · {len(courses)}\n"]
    for c in courses:
        progress = c.get("progress")
        bar = f" · {int(progress)}% complete" if isinstance(progress, (int, float)) else ""
        lines.append(f"• <b>{esc(short_course(c.get('fullname', ''), 48))}</b>{bar}")
    lines.append("\nPick a course below \U0001f447")
    return "\n".join(lines)


async def grades_overview_text(
    client: MoodleClient, userid: int, courses: list[dict]
) -> str:
    names = course_names(courses)
    try:
        grades = await client.course_grades(userid)
    except MoodleError as exc:
        return f"Grade overview unavailable ({esc(exc.code)})."
    rows = [g for g in grades if g.get("grade") not in (None, "", "-")]
    if not rows:
        return "No course totals published yet. Open a course for item-level grades."
    lines = ["<b>\U0001f4ca Course totals</b>\n"]
    for g in rows:
        cid = int(g.get("courseid", 0))
        name = short_course(names.get(cid, g.get("coursename", f"course {cid}")), 40)
        rank = f" · rank {g['rank']}" if g.get("rank") else ""
        lines.append(f"• <b>{esc(name)}</b> — {esc(g.get('grade'))}{rank}")
    return "\n".join(lines)


async def course_grades_text(client: MoodleClient, courseid: int, userid: int) -> str:
    try:
        items = await client.grade_items(courseid, userid)
    except MoodleError as exc:
        return f"Grades unavailable for this course ({esc(exc.code)})."
    if not items:
        return "No grade items in this course."
    lines = ["<b>\U0001f4ca Grades</b>\n"]
    for item in items:
        name = item.get("itemname") or (
            "Course total" if item.get("itemtype") == "course" else "—"
        )
        grade = item.get("gradeformatted") or "-"
        pct = item.get("percentageformatted") or ""
        pct = f" ({pct})" if pct and pct != "-" else ""
        feedback = item.get("feedback") or ""
        line = f"• {esc(short_course(name, 40))}: <b>{esc(grade)}</b>{esc(pct)}"
        if feedback:
            line += f"\n   \U0001f4ac <i>{esc(short_course(feedback, 90))}</i>"
        lines.append(line)
    return "\n".join(lines)


async def course_contents_text(client: MoodleClient, courseid: int) -> str:
    try:
        sections = await client.course_contents(courseid)
    except MoodleError as exc:
        return f"Contents unavailable ({esc(exc.code)})."
    lines = ["<b>\U0001f5c2 Course contents</b>"]
    shown = 0
    for section in sections:
        modules = section.get("modules", [])
        if not modules:
            continue
        lines.append(f"\n<b>{esc(short_course(section.get('name', ''), 46))}</b>")
        for module in modules:
            if shown >= 60:
                lines.append("…")
                return "\n".join(lines)
            url = module.get("url", "")
            title = esc(short_course(module.get("name", ""), 46))
            link = f'<a href="{esc(url)}">{title}</a>' if url else title
            lines.append(f"{icon(module.get('modname', ''))} {link}")
            shown += 1
    return "\n".join(lines)


def digest_text(events: list[dict], tz: ZoneInfo) -> str:
    if not events:
        return "☀️ <b>Good morning!</b>\nNothing due in the next 3 days. Enjoy."
    lines = [f"☀️ <b>PLATO digest</b> · {len(events)} upcoming\n"]
    lines += [event_line(e, tz) for e in events[:12]]
    return "\n\n".join(lines)


def reminder_text(event: dict, tz: ZoneInfo) -> str:
    course = (event.get("course") or {}).get("fullname", "")
    url = event.get("url") or (event.get("action") or {}).get("url") or ""
    title = esc(event.get("name", "Task"))
    head = f'<a href="{esc(url)}">{title}</a>' if url else f"<b>{title}</b>"
    ts = int(event.get("timesort") or event.get("timestart") or 0)
    return (
        f"⏰ <b>Deadline reminder</b>\n\n"
        f"{icon(event.get('modulename', ''))} {head}\n"
        f"<i>{esc(short_course(course, 60))}</i>\n"
        f"\U0001f5d3 Due {dt(ts, tz)}"
    )


def notification_text(item: dict, tz: ZoneInfo) -> str:
    subject = esc(item.get("subject") or "PLATO notification")
    body = item.get("fullmessage") or ""
    body = " ".join(str(body).split())[:500]
    url = item.get("contexturl") or ""
    head = f'\U0001f4e8 <b><a href="{esc(url)}">{subject}</a></b>' if url else f"\U0001f4e8 <b>{subject}</b>"
    when = dt(int(item.get("timecreated") or 0), tz)
    return f"{head}\n<i>{when}</i>\n\n{esc(body)}"
