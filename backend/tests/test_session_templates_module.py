"""The Session Template lifecycle, exercised directly.

These rules used to live in five HTTP handlers, so reaching them meant an ASGI
request, an auth override and a response body. They now live in
``app/sessions/templates.py`` and are called the way the router calls them —
with the in-memory fakes standing in for the repositories (#337).

The router tests still cover the endpoints. What is new is that a question like
"does rescheduling preserve an edited instance?" can be asked of the module
that answers it.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.sessions import templates
from tests.fake_repositories import (
    InMemorySessionInstanceRepository,
    InMemorySessionTemplateRepository,
)

_MONDAY = "2026-01-05"


def _repos() -> (
    tuple[InMemorySessionTemplateRepository, InMemorySessionInstanceRepository]
):
    return InMemorySessionTemplateRepository(), InMemorySessionInstanceRepository()


def _template_data(**overrides: object) -> dict[str, object]:
    return {
        "title": "Weekly Keiko",
        "start_date": _MONDAY,
        "end_date": "2026-02-02",  # four Mondays inclusive
        "recurrence_days": [0],
        "interval_weeks": 1,
        "segments": [{"start_time": "19:00", "duration_minutes": 90, "type_ids": []}],
        **overrides,
    }


async def test_create_generates_an_instance_for_every_covered_date() -> None:
    template_repo, instance_repo = _repos()

    template = await templates.create(_template_data(), template_repo, instance_repo)

    dates = sorted(r["date"] for r in await instance_repo.list())
    assert dates == [
        "2026-01-05",
        "2026-01-12",
        "2026-01-19",
        "2026-01-26",
        "2026-02-02",
    ]
    assert all(r["template_id"] == template["id"] for r in await instance_repo.list())


async def test_generating_twice_to_the_same_horizon_adds_nothing() -> None:
    """Idempotence belongs to the module: the dates already persisted for this
    template are excluded, so a repeated call cannot double up."""
    template_repo, instance_repo = _repos()
    template = await templates.create(_template_data(), template_repo, instance_repo)
    horizon = date(2026, 3, 2)

    first = await templates.generate_to_horizon(
        template["id"], horizon, template_repo, instance_repo
    )
    second = await templates.generate_to_horizon(
        template["id"], horizon, template_repo, instance_repo
    )

    assert first, "the later horizon should have covered further Mondays"
    assert second == []
    dates = [r["date"] for r in await instance_repo.list()]
    assert len(dates) == len(set(dates))


async def test_generate_to_horizon_reports_an_unknown_template_as_none() -> None:
    template_repo, instance_repo = _repos()

    assert (
        await templates.generate_to_horizon(
            "no-such-template", date(2026, 3, 2), template_repo, instance_repo
        )
        is None
    )


async def test_rescheduling_leaves_an_edited_instance_on_a_covered_date_alone() -> None:
    """#258 AC3: a date the recurrence still covers keeps whatever is there,
    edits included. Only dates that fall out of coverage are removed."""
    template_repo, instance_repo = _repos()
    template = await templates.create(_template_data(), template_repo, instance_repo)
    edited = next(r for r in await instance_repo.list() if r["date"] == "2026-01-12")
    await instance_repo.update(edited["id"], {"title": "Individually Edited"})

    await templates.reschedule(
        template["id"], {"location": "Second Hall"}, template_repo, instance_repo
    )

    preserved = await instance_repo.get(edited["id"])
    assert preserved is not None, "an instance on a still-covered date must survive"
    assert preserved["title"] == "Individually Edited"


async def test_rescheduling_onto_another_weekday_moves_the_instances() -> None:
    template_repo, instance_repo = _repos()
    template = await templates.create(_template_data(), template_repo, instance_repo)

    await templates.reschedule(
        template["id"], {"recurrence_days": [2]}, template_repo, instance_repo
    )

    weekdays = {
        date.fromisoformat(r["date"]).weekday() for r in await instance_repo.list()
    }
    assert weekdays == {2}, "Mondays no longer covered should have been removed"


async def test_extending_beyond_the_horizon_cap_is_refused() -> None:
    template_repo, instance_repo = _repos()
    template = await templates.create(_template_data(), template_repo, instance_repo)

    with pytest.raises(ValueError, match="months from today"):
        await templates.extend(
            template["id"],
            date.today() + timedelta(days=365),
            template_repo,
            instance_repo,
        )


async def test_extending_backwards_is_refused() -> None:
    template_repo, instance_repo = _repos()
    template = await templates.create(_template_data(), template_repo, instance_repo)

    with pytest.raises(ValueError, match="earlier than"):
        await templates.extend(
            template["id"], date(2026, 1, 12), template_repo, instance_repo
        )


async def test_extending_generates_the_newly_covered_dates() -> None:
    template_repo, instance_repo = _repos()
    template = await templates.create(_template_data(), template_repo, instance_repo)
    before = len(await instance_repo.list())

    new_end = date.today() + timedelta(days=21)
    extended = await templates.extend(
        template["id"], new_end, template_repo, instance_repo
    )

    assert extended is not None
    assert extended["end_date"] == new_end.isoformat()
    assert len(await instance_repo.list()) > before


async def test_cancelling_a_series_leaves_the_past_intact() -> None:
    """Past instances record training that happened; cancelling the series
    does not unmake it."""
    template_repo, instance_repo = _repos()
    template = await templates.create(_template_data(), template_repo, instance_repo)
    future = await instance_repo.add(
        {
            "title": "Weekly Keiko",
            "date": (date.today() + timedelta(days=7)).isoformat(),
            "template_id": template["id"],
        }
    )

    cancelled = await templates.cancel(template["id"], template_repo, instance_repo)

    assert cancelled is not None
    assert cancelled["is_active"] is False
    assert (await instance_repo.get(future["id"]))["cancelled"] is True
    past = [
        r for r in await instance_repo.list() if r["date"] < date.today().isoformat()
    ]
    assert past, "the seeded template's dates are in the past"
    assert all(r["cancelled"] is False for r in past)


async def test_cancelling_an_unknown_template_reports_none() -> None:
    template_repo, instance_repo = _repos()

    assert (
        await templates.cancel("no-such-template", template_repo, instance_repo) is None
    )
