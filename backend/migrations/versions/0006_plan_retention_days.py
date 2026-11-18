"""Set plan clip/highlight retention days (free=7d, paid tiers longer).

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-18 01:20:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# HD segments expire in ~1 day (app + S3 tmp/ lifecycle). Highlights/clips follow plan.
RETENTION = {
    "free": 7,
    "starter": 30,
    "creator": 60,
    "pro": 90,
    "business": 365,
}


def upgrade() -> None:
    connection = op.get_bind()
    for code, days in RETENTION.items():
        connection.execute(
            sa.text("UPDATE plans SET clip_retention_days = :days WHERE code = :code"),
            {"days": days, "code": code},
        )


def downgrade() -> None:
    connection = op.get_bind()
    for code in RETENTION:
        connection.execute(
            sa.text("UPDATE plans SET clip_retention_days = NULL WHERE code = :code"),
            {"code": code},
        )
