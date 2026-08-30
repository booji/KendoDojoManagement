"""How a member record is stored, for the stubs that stand in for the member
repository.

``members.dob`` and ``members.join_date`` are ``String(10)`` columns, so
``SqlMemberRepository`` converts a ``date`` to its ISO string on write. Three
test files carry their own member stub, and none of them did — so a stub could
hold a ``date`` where the implementation would hold a string, and
``MemberResponse`` rejects that.

Production used to paper over the difference: ``members/router.py`` and
``users/router.py`` converted the same values before every write. Those guards
are gone (#345), so the stubs have to store what the implementation stores.
Described once here rather than three times, for the reason
``dojo_settings_support.py`` exists (#221).
"""

from __future__ import annotations

from typing import Any

_DATE_COLUMNS = ("dob", "join_date")


def as_stored_member(data: dict[str, Any]) -> dict[str, Any]:
    """Return ``data`` the way SqlMemberRepository would store it."""
    stored = dict(data)
    for key in _DATE_COLUMNS:
        value = stored.get(key)
        if hasattr(value, "isoformat"):
            stored[key] = value.isoformat()
    return stored
