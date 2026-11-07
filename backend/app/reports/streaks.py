"""Attendance Streak (GLOSSARY.md): the week walk, kept free of the database."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class Streak:
    weeks: int
    running: bool


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def longest_streak(
    held: Iterable[date], attended: Iterable[date], today: date
) -> Streak:
    """The Member's longest Attendance Streak from 1 January to today.

    ``held`` are the dates of held Sessions, ``attended`` those of the Sessions
    the Member attended; dates outside the year to date are ignored, so the
    week holding 1 January counts only its days in the new year.
    """

    def in_year(dates: Iterable[date]) -> set[date]:
        return {d for d in dates if date(today.year, 1, 1) <= d <= today}

    held_weeks = sorted({_monday(d) for d in in_year(held)})
    attended_weeks = {_monday(d) for d in in_year(attended)}
    # The current week has not ended, so until it has Attendance it can
    # neither break nor extend the streak.
    this_week = _monday(today)
    if this_week not in attended_weeks and this_week in held_weeks:
        held_weeks.remove(this_week)
    run = best = 0
    for week in held_weeks:
        run = run + 1 if week in attended_weeks else 0
        best = max(best, run)
    # The run still open at the end is unbroken as of today. On a tie it is the
    # one reported, so the chart can mark it.
    return Streak(weeks=best, running=run > 0 and run == best)
