"""split full_name into first_name/surname, add display_name, make dob nullable, drop parental_consent_obtained

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-05-25

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "a7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("members") as batch_op:
        # Add new name columns (server_default="" for SQLite not-null compatibility)
        batch_op.add_column(
            sa.Column("first_name", sa.String(255), nullable=False, server_default="")
        )
        batch_op.add_column(
            sa.Column("surname", sa.String(255), nullable=False, server_default="")
        )
        batch_op.add_column(sa.Column("display_name", sa.String(255), nullable=True))
        # Drop legacy columns
        batch_op.drop_column("full_name")
        batch_op.drop_column("parental_consent_obtained")
        # Make dob nullable
        batch_op.alter_column("dob", existing_type=sa.String(10), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("members") as batch_op:
        batch_op.alter_column("dob", existing_type=sa.String(10), nullable=False)
        batch_op.add_column(
            sa.Column(
                "parental_consent_obtained",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column("full_name", sa.String(255), nullable=False, server_default="")
        )
        batch_op.drop_column("display_name")
        batch_op.drop_column("surname")
        batch_op.drop_column("first_name")
