"""A Member's current Grade is their latest *confirmed* Promotion (#565).

Runs against PostgreSQL (db_session): the rule lives in
SqlGradeRepository.get_current_grade, and members_report goes through it.
"""

from __future__ import annotations

import uuid
from datetime import date

from app.grades.repository import SqlGradeRepository
from app.members.repository import SqlMemberRepository
from app.reports.repository import SqlReportRepository


async def _member(db_session) -> str:
    member = await SqlMemberRepository(db_session).add(
        {
            "email": f"{uuid.uuid4().hex[:8]}@dojo.test",
            "first_name": "Ai",
            "surname": "Sato",
            "dob": date(2010, 2, 28),
            "join_date": date(2026, 1, 1),
        }
    )
    return member["id"]


async def _confirmed_shodan_then_pending_nidan(db_session, member_id: str) -> None:
    grades = SqlGradeRepository(db_session)
    await grades.add_promotion(
        member_id, "SHODAN", "Shodan", None, "2026-01-15T00:00:00+00:00"
    )
    await grades.add_promotion(
        member_id,
        "NIDAN",
        "Nidan",
        None,
        "2026-06-15T00:00:00+00:00",
        status="pending",
    )


async def test_pending_promotion_is_not_the_current_grade(db_session) -> None:
    member_id = await _member(db_session)
    await _confirmed_shodan_then_pending_nidan(db_session, member_id)

    current = await SqlGradeRepository(db_session).get_current_grade(member_id)

    assert current["grade"] == "SHODAN"
    assert current["promoted_at"] == "2026-01-15T00:00:00+00:00"


async def test_only_pending_promotions_means_no_current_grade(db_session) -> None:
    member_id = await _member(db_session)
    await SqlGradeRepository(db_session).add_promotion(
        member_id, "SHODAN", "Shodan", None, "2026-01-15T00:00:00+00:00", "pending"
    )

    assert await SqlGradeRepository(db_session).get_current_grade(member_id) is None


async def test_members_report_shows_the_latest_confirmed_grade(db_session) -> None:
    member_id = await _member(db_session)
    await _confirmed_shodan_then_pending_nidan(db_session, member_id)

    rows = await SqlReportRepository(db_session).members_report()

    [row] = [r for r in rows if r["member_id"] == member_id]
    assert row["current_grade"] == "SHODAN"
