"""Health probes, request handling, trusted-proxy rules and configuration safety."""

import secrets
from collections.abc import AsyncIterator

import httpx
import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import select, text

from app.context import AppContext
from app.core.config import Settings
from app.db.engine import normalize_database_url
from app.main import create_app
from app.models.system import AuditLog
from tests.conftest import BFF_SECRET, CRON_SECRET
from tests.helpers import API, PASSWORD, error_code, register, unique_email

STRONG = secrets.token_urlsafe(32)


def _production(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "production",
        "database_url": "postgresql://u:p@db.example.com/app",
        "jwt_signing_keys": f"k1:{STRONG}",
        "public_app_url": "https://app.example.com",
        "bff_shared_secret": STRONG,
        "cron_secret": STRONG,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


# --- Probes --------------------------------------------------------------------


async def test_liveness_and_readiness(client: httpx.AsyncClient, ctx: AppContext) -> None:
    assert (await client.get(f"{API}/healthz")).json() == {"status": "ok"}
    ready = await client.get(f"{API}/readyz?deep=true")
    assert ready.status_code == 200
    assert ready.json() == {
        "status": "ready",
        "checks": {"database": "ok", "migrations": "ok", "storage": "ok"},
    }

    # Code newer than the schema: not ready, so the platform keeps the old version.
    async with ctx.db.system_tx() as session:
        await session.execute(text("UPDATE alembic_version SET version_num = '0001'"))
    try:
        behind = await client.get(f"{API}/readyz")
    finally:
        async with ctx.db.system_tx() as session:
            await session.execute(text("UPDATE alembic_version SET version_num = '0003'"))
    assert behind.status_code == 503
    assert behind.json()["checks"]["migrations"] == "expected 0003, found 0001"


async def test_readiness_reports_an_unreachable_database(settings: Settings) -> None:
    from app.context import build_context

    broken = settings.model_copy(
        update={"database_url": SecretStr("postgresql://nobody:nothing@127.0.0.1:1/none")}
    )
    context = build_context(broken)
    transport = httpx.ASGITransport(app=create_app(broken, context))
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as http:
        assert (await http.get(f"{API}/healthz")).status_code == 200  # liveness is independent
        response = await http.get(f"{API}/readyz")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "checks": {"database": "unavailable"}}
    assert "nothing" not in response.text  # no connection details in the answer
    await context.db.dispose()


async def test_meta_describes_real_capabilities(client: httpx.AsyncClient) -> None:
    body = (await client.get(f"{API}/meta")).json()
    assert body["name"] == "STREAMCLIP" and body["environment"] == "test"
    assert body["password_min_length"] == 10
    assert body["capabilities"] == {
        "registration_open": True,
        "email_delivery": True,
        "billing": True,
        "billing_test_mode": True,
        "storage": True,
        "live_processing": True,
        "ingest_keys": True,
        "ingest_online": False,
        "ingest_rtmp_url": None,
        "ingest_api_url": "http://app.test/rtmp",
        "social_oauth": True,
    }


# --- Scheduled maintenance -----------------------------------------------------


async def test_cron_endpoint_requires_its_secret(client: httpx.AsyncClient) -> None:
    url = f"{API}/internal/cron/maintenance"
    for headers in (
        {},
        {"Authorization": "Bearer wrong"},
        {"Authorization": CRON_SECRET},
        {"Authorization": f"Basic {CRON_SECRET}"},
    ):
        response = await client.get(url, headers=headers)
        assert response.status_code == 401, headers
    authorized = {"Authorization": f"Bearer {CRON_SECRET}"}
    first = await client.get(url, headers=authorized)
    assert first.status_code == 200
    assert first.json() == {"status": "ok", "tasks": {"succeeded": 1, "retried": 0, "dead": 0}}
    # Idempotent within a day: the daily job is queued once.
    second = await client.get(url, headers=authorized)
    assert second.json()["tasks"] == {"succeeded": 0, "retried": 0, "dead": 0}


# --- Request handling ----------------------------------------------------------


async def test_responses_carry_request_id_and_safe_headers(client: httpx.AsyncClient) -> None:
    generated = await client.get(f"{API}/healthz")
    assert len(generated.headers["x-request-id"]) == 32
    assert generated.headers["x-content-type-options"] == "nosniff"
    assert generated.headers["cache-control"] == "no-store"
    assert generated.headers["referrer-policy"] == "no-referrer"

    echoed = await client.get(f"{API}/healthz", headers={"x-request-id": "trace-1234567"})
    assert echoed.headers["x-request-id"] == "trace-1234567"
    replaced = await client.get(f"{API}/healthz", headers={"x-request-id": "x"})
    assert replaced.headers["x-request-id"] != "x"

    error = await client.get(f"{API}/me", headers={"x-request-id": "trace-abcdefgh"})
    assert error.json()["error"]["request_id"] == "trace-abcdefgh"
    assert error.headers["www-authenticate"] == "Bearer"


async def test_errors_use_one_envelope(client: httpx.AsyncClient) -> None:
    missing = await client.get(f"{API}/no-such-route")
    assert missing.status_code == 404 and error_code(missing) == "not_found"
    wrong_method = await client.delete(f"{API}/healthz")
    assert wrong_method.status_code == 405 and error_code(wrong_method) == "method_not_allowed"
    malformed = await client.post(
        f"{API}/auth/login", content=b"{not json", headers={"content-type": "application/json"}
    )
    assert malformed.status_code == 422 and error_code(malformed) == "validation_error"
    for response in (missing, wrong_method, malformed):
        assert set(response.json()["error"]) == {"code", "message", "details", "request_id"}


async def test_oversized_bodies_are_refused(client: httpx.AsyncClient) -> None:
    big = b'{"email": "' + b"a" * 1_100_000 + b'"}'
    declared = await client.post(
        f"{API}/auth/login", content=big, headers={"content-type": "application/json"}
    )
    assert declared.status_code == 413 and error_code(declared) == "payload_too_large"

    async def chunks() -> AsyncIterator[bytes]:  # no Content-Length: chunked transfer
        for start in range(0, len(big), 64_000):
            yield big[start : start + 64_000]

    streamed = await client.post(
        f"{API}/auth/login", content=chunks(), headers={"content-type": "application/json"}
    )
    assert "content-length" not in streamed.request.headers
    assert streamed.status_code == 413 and error_code(streamed) == "payload_too_large"


async def test_interactive_docs_are_not_exposed_in_production(ctx: AppContext) -> None:
    app = create_app(_production(), ctx)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as http:
        for path in ("/api/v1/docs", "/api/v1/openapi.json", "/docs", "/openapi.json", "/redoc"):
            assert (await http.get(path)).status_code == 404, path
        assert (await http.get("/api/v1/healthz")).status_code == 200


# --- Client address: who is trusted to forward it -------------------------------


async def _login_ip(client: httpx.AsyncClient, ctx: AppContext, headers: dict[str, str]) -> str:
    email = unique_email()
    response = await client.post(
        f"{API}/auth/register",
        json={"email": email, "password": PASSWORD, "accept_terms": True},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    async with ctx.db.system_tx() as session:
        ip = (
            await session.execute(
                select(AuditLog.ip)
                .where(AuditLog.action == "auth.register")
                .order_by(AuditLog.occurred_at.desc())
                .limit(1)
            )
        ).scalar_one()
    return str(ip)


async def test_forwarded_client_address_is_trusted_only_from_our_front_end(
    client: httpx.AsyncClient, ctx: AppContext
) -> None:
    forwarded = {"x-streamclip-client-ip": "198.51.100.7", "x-streamclip-client-ua": "Real/1.0"}
    # Without the shared secret, the claimed address is ignored (spoofing attempt).
    assert await _login_ip(client, ctx, forwarded) == "203.0.113.10"
    assert (
        await _login_ip(client, ctx, {**forwarded, "x-streamclip-bff-token": "guess"})
        == "203.0.113.10"
    )
    # With it, the end user's address and browser are recorded.
    assert (
        await _login_ip(client, ctx, {**forwarded, "x-streamclip-bff-token": BFF_SECRET})
        == "198.51.100.7"
    )
    async with ctx.db.system_tx() as session:
        agent = (
            await session.execute(
                text("SELECT user_agent FROM auth_sessions ORDER BY created_at DESC LIMIT 1")
            )
        ).scalar_one()
    assert agent == "Real/1.0"


async def test_rate_limit_follows_the_real_client_not_the_proxy(
    client: httpx.AsyncClient,
) -> None:
    """Sign-ups are limited per end-user address, even when every request
    arrives from the same front-end server."""

    async def signup(ip: str) -> int:
        response = await client.post(
            f"{API}/auth/register",
            json={"email": unique_email(), "password": PASSWORD, "accept_terms": True},
            headers={"x-streamclip-bff-token": BFF_SECRET, "x-streamclip-client-ip": ip},
        )
        return response.status_code

    assert [await signup("198.51.100.1") for _ in range(11)] == [201] * 10 + [429]
    assert await signup("198.51.100.2") == 201


# --- Configuration safety ------------------------------------------------------


def test_production_configuration_refuses_unsafe_values() -> None:
    assert _production().is_production
    unsafe: list[dict[str, object]] = [
        {"jwt_signing_keys": "k1:short-secret"},
        {"public_app_url": "http://app.example.com"},
        {"email_transport": "console"},
        {"bff_shared_secret": None},
        {"cron_secret": None},
        {"stripe_secret_key": "sk_test_x", "stripe_webhook_secret": None},
    ]
    for overrides in unsafe:
        with pytest.raises(ValidationError, match="Invalid production configuration"):
            _production(**overrides)
    with pytest.raises(ValidationError):
        _production(jwt_signing_keys="no-key-id")
    with pytest.raises(ValidationError):
        _production(environment="prod")


def test_settings_never_print_their_secrets() -> None:
    settings = _production(stripe_secret_key="sk_test_abcdef", stripe_webhook_secret="whsec_abc")
    rendered = repr(settings) + str(settings.model_dump())
    for secret in (STRONG, "sk_test_abcdef", "whsec_abc", "u:p@"):
        assert secret not in rendered
    assert settings.stripe_livemode is False
    assert _production(stripe_secret_key="rk_live_x", stripe_webhook_secret="w").stripe_livemode
    assert _production().storage_enabled is False and _production().billing_enabled is False


def test_database_url_normalisation() -> None:
    assert (
        normalize_database_url("postgres://u:p%40ss@host:5432/db?sslmode=require")
        == "postgresql+psycopg://u:p%40ss@host:5432/db?sslmode=require"
    )
    assert normalize_database_url("postgresql+asyncpg://u@h/db").startswith("postgresql+psycopg://")
    with pytest.raises(ValueError, match="Only PostgreSQL"):
        normalize_database_url("mysql://u@h/db")


async def test_registration_is_refused_for_malformed_requests(client: httpx.AsyncClient) -> None:
    await register(client)
    wrong_type = await client.post(
        f"{API}/auth/register", content=b"email=a@b.co", headers={"content-type": "text/plain"}
    )
    assert wrong_type.status_code == 422
