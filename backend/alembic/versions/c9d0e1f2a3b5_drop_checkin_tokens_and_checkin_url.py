"""drop checkin_tokens and session_instances.checkin_url

Revision ID: c9d0e1f2a3b5
Revises: b8c9d0e1f2a3
Create Date: 2026-09-02

Drops two objects the baseline created: the `checkin_tokens` table and the
`session_instances.checkin_url` column that held the URL minted from it.

What changed. A session had two check-in links. `checkin_tokens` backed
`GET /sessions/{id}/checkin-token` -> `POST /checkin/{token}` (#9): a
single-use, 24-hour token whose URL `#122` persisted to
`session_instances.checkin_url` so the session detail page could show it.
`#191` then added a second, tokenless link — `/checkin/session/{id}` — to
the iCal feed, driving the member-authenticated `POST /sessions/{id}/checkin`
that enforces the check-in window.

What supersedes them. The tokenless link, which is now the one check-in link
a session has, surfaced as `checkin_link` on `SessionInstanceRead`. It is
strictly better at the job the token link was built for — an admin pasting a
link into a group chat: multi-use where the token died on first redemption,
window-enforced where the token path skipped the window entirely, and stable
where the token URL went stale the moment anyone used it. Neither link ever
worked without an authenticated member, so the token added no reach — only a
secret that `checkin_url` leaked to every member through
`GET /sessions/{id}`, letting any of them burn the admin's shared link.

Nothing replaces `checkin_tokens.used_at`: `attendance` already records
`checked_in_at` and `recorded_by` per member, which is more than the single
first-redemption stamp the token carried.

Both drops are `IF EXISTS`, following `a5b6c7d8e9f0` (#332): a database
bootstrapped by `Base.metadata.create_all` from the current ORM metadata and
then stamped never had either object, and an unguarded `DROP` would fail
`alembic upgrade head` on it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision: str = "c9d0e1f2a3b5"
down_revision: str | None = "b8c9d0e1f2a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS checkin_tokens")
    op.execute("ALTER TABLE session_instances DROP COLUMN IF EXISTS checkin_url")


def downgrade() -> None:
    op.add_column(
        "session_instances",
        sa.Column("checkin_url", sa.String(500), nullable=True),
    )
    op.create_table(
        "checkin_tokens",
        sa.Column("id", PG_UUID(as_uuid=False), primary_key=True),
        sa.Column("token", sa.String(255), nullable=False, unique=True),
        sa.Column("token_lookup", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "session_id",
            PG_UUID(as_uuid=False),
            sa.ForeignKey("session_instances.id"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.String(50), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
