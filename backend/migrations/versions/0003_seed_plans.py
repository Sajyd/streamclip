"""Reference data: the commercial plans.

Prices are monthly and tax-inclusive (TTC), in cents. They live in the
database so they can be changed from the back-office without a deployment;
this revision only provides the launch values and never overwrites a plan
that already exists.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-16 18:35:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HOUR = 3600

PLANS = [
    {
        "code": "free",
        "name": "Free",
        "description": "Pour découvrir STREAMCLIP AI sur vos premiers lives.",
        "price_cents": 0,
        "included_seconds": 1 * HOUR,
        "max_clips_per_session": 3,
        "features": {"highlights": ["Sans carte bancaire"]},
        "sort_order": 0,
    },
    {
        "code": "starter",
        "name": "Starter",
        "description": "Pour démarrer avec des lives réguliers.",
        "price_cents": 1900,
        "included_seconds": 20 * HOUR,
        "max_clips_per_session": None,
        "features": {},
        "sort_order": 10,
    },
    {
        "code": "creator",
        "name": "Creator",
        "description": "Pour les créateurs qui streament plusieurs fois par semaine.",
        "price_cents": 4900,
        "included_seconds": 60 * HOUR,
        "max_clips_per_session": None,
        "features": {},
        "sort_order": 20,
    },
    {
        "code": "pro",
        "name": "Pro",
        "description": "Pour les streamers quotidiens et les émissions longues.",
        "price_cents": 9900,
        "included_seconds": 150 * HOUR,
        "max_clips_per_session": None,
        "features": {},
        "sort_order": 30,
    },
    {
        "code": "business",
        "name": "Business",
        "description": "Pour les studios, agences et chaînes multi-émissions.",
        "price_cents": 19900,
        "included_seconds": 400 * HOUR,
        "max_clips_per_session": None,
        "features": {},
        "sort_order": 40,
    },
]


def upgrade() -> None:
    statement = sa.text(
        """
        INSERT INTO plans (id, code, name, description, price_cents, currency,
                           included_seconds, max_clips_per_session, features, sort_order)
        VALUES (gen_random_uuid(), :code, :name, :description, :price_cents, 'eur',
                :included_seconds, :max_clips_per_session, :features, :sort_order)
        ON CONFLICT (code) DO NOTHING
        """
    ).bindparams(sa.bindparam("features", type_=postgresql.JSONB))
    connection = op.get_bind()
    for plan in PLANS:
        connection.execute(statement, plan)


def downgrade() -> None:
    # Plans referenced by subscriptions cannot be removed (foreign key): a
    # downgrade is only possible on a database without customers.
    op.execute(
        sa.text("DELETE FROM plans WHERE code = ANY(:codes)").bindparams(
            codes=[plan["code"] for plan in PLANS]
        )
    )
