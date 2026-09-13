"""Offline self-test: exercises the client, storage, views and reminder logic
against a fake PLATO, then (optionally) checks the real site is reachable.

    python selftest.py            # offline only
    python selftest.py --live     # also probe plato.pusan.ac.kr
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

import httpx

from plato.db import Storage
from plato.formatting import left, urgency
from plato.moodle import InvalidLogin, MoodleClient, MoodleError, flatten
from plato.reminders import Jobs
from plato.views import assignments_text, upcoming_text

KST = ZoneInfo("Asia/Seoul")
NOW = int(time.time())
SOON = NOW + 3600 * 5


def fake_site(request: httpx.Request) -> httpx.Response:
    form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
    fn = form.get("wsfunction")
    if form.get("wstoken") == "dead":
        return httpx.Response(
            200,
            json={
                "exception": "moodle_exception",
                "errorcode": "invalidtoken",
                "message": "Invalid token",
            },
        )
    if fn == "core_webservice_get_site_info":
        return httpx.Response(200, json={"userid": 7, "fullname": "홍길동", "username": "202512345"})
    if fn == "core_course_get_enrolled_courses_by_timeline_classification":
        return httpx.Response(
            200,
            json={"courses": [{"id": 11, "fullname": "운영체제 (001)", "progress": 42}]},
        )
    if fn == "core_calendar_get_action_events_by_timesort":
        return httpx.Response(
            200,
            json={
                "events": [
                    {
                        "id": 900,
                        "name": "Lab 3 <report>",
                        "timesort": SOON,
                        "modulename": "assign",
                        "url": "https://plato.pusan.ac.kr/mod/assign/view.php?id=5",
                        "course": {"id": 11, "fullname": "운영체제 (001)"},
                    }
                ]
            },
        )
    if fn == "mod_assign_get_assignments":
        return httpx.Response(
            200,
            json={
                "courses": [
                    {
                        "id": 11,
                        "fullname": "운영체제 (001)",
                        "assignments": [
                            {"id": 5, "cmid": 55, "name": "Lab 3", "duedate": SOON},
                            {"id": 6, "cmid": 66, "name": "Lab 2", "duedate": NOW - 3600},
                        ],
                    }
                ]
            },
        )
    if fn == "mod_assign_get_submission_status":
        submitted = form.get("assignid") == "6"
        return httpx.Response(
            200,
            json={
                "lastattempt": {
                    "submission": {"status": "submitted" if submitted else "new"}
                },
                "feedback": {},
            },
        )
    return httpx.Response(200, json={"exception": "x", "errorcode": "unknown", "message": fn or "?"})


def check(name: str, condition: bool) -> None:
    print(f"{'PASS' if condition else 'FAIL'}  {name}")
    if not condition:
        raise SystemExit(1)


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str, **kwargs) -> None:
        self.sent.append((chat_id, text))


async def main(live: bool) -> None:
    check("flatten nests arrays", flatten({"courseids": [1, 2]}) == {"courseids[0]": 1, "courseids[1]": 2})
    check("left() formats", left(3600 * 26).startswith("1d") and "overdue" in left(-60))
    check("urgency escalates", urgency(-1) == "⛔" and urgency(3600) == "🔴" and urgency(10**6) == "🟢")

    transport = httpx.MockTransport(fake_site)
    async with httpx.AsyncClient(transport=transport, base_url="https://fake") as http:
        client = MoodleClient("https://fake", "good", http)

        info = await client.site_info()
        check("site_info", info["userid"] == 7)

        courses = await client.courses(7)
        check("courses", courses[0]["fullname"] == "운영체제 (001)")

        text = await upcoming_text(client, KST)
        check("deadlines render + escape html", "Lab 3 &lt;report&gt;" in text and "🔴" in text)

        text = await assignments_text(client, courses, KST)
        check("assignment status split", "Open" in text and "Submitted / graded" in text)

        dead = MoodleClient("https://fake", "dead", http)
        try:
            await dead.site_info()
            check("expired token raises", False)
        except MoodleError as exc:
            check("expired token raises", exc.code == "invalidtoken")

        # --- storage + reminder pipeline ------------------------------
        with tempfile.TemporaryDirectory() as tmp:
            store = Storage(Path(tmp) / "t.sqlite3")
            await store.open()
            await store.link_user(1, 7, "202512345", "홍길동", "enc")
            await store.set_prefs(1, leads="1440,360,60")
            users = await store.linked_users()
            check("user round-trip", users[0]["fullname"] == "홍길동" and users[0]["reminders"] == 1)

            class Svc:
                cfg = type(
                    "C",
                    (),
                    {
                        "tz": KST,
                        "check_interval_min": 10,
                    },
                )()
                storage = store

                async def client_for(self, tg_id):
                    return client

                def forget_client(self, tg_id):
                    pass

                async def invalidate_token(self, tg_id):
                    pass

            bot = FakeBot()
            jobs = Jobs(bot, Svc())
            await jobs.check_deadlines()
            check("reminder fired once", len(bot.sent) == 1 and "Deadline reminder" in bot.sent[0][1])
            await jobs.check_deadlines()
            check("reminder not repeated", len(bot.sent) == 1)
            check("wider windows suppressed", await store.already_sent(1, "900:1440"))
            await store.close()

    if live:
        async with httpx.AsyncClient(timeout=20) as http:
            from plato.moodle import fetch_token

            try:
                await fetch_token("https://plato.pusan.ac.kr", "0", "0", http)
                check("live: bad creds rejected", False)
            except InvalidLogin:
                check("live: token endpoint reachable, bad creds rejected", True)
            except MoodleError as exc:
                check(f"live: token endpoint answered ({exc.code})", True)

    print("\nall checks passed")


if __name__ == "__main__":
    asyncio.run(main("--live" in sys.argv))
