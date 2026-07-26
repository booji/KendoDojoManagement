from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete

from app.auth.db_models import (
    AdminRecoveryToken,
    PasskeyCredential,
    RecoveryAttempt,
    RecoveryCode,
    User,
)
from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import UserClaims
from app.db.unit_of_work import AbstractUnitOfWork
from app.dependencies import get_uow
from app.grades.db_models import GradeHistory
from app.member_federations.db_models import MemberFederation
from app.members.admin_directory import AbstractAdminDirectory
from app.members.dependencies import get_admin_directory, get_member_repo
from app.members.erasure import build_erasure_plan, can_erase
from app.members.models import CreateMemberRequest, MemberResponse, UpdateMemberRequest
from app.members.repository import AbstractMemberRepository

router = APIRouter(tags=["members"])

_Repo = Annotated[AbstractMemberRepository, Depends(get_member_repo)]
_UoW = Annotated[AbstractUnitOfWork, Depends(get_uow)]
_Admin = Annotated[UserClaims, Depends(REQUIRE_ADMIN)]
_Member = Annotated[UserClaims, Depends(REQUIRE_MEMBER)]
_AdminDirectory = Annotated[AbstractAdminDirectory, Depends(get_admin_directory)]


def _compute_is_minor(dob: str | None) -> bool:
    """Return True if person is under 18 today. Returns False when dob is None."""
    if not dob:
        return False
    birth = date.fromisoformat(dob) if isinstance(dob, str) else dob
    today = date.today()
    age = (
        today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
    )
    return age < 18


def _stringify(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _to_response(record: dict[str, Any]) -> MemberResponse:
    dob = record.get("dob")
    return MemberResponse(
        id=record["id"],
        email=record["email"],
        first_name=record["first_name"],
        surname=record["surname"],
        display_name=record.get("display_name"),
        dob=dob,
        join_date=str(record.get("join_date", "")),
        membership_status=record["membership_status"],
        is_coach=record["is_coach"],
        is_first_aider=record["is_first_aider"],
        emergency_contact_name=record.get("emergency_contact_name"),
        emergency_contact_phone=record.get("emergency_contact_phone"),
        is_minor=_compute_is_minor(dob),
        anonymised_at=_stringify(record.get("anonymised_at")),
        anonymised_by=record.get("anonymised_by"),
    )


# ---------------------------------------------------------------------------
# POST /members — admin only
# ---------------------------------------------------------------------------


@router.post("/members", status_code=status.HTTP_201_CREATED)
async def create_member(
    payload: CreateMemberRequest,
    _claims: _Admin,
    repo: _Repo,
    uow: _UoW,
) -> MemberResponse:
    data = payload.model_dump()
    # Convert date fields to ISO strings for storage
    if data["dob"] is not None:
        data["dob"] = data["dob"].isoformat()
    data["join_date"] = data["join_date"].isoformat()
    try:
        record = await repo.add(data)
        await uow.commit()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return _to_response(record)


# ---------------------------------------------------------------------------
# GET /members — admin only, with optional status and search filters
# ---------------------------------------------------------------------------


@router.get("/members")
async def list_members(
    _claims: _Admin,
    repo: _Repo,
    status: str | None = None,
    search: str | None = None,
) -> list[MemberResponse]:
    records = await repo.list(status=status, search=search)
    return [_to_response(r) for r in records]


# ---------------------------------------------------------------------------
# GET /members/{id} — admin sees any; member sees own only
# ---------------------------------------------------------------------------


@router.get("/members/{member_id}")
async def get_member(
    member_id: uuid.UUID,
    claims: _Member,
    repo: _Repo,
) -> MemberResponse:
    record = await repo.get(str(member_id))
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Member not found"
        )
    # Admins may see any member; non-admins may only see their own profile
    if claims.role != "admin":
        user_id = record.get("user_id")
        if user_id != claims.sub:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )
    return _to_response(record)


# ---------------------------------------------------------------------------
# PUT /members/{id} — admin only, partial update
# ---------------------------------------------------------------------------


@router.put("/members/{member_id}")
async def update_member(
    member_id: uuid.UUID,
    payload: UpdateMemberRequest,
    _claims: _Admin,
    repo: _Repo,
    uow: _UoW,
) -> MemberResponse:
    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    if "dob" in data and hasattr(data["dob"], "isoformat"):
        data["dob"] = data["dob"].isoformat()
    if "join_date" in data and hasattr(data["join_date"], "isoformat"):
        data["join_date"] = data["join_date"].isoformat()
    record = await repo.update(str(member_id), data)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Member not found"
        )
    await uow.commit()
    return _to_response(record)


# ---------------------------------------------------------------------------
# POST /members/{id}/erase — admin only, irreversible anonymisation (GDPR)
# ---------------------------------------------------------------------------


@router.post("/members/{member_id}/erase")
async def erase_member(
    member_id: str,
    claims: _Admin,
    repo: _Repo,
    uow: _UoW,
    directory: _AdminDirectory,
) -> MemberResponse:
    record = await repo.get(member_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Member not found"
        )

    target_user_id = record.get("user_id")

    # The "not archived" and "self erase" checks in can_erase don't depend on
    # is_admin/admin_count, so a preliminary check (with is_admin forced to
    # False) short-circuits those denials without ever touching the admin
    # directory. Only when that preliminary check would allow do we need the
    # real admin/last-admin lookup.
    preliminary = can_erase(
        actor_user_id=claims.sub, member=record, is_admin=False, admin_count=1
    )
    if not preliminary.allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=preliminary.reason
        )

    is_admin = await directory.is_admin(target_user_id)
    admin_count = await directory.count_admins()
    decision = can_erase(
        actor_user_id=claims.sub,
        member=record,
        is_admin=is_admin,
        admin_count=admin_count,
    )
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=decision.reason
        )

    plan = build_erasure_plan(record)
    session = uow.session

    # Children before parent: passkeys/recovery/tokens must go before the
    # users row itself, to satisfy foreign key constraints.
    if target_user_id is not None:
        await session.execute(
            delete(PasskeyCredential).where(
                PasskeyCredential.user_id == target_user_id
            )
        )
        await session.execute(
            delete(RecoveryCode).where(RecoveryCode.user_id == target_user_id)
        )
        await session.execute(
            delete(RecoveryAttempt).where(RecoveryAttempt.user_id == target_user_id)
        )
        await session.execute(
            delete(AdminRecoveryToken).where(
                AdminRecoveryToken.user_id == target_user_id
            )
        )
        await session.execute(delete(User).where(User.id == target_user_id))

    await session.execute(
        delete(GradeHistory).where(GradeHistory.member_id == member_id)
    )
    await session.execute(
        delete(MemberFederation).where(MemberFederation.member_id == member_id)
    )

    scrub = {
        **plan.scrub,
        "anonymised_at": datetime.now(UTC),
        "anonymised_by": claims.sub,
    }
    updated = await repo.update(member_id, scrub)
    await uow.commit()
    return _to_response(updated)


