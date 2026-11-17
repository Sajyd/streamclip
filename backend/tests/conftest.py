"""Test fixtures.

Tests run against a real PostgreSQL: a fresh database is created for the
session, owned by a non-superuser role (as on managed PostgreSQL services),
and migrated with Alembic. Row-level security is therefore exercised exactly
as in production. External services (Stripe, S3, e-mail) are replaced by
in-memory fakes; opt-in live tests cover the real ones.
"""

import os
import secrets
from collections.abc import AsyncIterator, Iterator

import httpx
import psycopg
import pytest
from sqlalchemy import make_url, text

# Credentials for the opt-in live tests are captured, then the ambient
# environment is scrubbed so that no developer setting can leak into a test.
LIVE_ENV = {
    key: os.environ.get(key)
    for key in ("STRIPE_SECRET_KEY", "S3_BUCKET", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")
}
LIVE_ENV["S3_REGION"] = os.environ.get("S3_REGION") or os.environ.get("AWS_REGION")
LIVE_ENV["S3_ACCESS_KEY_ID"] = os.environ.get("S3_ACCESS_KEY_ID") or LIVE_ENV["AWS_ACCESS_KEY_ID"]
LIVE_ENV["S3_SECRET_ACCESS_KEY"] = (
    os.environ.get("S3_SECRET_ACCESS_KEY") or LIVE_ENV["AWS_SECRET_ACCESS_KEY"]
)
for _key in list(os.environ):
    if _key.startswith(
        ("STRIPE_", "S3_", "EMAIL_", "SMTP_", "SES_", "DATABASE_", "JWT_", "CRON_", "BFF_")
    ) or _key in ("ENVIRONMENT", "PUBLIC_APP_URL", "REGISTRATION_OPEN"):
        del os.environ[_key]

from app.context import AppContext  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.db import migrations  # noqa: E402
from app.db.engine import Database  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Base  # noqa: E402
from app.security.rate_limit import RateLimiter  # noqa: E402
from tests.helpers import CapturingMailer, FakeStorage, FakeStripeGateway  # noqa: E402

ADMIN_URL = os.environ.get(
    "TEST_DATABASE_ADMIN_URL", "postgresql://postgres:postgres@127.0.0.1:55432/postgres"
)
OWNER_ROLE = "streamclip_test_owner"
OWNER_PASSWORD = "test-owner-password"
WEBHOOK_SECRET = "whsec_test_" + secrets.token_hex(16)
BFF_SECRET = "bff-" + secrets.token_hex(16)
CRON_SECRET = "cron-" + secrets.token_hex(16)

_PRESERVED_TABLES = {"plans", "alembic_version"}


def create_test_database(name: str) -> str:
    """Create an empty database owned by a non-superuser role; return its URL."""
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        role_exists = admin.execute(
            "SELECT 1 FROM pg_roles WHERE rolname = %s", (OWNER_ROLE,)
        ).fetchone()
        if not role_exists:
            admin.execute(
                f"CREATE ROLE {OWNER_ROLE} LOGIN PASSWORD '{OWNER_PASSWORD}' CREATEROLE BYPASSRLS"
            )
        # On a shared development cluster the application role may already
        # exist, created by someone else: let the test owner administer it.
        if admin.execute("SELECT 1 FROM pg_roles WHERE rolname = 'streamclip_app'").fetchone():
            admin.execute(f"GRANT streamclip_app TO {OWNER_ROLE} WITH ADMIN TRUE")
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.execute(f'CREATE DATABASE "{name}" OWNER {OWNER_ROLE}')
    admin_url = make_url(ADMIN_URL)
    return admin_url.set(
        username=OWNER_ROLE, password=OWNER_PASSWORD, database=name
    ).render_as_string(hide_password=False)


def drop_test_database(name: str) -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    name = f"streamclip_test_{os.getpid()}"
    url = create_test_database(name)
    migrations.upgrade(url)
    yield url
    drop_test_database(name)


@pytest.fixture(scope="session")
def settings(database_url: str) -> Settings:
    return Settings(
        environment="test",
        database_url=database_url,
        public_app_url="http://app.test",
        # Two keys: "new" signs, "old" is still accepted (rotation).
        jwt_signing_keys=f"new:{secrets.token_urlsafe(32)},old:{secrets.token_urlsafe(32)}",
        bff_shared_secret=BFF_SECRET,
        cron_secret=CRON_SECRET,
        stripe_secret_key="sk_test_dummy_key_for_unit_tests",
        stripe_webhook_secret=WEBHOOK_SECRET,
        log_level="WARNING",
        password_reset_response_floor_seconds=0.0,
        # Keep role promotion explicit in tests (CLI / _set_role).
        platform_admin_emails="",
    )


@pytest.fixture(scope="session")
async def ctx(settings: Settings) -> AsyncIterator[AppContext]:
    db = Database(settings)
    from app.services.asr import NoneAsr

    context = AppContext(
        settings=settings,
        db=db,
        rate_limiter=RateLimiter(db),
        mailer=CapturingMailer(),
        stripe=FakeStripeGateway(settings),
        storage=FakeStorage(),  # type: ignore[arg-type]
        asr=NoneAsr(),
    )
    async with db.system_tx() as session:
        # Link the paid plans to (fake) Stripe products, as stripe-sync would.
        await session.execute(
            text(
                "UPDATE plans SET stripe_product_id = 'prod_' || code,"
                " stripe_price_id = 'price_' || code WHERE price_cents > 0"
            )
        )
    yield context
    await db.dispose()


@pytest.fixture(autouse=True)
async def _clean_state(ctx: AppContext) -> None:
    tables = ", ".join(
        f'"{name}"' for name in Base.metadata.tables if name not in _PRESERVED_TABLES
    )
    async with ctx.db.system_tx() as session:
        await session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    assert isinstance(ctx.mailer, CapturingMailer)
    ctx.mailer.reset()
    assert isinstance(ctx.stripe, FakeStripeGateway)
    ctx.stripe.reset()
    assert isinstance(ctx.storage, FakeStorage)
    ctx.storage.reset()


@pytest.fixture
def mailer(ctx: AppContext) -> CapturingMailer:
    assert isinstance(ctx.mailer, CapturingMailer)
    return ctx.mailer


@pytest.fixture
def fake_stripe(ctx: AppContext) -> FakeStripeGateway:
    assert isinstance(ctx.stripe, FakeStripeGateway)
    return ctx.stripe


@pytest.fixture
def storage(ctx: AppContext) -> FakeStorage:
    assert isinstance(ctx.storage, FakeStorage)
    return ctx.storage


@pytest.fixture
async def client(settings: Settings, ctx: AppContext) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings, ctx)
    transport = httpx.ASGITransport(app=app, client=("203.0.113.10", 51000))
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as http:
        yield http
