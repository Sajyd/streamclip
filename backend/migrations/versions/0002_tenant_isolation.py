"""Tenant isolation: application role, grants and row-level security.

The API serves tenant requests as the unprivileged role `streamclip_app`
(entered with a transaction-local SET ROLE) with the caller's organization in
the `app.current_org_id` setting. This revision gives that role the minimum
privileges it needs and makes PostgreSQL itself filter every tenant-owned
table by organization: a forgotten WHERE clause cannot leak another tenant's
rows. A missing or empty setting matches nothing (fail closed).

The lists below are a frozen snapshot of the models' `access(...)`
declarations. A test compares the live database with the models, so adding a
table without a matching migration fails the build.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-16 18:30:00+00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "streamclip_app"
CURRENT_ORG = "NULLIF(current_setting('app.current_org_id', true), '')::uuid"

# Tables whose rows belong to one organization (column organization_id).
TENANT_TABLES = [
    "analysis_jobs",
    "analysis_windows",
    "captions",
    "clip_feedback_events",
    "clip_versions",
    "clips",
    "detected_events",
    "highlight_candidate_events",
    "highlight_candidates",
    "media_segments",
    "memberships",
    "notifications",
    "organization_settings",
    "social_accounts",
    "social_publications",
    "speakers",
    "storage_assets",
    "stream_connections",
    "stream_keys",
    "stream_sessions",
    "subscriptions",
    "usage_periods",
    "usage_records",
]

# The organizations table itself: a tenant sees only its own row.
ORGANIZATION_SELF_TABLES = [
    "organizations",
]

# Table-level privileges of the application role. Tables absent from this
# mapping are not accessible to it at all.
TABLE_GRANTS: dict[str, tuple[str, ...]] = {
    "captions": ("SELECT",),
    "clip_feedback_events": ("SELECT",),
    "clip_versions": ("SELECT",),
    "clips": ("SELECT",),
    "memberships": ("SELECT",),
    "notifications": ("SELECT",),
    "organization_settings": ("SELECT", "UPDATE"),
    "organizations": ("SELECT",),
    "plans": ("SELECT",),
    "social_publications": ("SELECT",),
    "speakers": ("SELECT",),
    "storage_assets": ("SELECT",),
    "stream_connections": ("SELECT",),
    "stream_keys": ("SELECT",),
    "stream_sessions": ("SELECT",),
    "subscriptions": ("SELECT",),
    "usage_periods": ("SELECT",),
    "usage_records": ("SELECT",),
}

# Tables where the application role may only update specific columns.
COLUMN_UPDATE_GRANTS: dict[str, tuple[str, ...]] = {
    "notifications": ("read_at",),
    "organizations": ("name", "updated_at"),
}


def upgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                    NOINHERIT NOBYPASSRLS;
            END IF;
        END
        $$;
        """
    )
    # Lets the login role switch to the application role, without inheriting it.
    op.execute(f"GRANT {APP_ROLE} TO CURRENT_USER WITH SET TRUE, INHERIT FALSE")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    # Nothing is granted implicitly: future tables start with no access.
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_ROLE}")

    for table, privileges in TABLE_GRANTS.items():
        op.execute(f"GRANT {', '.join(privileges)} ON {table} TO {APP_ROLE}")
    for table, columns in COLUMN_UPDATE_GRANTS.items():
        op.execute(f"GRANT UPDATE ({', '.join(columns)}) ON {table} TO {APP_ROLE}")

    for table in TENANT_TABLES:
        _enable_rls(table, f"organization_id = {CURRENT_ORG}")
    for table in ORGANIZATION_SELF_TABLES:
        _enable_rls(table, f"id = {CURRENT_ORG}")


def _enable_rls(table: str, predicate: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} AS PERMISSIVE FOR ALL TO {APP_ROLE} "
        f"USING ({predicate}) WITH CHECK ({predicate})"
    )


def downgrade() -> None:
    for table in [*TENANT_TABLES, *ORGANIZATION_SELF_TABLES]:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {APP_ROLE}")
    # The role itself is cluster-wide and may serve other databases: kept.
