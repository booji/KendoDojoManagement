"""Grade distribution on the Charts tab (#560).

How many counted Members hold each Grade, as of today. A Member's Grade is
their latest *confirmed* Promotion (#565); no confirmed Promotion means Mukyū.
Served from PostgreSQL (db_client) through GET /reports/grades.

Other tests leave Members in the shared database, so each test records the
distribution before it seeds and asserts only the change its own Members make.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.guards import REQUIRE_ADMIN
from app.auth.models import AccountClaims
from app.grades.models import Grade
from app.grades.repository import SqlGradeRepository
from app.main import app
from app.members.repository import SqlMemberRepository
from app.reports.repository import SqlReportRepository

_ADMIN = AccountClaims(sub=str(uuid.uuid4()), email="a@dojo.test", role="admin")


@pytest.fixture
def as_admin(db_client):
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: _ADMIN
    yield
    app.dependency_overrides.pop(REQUIRE_ADMIN, None)


async def _get(path: str, **kwargs):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        return await c.get(path, **kwargs)


async def _member(session, status: str = "active") -> str:
    member = await SqlMemberRepository(session).add(
        {
            "email": f"{uuid.uuid4().hex[:8]}@dojo.test",
            "first_name": "Ai",
            "surname": "Sato",
            "join_date": date(2026, 1, 1),
            "membership_status": status,
        }
    )
    return member["id"]


async def _promote(session, member_id: str, grade: str, status: str = "confirmed"):
    await SqlGradeRepository(session).add_promotion(
        member_id, grade, grade.title(), None, "2026-01-15T00:00:00+00:00", status
    )


async def _distribution(params: str = "") -> list[dict]:
    response = await _get(f"/reports/grades{params}")
    assert response.status_code == 200, response.text
    return response.json()


async def _counts(params: str = "") -> dict[str, int]:
    return {row["grade"]: row["count"] for row in await _distribution(params)}


def _change(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    """Each Grade whose count moved, by how much."""
    return {
        g: after.get(g, 0) - before.get(g, 0)
        for g in before.keys() | after.keys()
        if after.get(g, 0) != before.get(g, 0)
    }


async def test_a_member_with_no_promotion_counts_as_mukyu(db_client, as_admin):
    before = await _counts()
    await _member(db_client)

    after = await _distribution()

    assert after[0]["display_name"] == "Mukyū"
    assert _change(before, {r["grade"]: r["count"] for r in after}) == {"MUKYUU": 1}


async def test_bars_run_in_grade_order_up_to_the_highest_held_with_zeros_kept(
    db_client, as_admin
):
    before = await _counts()
    await _member(db_client)
    sankyu = await _member(db_client)
    await _promote(db_client, sankyu, "SANKYUU")
    ikkyu = await _member(db_client)
    await _promote(db_client, ikkyu, "IKKYUU")
    # Pending, so not their Grade yet (#565): Shodan does not move.
    await _promote(db_client, ikkyu, "SHODAN", status="pending")

    after = await _distribution()

    grades = [row["grade"] for row in after]
    assert grades == [g.value for g in Grade][: len(grades)]
    assert "IKKYUU" in grades
    assert after[-1]["count"] > 0
    assert _change(before, {r["grade"]: r["count"] for r in after}) == {
        "MUKYUU": 1,
        "SANKYUU": 1,
        "IKKYUU": 1,
    }


async def test_only_active_members_are_counted_by_default(db_client, as_admin):
    before = await _counts()
    await _member(db_client, "active")
    await _member(db_client, "inactive")
    await _member(db_client, "suspended")

    assert _change(before, await _counts()) == {"MUKYUU": 1}


async def test_the_status_filter_chooses_who_is_counted(db_client, as_admin):
    params = "?status=inactive&status=archived"
    before = await _counts(params)
    await _member(db_client, "active")
    await _member(db_client, "inactive")
    await _member(db_client, "suspended")
    await _member(db_client, "archived")

    assert _change(before, await _counts(params)) == {"MUKYUU": 2}


async def test_an_unknown_status_is_rejected(db_client, as_admin):
    response = await _get("/reports/grades?status=active&status=visitor")

    assert response.status_code == 422


async def test_no_counted_members_means_no_bars(db_client):
    assert await SqlReportRepository(db_client).grade_distribution([]) == []


async def test_members_may_not_see_the_distribution(cookies_for):
    member = AccountClaims(sub=str(uuid.uuid4()), email="m@dojo.test", role="member")

    response = await _get("/reports/grades", cookies=cookies_for(member))

    assert response.status_code == 403


async def test_the_distribution_needs_a_signed_in_admin():
    response = await _get("/reports/grades")

    assert response.status_code == 401
