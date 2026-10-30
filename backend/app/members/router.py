from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete

from app.auth.accounts import delete_account
from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import AccountClaims
from app.core.security_logger import log_security_event
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
_Admin = Annotated[AccountClaims, Depends(REQUIRE_ADMIN)]
_Member = Annotated[AccountClaims, Depends(REQUIRE_MEMBER)]
_AdminDirectory = Annotated[AbstractAdminDirectory, Depends(get_admin_directory)]

# Member fields an admin may clear by sending an explicit null. Every other
# field on UpdateMemberRequest is required-by-domain, so a null there means
# "leave alone" rather than "wipe".
_CLEARABLE_FIELDS = (
    "display_name",
    "dob",
    "emergency_contact_name",
    "emergency_contact_phone",
)


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
        anonymised_at=_stringify(record.get("anonymised_at")),
        anonymised_by=record.get("anonymised_by"),
    )


# ---------------------------------------------------------------------------
# POST /members — admin only
# ---------------------------------------------------------------------------


@router.post("/members", status_code=status.HTTP_201_CREATED)
async def create_member(
    payload: CreateMemberRequest,
    claims: _Admin,
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
    log_security_event(
        "member_created",
        "success",
        user_id=claims.sub,
        detail={"member_id": record["id"]},
    )
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
    claims: _Admin,
    repo: _Repo,
    uow: _UoW,
) -> MemberResponse:
    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    # The optional PII fields are nullable-by-design: an explicitly provided
    # None clears the stored value, so it must survive the generic not-None
    # filter above (which otherwise treats missing and None alike — the
    # correct reading for the required-by-domain fields in this payload).
    explicitly_set = payload.model_dump(exclude_unset=True)
    for key in _CLEARABLE_FIELDS:
        if key in explicitly_set:
            data[key] = explicitly_set[key]
    before = await repo.get(str(member_id))
    if before is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Member not found"
        )
    record = await repo.update(str(member_id), data)
    await uow.commit()
    log_security_event(
        "member_updated",
        "success",
        user_id=claims.sub,
        detail={
            "member_id": record["id"],
            # Names only: the values are the personal data being audited.
            "changed_fields": sorted(k for k in data if before[k] != record[k]),
        },
    )
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

    plan = build_erasure_plan()
    session = uow.session

    if target_user_id is not None:
        await delete_account(session, target_user_id)

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
