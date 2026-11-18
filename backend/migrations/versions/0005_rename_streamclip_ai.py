"""Replace leftover « STREAMCLIP AI » branding with « STREAMCLIP ».

The Free plan description was seeded with the old product name; the seed
revision never overwrites existing rows.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-18 00:40:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE plans
            SET description = replace(description, 'STREAMCLIP AI', 'STREAMCLIP')
            WHERE description LIKE '%STREAMCLIP AI%'
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE plans
            SET description = 'Pour découvrir STREAMCLIP AI sur vos premiers lives.'
            WHERE code = 'free'
              AND description = 'Pour découvrir STREAMCLIP sur vos premiers lives.'
            """
        )
    )
