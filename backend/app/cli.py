"""Break-glass CLI for admin recovery token generation."""

from __future__ import annotations

import os
import uuid

import typer
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

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


def _get_engine():
    url = os.environ.get("DATABASE_URL")
    if not url:
        typer.echo("Error: DATABASE_URL environment variable is not set.", err=True)
        raise typer.Exit(code=1)
    sync_url = url.replace("+aiosqlite", "").replace("+asyncpg", "")
    return create_engine(sync_url)


@app.command()
def create_recovery_token(email: str) -> None:
    """Generate a break-glass admin recovery token for the user with EMAIL."""
    engine = _get_engine()
    with Session(engine) as session:
        result = session.execute(select(User).where(User.email == email))
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

    with Session(engine) as session:
        session.add(obj)
        session.commit()

    typer.echo(plaintext)


if __name__ == "__main__":
    app()
