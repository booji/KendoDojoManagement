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
from playwright.sync_api import Page, expect

from tests.e2e_support import API_URL, BASE_URL, authenticate

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

    today = datetime.date.today()
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    sundays = 0
    for n in range(1, days_in_month + 1):
        day = today.replace(day=n)
        weekday = day.weekday()
        if weekday in (calendar.TUESDAY, calendar.THURSDAY):
            session(day, "Evening keiko", "19:30", 90, "Kihon", "Keiko")
        elif weekday == calendar.WEDNESDAY and (n - 1) // 7 in (1, 3):  # 2nd and 4th
            session(day, "Shiai practice", "19:30", 90, "Shiai practice")
        elif weekday == calendar.SATURDAY:
            session(day, "Kids class", "10:00", 60, "Kids class")
        elif weekday == calendar.SUNDAY:
            sundays += 1
            if sundays == 3:
                session(day, "Dojo grading", "13:00", 180, "Grading")


def test_session_calendar_screenshots(page: Page) -> None:
    assert (
        OUT.is_dir()
    ), "docs/assets is not mounted at /screenshots — run `make screenshots`"
    token = authenticate(page, "admin", first_name="Aiko", surname="Tanaka")
    _seed(token)

    page.set_viewport_size({"width": 1280, "height": 640})
    for scheme in ("light", "dark"):
        page.emulate_media(color_scheme=scheme)
        page.goto(f"{BASE_URL}/sessions")
        page.get_by_role("button", name="Calendar").click()
        expect(page.get_by_role("button", name="Evening keiko").first).to_be_visible()
        page.screenshot(path=OUT / f"session-calendar-{scheme}.png")
