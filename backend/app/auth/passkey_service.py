from datetime import UTC, datetime, timedelta

import webauthn
from fastapi import HTTPException, status
from sqlalchemy import exists, func, select

from app import config
from app.auth.aaguid import label_from_aaguid
from app.auth.accounts import account_for_email, account_for_member
from app.auth.db_models import Account, PasskeyCredential, RecoveryCode
from app.auth.member_directory import MemberDirectory, member_directory_for
from app.auth.models import (
    AccountClaims,
    PasskeyCredentialResponse,
    PasskeyLoginCompleteRequest,
    PasskeyRegisterCompleteRequest,
    PasskeyRegisterCompleteResponse,
    TokenResponse,
)
from app.auth.token import encode_token
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


async def _is_bootstrap(uow: AbstractUnitOfWork) -> bool:
    """True when no fully-registered user exists yet.

    Counts PasskeyCredential rows, not Account rows, matching the convention in
    app/routers/setup.py. An Account row is inserted before the interactive
    WebAuthn ceremony completes, so counting users would let a single
    abandoned first-run ceremony leave a phantom user behind, flip this to
    False forever, and permanently brick setup (no Member row exists yet, so
    every retry would get a decoy).
    """
    passkey_count = await uow.session.execute(
        select(func.count()).select_from(PasskeyCredential)
    )
    return passkey_count.scalar_one() == 0


async def _get_or_create_account(member_id: str, uow: AbstractUnitOfWork) -> Account:
    """The Member's Account, created if it has none (#432: every Account
    belongs to exactly one Member).

    Always as a member, the first-admin claim included: admin is granted when
    the claim *completes* (app/routers/setup.py), never when it begins. A
    claim begun under one address and finished under another leaves the
    first attempt's Member and Account behind with no passkey, and once the
    instance is claimed the ordinary registration route can reach them. An
    admin role on that leftover would be an admin account for whoever knew
    the abandoned address.
    """
    user = await account_for_member(uow.session, member_id)
    if user is None:
        user = Account(member_id=member_id, role="member", is_active=True)
        uow.session.add(user)
        await uow.session.flush()
    return user


async def register_passkey_begin(
    email: str,
    uow: AbstractUnitOfWork,
    member_directory: MemberDirectory | None = None,
    *,
    bootstrap_names: tuple[str, str] | None = None,
) -> dict:
    """Begin a registration ceremony, whether or not `email` is authorized.

    `bootstrap_names` (first name, surname) is the first-admin claim gate
    (ADR-0003): only the setup router passes it, and only after checking the
    pre-provisioned SETUP_TOKEN. Without it the bootstrap branch below is
    unreachable, so the ordinary registration route cannot be used to claim
    admin on an unclaimed instance — it sees an email with no Member row and
    answers with the decoy, exactly as it does on a claimed one. With it, the
    claim creates the first Admin's Member as well as their Account (#432):
    there is no sign-in without a kendoka, the first Admin included.

    The Member gate (#239) decides only whether there is a `Subject`;
    app.auth.webauthn_ceremony decides what the response looks like in either
    case, so the real and decoy bodies cannot drift apart. Only the real
    path persists a challenge; there is no account row on the decoy path to
    persist one against. That missing write is what makes the decoy faster,
    which is a latency channel rather than a shape one -- covered by
    app.core.middleware.ConstantTimeAuthMiddleware, not here.
    """
    directory = member_directory or member_directory_for(uow)

    is_bootstrap = bootstrap_names is not None and await _is_bootstrap(uow)
    if is_bootstrap:
        assert bootstrap_names is not None  # narrowed by is_bootstrap
        member_id = await directory.ensure_member(email, *bootstrap_names)
    else:
        member_id = await directory.member_id_for(email)
        if member_id is None:
            return register_begin(email, subject=None).response

    user = await _get_or_create_account(member_id, uow)

    ceremony = register_begin(email, Subject(user_id=user.id, user_name=email))

    user.pending_challenge = ceremony.challenge
    user.challenge_issued_at = datetime.now(UTC)
    await uow.commit()

    return ceremony.response


async def register_passkey_complete(
    payload: PasskeyRegisterCompleteRequest,
    uow: AbstractUnitOfWork,
    *,
    allow_bootstrap: bool = False,
) -> PasskeyRegisterCompleteResponse:
    # The other half of the claim gate (ADR-0003). A phantom admin row left by
    # setup's begin would otherwise be completable through the ordinary
    # registration route, which presents no token. Indistinguishable from every
    # other failure here, for the same enumeration reason.
    if not allow_bootstrap and await _is_bootstrap(uow):
        log_security_event("passkey_registered", "failure")
        raise _AUTH_FAILED

    user = await account_for_email(uow.session, payload.email)
    if user is None:
        log_security_event("passkey_registered", "failure")
        raise _AUTH_FAILED

    # The submitted email is all that identifies the caller here, so this
    # ceremony may only enrol an Account nobody has enrolled yet, as an invite
    # does (#443). Otherwise anyone who knows a Member's address could enrol
    # their own authenticator on that Account and sign in as them. Recovery
    # codes count as enrolment too: a Member may delete their only passkey
    # while holding codes, and that Account is still theirs. Adding another
    # passkey goes through add_passkey_*, which takes the Account from the
    # session. Same generic 401, for the same enumeration reason as below.
    if await _is_enrolled(uow, user.id):
        log_security_event("passkey_registered", "failure", user_id=user.id)
        raise _AUTH_FAILED

    return await add_passkey_complete(user, payload.email, payload.credential, uow)


async def add_passkey_begin(
    account: Account, email: str, uow: AbstractUnitOfWork
) -> dict:
    """Begin adding a passkey to an Account the caller has already proved is
    theirs (a session, or a recovery token). See register_passkey_complete
    for why this is not the email-addressed ceremony."""
    ceremony = register_begin(email, Subject(user_id=account.id, user_name=email))
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
    only an Account with no passkey yet.
    """
    # These must not be distinguishable from the unknown-email case above: a
    # 400 here would only ever be reachable for an email that already cleared
    # the Member gate, and accounts sit in the "no pending challenge" state
    # most of the time -- making 400-vs-401 a high-hit-rate enumeration
    # oracle. The specific reason still goes to the security log.
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
        role=user.role,  # type: ignore[arg-type]
        is_active=user.is_active,
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

    # NOTE: the is_active check deliberately happens *after* signature
    # verification below, not here. Rejecting an inactive account before the
    # credential is checked lets anyone distinguish "deactivated member" from
    # "unknown email" with a single request carrying a junk credential.
    # Account status is only disclosed to someone who has already proved
    # possession of a registered passkey.

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

    # Credential possession is now proven, so disclosing account status here
    # tells the caller nothing they could not already infer about their own
    # account. See the note above where this check used to live.
    if not user.is_active:
        user.pending_challenge = None
        await uow.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account deactivated",
        )

    stored_cred.sign_count = verified.new_sign_count
    stored_cred.last_used_at = datetime.now(UTC)
    user.pending_challenge = None
    await uow.commit()

    claims = AccountClaims(
        sub=user.id,
        email=payload.email,
        role=user.role,  # type: ignore[arg-type]
        is_active=user.is_active,
    )
    log_security_event("login_passkey", "success", user_id=user.id)
    return TokenResponse(access_token=encode_token(claims), theme=user.theme)
