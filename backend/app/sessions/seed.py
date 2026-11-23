"""Default session types seeded on first boot (issues #173, #614).

A fresh dojo gets a useful spread of session types so it can schedule
immediately. Seeding is idempotent: it runs only while the session-types table
is empty, so an admin's customised list is never overwritten. Session types
remain managed exclusively through Admin Settings — this module only provides
the initial defaults.
"""

from typing import Any
from uuid import uuid4

from sqlalchemy import insert, select

from app.sessions.db_models import SessionType

# (name, hex colour). Five kinds of practice, not audience or equipment: what
# is practised within a Session lives in its Segments (#614). Each colour is
# distinct so types are visually distinguishable in the calendar and listings.
DEFAULT_SESSION_TYPES: list[tuple[str, str]] = [
    ("General Keiko", "#1E88E5"),
    ("Beginners", "#FDD835"),
    ("Kata", "#F4511E"),
    ("Jigeiko", "#C0CA33"),
    ("Shiai Practice", "#D81B60"),
]


async def seed_session_types(conn: Any) -> int:
    """Insert all default session types if none exist yet.

    Returns the number of rows inserted — 0 when the table already holds any
    session type (the existing list is left untouched).
    """
    existing = await conn.execute(select(SessionType))
    if existing.fetchone():
        return 0
    await conn.execute(
        insert(SessionType),
        [
            {"id": str(uuid4()), "name": name, "colour": colour}
            for name, colour in DEFAULT_SESSION_TYPES
        ],
    )
    return len(DEFAULT_SESSION_TYPES)
