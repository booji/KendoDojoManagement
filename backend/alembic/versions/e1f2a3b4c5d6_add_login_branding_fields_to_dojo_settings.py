"""add login screen branding fields to dojo settings

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-07-12

"""

import sqlalchemy as sa

from alembic import op

revision = "e1f2a3b4c5d6"
down_revision = "d0e1f2a3b4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "dojo_settings",
        sa.Column("background_image_url", sa.String(length=1024), nullable=True),
    )
    op.add_column(
        "dojo_settings",
        sa.Column(
            "login_show_background",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "dojo_settings",
        sa.Column(
            "login_show_logo",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "dojo_settings",
        sa.Column(
            "login_show_name",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("dojo_settings", "login_show_name")
    op.drop_column("dojo_settings", "login_show_logo")
    op.drop_column("dojo_settings", "login_show_background")
    op.drop_column("dojo_settings", "background_image_url")
