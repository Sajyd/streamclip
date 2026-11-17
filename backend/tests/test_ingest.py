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
    ctx.settings.ingest_hook_secret = SecretStr(HOOK_SECRET)
    # Test env uses FakeSpotLauncher (unique host per org, no shared fallback).
    yield
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
    assert body["ingest_api_url"].endswith("/rtmp")
    assert body["ingest_online"] is True
    clear = body["stream_key"]

    again = await client.get(f"{API}/ingest/key", headers=account.headers)
    assert again.status_code == 200
    assert again.json()["stream_key"] is None  # never re-shown
    assert again.json()["ingest_api_url"].endswith("/rtmp")
    assert again.json()["public_id"] == body["public_id"]

    rotated = await client.post(f"{API}/ingest/key/rotate", json={}, headers=account.headers)
    assert rotated.status_code == 201
    assert rotated.json()["stream_key"] != clear
    assert rotated.json()["public_id"] != body["public_id"]

    revoked = await client.delete(f"{API}/ingest/key", headers=account.headers)
    assert revoked.status_code == 200
    missing = await client.get(f"{API}/ingest/key", headers=account.headers)
    assert missing.status_code == 404


async def test_rtmp_resolve_starts_unique_spot_and_redirects(
    client: httpx.AsyncClient,
) -> None:
    """GET /rtmp?key=… → quota OK → unique spot → 302 rtmp://{org-host}/live."""
    account = await register(client, email="ingest-resolve@example.com")
    issued = (await client.post(f"{API}/ingest/key", json={}, headers=account.headers)).json()
    clear = issued["stream_key"]
    org_hex = None

    # Memorable public URL (also available under /api/v1/ingest/resolve).
    redirected = await client.get("/rtmp", params={"key": clear}, follow_redirects=False)
    assert redirected.status_code == 302
    location = redirected.headers["location"]
    assert location.startswith("rtmp://")
    assert location.endswith(":1935/live")
    host = location.removeprefix("rtmp://").split(":")[0]
    assert host.endswith(".ingest.test")
    org_hex = host.split(".", 1)[0]

    # Second org must get a different host (no shared fallback).
    other = await register(client, email="ingest-resolve-b@example.com")
    other_key = (await client.post(f"{API}/ingest/key", json={}, headers=other.headers)).json()[
        "stream_key"
    ]
    other_redir = await client.get("/rtmp", params={"key": other_key}, follow_redirects=False)
    assert other_redir.status_code == 302
    other_host = other_redir.headers["location"].removeprefix("rtmp://").split(":")[0]
    assert other_host != host
    assert other_host.split(".", 1)[0] != org_hex

    # Logged-in dashboard resolve returns JSON (no need to re-enter secret).
    resolved = await client.post(f"{API}/ingest/resolve", json={}, headers=account.headers)
    assert resolved.status_code == 200
    body = resolved.json()
    assert body["status"] == "ready"
    assert body["rtmp_url"] == location
    assert body["ingest_api_url"].endswith("/rtmp")


async def test_rtmp_resolve_rejects_exhausted_quota(client: httpx.AsyncClient) -> None:
    account = await register(client, email="ingest-resolve-quota@example.com")
    issued = (await client.post(f"{API}/ingest/key", json={}, headers=account.headers)).json()
    clear = issued["stream_key"]
    public_id, _, secret = clear.partition("/")
    hook = {"x-streamclip-ingest-secret": HOOK_SECRET}

    # Burn the free quota via a live tick, then resolve must refuse.
    assert (
        await client.get("/rtmp", params={"key": clear}, follow_redirects=False)
    ).status_code == 302
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
            json={"event": "tick", "path": f"live/{public_id}", "processed_ms": 3_600_000},
            headers=hook,
        )
    ).status_code == 200

    blocked = await client.get("/rtmp", params={"key": clear}, follow_redirects=False)
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "quota_exhausted"


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
    assert caps["ingest_api_url"].endswith("/rtmp")
    assert caps["live_processing"] is False
