"""Operator CLI: break-glass admin recovery tokens, and the recovery-attempt IP
retention job kendo-ip-retention.timer runs daily (#467)."""

from __future__ import annotations

import asyncio
import concurrent.futures
import uuid
from collections.abc import Coroutine
from typing import Any

import typer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.accounts import MAY_SIGN_IN, account_for_email
from app.auth.attempt_repository import SqlAttemptRepository
from app.auth.db_models import AdminRecoveryToken
from app.auth.recovery_service import (
    admin_token_expiry,
    generate_admin_token_plaintext,
    hash_admin_token,
)
from app.config import read_secret
from app.members.db_models import Member

app = typer.Typer()


@app.callback(invoke_without_command=True)
def _main(ctx: typer.Context) -> None:
    """KendoDojoManagement break-glass CLI."""


def _make_session_factory(url: str) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(url)
    return async_sessionmaker(engine, expire_on_commit=False)


def _database_url() -> str:
    # Read now, not at import: DATABASE_URL_FILE in the hardened container.
    url = read_secret("DATABASE_URL")
    if not url:
        typer.echo("Error: DATABASE_URL (or DATABASE_URL_FILE) is not set.", err=True)
        raise typer.Exit(code=1)
    return url


def _run(coro: Coroutine[Any, Any, None]) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(asyncio.run, coro).result()
    else:
        asyncio.run(coro)


@app.command()
def create_recovery_token(email: str) -> None:
    """Generate a break-glass admin recovery token for the user with EMAIL."""
    url = _database_url()

    async def _create() -> None:
        factory = _make_session_factory(url)
        async with factory() as session:
            user = await account_for_email(session, email)
            standing = (
                await session.execute(
                    select(Member.membership_status, MAY_SIGN_IN).where(
                        Member.email == email
                    )
                )
            ).one_or_none()

        if user is None or standing is None:
            typer.echo(f"Error: no account found with email '{email}'", err=True)
            raise typer.Exit(code=1)

        # Redemption refuses a Member who may not sign in (#484), so a token
        # minted for one could never be used.
        membership_status, may_sign_in = standing
        if not may_sign_in:
            typer.echo(
                f"Error: Member is {membership_status}; reinstate first "
                "(set membership_status to 'active').",
                err=True,
            )
            raise typer.Exit(code=1)

        plaintext = generate_admin_token_plaintext()
        token_hash = hash_admin_token(plaintext)
        expires_at = admin_token_expiry()

        obj = AdminRecoveryToken(
            id=str(uuid.uuid4()),
            user_id=user.id,
            created_by_id=None,
            token_hash=token_hash,
            expires_at=expires_at,
        )

        async with factory() as session:
            session.add(obj)
            await session.commit()

        typer.echo(plaintext)

    _run(_create())


@app.command()
def clear_expired_ip_addresses() -> None:
    """Clear recovery-attempt IP addresses older than IP_RETENTION (#467)."""
    url = _database_url()

    async def _clear() -> None:
        async with _make_session_factory(url)() as session, session.begin():
            await SqlAttemptRepository(session).clear_expired_ip_addresses()

    _run(_clear())


if __name__ == "__main__":
    app()
