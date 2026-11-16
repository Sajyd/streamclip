"""Helpers around Alembic: locate the migration scripts, run them, and tell
which revision this version of the code expects."""

from functools import lru_cache
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.db.engine import normalize_database_url

BACKEND_DIR = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = BACKEND_DIR / "migrations"


def alembic_config(database_url: str | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    if database_url:
        # '%' must be doubled: Alembic passes options through ConfigParser interpolation.
        config.set_main_option(
            "sqlalchemy.url", normalize_database_url(database_url).replace("%", "%%")
        )
    return config


@lru_cache(maxsize=1)
def expected_revision() -> str:
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    if head is None:
        raise RuntimeError("No Alembic revision found")
    return head


def upgrade(database_url: str, revision: str = "head") -> None:
    command.upgrade(alembic_config(database_url), revision)


def downgrade(database_url: str, revision: str) -> None:
    command.downgrade(alembic_config(database_url), revision)
