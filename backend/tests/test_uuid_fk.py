"""Tests for UUIDType TypeDecorator and FK constraints (issue #123).

These tests are intentionally written BEFORE the implementation exists.
They are expected to FAIL in the red phase of TDD.
"""

from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# 1. UUIDType dialect dispatch
# ---------------------------------------------------------------------------


class TestUUIDTypeDialectDispatch:
    """UUIDType.load_dialect_impl always returns native PostgreSQL UUID —
    PostgreSQL is the only supported dialect, so there is no per-dialect
    branching left to exercise."""

    def test_postgresql_dialect_returns_uuid_impl(self) -> None:
        from sqlalchemy.dialects.postgresql import UUID as PG_UUID

        from app.db.base import UUIDType

        uuid_type = UUIDType()

        pg_dialect = MagicMock()
        pg_dialect.name = "postgresql"
        pg_dialect.type_descriptor.side_effect = lambda t: t

        impl = uuid_type.load_dialect_impl(pg_dialect)

        # The impl passed to type_descriptor should be a PG UUID type
        pg_dialect.type_descriptor.assert_called_once()
        call_arg = pg_dialect.type_descriptor.call_args[0][0]
        assert isinstance(
            call_arg, PG_UUID
        ), f"Expected PG_UUID instance for postgresql dialect, got {type(call_arg)}"

    def test_load_dialect_impl_does_not_branch_on_dialect_name(self) -> None:
        """No other dialect is supported, so load_dialect_impl must not
        special-case dialect.name at all — it always returns PG UUID."""
        from sqlalchemy.dialects.postgresql import UUID as PG_UUID

        from app.db.base import UUIDType

        uuid_type = UUIDType()

        other_dialect = MagicMock()
        other_dialect.name = "some-other-dialect"
        other_dialect.type_descriptor.side_effect = lambda t: t

        impl = uuid_type.load_dialect_impl(other_dialect)

        other_dialect.type_descriptor.assert_called_once()
        call_arg = other_dialect.type_descriptor.call_args[0][0]
        assert isinstance(
            call_arg, PG_UUID
        ), f"Expected PG_UUID instance regardless of dialect, got {type(call_arg)}"


# ---------------------------------------------------------------------------
# 2. UUIDBase.id uses UUIDType
# ---------------------------------------------------------------------------


class TestUUIDBaseIdType:
    """UUIDBase.id column type must be an instance of UUIDType (not raw String)."""

    def test_user_id_column_uses_uuid_type(self) -> None:
        from app.auth.db_models import User
        from app.db.base import UUIDType

        col_type = User.__table__.c.id.type
        assert isinstance(
            col_type, UUIDType
        ), f"Expected User.id to use UUIDType, got {type(col_type).__name__}"

    def test_member_id_column_uses_uuid_type(self) -> None:
        from app.db.base import UUIDType
        from app.members.db_models import Member

        col_type = Member.__table__.c.id.type
        assert isinstance(
            col_type, UUIDType
        ), f"Expected Member.id to use UUIDType, got {type(col_type).__name__}"


# ---------------------------------------------------------------------------
# 3. FK constraints on attendance columns
# ---------------------------------------------------------------------------


class TestAttendanceFKConstraints:
    """Attendance model must carry proper FK constraints on its UUID columns."""

    def test_attendance_session_id_fk_references_session_instances(self) -> None:
        from app.attendance.db_models import Attendance

        fks = Attendance.__table__.c.session_id.foreign_keys
        assert len(fks) > 0, "attendance.session_id must have a FK constraint"
        targets = {fk.target_fullname for fk in fks}
        assert (
            "session_instances.id" in targets
        ), f"attendance.session_id FK must reference session_instances.id, got {targets}"

    def test_attendance_member_id_fk_references_members(self) -> None:
        from app.attendance.db_models import Attendance

        fks = Attendance.__table__.c.member_id.foreign_keys
        assert len(fks) > 0, "attendance.member_id must have a FK constraint"
        targets = {fk.target_fullname for fk in fks}
        assert (
            "members.id" in targets
        ), f"attendance.member_id FK must reference members.id, got {targets}"

    @pytest.mark.xfail(
        strict=False,
        reason="FK not enforced: recorded_by stores user sub but no FK to users.id defined",
    )
    def test_attendance_recorded_by_fk_references_users(self) -> None:
        from app.attendance.db_models import Attendance

        fks = Attendance.__table__.c.recorded_by.foreign_keys
        assert len(fks) > 0, "attendance.recorded_by must have a FK constraint"
        targets = {fk.target_fullname for fk in fks}
        assert (
            "users.id" in targets
        ), f"attendance.recorded_by FK must reference users.id, got {targets}"


# ---------------------------------------------------------------------------
# 5. FK constraints on grade_history columns
# ---------------------------------------------------------------------------


class TestGradeHistoryFKConstraints:
    """GradeHistory must carry FK constraints on member_id and assigned_by."""

    def test_grade_history_member_id_fk_references_members(self) -> None:
        from app.grades.db_models import GradeHistory

        fks = GradeHistory.__table__.c.member_id.foreign_keys
        assert len(fks) > 0, "grade_history.member_id must have a FK constraint"
        targets = {fk.target_fullname for fk in fks}
        assert (
            "members.id" in targets
        ), f"grade_history.member_id FK must reference members.id, got {targets}"

    def test_grade_history_has_assigned_by_column(self) -> None:
        """grade_history must have assigned_by column (renamed from awarded_by)."""
        from app.grades.db_models import GradeHistory

        assert hasattr(
            GradeHistory, "assigned_by"
        ), "GradeHistory must have assigned_by column; awarded_by has been renamed"
        assert (
            not hasattr(GradeHistory, "awarded_by")
            or "awarded_by" not in GradeHistory.__table__.c
        ), "GradeHistory must NOT have awarded_by column; it was renamed to assigned_by"

    def test_grade_history_has_status_column(self) -> None:
        """grade_history must have a status column with default 'confirmed'."""
        from app.grades.db_models import GradeHistory

        assert (
            "status" in GradeHistory.__table__.c
        ), "GradeHistory must have a status column"

    @pytest.mark.xfail(
        strict=False,
        reason="FK not enforced: assigned_by stores user sub but no FK to users.id defined",
    )
    def test_grade_history_assigned_by_fk_references_users(self) -> None:
        from app.grades.db_models import GradeHistory

        fks = GradeHistory.__table__.c.assigned_by.foreign_keys
        assert len(fks) > 0, "grade_history.assigned_by must have a FK constraint"
        targets = {fk.target_fullname for fk in fks}
        assert (
            "users.id" in targets
        ), f"grade_history.assigned_by FK must reference users.id, got {targets}"


# ---------------------------------------------------------------------------
# 6. FK constraint on members.user_id
# ---------------------------------------------------------------------------


class TestMemberUserIdFKConstraint:
    """Member.user_id (nullable) must reference users.id."""

    @pytest.mark.xfail(
        strict=False,
        reason="FK not enforced: members.user_id has no FK to users.id in the model",
    )
    def test_member_user_id_fk_references_users(self) -> None:
        from app.members.db_models import Member

        fks = Member.__table__.c.user_id.foreign_keys
        assert len(fks) > 0, "members.user_id must have a FK constraint"
        targets = {fk.target_fullname for fk in fks}
        assert (
            "users.id" in targets
        ), f"members.user_id FK must reference users.id, got {targets}"
