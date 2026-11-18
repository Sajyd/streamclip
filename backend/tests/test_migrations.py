"""Database migrations: reversible, repeatable and in sync with the models."""

import importlib.util
import os
from pathlib import Path

import psycopg
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, make_url

from app.db import migrations
from app.db.engine import normalize_database_url
from app.models import Base
from tests.conftest import create_test_database, drop_test_database


def _libpq(url: str) -> str:
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


def _snapshot(url: str) -> dict[str, list[str]]:
    with psycopg.connect(_libpq(url)) as connection:

        def column(sql: str) -> list[str]:
            return sorted(row[0] for row in connection.execute(sql).fetchall())

        return {
            "tables": column("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"),
            "policies": column("SELECT tablename FROM pg_policies WHERE schemaname = 'public'"),
            "plans": column("SELECT code FROM plans")
            if connection.execute("SELECT to_regclass('public.plans')").fetchone()[0]  # type: ignore[index]
            else [],
        }


def test_upgrade_downgrade_upgrade_roundtrip() -> None:
    name = f"streamclip_migration_{os.getpid()}"
    url = create_test_database(name)
    try:
        migrations.upgrade(url)
        head = _snapshot(url)
        assert set(head["tables"]) == set(Base.metadata.tables) | {"alembic_version"}
        assert len(head["policies"]) == 24
        assert head["plans"] == ["business", "creator", "free", "pro", "starter"]

        # Step by step back to an empty database.
        migrations.downgrade(url, "0002")
        assert _snapshot(url)["plans"] == []
        migrations.downgrade(url, "0001")
        assert _snapshot(url)["policies"] == []
        migrations.downgrade(url, "base")
        assert _snapshot(url)["tables"] == ["alembic_version"]

        # And forward again: the application role already exists, which must not matter.
        migrations.upgrade(url)
        assert _snapshot(url) == head
        migrations.upgrade(url)  # already at head: a no-op
        assert _snapshot(url) == head
    finally:
        drop_test_database(name)


def test_models_and_migrated_schema_are_identical(database_url: str) -> None:
    """What `alembic revision --autogenerate` would produce must be empty:
    every model change ships with its migration."""
    engine = create_engine(normalize_database_url(database_url))
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection, opts={"compare_type": True, "compare_server_default": True}
            )
            differences = compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()
    assert differences == []


def test_isolation_migration_snapshot_matches_the_models() -> None:
    path = Path(migrations.MIGRATIONS_DIR) / "versions" / "0002_tenant_isolation.py"
    spec = importlib.util.spec_from_file_location("migration_0002", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    tables = Base.metadata.tables
    assert module.APP_ROLE == "streamclip_app"
    assert sorted(module.TENANT_TABLES) == sorted(
        name for name, table in tables.items() if table.info["rls"] == "tenant"
    )
    assert sorted(module.ORGANIZATION_SELF_TABLES) == sorted(
        name for name, table in tables.items() if table.info["rls"] == "organization_self"
    )
    expected_grants = {}
    expected_columns = {}
    for name, table in tables.items():
        privileges = tuple(
            privilege
            for privilege in table.info["app"]
            if not (privilege == "UPDATE" and table.info["app_update_columns"])
        )
        if privileges:
            expected_grants[name] = privileges
        if table.info["app_update_columns"]:
            expected_columns[name] = tuple(table.info["app_update_columns"])
    assert expected_grants == module.TABLE_GRANTS
    assert expected_columns == module.COLUMN_UPDATE_GRANTS


def test_code_expects_the_latest_revision() -> None:
    assert migrations.expected_revision() == "0006"
