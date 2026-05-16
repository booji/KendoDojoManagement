"""Break-glass CLI for admin recovery token generation."""

from __future__ import annotations

import asyncio
import os
import uuid

import typer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.db_models import AdminRecoveryToken, User
from app.auth.recovery_service import (
    admin_token_expiry,
    generate_admin_token_plaintext,
    hash_admin_token,
)

app = typer.Typer()


@app.callback(invoke_without_command=True)
def _main(ctx: typer.Context) -> None:
    """KendoDojoManagement break-glass CLI."""


def _make_session_factory(url: str) -> async_sessionmaker[AsyncSession]:
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    engine = create_async_engine(url, connect_args=connect_args)
    return async_sessionmaker(engine, expire_on_commit=False)


@app.command()
def create_recovery_token(email: str) -> None:
    """Generate a break-glass admin recovery token for the user with EMAIL."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        typer.echo("Error: DATABASE_URL environment variable is not set.", err=True)
        raise typer.Exit(code=1)

    async def _run() -> None:
        factory = _make_session_factory(url)
        async with factory() as session:
            result = await session.execute(select(User).where(User.email == email))
            user = result.scalar_one_or_none()

        if user is None:
            typer.echo(f"Error: no user found with email '{email}'", err=True)
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

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, _run())
            future.result()
    else:
        asyncio.run(_run())


if __name__ == "__main__":
    app()
