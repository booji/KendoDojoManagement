"""Regenerates the session-calendar screenshots in docs/assets (issue #416).

Not a test: the filename is outside pytest's ``test_*.py`` pattern, so the
suite never collects it. It is a pytest file only to borrow the e2e harness —
``run_tests.sh`` brings up uvicorn and Vite on a fresh per-run database, which
this fills with a made-up dojo. No real member data ever reaches an image.

    make screenshots
"""

from __future__ import annotations

import calendar
import datetime
from pathlib import Path

import requests
from playwright.sync_api import Browser, expect

from tests.e2e_support import (
    API_URL,
    BASE_URL,
    complete_onboarding,
    make_token,
    set_cookie,
)

# `make screenshots` bind-mounts docs/assets here.
OUT = Path("/screenshots")

TYPES = {
    "Keiko": "#2563eb",
    "Kihon": "#16a34a",
    "Kids class": "#d97706",
    "Shiai practice": "#7c3aed",
    "Grading": "#dc2626",
}


def _seed(token: str) -> None:
    cookies = {"access_token": token}

    def call(method: str, path: str, body: dict) -> dict:
        resp = requests.request(method, f"{API_URL}{path}", json=body, cookies=cookies)
        resp.raise_for_status()
        return resp.json()

    call("PUT", "/settings/dojo", {"dojo_name": "Riverside Kendo Club"})
    # Migrations seed a few types; reuse those, create the rest.
    existing = requests.get(f"{API_URL}/session-types", cookies=cookies).json()
    type_ids = {t["name"]: t["id"] for t in existing}
    for name, colour in TYPES.items():
        if name not in type_ids:
            type_ids[name] = call("POST", "/session-types", {"name": name})["id"]
        type_id = type_ids[name]
        call("PUT", f"/session-types/{type_id}", {"colour": colour})

    def session(
        day: datetime.date, title: str, start: str, minutes: int, *types
    ) -> None:
        call(
            "POST",
            "/sessions",
            {
                "title": title,
                "date": day.isoformat(),
                "location": "Riverside Sports Centre",
                "segments": [
                    {
                        "start_time": start,
                        "duration_minutes": minutes,
                        "type_ids": [type_ids[t] for t in types],
                    }
                ],
            },
        )

    # This month and next: the month grid shows this one, and the mobile list
    # only shows what is still upcoming.
    first = datetime.date.today().replace(day=1)
    for i in range(62):
        day = first + datetime.timedelta(days=i)
        weekday, week = day.weekday(), (day.day - 1) // 7
        if weekday in (calendar.TUESDAY, calendar.THURSDAY):
            session(day, "Evening keiko", "19:30", 90, "Kihon", "Keiko")
        elif weekday == calendar.WEDNESDAY and week in (1, 3):
            session(day, "Shiai practice", "19:30", 90, "Shiai practice")
        elif weekday == calendar.SATURDAY:
            session(day, "Kids class", "10:00", 60, "Kids class")
        elif weekday == calendar.SUNDAY and week == 2:
            session(day, "Dojo grading", "13:00", 180, "Grading")


# Mobile has no List/Calendar toggle: below md the page is always the list.
VIEWS = {
    "": {"viewport": {"width": 1280, "height": 640}},
    "-mobile": {"viewport": {"width": 390, "height": 844}, "device_scale_factor": 2},
}


def test_session_calendar_screenshots(browser: Browser) -> None:
    assert OUT.is_dir(), (
        "docs/assets is not mounted at /screenshots — run `make screenshots`"
    )
    token = make_token("admin")
    complete_onboarding(token, first_name="Aiko", surname="Tanaka")
    _seed(token)

    for suffix, options in VIEWS.items():
        for scheme in ("light", "dark"):
            context = browser.new_context(color_scheme=scheme, **options)
            page = context.new_page()
            set_cookie(page, token)
            page.goto(f"{BASE_URL}/sessions")
            if not suffix:
                page.get_by_role("button", name="Calendar").click()
            expect(
                page.locator("text=Evening keiko >> visible=true").first
            ).to_be_visible()
            page.screenshot(path=OUT / f"session-calendar{suffix}-{scheme}.png")
            context.close()
