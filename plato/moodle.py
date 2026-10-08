"""Async client for the Moodle web-service REST API used by PLATO.

PLATO keeps the mobile web service (``moodle_mobile_app``) enabled, so the bot
authenticates once via ``/login/token.php`` and afterwards only ever holds a
web-service token -- the password is never stored.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

TOKEN_PATH = "/login/token.php"
REST_PATH = "/webservice/rest/server.php"
SERVICE = "moodle_mobile_app"

# Errors that mean "this token is dead, ask the user to log in again".
DEAD_TOKEN_CODES = {"invalidtoken", "accessexception", "sitemaintenance", "usernotfullysetup"}


class MoodleError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class InvalidLogin(MoodleError):
    """Wrong ID / password, or the account cannot use web services."""


class TokenExpired(MoodleError):
    """Stored token is no longer accepted."""


def flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    """Moodle REST wants nested structures as ``a[0][b]=c`` form fields."""
    out: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            out.update(flatten(item, f"{prefix}[{key}]" if prefix else str(key)))
    elif isinstance(value, (list, tuple)):
        for idx, item in enumerate(value):
            out.update(flatten(item, f"{prefix}[{idx}]"))
    elif value is not None:
        out[prefix] = int(value) if isinstance(value, bool) else value
    return out


async def fetch_token(
    base_url: str, username: str, password: str, client: httpx.AsyncClient
) -> str:
    resp = await client.post(
        base_url + TOKEN_PATH,
        data={"username": username, "password": password, "service": SERVICE},
    )
    resp.raise_for_status()
    data = resp.json()
    if "token" in data:
        return data["token"]
    code = data.get("errorcode", "unknown")
    message = data.get("error") or data.get("message") or "login failed"
    if code in {"invalidlogin", "invalidaccount"}:
        raise InvalidLogin(code, message)
    raise MoodleError(code, message)


class MoodleClient:
    """Thin REST wrapper with a short-lived response cache."""

    def __init__(
        self,
        base_url: str,
        token: str,
        client: httpx.AsyncClient,
        cache_ttl: int = 180,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._http = client
        self._ttl = cache_ttl
        self._cache: dict[str, tuple[float, Any]] = {}
        self._gate = asyncio.Semaphore(4)

    # --- plumbing -----------------------------------------------------
    def invalidate(self) -> None:
        self._cache.clear()

    async def call(self, function: str, cached: bool = True, **params: Any) -> Any:
        key = f"{function}:{sorted(flatten(params).items())}"
        if cached and (hit := self._cache.get(key)):
            if time.monotonic() - hit[0] < self._ttl:
                return hit[1]

        payload = flatten(params)
        payload.update(
            wstoken=self.token, wsfunction=function, moodlewsrestformat="json"
        )
        async with self._gate:
            resp = await self._http.post(self.base_url + REST_PATH, data=payload)
        resp.raise_for_status()
        data = resp.json()

        if isinstance(data, dict) and data.get("exception"):
            code = data.get("errorcode", "unknown")
            message = data.get("message", "")
            if code in DEAD_TOKEN_CODES:
                raise TokenExpired(code, message)
            raise MoodleError(code, message)

        if cached:
            self._cache[key] = (time.monotonic(), data)
        return data

    # --- endpoints ----------------------------------------------------
    async def site_info(self) -> dict:
        return await self.call("core_webservice_get_site_info")

    async def courses(self, userid: int) -> list[dict]:
        """Active courses, newest first. Falls back if the timeline API is off."""
        try:
            data = await self.call(
                "core_course_get_enrolled_courses_by_timeline_classification",
                classification="inprogress",
                limit=0,
                offset=0,
                sort="fullname",
            )
            courses = data.get("courses", [])
            if courses:
                return courses
        except MoodleError:
            pass
        raw = await self.call("core_enrol_get_users_courses", userid=userid)
        raw.sort(key=lambda c: c.get("startdate", 0), reverse=True)
        return raw

    async def upcoming(self, days: int = 14, limit: int = 50) -> list[dict]:
        """Calendar action events -- assignments, quizzes, anything due."""
        now = int(time.time())
        data = await self.call(
            "core_calendar_get_action_events_by_timesort",
            timesortfrom=now,
            timesortto=now + days * 86400,
            limitnum=limit,
            limittononsuspendedevents=True,
        )
        return data.get("events", [])

    async def assignments(self, courseids: list[int]) -> list[dict]:
        data = await self.call("mod_assign_get_assignments", courseids=courseids)
        return data.get("courses", [])

    async def submission_status(self, assignid: int) -> dict:
        return await self.call("mod_assign_get_submission_status", assignid=assignid)

    async def quizzes(self, courseids: list[int]) -> list[dict]:
        data = await self.call("mod_quiz_get_quizzes_by_courses", courseids=courseids)
        return data.get("quizzes", [])

    async def course_grades(self, userid: int) -> list[dict]:
        data = await self.call("gradereport_overview_get_course_grades", userid=userid)
        return data.get("grades", [])

    async def grade_items(self, courseid: int, userid: int) -> list[dict]:
        data = await self.call(
            "gradereport_user_get_grade_items", courseid=courseid, userid=userid
        )
        users = data.get("usergrades", [])
        return users[0].get("gradeitems", []) if users else []

    async def notifications(self, userid: int, limit: int = 10) -> list[dict]:
        data = await self.call(
            "message_popup_get_popup_notifications",
            cached=False,
            useridto=userid,
            newestfirst=True,
            limit=limit,
            offset=0,
        )
        return data.get("notifications", [])

    async def course_contents(self, courseid: int) -> list[dict]:
        return await self.call("core_course_get_contents", courseid=courseid)

    async def forums(self, courseids: list[int]) -> list[dict]:
        """Forum instances across courses (plain array)."""
        if not courseids:
            return []
        return await self.call("mod_forum_get_forums_by_courses", courseids=courseids)

    async def forum_discussions(self, forumid: int, perpage: int = 15) -> list[dict]:
        """Discussions in a forum, newest first. Handles both API names."""
        for fn in (
            "mod_forum_get_forum_discussions",
            "mod_forum_get_forum_discussions_paginated",
        ):
            try:
                data = await self.call(
                    fn, forumid=forumid, sortorder=1, page=0, perpage=perpage
                )
            except MoodleError:
                continue
            return data.get("discussions", [])
        return []


# --- helpers over raw payloads ----------------------------------------
def assignment_state(status: dict) -> tuple[str, str]:
    """(state, human label) from mod_assign_get_submission_status."""
    last = status.get("lastattempt") or {}
    submission = last.get("submission") or last.get("teamsubmission") or {}
    feedback = status.get("feedback") or {}
    if feedback.get("grade") and feedback["grade"].get("grade") not in (None, "", "-1.00000"):
        return "graded", "graded"
    if submission.get("status") == "submitted":
        return "submitted", "submitted"
    if last.get("submissionsenabled") is False:
        return "closed", "closed"
    return "todo", "not submitted"
