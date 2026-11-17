"""Allow tenants to read highlight_candidates (Remotion gallery).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-17 01:00:00+00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "streamclip_app"


def upgrade() -> None:
    op.execute(f"GRANT SELECT ON highlight_candidates TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE SELECT ON highlight_candidates FROM {APP_ROLE}")
