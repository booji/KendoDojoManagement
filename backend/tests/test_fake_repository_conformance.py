"""Every implementation of a repository interface must match that interface.

A Protocol is structural: Python verifies nothing at definition or at
instantiation, and ``app.dependency_overrides`` is typed
``dict[Callable, Callable]``, so nothing checks a test double against the
interface it stands in for either. That gap is how ``app/sessions/router.py``
came to ask ``hasattr(repo, "list_in_range")`` -- most stubs simply did not have
the method the interface declares (#337).

This walks each interface's members and checks both implementations -- the fake
and the SQL one -- for presence, parameter names, kinds, defaults, and
coroutine-ness.

Checking the SQL implementation too costs one row in the table and catches the
reverse drift: an interface growing a member that only the fake implements.

ponytail: shape only, never behaviour. Whether the fake derives a session's
envelope the way the SQL implementation does is not covered here -- the e2e
suite exercises the SQL path. Upgrade path is a shared contract suite run
against both implementations, worth writing only if the two are found to have
drifted in behaviour rather than in shape.

Annotations are deliberately not compared: they are strings under
``from __future__ import annotations`` and would fail on formatting rather than
on meaning.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from app.attendance.repository import (
    AbstractAttendanceRepository,
    SqlAttendanceRepository,
)
from app.attendance.repository import (
    AbstractSessionInstanceRepository as AbstractAttendanceSessionInstanceRepository,
)
from app.attendance.repository import (
    SqlSessionInstanceRepository as SqlAttendanceSessionInstanceRepository,
)
from app.members.repository import AbstractMemberRepository, SqlMemberRepository
from app.sessions.repository import (
    AbstractSessionInstanceRepository,
    AbstractSessionTemplateRepository,
    AbstractSessionTypeRepository,
    SqlSessionInstanceRepository,
    SqlSessionTemplateRepository,
    SqlSessionTypeRepository,
)
from tests.fake_repositories import (
    InMemoryAttendanceRepository,
    InMemoryMemberRepository,
    InMemorySessionInstanceRepository,
    InMemorySessionTemplateRepository,
    InMemorySessionTypeRepository,
)

# (interface, implementation) — every implementation of every interface the
# fakes cover, fake and SQL alike.
_PAIRS = [
    (AbstractSessionTypeRepository, InMemorySessionTypeRepository),
    (AbstractSessionTypeRepository, SqlSessionTypeRepository),
    (AbstractSessionTemplateRepository, InMemorySessionTemplateRepository),
    (AbstractSessionTemplateRepository, SqlSessionTemplateRepository),
    (AbstractSessionInstanceRepository, InMemorySessionInstanceRepository),
    (AbstractSessionInstanceRepository, SqlSessionInstanceRepository),
    # The narrower same-named interface Attendance declares. One fake serves
    # both; the SQL side has a separate implementation.
    (
        AbstractAttendanceSessionInstanceRepository,
        InMemorySessionInstanceRepository,
    ),
    (
        AbstractAttendanceSessionInstanceRepository,
        SqlAttendanceSessionInstanceRepository,
    ),
    (AbstractAttendanceRepository, InMemoryAttendanceRepository),
    (AbstractAttendanceRepository, SqlAttendanceRepository),
    (AbstractMemberRepository, InMemoryMemberRepository),
    (AbstractMemberRepository, SqlMemberRepository),
]


def _interface_members(interface: type) -> list[str]:
    return sorted(
        name
        for name, value in vars(interface).items()
        if not name.startswith("_") and callable(value)
    )


def _shape(func: Any) -> list[tuple[str, Any, Any]]:
    """Parameter names, kinds and defaults — annotations excluded on purpose."""
    return [
        (p.name, p.kind, p.default) for p in inspect.signature(func).parameters.values()
    ]


@pytest.mark.parametrize(
    "interface, implementation",
    _PAIRS,
    ids=[f"{i.__name__}-{impl.__name__}" for i, impl in _PAIRS],
)
def test_implementation_matches_interface(
    interface: type, implementation: type
) -> None:
    members = _interface_members(interface)
    assert members, f"{interface.__name__} declares no members to check"

    for name in members:
        declared = getattr(interface, name)
        actual = getattr(implementation, name, None)

        assert actual is not None, (
            f"{implementation.__name__} is missing {name}(), which "
            f"{interface.__name__} declares. A partial implementation is what "
            f"grows hasattr() branches in production code."
        )
        assert _shape(actual) == _shape(declared), (
            f"{implementation.__name__}.{name}() does not match "
            f"{interface.__name__}.{name}()"
        )
        assert inspect.iscoroutinefunction(actual) == inspect.iscoroutinefunction(
            declared
        ), f"{implementation.__name__}.{name}() differs in async-ness"
