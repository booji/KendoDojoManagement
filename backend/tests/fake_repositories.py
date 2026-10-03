"""In-memory fakes for the session, attendance and member repository interfaces.

These are *fakes*, not stubs: a working implementation of the whole interface,
not canned answers for the two methods one test happens to call. That
distinction is the point of issue #337.

Seventeen test files used to carry their own ``StubSessionInstanceRepo``, and
only four of them implemented ``list_in_range``. Production code grew branches
to tolerate that -- ``hasattr(repo, "list_in_range")`` and a ``_with_envelope``
fallback in ``app/sessions/router.py`` -- so a partial test double was shaping
the production interface. One complete implementation per interface removes the
reason those branches exist.

``members`` repeated the shape: eleven partial stubs, three of which stored a
``date`` where the implementation stores an ISO string, and two routers
converting before every write to compensate (#348).

Seeding follows Front Door First (Meszaros, *xUnit Test Patterns*): fixture data
enters through the constructor or ``seed(**overrides)``, both of which funnel
into the same private ``_insert`` that ``add()`` uses. Tests never touch
``_store``. A record a test plants is therefore always a shape production could
have produced -- which is exactly the invariant the ``_with_envelope`` fallback
was written to paper over.

Unknown keys are rejected rather than stored, mirroring ``SessionInstance(**data)``
raising on a column that does not exist. A test seeding a field the schema has
never had fails at the seed, not three assertions later.

The record projections below deliberately mirror ``_instance_to_dict`` /
``_template_to_dict`` / ``_type_to_dict`` in ``app/sessions/repository.py``, and
reuse that module's envelope helpers rather than recomputing the derivation, so
there is exactly one definition of a session's displayed time.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime
from typing import Any

# Private imports on purpose: the fake must project a record the same way the
# SQL implementation does, and importing the derivation is the only way to
# guarantee that without a second copy of it drifting.
from sqlalchemy.exc import IntegrityError

from app.sessions.repository import _minutes_between, _segments_envelope

# ---------------------------------------------------------------------------
# Row handling shared by the three session fakes
# ---------------------------------------------------------------------------


def _row(defaults: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """Apply column defaults to seeded data, rejecting keys that are not columns."""
    unknown = set(data) - set(defaults)
    if unknown:
        raise TypeError(
            f"unknown column(s) {sorted(unknown)} -- the SQL repository would "
            f"raise here too. Known columns: {sorted(defaults)}"
        )
    return {**defaults, **data}


def _segments(segments_data: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Build stored segments, assigning the ids the database would assign."""
    return [
        {
            "id": seg.get("id") or str(uuid.uuid4()),
            "start_time": seg["start_time"],
            "duration_minutes": seg["duration_minutes"],
            "title": seg.get("title"),
            "note": seg.get("note"),
            "type_ids": list(seg.get("type_ids") or []),
        }
        for seg in segments_data or []
    ]


# One segment that yields a valid envelope, so ``seed()`` with no arguments
# produces a record the router can render.
def _default_segments() -> list[dict[str, Any]]:
    return [
        {
            "start_time": "19:00",
            "duration_minutes": 90,
            "title": None,
            "note": None,
            "type_ids": [],
        }
    ]


# ---------------------------------------------------------------------------
# Session types
# ---------------------------------------------------------------------------


class InMemorySessionTypeRepository:
    """In-memory implementation of ``AbstractSessionTypeRepository``."""

    _DEFAULTS: dict[str, Any] = {"id": None, "name": None, "colour": None}

    def __init__(self, records: list[dict[str, Any]] | None = None) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        for record in records or []:
            self._insert(record)

    # -- seeding ------------------------------------------------------------

    def seed(self, **overrides: Any) -> dict[str, Any]:
        return self._insert(overrides)

    def _insert(self, data: dict[str, Any]) -> dict[str, Any]:
        row = _row(self._DEFAULTS, data)
        if row["name"] is None:
            raise TypeError("a session type needs a name")
        if any(r["name"] == row["name"] for r in self._store.values()):
            raise ValueError(f"Session type '{row['name']}' already exists")
        row["id"] = row["id"] or str(uuid.uuid4())
        self._store[row["id"]] = row
        return dict(row)

    # -- interface ----------------------------------------------------------

    async def add(self, name: str) -> dict[str, Any]:
        return self._insert({"name": name})

    async def get_by_name(self, name: str) -> dict[str, Any] | None:
        return next((dict(r) for r in self._store.values() if r["name"] == name), None)

    async def get(self, type_id: str) -> dict[str, Any] | None:
        row = self._store.get(type_id)
        return dict(row) if row else None

    async def list(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._store.values()]

    async def update(self, type_id: str, colour: str | None) -> dict[str, Any] | None:
        row = self._store.get(type_id)
        if row is None:
            return None
        row["colour"] = colour
        return dict(row)

    async def delete(self, type_id: str) -> dict[str, Any] | None:
        row = self._store.pop(type_id, None)
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# Session templates
# ---------------------------------------------------------------------------


class InMemorySessionTemplateRepository:
    """In-memory implementation of ``AbstractSessionTemplateRepository``."""

    _DEFAULTS: dict[str, Any] = {
        "id": None,
        "title": "Template",
        "start_date": None,
        "end_date": None,
        "recurrence": "weekly",
        "day_of_week": None,
        "location": None,
        "recurrence_days": [],
        "interval_weeks": 1,
        "info": None,
        "coach_notes": None,
        "is_active": True,
        "segments": None,
    }

    def __init__(self, records: list[dict[str, Any]] | None = None) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        for record in records or []:
            self._insert(record)

    # -- seeding ------------------------------------------------------------

    def seed(self, **overrides: Any) -> dict[str, Any]:
        return self._insert(overrides)

    def _insert(self, data: dict[str, Any]) -> dict[str, Any]:
        row = _row(self._DEFAULTS, data)
        row["id"] = row["id"] or str(uuid.uuid4())
        row["start_date"] = row["start_date"] or date.today().isoformat()
        row["end_date"] = row["end_date"] or date.today().isoformat()
        row["segments"] = _segments(
            row["segments"] if row["segments"] is not None else _default_segments()
        )
        self._store[row["id"]] = row
        return _template_record(row)

    # -- interface ----------------------------------------------------------

    async def add(self, data: dict[str, Any]) -> dict[str, Any]:
        return self._insert(data)

    async def get(self, template_id: str) -> dict[str, Any] | None:
        row = self._store.get(template_id)
        return _template_record(row) if row else None

    async def list(self) -> list[dict[str, Any]]:
        return [_template_record(r) for r in self._store.values()]

    async def update(
        self, template_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        row = self._store.get(template_id)
        if row is None:
            return None
        updates = _row(self._DEFAULTS, data) if data else {}
        for key, value in data.items():
            row[key] = _segments(value) if key == "segments" else updates[key]
        return _template_record(row)

    async def deactivate(self, template_id: str) -> dict[str, Any] | None:
        row = self._store.get(template_id)
        if row is None:
            return None
        row["is_active"] = False
        return _template_record(row)


def _template_record(row: dict[str, Any]) -> dict[str, Any]:
    """Mirror of ``_template_to_dict`` in app/sessions/repository.py."""
    raw_days = row["recurrence_days"]
    if isinstance(raw_days, str):
        try:
            recurrence_days = json.loads(raw_days)
        except json.JSONDecodeError:
            recurrence_days = []
    else:
        recurrence_days = list(raw_days or [])
    segments = [dict(s) for s in row["segments"]]
    start_time, end_time = _segments_envelope(segments)
    return {
        "id": row["id"],
        "title": row["title"],
        "start_date": row["start_date"],
        "end_date": row["end_date"],
        "start_time": start_time,
        "duration_minutes": _minutes_between(start_time, end_time) if segments else 0,
        "recurrence": row["recurrence"],
        "day_of_week": row["day_of_week"],
        "location": row["location"],
        "recurrence_days": recurrence_days,
        "interval_weeks": row["interval_weeks"] if row["interval_weeks"] else 1,
        "info": row["info"],
        "coach_notes": row["coach_notes"],
        "is_active": row["is_active"],
        "segments": segments,
    }


# ---------------------------------------------------------------------------
# Session instances
# ---------------------------------------------------------------------------


class InMemorySessionInstanceRepository:
    """In-memory implementation of ``AbstractSessionInstanceRepository``.

    Satisfies both the interface in ``app/sessions/repository.py`` and the
    narrower one of the same name declared in ``app/attendance/repository.py``.
    """

    _DEFAULTS: dict[str, Any] = {
        "id": None,
        "title": "Session",
        "date": None,
        "template_id": None,
        "cancelled": False,
        "location": None,
        "info": None,
        "coach_notes": None,
        "checkin_window_before_minutes": None,
        "checkin_window_after_minutes": None,
        "segments": None,
    }

    def __init__(self, records: list[dict[str, Any]] | None = None) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        for record in records or []:
            self._insert(record)

    # -- seeding ------------------------------------------------------------

    def seed(self, **overrides: Any) -> dict[str, Any]:
        return self._insert(overrides)

    def _insert(self, data: dict[str, Any]) -> dict[str, Any]:
        row = _row(self._DEFAULTS, data)
        row["id"] = row["id"] or str(uuid.uuid4())
        row["date"] = row["date"] or date.today().isoformat()
        row["segments"] = _segments(
            row["segments"] if row["segments"] is not None else _default_segments()
        )
        self._store[row["id"]] = row
        return _instance_record(row)

    # -- interface ----------------------------------------------------------

    async def add(self, data: dict[str, Any]) -> dict[str, Any]:
        return self._insert(data)

    async def get(self, instance_id: str) -> dict[str, Any] | None:
        row = self._store.get(instance_id)
        return _instance_record(row) if row else None

    async def list(self) -> list[dict[str, Any]]:
        return [_instance_record(r) for r in self._store.values()]

    async def list_upcoming(self, as_of: date | None = None) -> list[dict[str, Any]]:
        today = (as_of or date.today()).isoformat()
        return [
            _instance_record(r)
            for r in self._store.values()
            if r["date"] >= today and not r["cancelled"]
        ]

    async def list_in_range(
        self, from_date: date, to_date: date
    ) -> list[dict[str, Any]]:
        from_iso, to_iso = from_date.isoformat(), to_date.isoformat()
        return [
            _instance_record(r)
            for r in self._store.values()
            if from_iso <= r["date"] <= to_iso
        ]

    async def cancel(self, instance_id: str) -> dict[str, Any] | None:
        row = self._store.get(instance_id)
        if row is None:
            return None
        row["cancelled"] = True
        return _instance_record(row)

    async def update(
        self, instance_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        row = self._store.get(instance_id)
        if row is None:
            return None
        updates = _row(self._DEFAULTS, data) if data else {}
        for key, value in data.items():
            row[key] = _segments(value) if key == "segments" else updates[key]
        return _instance_record(row)

    async def delete(self, instance_id: str) -> dict[str, Any] | None:
        row = self._store.pop(instance_id, None)
        return _instance_record(row) if row else None

    async def cancel_future_for_template(
        self, template_id: str, as_of_date: date
    ) -> list[dict[str, Any]]:
        as_of = as_of_date.isoformat()
        cancelled = []
        for row in self._store.values():
            if (
                row["template_id"] == template_id
                and row["date"] >= as_of
                and not row["cancelled"]
            ):
                row["cancelled"] = True
                cancelled.append(_instance_record(row))
        return cancelled

    async def delete_future_for_template(
        self, template_id: str, as_of_date: date
    ) -> int:
        as_of = as_of_date.isoformat()
        doomed = [
            row_id
            for row_id, row in self._store.items()
            if row["template_id"] == template_id and row["date"] >= as_of
        ]
        for row_id in doomed:
            del self._store[row_id]
        return len(doomed)


def _instance_record(row: dict[str, Any]) -> dict[str, Any]:
    """Mirror of ``_instance_to_dict`` in app/sessions/repository.py.

    ``end_time`` is the one addition. Attendance declares its own narrower
    ``AbstractSessionInstanceRepository`` served by a *different*
    ``SqlSessionInstanceRepository`` (app/attendance/repository.py), whose
    projection carries ``end_time`` because the check-in window needs it. One
    fake serves both interfaces, so it carries the union. The extra field never
    reaches a sessions response: the router normalises through
    ``SessionInstanceRead``, which drops anything it does not declare.
    """
    segments = [dict(s) for s in row["segments"]]
    start_time, end_time = _segments_envelope(segments)
    return {
        "id": row["id"],
        "title": row["title"],
        "scheduled_at": f"{row['date']}T{start_time}:00",
        "start_time": start_time,
        "end_time": end_time,
        "duration_minutes": _minutes_between(start_time, end_time) if segments else 0,
        "location": row["location"],
        "template_id": row["template_id"],
        "status": "cancelled" if row["cancelled"] else "scheduled",
        "date": row["date"],
        "cancelled": row["cancelled"],
        "info": row["info"],
        "coach_notes": row["coach_notes"],
        "checkin_window_before_minutes": row["checkin_window_before_minutes"],
        "checkin_window_after_minutes": row["checkin_window_after_minutes"],
        "segments": segments,
    }


# ---------------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------------


class InMemoryAttendanceRepository:
    """In-memory implementation of ``AbstractAttendanceRepository``.

    ``display_names`` stands in for the outer join the SQL implementation does
    against Member: a mapping of member id to the name that join would resolve.
    Absent an entry, the name comes back None, which is what the SQL path
    returns for an attendance row with no matching Member. It is public and
    mutable so a test can name a member after construction -- that is fixture
    configuration, not a back door into stored records.
    """

    _DEFAULTS: dict[str, Any] = {
        "id": None,
        "session_id": None,
        "member_id": None,
        "visitor_name": None,
        "checked_in_at": None,
        "recorded_by": None,
    }

    def __init__(
        self,
        records: list[dict[str, Any]] | None = None,
        display_names: dict[str, str] | None = None,
    ) -> None:
        self._store: list[dict[str, Any]] = []
        self.display_names = dict(display_names or {})
        for record in records or []:
            self._insert(record)

    # -- seeding ------------------------------------------------------------

    def seed(self, **overrides: Any) -> dict[str, Any]:
        return self._insert(overrides)

    def _insert(self, data: dict[str, Any]) -> dict[str, Any]:
        row = _row(self._DEFAULTS, data)
        row["id"] = row["id"] or str(uuid.uuid4())
        row["checked_in_at"] = row["checked_in_at"] or datetime.now(UTC).isoformat()
        self._store.append(row)
        return dict(row)

    def _named(self, row: dict[str, Any]) -> dict[str, Any]:
        return {**row, "display_name": self.display_names.get(row["member_id"])}

    # -- interface ----------------------------------------------------------

    def _refuse_duplicate(self, session_id: str, member_id: str) -> None:
        # Mirrors uq_attendance_session_member (#431), as the database says it.
        if any(
            r["session_id"] == session_id and r["member_id"] == member_id
            for r in self._store
        ):
            raise IntegrityError(
                "INSERT INTO attendance",
                {},
                Exception('unique constraint "uq_attendance_session_member"'),
            )

    async def check_in(
        self, session_id: str, member_id: str, recorded_by: str
    ) -> dict[str, Any]:
        self._refuse_duplicate(session_id, member_id)
        return self._insert(
            {
                "session_id": session_id,
                "member_id": member_id,
                "recorded_by": recorded_by,
            }
        )

    async def list_for_session(self, session_id: str) -> list[dict[str, Any]]:
        return [self._named(r) for r in self._store if r["session_id"] == session_id]

    async def get_by_session_member(
        self, session_id: str, member_id: str
    ) -> dict[str, Any] | None:
        return next(
            (
                dict(r)
                for r in self._store
                if r["session_id"] == session_id and r["member_id"] == member_id
            ),
            None,
        )

    async def admin_mark_attended(
        self, session_id: str, member_id: str, recorded_by: str
    ) -> dict[str, Any]:
        self._refuse_duplicate(session_id, member_id)
        record = self._insert(
            {
                "session_id": session_id,
                "member_id": member_id,
                "visitor_name": None,
                "recorded_by": recorded_by,
            }
        )
        return self._named(record)

    async def remove_attendance(self, session_id: str, member_id: str) -> bool:
        for index, row in enumerate(self._store):
            if row["session_id"] == session_id and row["member_id"] == member_id:
                del self._store[index]
                return True
        return False

    async def add_visitor(
        self, session_id: str, visitor_name: str, recorded_by: str
    ) -> dict[str, Any]:
        return self._insert(
            {
                "session_id": session_id,
                "member_id": None,
                "visitor_name": visitor_name,
                "recorded_by": recorded_by,
            }
        )

    async def list_for_member(self, member_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self._store if r["member_id"] == member_id]

    async def summary_for_sessions(
        self, session_ids: list[str], member_id: str | None
    ) -> dict[str, dict[str, Any]]:
        wanted = set(session_ids)
        rows = [r for r in self._store if r["session_id"] in wanted]
        return {
            session_id: {
                "attendance_count": sum(
                    1 for r in rows if r["session_id"] == session_id
                ),
                # member_id None (a user with no member record) is never
                # checked in -- matching it against a visitor row's NULL
                # member_id is the bug the SQL path guards too (#340).
                "is_checked_in": member_id is not None
                and any(
                    r["session_id"] == session_id and r["member_id"] == member_id
                    for r in rows
                ),
            }
            for session_id in session_ids
        }


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------

# ``members.dob`` and ``members.join_date`` are ``String(10)`` columns, so
# ``SqlMemberRepository`` writes a ``date`` as its ISO string. Eleven partial
# stubs stored whatever they were handed, and ``members/router.py`` and
# ``users/router.py`` each converted before writing to compensate -- production
# shaped by incomplete test doubles, the shape #337 found for sessions. #345
# deleted those guards; the rule lives here now (#348).
_MEMBER_DATE_COLUMNS = ("dob", "join_date")


def _stored_member(data: dict[str, Any]) -> dict[str, Any]:
    """Return ``data`` the way ``SqlMemberRepository`` would store it."""
    stored = dict(data)
    for key in _MEMBER_DATE_COLUMNS:
        value = stored.get(key)
        if hasattr(value, "isoformat"):
            stored[key] = value.isoformat()
    return stored


class InMemoryMemberRepository:
    """In-memory implementation of ``AbstractMemberRepository``."""

    _DEFAULTS: dict[str, Any] = {
        "id": None,
        "email": None,
        "first_name": "Member",
        "surname": "Test",
        "display_name": None,
        "dob": None,
        "join_date": None,
        "membership_status": "active",
        "is_coach": False,
        "is_first_aider": False,
        "emergency_contact_name": None,
        "emergency_contact_phone": None,
        "user_id": None,
        "anonymised_at": None,
        "anonymised_by": None,
    }

    def __init__(self, records: list[dict[str, Any]] | None = None) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        for record in records or []:
            self._insert(record)

    # -- seeding ------------------------------------------------------------

    def seed(self, **overrides: Any) -> dict[str, Any]:
        return self._insert(overrides)

    def _insert(self, data: dict[str, Any]) -> dict[str, Any]:
        row = _stored_member(_row(self._DEFAULTS, data))
        row["id"] = row["id"] or str(uuid.uuid4())
        row["join_date"] = row["join_date"] or date.today().isoformat()
        self._store[row["id"]] = row
        return dict(row)

    # -- interface ----------------------------------------------------------

    async def get(self, member_id: str) -> dict[str, Any] | None:
        row = self._store.get(member_id)
        return dict(row) if row else None

    async def get_by_email(self, email: str) -> dict[str, Any] | None:
        # An erased member has a NULL email; Postgres never matches those with
        # ``=``, so neither does this.
        if email is None:
            return None
        return next(
            (dict(r) for r in self._store.values() if r["email"] == email), None
        )

    async def get_by_user_id(self, user_id: str) -> dict[str, Any] | None:
        return next(
            (dict(r) for r in self._store.values() if r["user_id"] == user_id), None
        )

    async def add(self, data: dict[str, Any]) -> dict[str, Any]:
        if await self.get_by_email(data.get("email")):
            raise ValueError(f"Member with email '{data['email']}' already exists")
        return self._insert(data)

    async def update(
        self, member_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        row = self._store.get(member_id)
        if row is None:
            return None
        updates = _stored_member(_row(self._DEFAULTS, data)) if data else {}
        for key in data:
            row[key] = updates[key]
        return dict(row)

    async def list(
        self,
        status: str | None = None,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = list(self._store.values())
        if status is not None:
            rows = [r for r in rows if r["membership_status"] == status]
        else:
            # Archived members are shelved out of the default roster.
            rows = [r for r in rows if r["membership_status"] != "archived"]
        if search is not None:
            term = search.lower()
            rows = [
                r
                for r in rows
                if term in (r["first_name"] or "").lower()
                or term in (r["surname"] or "").lower()
                or term in (r["email"] or "").lower()
            ]
        return [dict(r) for r in rows]
