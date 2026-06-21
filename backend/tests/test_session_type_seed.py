"""Tests for default session-type seeding (issue #173).

Acceptance criteria:
  1. On a fresh database, all 13 default types exist after first boot.
  2. Each default type has a distinct, valid hex colour.
  3. Seeding does NOT run when any session type already exists.
  4. Types remain manageable exclusively in Admin Settings (no inline creation).

The seed constants are covered with a pure unit test; the guard behaviour is
covered by driving the seed function with a fake connection that records what
would be written, so the assertions are deterministic and DB-free.
"""

import re
from typing import Any

import pytest

from app.sessions.seed import DEFAULT_SESSION_TYPES, seed_session_types

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")

_EXPECTED_NAMES = {
    "General Keiko",
    "Kihon",
    "Kihon-Keiko-Ho",
    "Kata",
    "Beginners",
    "Kids",
    "Mudansha",
    "Yudansha",
    "Jigeiko",
    "Shiai",
    "Shiai Practice",
    "Bogu Practice",
    "Non Bogu Practice",
}


# --- AC1 / AC2: the default set itself --------------------------------------


def test_thirteen_defaults_with_expected_names() -> None:
    names = {name for name, _ in DEFAULT_SESSION_TYPES}
    assert len(DEFAULT_SESSION_TYPES) == 13
    assert names == _EXPECTED_NAMES


def test_every_default_has_a_valid_hex_colour() -> None:
    for name, colour in DEFAULT_SESSION_TYPES:
        assert _HEX.match(colour), f"{name} has invalid colour {colour!r}"


def test_default_colours_are_distinct() -> None:
    colours = [colour for _, colour in DEFAULT_SESSION_TYPES]
    assert len(set(colours)) == len(colours)


def test_default_names_are_distinct() -> None:
    names = [name for name, _ in DEFAULT_SESSION_TYPES]
    assert len(set(names)) == len(names)


# --- AC1 / AC3: the seeding guard -------------------------------------------


class _Result:
    def __init__(self, row: Any) -> None:
        self._row = row

    def fetchone(self) -> Any:
        return self._row


class _FakeConn:
    """Records insert payloads; first execute is the emptiness probe."""

    def __init__(self, existing_row: Any) -> None:
        self._existing_row = existing_row
        self.inserted: list[dict[str, Any]] = []

    async def execute(self, statement: Any, params: Any = None) -> _Result:
        if params is None:
            # SELECT probe for existing rows
            return _Result(self._existing_row)
        # INSERT with a list of row dicts
        self.inserted.extend(params)
        return _Result(None)


@pytest.mark.anyio
async def test_seed_inserts_all_defaults_on_empty_table() -> None:
    conn = _FakeConn(existing_row=None)
    inserted = await seed_session_types(conn)
    assert inserted == 13
    seeded_names = {row["name"] for row in conn.inserted}
    assert seeded_names == _EXPECTED_NAMES
    for row in conn.inserted:
        assert _HEX.match(row["colour"])
        assert row["id"]


@pytest.mark.anyio
async def test_seed_is_skipped_when_a_type_already_exists() -> None:
    conn = _FakeConn(existing_row=("some-existing-id",))
    inserted = await seed_session_types(conn)
    assert inserted == 0
    assert conn.inserted == []
