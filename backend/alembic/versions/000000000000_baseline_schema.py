"""baseline schema (revision zero)

Revision ID: 000000000000
Revises:
Create Date: 2026-08-09

Issue #264 — Alembic as the single source of truth for schema.

Before this revision existed, the migration chain started at
``a1b2c3d4e5f6`` (add_federations_table) with ``down_revision = None`` and
assumed ``members``, ``sessions``/``session_*``, ``users`` etc. already
existed — because every deployment up to that point got its schema from
``Base.metadata.create_all`` (run once by ``app.db.bootstrap`` on a "fresh"
database, followed by ``alembic stamp head``), never from replaying the
migration chain itself. That made ``alembic upgrade head`` against a
genuinely empty database impossible, and left two schema sources
(``create_all`` and the migration chain) free to drift apart.

This revision creates the full schema *as it existed immediately before*
``a1b2c3d4e5f6`` was written — i.e. the state every migration from
``a1b2c3d4e5f6`` onward already assumes as its starting point. It was
derived by reading every file in ``alembic/versions/``, following the
``down_revision`` links to establish the true (non-alphabetical) chain
order, and reversing each migration's ``upgrade()`` on top of the current
ORM metadata (``app.db.base.Base.metadata``) — i.e. this is exactly the
schema you'd get by running ``alembic downgrade`` from head down through
(and including) ``a1b2c3d4e5f6``.

Column/FK types here use ``postgresql.UUID(as_uuid=False)`` for every id and
UUID-valued foreign key — the exact physical type the app's ``UUIDType``
(``app/db/base.py``) resolves to on Postgres via its ``load_dialect_impl``.
A plain ``sa.String(36)`` was tried first and rejected: `alembic`'s
autogenerate diff *does* compare column type/length by default here (see
``test_migrated_schema_matches_orm_metadata_exactly``, which failed loudly
with `modify_type` entries for every `VARCHAR(36)` id column against the
ORM's `UUIDType`) — `varchar` and Postgres' native `uuid` are genuinely
different physical column types, not merely a cosmetic difference autogenerate
ignores. Matching the ORM's type exactly here (`postgresql.UUID`, not the
app's `UUIDType` wrapper — importing app code into a migration would couple
it to code that changes independently of the schema it describes) was
required, and the existing chain files that created UUID-ish columns as
plain `String(36)` (`a1b2c3d4e5f6`, `b2c3d4e5f6a7`, `a3b4c5d6e7f8`,
`f2a3b4c5d6e7`) were fixed the same way as part of this change — see their
own diffs. `federations.website`/`continental_grouping`'s declared lengths
in `a1b2c3d4e5f6` were also out of sync with the ORM and fixed likewise.
Separately, `members.federation_number` was added by `c3d4e5f6a7b8` and
never dropped by any later migration despite the ORM `Member` model no
longer declaring it (AC20, `test_federation.py`) — a second, independent
pre-existing drift, closed by the tip migration
`a5b6c7d8e9f0_drop_federation_number_from_members.py`.

--------------------------------------------------------------------------
Deployment migration path (issue #264, item 6)
--------------------------------------------------------------------------

**A deploy already stamped at or past ``a1b2c3d4e5f6``** (i.e. every
deployment created before this revision existed — schema built by
``create_all``, then ``alembic stamp head``, then possibly advanced further
by real ``alembic upgrade head`` runs as later migrations were added):
``alembic upgrade head`` continues to behave correctly after this
re-parenting. Alembic reads the applied revision from the single row in
``alembic_version`` and walks forward from there along ``down_revision``
links; it never re-verifies that the ancestors behind the stamped revision
were actually applied. Since ``alembic_version`` already names a revision
at or after ``a1b2c3d4e5f6``, this baseline (now an ancestor of that
revision) is never visited and never re-executed. No action is required for
these deployments.

**A legacy pre-alembic deploy** — tables exist (created by an even older
``create_all``-only bootstrap) but there is no ``alembic_version`` table at
all: this can only mean the instance predates ``a1b2c3d4e5f6`` ever merging
*and* has never been restarted since (every restart under the pre-#264
``app.db.bootstrap`` already ran ``alembic upgrade head`` unconditionally
for a non-"fresh" database, which creates ``alembic_version`` on its very
first successful migration — so any instance that has restarted even once
since ``a1b2c3d4e5f6`` shipped is *not* in this state to begin with).

For such an instance, whose schema was produced by ``Base.metadata.create_all``
against whatever commit was deployed:

    alembic stamp head

is correct **only if that schema is known to match the ORM at the current
commit exactly** — i.e. the deployment has been kept current (this mirrors
what the pre-#264 bootstrap did for a "fresh" database: ``create_all`` then
``stamp head``, and ``test_migrated_schema_matches_orm_metadata_exactly``
is exactly what guarantees a ``create_all`` schema and a fully-migrated
schema are identical at head). Do **not** stamp at ``a1b2c3d4e5f6`` or at
this baseline (``000000000000``) — either leaves ``alembic_version`` naming
a revision *before* tables this legacy database's ``create_all`` already
built (``federations``, ``member_federations``, ``invites``, and every
column added after them), so the next ``alembic upgrade head`` tries to
``CREATE TABLE``/``ADD COLUMN`` things that already exist, and fails.

**If there is any doubt the schema is current** — the deployment predates
some migrations that shipped after it was last redeployed, so its
``create_all`` output is missing tables/columns those migrations would add —
**no single stamp target is correct.** Stamping at any revision either skips
real schema changes that database still needs (stamped too late) or tries
to recreate things it already has (stamped too early), and there is no
revision in between that exactly matches an out-of-date ``create_all``
snapshot, because ``create_all`` was never revision-aware in the first
place. Do not guess. Instead: diff the live schema against
``app.db.base.Base.metadata`` (e.g. ``alembic.autogenerate.compare_metadata``
against a connection to it, the same mechanism
``test_migrated_schema_matches_orm_metadata_exactly`` uses) to see exactly
what is missing, then either apply those specific changes by hand and stamp
head, or — safer — take a data backup, run ``alembic upgrade head`` against
a fresh empty database, and migrate the data across rather than trying to
reconcile the old schema in place.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "000000000000"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", PG_UUID(as_uuid=False), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("theme", sa.String(10), nullable=False),
        sa.Column("pending_challenge", sa.String(255), nullable=True),
        sa.Column("challenge_issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("login_failures", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "members",
        sa.Column("id", PG_UUID(as_uuid=False), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("dob", sa.String(10), nullable=False),
        sa.Column("join_date", sa.String(10), nullable=False),
        sa.Column("membership_status", sa.String(20), nullable=False),
        sa.Column("is_coach", sa.Boolean(), nullable=False),
        sa.Column("is_first_aider", sa.Boolean(), nullable=False),
        sa.Column("emergency_contact_name", sa.String(255), nullable=True),
        sa.Column("emergency_contact_phone", sa.String(50), nullable=True),
        sa.Column("user_id", PG_UUID(as_uuid=False), nullable=True),
        sa.Column("parental_consent_obtained", sa.Boolean(), nullable=False),
        sa.Column("federation_number", sa.String(50), nullable=True),
    )

    op.create_table(
        "session_types",
        sa.Column("id", PG_UUID(as_uuid=False), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("colour", sa.String(7), nullable=True),
    )

    op.create_table(
        "session_templates",
        sa.Column("id", PG_UUID(as_uuid=False), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("start_date", sa.String(10), nullable=False),
        sa.Column("recurrence", sa.String(20), nullable=False),
        sa.Column("day_of_week", sa.Integer(), nullable=True),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("recurrence_days", sa.Text(), nullable=True),
        sa.Column("interval_weeks", sa.Integer(), nullable=False),
        sa.Column("info", sa.Text(), nullable=True),
        sa.Column("coach_notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
    )

    op.create_table(
        "session_template_segments",
        sa.Column("id", PG_UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "template_id",
            PG_UUID(as_uuid=False),
            sa.ForeignKey("session_templates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("start_time", sa.String(5), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(100), nullable=True),
        sa.Column("note", sa.String(280), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("coach_notes", sa.Text(), nullable=True),
    )

    op.create_table(
        "session_template_segment_types",
        sa.Column("id", PG_UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "segment_id",
            PG_UUID(as_uuid=False),
            sa.ForeignKey("session_template_segments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "session_type_id",
            PG_UUID(as_uuid=False),
            sa.ForeignKey("session_types.id"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
    )

    op.create_table(
        "session_instances",
        sa.Column("id", PG_UUID(as_uuid=False), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("date", sa.String(10), nullable=False),
        sa.Column("notes", sa.String(1000), nullable=True),
        sa.Column(
            "template_id",
            PG_UUID(as_uuid=False),
            sa.ForeignKey("session_templates.id"),
            nullable=True,
        ),
        sa.Column("cancelled", sa.Boolean(), nullable=False),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("info", sa.Text(), nullable=True),
        sa.Column("coach_notes", sa.Text(), nullable=True),
        sa.Column("checkin_url", sa.String(500), nullable=True),
    )

    op.create_table(
        "session_instance_segments",
        sa.Column("id", PG_UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "instance_id",
            PG_UUID(as_uuid=False),
            sa.ForeignKey("session_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("start_time", sa.String(5), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(100), nullable=True),
        sa.Column("note", sa.String(280), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("coach_notes", sa.Text(), nullable=True),
    )

    op.create_table(
        "session_instance_segment_types",
        sa.Column("id", PG_UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "segment_id",
            PG_UUID(as_uuid=False),
            sa.ForeignKey("session_instance_segments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "session_type_id",
            PG_UUID(as_uuid=False),
            sa.ForeignKey("session_types.id"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
    )

    op.create_table(
        "grade_history",
        sa.Column("id", PG_UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "member_id",
            PG_UUID(as_uuid=False),
            sa.ForeignKey("members.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("grade", sa.String(20), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("promoted_at", sa.String(50), nullable=False),
        sa.Column("awarded_by", PG_UUID(as_uuid=False), nullable=False),
    )

    op.create_table(
        "dojo_settings",
        sa.Column("id", PG_UUID(as_uuid=False), primary_key=True),
        sa.Column("dojo_name", sa.String(255), nullable=False),
        sa.Column("logo_url", sa.String(1024), nullable=True),
        sa.Column("primary_colour", sa.String(7), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "attendance",
        sa.Column("id", PG_UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "session_id",
            PG_UUID(as_uuid=False),
            sa.ForeignKey("session_instances.id"),
            nullable=False,
        ),
        sa.Column("member_id", PG_UUID(as_uuid=False), nullable=True),
        sa.Column("visitor_name", sa.String(255), nullable=True),
        sa.Column("checked_in_at", sa.String(50), nullable=False),
        sa.Column("recorded_by", PG_UUID(as_uuid=False), nullable=False),
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

    op.create_table(
        "passkey_credentials",
        sa.Column("id", PG_UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            PG_UUID(as_uuid=False),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("credential_id", sa.LargeBinary(), nullable=False, unique=True),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("sign_count", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("aaguid", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "recovery_codes",
        sa.Column("id", PG_UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            PG_UUID(as_uuid=False),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("code_hash", sa.String(255), nullable=False),
        sa.Column("set_id", sa.String(36), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "recovery_attempts",
        sa.Column("id", PG_UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            PG_UUID(as_uuid=False),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
    )

    op.create_table(
        "admin_recovery_tokens",
        sa.Column("id", PG_UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            PG_UUID(as_uuid=False),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "created_by_id",
            PG_UUID(as_uuid=False),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("admin_recovery_tokens")
    op.drop_table("recovery_attempts")
    op.drop_table("recovery_codes")
    op.drop_table("passkey_credentials")
    op.drop_table("checkin_tokens")
    op.drop_table("attendance")
    op.drop_table("dojo_settings")
    op.drop_table("grade_history")
    op.drop_table("session_instance_segment_types")
    op.drop_table("session_instance_segments")
    op.drop_table("session_instances")
    op.drop_table("session_template_segment_types")
    op.drop_table("session_template_segments")
    op.drop_table("session_templates")
    op.drop_table("session_types")
    op.drop_table("members")
    op.drop_table("users")
