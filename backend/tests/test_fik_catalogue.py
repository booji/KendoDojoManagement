"""Syncing the bundled FIK affiliate list into the Federation catalogue (#613)."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.guards import REQUIRE_ADMIN
from app.auth.schemas import AccountClaims
from app.federations import fik_catalogue
from app.federations.db_models import Federation
from app.main import app
from app.member_federations.repository import SqlMemberFederationRepository
from app.members.repository import SqlMemberRepository


def _record(key: str = "JP", **overrides) -> dict:
    return {
        "source_key": key,
        "name": f"Federation {key}",
        "iso_code": key,
        "continental_grouping": "Asia",
        "website": f"https://{key.lower()}.example.org",
        "type": "National",
        **overrides,
    }


@pytest.fixture
async def session(db_session: AsyncSession) -> AsyncSession:
    """db_session without the FIK rows kendo-migrate synced into the test
    database (deleted inside its rolled-back transaction)."""
    await db_session.execute(delete(Federation).where(Federation.source == "fik"))
    return db_session


async def _rows(session: AsyncSession) -> dict[str, Federation]:
    result = await session.execute(select(Federation))
    return {r.name: r for r in result.scalars().all()}


async def _fik_names(session: AsyncSession) -> set[str]:
    return {n for n, r in (await _rows(session)).items() if r.source == "fik"}


def test_the_bundled_list_passes_the_schema_check() -> None:
    records = fik_catalogue.load()

    assert len(records) >= 60
    assert {"fik", "ekf", "lakc", "JP", "US-HI"} <= {r["source_key"] for r in records}


async def test_sync_inserts_every_affiliate(session: AsyncSession) -> None:
    await fik_catalogue.sync(session, [_record("JP"), _record("KR")])

    assert await _fik_names(session) == {"Federation JP", "Federation KR"}
    rows = await _rows(session)
    jp = rows["Federation JP"]
    assert (jp.source, jp.source_key, jp.iso_code) == ("fik", "JP", "JP")
    assert jp.website == "https://jp.example.org"
    assert (jp.is_active, jp.is_pinned, jp.abbreviation) == (True, False, None)


async def test_resync_updates_fik_fields_and_keeps_admin_fields(
    session: AsyncSession,
) -> None:
    await fik_catalogue.sync(session, [_record("JP")])
    row = (await _rows(session))["Federation JP"]
    row.abbreviation, row.is_pinned, row.is_active = "AJKF", True, False
    await session.flush()

    renamed = _record("JP", name="All Japan Kendo Federation", website=None)
    await fik_catalogue.sync(session, [renamed])
    await fik_catalogue.sync(session, [renamed])

    assert await _fik_names(session) == {"All Japan Kendo Federation"}
    rows = await _rows(session)
    jp = rows["All Japan Kendo Federation"]
    assert jp.id == row.id
    assert jp.website is None
    assert (jp.abbreviation, jp.is_pinned, jp.is_active) == ("AJKF", True, False)


async def test_an_affiliate_dropped_from_the_list_is_deactivated_not_deleted(
    session: AsyncSession,
) -> None:
    await fik_catalogue.sync(session, [_record("JP"), _record("KR")])

    await fik_catalogue.sync(session, [_record("JP")])

    rows = await _rows(session)
    assert rows["Federation KR"].is_active is False
    assert rows["Federation JP"].is_active is True


async def test_two_affiliates_can_swap_names_in_one_sync(
    session: AsyncSession,
) -> None:
    await fik_catalogue.sync(session, [_record("JP"), _record("KR")])
    ids = {n: r.id for n, r in (await _rows(session)).items()}

    await fik_catalogue.sync(
        session,
        [_record("JP", name="Federation KR"), _record("KR", name="Federation JP")],
    )

    rows = await _rows(session)
    assert rows["Federation KR"].source_key == "JP"
    assert rows["Federation JP"].source_key == "KR"
    assert rows["Federation KR"].id == ids["Federation JP"]


async def test_a_deactivated_affiliate_still_shows_on_its_federation_memberships(
    session: AsyncSession, db_client: AsyncSession
) -> None:
    await fik_catalogue.sync(session, [_record("JP"), _record("KR")])
    kr = (await _rows(session))["Federation KR"]
    member = await SqlMemberRepository(session).add(
        {
            "email": f"{uuid.uuid4().hex[:8]}@dojo.test",
            "first_name": "Ai",
            "surname": "Sato",
            "join_date": "2026-01-01",
            "membership_status": "active",
        }
    )
    await SqlMemberFederationRepository(session).add(
        {"member_id": member["id"], "federation_id": kr.id, "member_number": "K-1"}
    )

    await fik_catalogue.sync(session, [_record("JP")])
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: AccountClaims(
        sub=str(uuid.uuid4()), email="a@dojo.test", role="admin"
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test/api"
        ) as client:
            response = await client.get(f"/members/{member['id']}/federations")
    finally:
        app.dependency_overrides.clear()

    assert kr.is_active is False
    assert response.status_code == 200
    assert [(m["federation_id"], m["member_number"]) for m in response.json()] == [
        (kr.id, "K-1")
    ]


async def test_admin_added_federations_are_untouched(session: AsyncSession) -> None:
    session.add(Federation(name="Dojo League", abbreviation="DL", type="Other"))
    await session.flush()

    await fik_catalogue.sync(session, [_record("JP")])

    league = (await _rows(session))["Dojo League"]
    assert (league.source, league.abbreviation, league.type) == (None, "DL", "Other")
    assert league.is_active is True


async def test_a_name_taken_by_an_admin_row_stops_the_sync(
    session: AsyncSession,
) -> None:
    session.add(Federation(name="Federation JP"))
    await session.flush()

    with pytest.raises(RuntimeError, match="Federation JP"):
        await fik_catalogue.sync(session, [_record("JP"), _record("KR")])

    assert await _fik_names(session) == set()


async def test_sync_refuses_a_malformed_list(session: AsyncSession) -> None:
    with pytest.raises(ValueError):
        await fik_catalogue.sync(session, [_record("JP", type="Club")])
