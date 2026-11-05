"""The week walk behind the Attendance Streak chart (#563).

An Attendance Streak (GLOSSARY.md) is a run of consecutive weeks, Monday to
Sunday by Session date, each with at least one Attendance. A week with no held
Sessions neither breaks nor extends it. The chart covers 1 January of the
current year to today.
"""

from datetime import date

from app.reports.streaks import Streak, longest_streak

# The Thursday of four consecutive weeks in March 2026.
WEEK_1, WEEK_2, WEEK_3, WEEK_4 = (date(2026, 3, d) for d in (5, 12, 19, 26))
TODAY = date(2026, 3, 29)


def test_consecutive_attended_weeks_make_a_streak():
    held = [WEEK_1, WEEK_2, WEEK_3]

    assert longest_streak(held, held, TODAY) == Streak(weeks=3, running=True)


def test_a_held_week_without_attendance_ends_the_streak():
    held = [WEEK_1, WEEK_2, WEEK_3, WEEK_4]
    attended = [WEEK_1, WEEK_2, WEEK_4]  # WEEK_3 is the gap

    assert longest_streak(held, attended, TODAY) == Streak(weeks=2, running=False)


def test_a_week_with_no_held_sessions_neither_breaks_nor_extends_it():
    # WEEK_3's only Session was cancelled, so it is not held at all.
    held = [WEEK_1, WEEK_2, WEEK_4]

    assert longest_streak(held, held, TODAY) == Streak(weeks=3, running=True)


def test_several_sessions_in_one_week_count_once():
    monday, thursday = date(2026, 3, 2), WEEK_1
    held = [monday, thursday, WEEK_2]

    assert longest_streak(held, held, TODAY) == Streak(weeks=2, running=True)


def test_only_sessions_from_1_january_count():
    # 1 January 2026 is a Thursday: its week runs Mon 29 Dec 2025 to Sun 4 Jan.
    new_year_week_2025_side, new_year_week_2026_side = (
        date(2025, 12, 30),
        date(2026, 1, 2),
    )
    week_before = date(2025, 12, 23)
    next_week = date(2026, 1, 6)
    today = date(2026, 1, 7)
    held = [week_before, new_year_week_2025_side, new_year_week_2026_side, next_week]

    # December's Attendance is last year's: it neither extends the streak nor
    # stands in for the 2 January Session missed in the same week.
    assert longest_streak(
        held, [week_before, new_year_week_2025_side, next_week], today
    ) == Streak(weeks=1, running=True)
    assert longest_streak(
        held, [week_before, new_year_week_2026_side, next_week], today
    ) == Streak(weeks=2, running=True)


def test_sessions_after_today_do_not_count():
    # Missing next week's Session cannot end a streak that is still running.
    held = [WEEK_1, WEEK_2, WEEK_3, WEEK_4]

    assert longest_streak(held, [WEEK_1, WEEK_2], date(2026, 3, 15)) == Streak(
        weeks=2, running=True
    )
