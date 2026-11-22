from datetime import UTC, datetime, timedelta
from typing import NoReturn

import webauthn
from fastapi import HTTPException, status
from sqlalchemy import exists, func, select

from app import config
from app.auth.aaguid import label_from_aaguid
from app.auth.accounts import account_for_email, account_for_member, may_sign_in
from app.auth.auth_session_repository import SqlAuthSessionRepository
from app.auth.auth_sessions import start_auth_session
from app.auth.db_models import Account, PasskeyCredential, RecoveryCode
from app.auth.member_directory import member_directory_for
from app.auth.models import (
    PasskeyCredentialResponse,
    PasskeyLoginCompleteRequest,
    PasskeyRegisterCompleteRequest,
    PasskeyRegisterCompleteResponse,
    TokenResponse,
)
from app.auth.webauthn_ceremony import (
    Subject,
    decode_challenge,
    login_begin,
    register_begin,
    to_authentication_credential,
    to_registration_credential,
)
from app.core.security_logger import log_security_event
from app.db.unit_of_work import AbstractUnitOfWork

# Generic, indistinguishable failure for both begin-completion decoy paths and
# genuine "wrong credential" paths -- must never leak which case occurred.
_AUTH_FAILED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication failed"
)


def refuse_registration() -> NoReturn:
    """Refuse an email-addressed registration with the generic failure (#472):
    the register decoy's whole answer, kept here beside _AUTH_FAILED so the
    two cannot drift apart."""
    log_security_event("passkey_registered", "failure")
    raise _AUTH_FAILED


async def _get_or_create_account(member_id: str, uow: AbstractUnitOfWork) -> Account:
    """The Member's Account, created if it has none (#432: every Account
    belongs to exactly one Member).

    Always as a member: admin is granted when the claim *completes*
    (app/routers/setup.py), never when it begins. A claim begun under one
    address and finished under another leaves the first attempt's Member and
    Account behind with no passkey, and an admin role on that leftover would be
    an admin account for whoever later completed it.
    """
    user = await account_for_member(uow.session, member_id)
    if user is None:
        user = Account(member_id=member_id, role="member")
        uow.session.add(user)
        await uow.session.flush()
    return user


async def register_passkey_begin(
    email: str, first_name: str, surname: str, uow: AbstractUnitOfWork
) -> dict:
    """Begin the first-admin claim ceremony (ADR-0003), creating the first
    Admin's Member as well as their Account (#432): there is no sign-in without
    a kendoka, the first Admin included.

    Only the setup router calls this, after checking the pre-provisioned
    SETUP_TOKEN and that the instance is unclaimed. There is no anonymous
    registration: every other Member joins by invite (#472).

    An existing archived or suspended Member is refused here, as complete
    would refuse them, before the browser is asked for a passkey (#484).
    """
    directory = member_directory_for(uow)
    if await directory.barred_status(email) is not None:
        refuse_registration()
    member_id = await directory.ensure_member(email, first_name, surname, claim=True)
    user = await _get_or_create_account(member_id, uow)

    ceremony = register_begin(Subject(user_id=user.id, user_name=email))

    user.pending_challenge = ceremony.challenge
    user.challenge_issued_at = datetime.now(UTC)
    await uow.commit()

    return ceremony.response


async def register_passkey_complete(
    payload: PasskeyRegisterCompleteRequest, uow: AbstractUnitOfWork
) -> PasskeyRegisterCompleteResponse:
    """Complete the first-admin claim ceremony begun by register_passkey_begin.
    Same callers, same gate."""
    user = await account_for_email(uow.session, payload.email)
    if user is None:
        log_security_event("passkey_registered", "failure")
        raise _AUTH_FAILED

    # Only an Account nobody has enrolled yet. Setup reopens once the last
    # passkey on the instance is gone, and an Admin who deleted their only
    # passkey while holding recovery codes still owns that Account; the claim
    # must not hand it to whoever holds the setup token. Adding a passkey to
    # an enrolled Account goes through add_passkey_*, which takes the Account
    # from the session.
    if await _is_enrolled(uow, user.id):
        log_security_event("passkey_registered", "failure", user_id=user.id)
        raise _AUTH_FAILED

    # The claim reuses an existing Member with this email. An archived or
    # suspended one would become an Admin who can never sign in, and closing
    # setup behind them would lock the dojo out (#484). Refused before the
    # passkey is stored, so setup stays open.
    if not await may_sign_in(uow.session, user.id):
        log_security_event("passkey_registered", "failure", user_id=user.id)
        raise _AUTH_FAILED

    return await add_passkey_complete(user, payload.email, payload.credential, uow)


async def add_passkey_begin(
    account: Account, email: str, uow: AbstractUnitOfWork
) -> dict:
    """Begin adding a passkey to an Account the caller has already proved is
    theirs (a session, or a recovery token), never one named by a submitted
    email (#443, #472)."""
    ceremony = register_begin(Subject(user_id=account.id, user_name=email))
    account.pending_challenge = ceremony.challenge
    account.challenge_issued_at = datetime.now(UTC)
    await uow.commit()
    return ceremony.response


async def _is_enrolled(uow: AbstractUnitOfWork, account_id: str) -> bool:
    """Whether the Account has a passkey or recovery codes."""
    result = await uow.session.execute(
        select(
            exists().where(PasskeyCredential.user_id == account_id)
            | exists().where(RecoveryCode.user_id == account_id)
        )
    )
    return result.scalar_one()


async def add_passkey_complete(
    user: Account,
    email: str,
    credential: PasskeyCredentialResponse,
    uow: AbstractUnitOfWork,
) -> PasskeyRegisterCompleteResponse:
    """Verify a registration response against `user`'s pending challenge and
    store the credential.

    Trusts that the caller may add a passkey to `user`: the router only passes
    the Account from a session or recovery token, and register_passkey_complete
    only the setup claim's Account, with no passkey or recovery codes yet.
    """
    # The same generic 401 as every other failure: a 400 here would only ever
    # be reachable for an Account that exists, and accounts sit in the "no
    # pending challenge" state most of the time -- making 400-vs-401 a
    # high-hit-rate enumeration oracle. The specific reason still goes to the
    # security log.
    if not user.pending_challenge or not user.challenge_issued_at:
        log_security_event("passkey_registered", "failure", user_id=user.id)
        raise _AUTH_FAILED
    age = datetime.now(UTC) - user.challenge_issued_at.replace(tzinfo=UTC)
    if age > timedelta(seconds=config.WEBAUTHN_CHALLENGE_TTL_SECONDS):
        log_security_event("passkey_registered", "failure", user_id=user.id)
        raise _AUTH_FAILED
    expected_challenge = decode_challenge(user.pending_challenge)

    try:
        verified = webauthn.verify_registration_response(
            credential=to_registration_credential(credential),
            expected_challenge=expected_challenge,
            expected_rp_id=config.WEBAUTHN_RP_ID,
            expected_origin=config.WEBAUTHN_ORIGIN,
            # Enforce, do not merely request. py_webauthn defaults this to
            # False and only checks authenticator-data's uv bit when it is
            # True, so without it the userVerification="required" advertised
            # by register_passkey_begin is decorative: a caller driving the
            # API directly could enrol a credential that performed no user
            # verification at all.
            require_user_verification=True,
        )
    except Exception as exc:
        log_security_event("passkey_registered", "failure", user_id=user.id)
        raise _AUTH_FAILED from exc

    existing_count_result = await uow.session.execute(
        select(func.count())
        .select_from(PasskeyCredential)
        .where(PasskeyCredential.user_id == user.id)
    )
    existing_count = existing_count_result.scalar_one()
    show_nudge = existing_count == 0

    aaguid_raw = verified.aaguid
    aaguid_str = str(aaguid_raw) if aaguid_raw is not None else None
    passkey = PasskeyCredential(
        user_id=user.id,
        credential_id=verified.credential_id,
        public_key=verified.credential_public_key,
        sign_count=verified.sign_count,
        aaguid=aaguid_str,
        label=label_from_aaguid(aaguid_str),
    )
    uow.session.add(passkey)
    user.pending_challenge = None
    await uow.commit()

    log_security_event("passkey_registered", "success", user_id=user.id)
    return PasskeyRegisterCompleteResponse(
        sub=user.id,
        email=email,
        role=user.role,
        show_nudge=show_nudge,
    )


async def login_passkey_begin(email: str, uow: AbstractUnitOfWork) -> dict:
    """Begin an authentication ceremony, whether or not `email` is known.

    Both outcomes call the same `login_begin()`, so the response cannot
    differ; the only branch here is whether there is a row to persist the
    challenge against. See app.auth.webauthn_ceremony for the shape rules and
    the three enumeration bugs behind them.
    """
    user = await account_for_email(uow.session, email)
    ceremony = login_begin()
    if user is None:
        return ceremony.response

    user.pending_challenge = ceremony.challenge
    user.challenge_issued_at = datetime.now(UTC)
    await uow.commit()

    return ceremony.response


async def login_passkey_complete(
    payload: PasskeyLoginCompleteRequest, uow: AbstractUnitOfWork
) -> TokenResponse:
    user = await account_for_email(uow.session, payload.email)
    if user is None:
        raise _AUTH_FAILED

    # NOTE: the may-sign-in check (#484) deliberately happens *after*
    # signature verification below, not here. Rejecting a barred Member before
    # the credential is checked lets anyone distinguish "archived or suspended
    # member" from "unknown email" with a single request carrying a junk
    # credential. Membership Status is only disclosed to someone who has
    # already proved possession of a registered passkey.

    # Decode credential_id from the request to find the matching stored credential
    cred_id_b64 = payload.credential.id
    cred_id_bytes = decode_challenge(cred_id_b64)

    cred_result = await uow.session.execute(
        select(PasskeyCredential).where(
            PasskeyCredential.user_id == user.id,
            PasskeyCredential.credential_id == cred_id_bytes,
        )
    )
    stored_cred = cred_result.scalar_one_or_none()
    if stored_cred is None:
        raise _AUTH_FAILED

    if not user.pending_challenge or not user.challenge_issued_at:
        raise _AUTH_FAILED
    age = datetime.now(UTC) - user.challenge_issued_at.replace(tzinfo=UTC)
    if age > timedelta(seconds=config.WEBAUTHN_CHALLENGE_TTL_SECONDS):
        raise _AUTH_FAILED
    expected_challenge = decode_challenge(user.pending_challenge)

    try:
        verified = webauthn.verify_authentication_response(
            credential=to_authentication_credential(payload.credential),
            expected_challenge=expected_challenge,
            expected_rp_id=config.WEBAUTHN_RP_ID,
            expected_origin=config.WEBAUTHN_ORIGIN,
            credential_public_key=stored_cred.public_key,
            credential_current_sign_count=stored_cred.sign_count,
            # See register_passkey_complete: this is what actually checks the
            # uv flag that login_passkey_begin asks for.
            require_user_verification=True,
        )
    except Exception as exc:
        raise _AUTH_FAILED from exc

    # Credential possession is now proven, so disclosing Membership Status
    # here tells the caller nothing they could not already infer about their
    # own membership. See the note above on where this check sits.
    if not await may_sign_in(uow.session, user.id):
        user.pending_challenge = None
        await uow.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Membership is archived or suspended",
        )

    stored_cred.sign_count = verified.new_sign_count
    stored_cred.last_used_at = datetime.now(UTC)
    user.pending_challenge = None
    token = await start_auth_session(
        SqlAuthSessionRepository(uow.session), user.id, stored_cred.id
    )
    await uow.commit()

    log_security_event("login_passkey", "success", user_id=user.id)
    return TokenResponse(access_token=token, theme=user.theme)
