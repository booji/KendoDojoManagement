"""A Member's current Grade is their latest *confirmed* Promotion (#565).

Runs against PostgreSQL (db_session): the rule lives in
SqlGradeRepository.get_current_grade, and the members CSV goes through it.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.guards import REQUIRE_ADMIN
from app.auth.schemas import AccountClaims
from app.grades.repository import SqlGradeRepository
from app.main import app
from app.members.repository import SqlMemberRepository

_ADMIN = AccountClaims(sub=str(uuid.uuid4()), email="a@dojo.test", role="admin")


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


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
        member_id, "SHODAN", "Shodan (1-dan)", None, "2026-01-15T00:00:00+00:00"
    )
    await grades.add_promotion(
        member_id,
        "NIDAN",
        "Nidan (2-dan)",
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


async def test_members_csv_writes_the_confirmed_grade_name_and_number(
    db_client,
) -> None:
    """The members CSV's current_grade is the short Grade name, and
    grade_number right after it the sortable Grade number (#571): the latest
    confirmed Promotion, both blank for a Member with none."""
    shodan = await _member(db_client)
    await _confirmed_shodan_then_pending_nidan(db_client, shodan)
    ikkyuu = await _member(db_client)
    await SqlGradeRepository(db_client).add_promotion(
        ikkyuu, "IKKYUU", "Ikkyū (1-kyu)", None, "2026-01-15T00:00:00+00:00"
    )
    ungraded = await _member(db_client)
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: _ADMIN

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/reports/members/csv")

    assert response.status_code == 200, response.text
    reader = csv.DictReader(io.StringIO(response.text))
    rows = {r["member_id"]: r for r in reader}
    assert reader.fieldnames == [
        "member_id",
        "display_name",
        "join_date",
        "current_grade",
        "grade_number",
    ]
    grade = {m: (rows[m]["current_grade"], rows[m]["grade_number"]) for m in rows}
    assert grade[shodan] == ("Shodan", "1")
    assert grade[ikkyuu] == ("Ikkyū", "-1")
    assert grade[ungraded] == ("", "")
