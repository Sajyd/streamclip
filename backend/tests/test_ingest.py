"""Ingest keys, MediaMTX hooks and quota enforcement at publish time."""

from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import text

from app.context import AppContext
from app.core import release
from tests.helpers import API, register

HOOK_SECRET = "ingest-hook-test-secret-value-32b"


@pytest.fixture(autouse=True)
def _configure_ingest(ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(release, "INGEST_KEYS_AVAILABLE", True)
    ctx.settings.ingest_hook_secret = SecretStr(HOOK_SECRET)
    ctx.settings.ingest_public_host = "edge.ingest.test"
    # FakeSpotLauncher for dedicated compute spots behind the edge.
    yield
    ctx.settings.ingest_hook_secret = None
    ctx.settings.ingest_public_host = None


async def test_issue_rotate_and_revoke_stream_key(client: httpx.AsyncClient) -> None:
    account = await register(client, email="ingest-key@example.com")
    created = await client.post(f"{API}/ingest/key", json={"label": "OBS"}, headers=account.headers)
    assert created.status_code == 201
    body = created.json()
    assert body["label"] == "OBS"
    assert body["status"] == "active"
    assert body["stream_key"].startswith(body["public_id"] + "/")
    assert "sc_live_" in body["stream_key"]
    assert body["rtmps_url"] == "rtmp://edge.ingest.test/live"
    assert body["ingest_online"] is True
    clear = body["stream_key"]

    again = await client.get(f"{API}/ingest/key", headers=account.headers)
    assert again.status_code == 200
    assert again.json()["stream_key"] is None  # never re-shown
    assert again.json()["rtmps_url"] == "rtmp://edge.ingest.test/live"
    assert again.json()["public_id"] == body["public_id"]

    rotated = await client.post(f"{API}/ingest/key/rotate", json={}, headers=account.headers)
    assert rotated.status_code == 201
    assert rotated.json()["stream_key"] != clear
    assert rotated.json()["public_id"] != body["public_id"]

    revoked = await client.delete(f"{API}/ingest/key", headers=account.headers)
    assert revoked.status_code == 200
    missing = await client.get(f"{API}/ingest/key", headers=account.headers)
    assert missing.status_code == 404


async def test_relay_target_starts_unique_dedicated_spot(
    client: httpx.AsyncClient,
) -> None:
    """Edge polls relay-target → unique dedicated host per org for ffmpeg push."""
    account = await register(client, email="ingest-relay@example.com")
    issued = (await client.post(f"{API}/ingest/key", json={}, headers=account.headers)).json()
    public_id = issued["public_id"]
    hook = {"x-streamclip-ingest-secret": HOOK_SECRET}

    assert issued["rtmps_url"] == "rtmp://edge.ingest.test/live"

    relay = await client.get(
        f"{API}/ingest/hooks/relay-target",
        params={"path": f"live/{public_id}/sc_live_x"},
        headers=hook,
    )
    assert relay.status_code == 200
    body = relay.json()
    assert body["status"] == "ready"
    assert body["rtmp_push_url"].startswith("rtmp://")
    assert ".ingest.test" in body["rtmp_push_url"]
    host = body["rtmp_push_url"].removeprefix("rtmp://").split(":")[0]

    other = await register(client, email="ingest-relay-b@example.com")
    other_id = (await client.post(f"{API}/ingest/key", json={}, headers=other.headers)).json()[
        "public_id"
    ]
    other_relay = (
        await client.get(
            f"{API}/ingest/hooks/relay-target",
            params={"path": f"live/{other_id}/sc_live_y"},
            headers=hook,
        )
    ).json()
    other_host = other_relay["rtmp_push_url"].removeprefix("rtmp://").split(":")[0]
    assert other_host != host


async def test_auth_rejects_exhausted_quota(
    client: httpx.AsyncClient, ctx: AppContext
) -> None:
    """Quota is charged per analyzed 5-min segment — not wall-clock ticks."""
    from sqlalchemy import select

    from app.models.media import StreamSession
    from app.services import ingest as ingest_service

    account = await register(client, email="ingest-auth-quota@example.com")
    issued = (await client.post(f"{API}/ingest/key", json={}, headers=account.headers)).json()
    clear = issued["stream_key"]
    public_id, _, secret = clear.partition("/")
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

    # Tick is heartbeat only — must not exhaust quota.
    assert (
        await client.post(
            f"{API}/ingest/hooks/event",
            json={"event": "tick", "path": f"live/{public_id}", "processed_ms": 3_600_000},
            headers=hook,
        )
    ).status_code == 200
    still_ok = await client.post(
        f"{API}/ingest/hooks/auth",
        json={
            "action": "publish",
            "path": f"live/{public_id}",
            "protocol": "rtmp",
            "password": secret,
        },
        headers=hook,
    )
    assert still_ok.status_code == 200

    # Simulate successful analysis of enough 5-min windows to exhaust free quota.
    async with ctx.db.system_tx() as session:
        stream = (
            await session.execute(
                select(StreamSession).order_by(StreamSession.created_at.desc()).limit(1)
            )
        ).scalar_one()
        await ingest_service.record_processed_tick(
            session, stream, processed_ms=3_600_000, media_end_ms=3_600_000
        )

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

    # Local ffmpeg re-reads the path (action=read) — must not be denied.
    read_ok = await client.post(
        f"{API}/ingest/hooks/auth",
        json={
            "action": "read",
            "path": f"live/{public_id}",
            "protocol": "rtmp",
            "ip": "127.0.0.1",
        },
        headers=hook,
    )
    assert read_ok.status_code == 200

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
    # Ticks do not bill — processed_ms stays 0 until a segment is analyzed.
    assert sessions[0]["processed_ms"] == 0


async def test_stale_live_session_closed_when_listing(
    client: httpx.AsyncClient, ctx: AppContext
) -> None:
    """Abrupt OBS quit without publisher_disconnect must clear 'En direct'."""
    account = await register(client, email="ingest-stale@example.com")
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

    live = (await client.get(f"{API}/ingest/sessions", headers=account.headers)).json()["items"]
    assert live[0]["status"] == "live"

    async with ctx.db.system_tx() as session:
        await session.execute(
            text(
                "UPDATE stream_sessions"
                " SET last_media_at = now() - interval '13 minutes',"
                "     started_at = now() - interval '20 minutes'"
            )
        )

    sessions = (await client.get(f"{API}/ingest/sessions", headers=account.headers)).json()["items"]
    assert sessions[0]["status"] == "completed"
    assert sessions[0]["end_reason"] == "signal_lost"


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
    # Tick alone must not close the session for quota.
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
    assert sessions[0]["status"] == "live"
    assert sessions[0]["processed_ms"] == 0


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
    assert caps["ingest_rtmp_url"] == "rtmp://edge.ingest.test/live"
    assert caps["live_processing"] is True
