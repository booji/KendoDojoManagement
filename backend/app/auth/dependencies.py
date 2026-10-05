from typing import Annotated

from fastapi import Depends

from app.auth.attempt_repository import AbstractAttemptRepository, SqlAttemptRepository
from app.auth.auth_session_repository import (
    AbstractAuthSessionRepository,
    SqlAuthSessionRepository,
)
from app.auth.invite_repository import AbstractInviteRepository, SqlInviteRepository
from app.auth.passkey_repository import AbstractPasskeyRepository, SqlPasskeyRepository
from app.auth.recovery_repository import (
    AbstractAdminTokenRepository,
    AbstractRecoveryRepository,
    SqlAdminTokenRepository,
    SqlRecoveryRepository,
)
from app.db.unit_of_work import AbstractUnitOfWork
from app.dependencies import get_uow


def get_passkey_repo(
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> AbstractPasskeyRepository:
    return SqlPasskeyRepository(uow.session)


def get_recovery_repo(
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> AbstractRecoveryRepository:
    return SqlRecoveryRepository(uow.session)


def get_attempt_repo(
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> AbstractAttemptRepository:
    return SqlAttemptRepository(uow.session)


def get_admin_token_repo(
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> AbstractAdminTokenRepository:
    return SqlAdminTokenRepository(uow.session)


def get_invite_repo(
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> AbstractInviteRepository:
    return SqlInviteRepository(uow.session)


def get_auth_session_repo(
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> AbstractAuthSessionRepository:
    return SqlAuthSessionRepository(uow.session)
