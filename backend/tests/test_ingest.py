"""Ingest keys, MediaMTX hooks and quota enforcement at publish time."""

from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr

from app.context import AppContext
from app.core import release
from tests.helpers import API, register

HOOK_SECRET = "ingest-hook-test-secret-value-32b"


@pytest.fixture(autouse=True)
def _configure_ingest(ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(release, "INGEST_KEYS_AVAILABLE", True)
    ctx.settings.ingest_public_host = "ingest.test.local"
    ctx.settings.ingest_hook_secret = SecretStr(HOOK_SECRET)
    yield
    ctx.settings.ingest_public_host = None
    ctx.settings.ingest_hook_secret = None


async def test_issue_rotate_and_revoke_stream_key(client: httpx.AsyncClient) -> None:
    account = await register(client, email="ingest-key@example.com")
    created = await client.post(f"{API}/ingest/key", json={"label": "OBS"}, headers=account.headers)
    assert created.status_code == 201
    body = created.json()
    assert body["label"] == "OBS"
    assert body["status"] == "active"
    assert body["stream_key"].startswith(body["public_id"] + "/")
    assert "sc_live_" in body["stream_key"]
    assert body["rtmps_url"].endswith(f"/live/{body['public_id']}")
    assert body["ingest_online"] is True
    clear = body["stream_key"]

    again = await client.get(f"{API}/ingest/key", headers=account.headers)
    assert again.status_code == 200
    assert again.json()["stream_key"] is None  # never re-shown
    assert again.json()["public_id"] == body["public_id"]

    rotated = await client.post(f"{API}/ingest/key/rotate", json={}, headers=account.headers)
    assert rotated.status_code == 201
    assert rotated.json()["stream_key"] != clear
    assert rotated.json()["public_id"] != body["public_id"]

    revoked = await client.delete(f"{API}/ingest/key", headers=account.headers)
    assert revoked.status_code == 200
    missing = await client.get(f"{API}/ingest/key", headers=account.headers)
    assert missing.status_code == 404


async def test_mediamtx_auth_opens_session_and_disconnect_closes(
    client: httpx.AsyncClient,
) -> None:
    account = await register(client, email="ingest-live@example.com")
    issued = (await client.post(f"{API}/ingest/key", json={}, headers=account.headers)).json()
    public_id, _, secret = issued["stream_key"].partition("/")
    hook = {"x-streamclip-ingest-secret": HOOK_SECRET}

    denied = await client.post(
        f"{API}/ingest/hooks/auth",
        json={
            "action": "publish",
            "path": f"live/{public_id}",
            "protocol": "rtmp",
            "password": "wrong",
            "ip": "203.0.113.10",
        },
        headers=hook,
    )
    assert denied.status_code == 403

    allowed = await client.post(
        f"{API}/ingest/hooks/auth",
        json={
            "action": "publish",
            "path": f"live/{public_id}",
            "protocol": "rtmps",
            "password": secret,
            "ip": "203.0.113.10",
        },
        headers=hook,
    )
    assert allowed.status_code == 200

    sessions = (await client.get(f"{API}/ingest/sessions", headers=account.headers)).json()["items"]
    assert len(sessions) == 1
    assert sessions[0]["status"] == "live"
    assert sessions[0]["protocol"] == "rtmps"

    tick = await client.post(
        f"{API}/ingest/hooks/event",
        json={"event": "tick", "path": f"live/{public_id}", "processed_ms": 5_000},
        headers=hook,
    )
    assert tick.status_code == 200

    end = await client.post(
        f"{API}/ingest/hooks/event",
        json={"event": "publisher_disconnect", "path": f"live/{public_id}"},
        headers=hook,
    )
    assert end.status_code == 200
    sessions = (await client.get(f"{API}/ingest/sessions", headers=account.headers)).json()["items"]
    assert sessions[0]["status"] == "completed"
    assert sessions[0]["processed_ms"] == 5_000


async def test_publish_rejected_when_quota_exhausted(client: httpx.AsyncClient) -> None:
    account = await register(client, email="ingest-quota@example.com")
    issued = (await client.post(f"{API}/ingest/key", json={}, headers=account.headers)).json()
    public_id, _, secret = issued["stream_key"].partition("/")
    hook = {"x-streamclip-ingest-secret": HOOK_SECRET}

    assert (
        await client.post(
            f"{API}/ingest/hooks/auth",
            json={
                "action": "publish",
                "path": f"live/{public_id}",
                "protocol": "rtmp",
                "password": secret,
            },
            headers=hook,
        )
    ).status_code == 200
    assert (
        await client.post(
            f"{API}/ingest/hooks/event",
            json={
                "event": "tick",
                "path": f"live/{public_id}",
                "processed_ms": 3_600_000,
            },
            headers=hook,
        )
    ).status_code == 200

    sessions = (await client.get(f"{API}/ingest/sessions", headers=account.headers)).json()["items"]
    assert sessions[0]["status"] == "completed"
    assert sessions[0]["end_reason"] == "quota_exhausted"

    blocked = await client.post(
        f"{API}/ingest/hooks/auth",
        json={
            "action": "publish",
            "path": f"live/{public_id}",
            "protocol": "rtmp",
            "password": secret,
        },
        headers=hook,
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "quota_exhausted"


async def test_hook_requires_shared_secret(client: httpx.AsyncClient) -> None:
    response = await client.post(
        f"{API}/ingest/hooks/auth",
        json={"action": "publish", "path": "live/x", "password": "y"},
    )
    assert response.status_code == 401


async def test_meta_advertises_ingest_keys(client: httpx.AsyncClient) -> None:
    caps = (await client.get(f"{API}/meta")).json()["capabilities"]
    assert caps["ingest_keys"] is True
    assert caps["ingest_online"] is True
    assert caps["live_processing"] is False
