"""dojo settings: login_show_logo defaults to true

Issue #615. A fresh install's login screen showed no logo: the toggle
defaulted to false, and with no uploaded logo there was nothing to draw.
The login screen now falls back to the app's own /logo.svg, so the toggle
defaults to on.

Only the column's server default changes. Existing rows keep whatever an
Admin chose (or the old default), so an upgrade changes no login screen.
"""

import sqlalchemy as sa

from alembic import op

revision = "b8c9d0e1f2a4"
down_revision = "a7b8c9d0e1f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("dojo_settings", "login_show_logo", server_default=sa.true())


def downgrade() -> None:
    op.alter_column("dojo_settings", "login_show_logo", server_default=sa.false())
