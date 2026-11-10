from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import UUIDBase, UUIDType


class Account(UUIDBase):
    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint("member_id", name="uq_accounts_member_id"),)

    # The Member this Account signs in as (#432, ADR-0006). Every Account has
    # exactly one; the email it signs in with is that Member's. RESTRICT
    # because Members are deactivated or anonymised, never hard-deleted.
    member_id: Mapped[str] = mapped_column(
        UUIDType(),
        ForeignKey("members.id", name="fk_accounts_member_id", ondelete="RESTRICT"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="member")
    theme: Mapped[str] = mapped_column(String(10), nullable=False, default="system")
    # One WebAuthn ceremony in flight per Account: a second concurrent
    # registration or login for the same Account overwrites the challenge, and
    # the first then fails. Accepted at dojo scale (#418, #435).
    pending_challenge: Mapped[str | None] = mapped_column(String(255), nullable=True)
    challenge_issued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PasskeyCredential(UUIDBase):
    __tablename__ = "passkey_credentials"

    user_id: Mapped[str] = mapped_column(
        UUIDType(), ForeignKey("accounts.id"), nullable=False
    )
    credential_id: Mapped[bytes] = mapped_column(
        LargeBinary, nullable=False, unique=True
    )
    public_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sign_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    label: Mapped[str] = mapped_column(String(255), nullable=False, default="Passkey")
    aaguid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class RecoveryCode(UUIDBase):
    __tablename__ = "recovery_codes"

    user_id: Mapped[str] = mapped_column(
        UUIDType(), ForeignKey("accounts.id"), nullable=False, index=True
    )
    code_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    set_id: Mapped[str] = mapped_column(String(36), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class RecoveryAttempt(UUIDBase):
    __tablename__ = "recovery_attempts"

    user_id: Mapped[str] = mapped_column(
        UUIDType(), ForeignKey("accounts.id"), nullable=False, index=True
    )
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    # Cleared after IP_RETENTION (app.auth.attempt_repository, #434).
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)


class Invite(UUIDBase):
    """Admin-issued invite token for passkey registration (#257).

    Only `token_hash` is ever persisted -- the plaintext token is returned to
    the admin exactly once, at mint time, and never stored. The hash is a
    deterministic sha256 digest rather than a per-row-salted bcrypt hash,
    because redemption must look a row up by token alone with no scoping
    identity known ahead of time (see app.auth.invite_service).
    """

    __tablename__ = "invites"

    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # The admin issuing the invite supplies the invitee's name, so redemption
    # can create a real Member row rather than guessing from the email.
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    surname: Mapped[str] = mapped_column(String(100), nullable=False)
    token_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    issued_by: Mapped[str | None] = mapped_column(
        # SET NULL rather than RESTRICT: erasure deletes the Account row, and an
        # admin who once issued an invite must not become un-erasable. The
        # invite itself is still worth keeping as an audit record.
        UUIDType(),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    redeemed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class AdminRecoveryToken(UUIDBase):
    __tablename__ = "admin_recovery_tokens"

    user_id: Mapped[str] = mapped_column(
        UUIDType(), ForeignKey("accounts.id"), nullable=False, index=True
    )
    # SET NULL: erasing the issuer leaves the token usable by its target (#570).
    created_by_id: Mapped[str | None] = mapped_column(
        UUIDType(), ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class AuthSession(UUIDBase):
    """One signed-in device (#455, ADR-0008).

    The cookie carries a random id; only its SHA-256 is stored, so a dump of
    this table yields no live Auth Session. Both foreign keys cascade, and
    that is the revocation: erasing the Account, or removing the passkey a
    device signed in with, ends the Auth Sessions that depend on it.
    """

    __tablename__ = "auth_sessions"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('sign_in', 'recovery')", name="ck_auth_sessions_kind"
        ),
    )

    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    account_id: Mapped[str] = mapped_column(
        UUIDType(),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # NULL where no passkey was used: the test-only login.
    passkey_id: Mapped[str | None] = mapped_column(
        UUIDType(),
        ForeignKey("passkey_credentials.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # `recovery`: redeemed from a recovery code or admin recovery token, good
    # only for enrolling one passkey (#486).
    kind: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default="sign_in"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
