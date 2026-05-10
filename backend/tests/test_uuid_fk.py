"""Tests for UUIDType TypeDecorator and FK constraints (issue #123).

These tests are intentionally written BEFORE the implementation exists.
They are expected to FAIL in the red phase of TDD.
"""

import pytest
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# 1. UUIDType dialect dispatch
# ---------------------------------------------------------------------------


class TestUUIDTypeDialectDispatch:
    """UUIDType.load_dialect_impl returns native UUID for PostgreSQL,
    String(36) for everything else."""

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
        assert isinstance(call_arg, PG_UUID), (
            f"Expected PG_UUID instance for postgresql dialect, got {type(call_arg)}"
        )

    def test_sqlite_dialect_returns_string36_impl(self) -> None:
        from sqlalchemy import String

        from app.db.base import UUIDType

        uuid_type = UUIDType()

        sqlite_dialect = MagicMock()
        sqlite_dialect.name = "sqlite"
        sqlite_dialect.type_descriptor.side_effect = lambda t: t

        impl = uuid_type.load_dialect_impl(sqlite_dialect)

        sqlite_dialect.type_descriptor.assert_called_once()
        call_arg = sqlite_dialect.type_descriptor.call_args[0][0]
        assert isinstance(call_arg, String), (
            f"Expected String instance for sqlite dialect, got {type(call_arg)}"
        )
        assert call_arg.length == 36, (
            f"Expected String(36) for sqlite dialect, got String({call_arg.length})"
        )


# ---------------------------------------------------------------------------
# 2. UUIDBase.id uses UUIDType
# ---------------------------------------------------------------------------


class TestUUIDBaseIdType:
    """UUIDBase.id column type must be an instance of UUIDType (not raw String)."""

    def test_user_id_column_uses_uuid_type(self) -> None:
        from app.auth.db_models import User
        from app.db.base import UUIDType

        col_type = User.__table__.c.id.type
        assert isinstance(col_type, UUIDType), (
            f"Expected User.id to use UUIDType, got {type(col_type).__name__}"
        )

    def test_member_id_column_uses_uuid_type(self) -> None:
        from app.db.base import UUIDType
        from app.members.db_models import Member

        col_type = Member.__table__.c.id.type
        assert isinstance(col_type, UUIDType), (
            f"Expected Member.id to use UUIDType, got {type(col_type).__name__}"
        )


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
        assert "session_instances.id" in targets, (
            f"attendance.session_id FK must reference session_instances.id, got {targets}"
        )

    @pytest.mark.xfail(
        strict=False,
        reason="FK not enforced: checkin_to_session uses current_user.sub as member_id, not a members.id",
    )
    def test_attendance_member_id_fk_references_members(self) -> None:
        from app.attendance.db_models import Attendance

        fks = Attendance.__table__.c.member_id.foreign_keys
        assert len(fks) > 0, "attendance.member_id must have a FK constraint"
        targets = {fk.target_fullname for fk in fks}
        assert "members.id" in targets, (
            f"attendance.member_id FK must reference members.id, got {targets}"
        )

    @pytest.mark.xfail(
        strict=False,
        reason="FK not enforced: recorded_by stores user sub but no FK to users.id defined",
    )
    def test_attendance_recorded_by_fk_references_users(self) -> None:
        from app.attendance.db_models import Attendance

        fks = Attendance.__table__.c.recorded_by.foreign_keys
        assert len(fks) > 0, "attendance.recorded_by must have a FK constraint"
        targets = {fk.target_fullname for fk in fks}
        assert "users.id" in targets, (
            f"attendance.recorded_by FK must reference users.id, got {targets}"
        )


# ---------------------------------------------------------------------------
# 4. FK constraint on checkin_tokens.session_id
# ---------------------------------------------------------------------------


class TestCheckinTokenFKConstraint:
    """CheckinToken.session_id must reference session_instances.id."""

    def test_checkin_token_session_id_fk_references_session_instances(self) -> None:
        from app.attendance.db_models import CheckinToken

        fks = CheckinToken.__table__.c.session_id.foreign_keys
        assert len(fks) > 0, "checkin_tokens.session_id must have a FK constraint"
        targets = {fk.target_fullname for fk in fks}
        assert "session_instances.id" in targets, (
            f"checkin_tokens.session_id FK must reference session_instances.id, got {targets}"
        )


# ---------------------------------------------------------------------------
# 5. FK constraints on grade_history columns
# ---------------------------------------------------------------------------


class TestGradeHistoryFKConstraints:
    """GradeHistory must carry FK constraints on member_id and awarded_by."""

    def test_grade_history_member_id_fk_references_members(self) -> None:
        from app.grades.db_models import GradeHistory

        fks = GradeHistory.__table__.c.member_id.foreign_keys
        assert len(fks) > 0, "grade_history.member_id must have a FK constraint"
        targets = {fk.target_fullname for fk in fks}
        assert "members.id" in targets, (
            f"grade_history.member_id FK must reference members.id, got {targets}"
        )

    @pytest.mark.xfail(
        strict=False,
        reason="FK not enforced: awarded_by stores user sub but no FK to users.id defined",
    )
    def test_grade_history_awarded_by_fk_references_users(self) -> None:
        from app.grades.db_models import GradeHistory

        fks = GradeHistory.__table__.c.awarded_by.foreign_keys
        assert len(fks) > 0, "grade_history.awarded_by must have a FK constraint"
        targets = {fk.target_fullname for fk in fks}
        assert "users.id" in targets, (
            f"grade_history.awarded_by FK must reference users.id, got {targets}"
        )


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
        assert "users.id" in targets, (
            f"members.user_id FK must reference users.id, got {targets}"
        )
