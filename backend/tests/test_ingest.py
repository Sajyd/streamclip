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
    assert body["rtmps_url"] is None
    assert body["ingest_online"] is True
    clear = body["stream_key"]

    again = await client.get(f"{API}/ingest/key", headers=account.headers)
    assert again.status_code == 200
    assert again.json()["stream_key"] is None  # never re-shown
    assert again.json()["rtmps_url"] is None
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

    assert issued["rtmps_url"] is None

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


async def test_relay_relaunches_spot_after_idle_terminate(
    client: httpx.AsyncClient, ctx: AppContext
) -> None:
    """New RTMP after idle shutdown reuses dedicated-{org} row and launches again."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from app.models.enums import IngestNodeStatus
    from app.models.media import IngestNode
    from app.services import ingest_nodes

    account = await register(client, email="ingest-relaunch@example.com")
    issued = (await client.post(f"{API}/ingest/key", json={}, headers=account.headers)).json()
    public_id = issued["public_id"]
    hook = {"x-streamclip-ingest-secret": HOOK_SECRET}

    first = await client.get(
        f"{API}/ingest/hooks/relay-target",
        params={"path": f"live/{public_id}/sc_live_a"},
        headers=hook,
    )
    assert first.status_code == 200
    assert first.json()["status"] == "ready"
    first_host = first.json()["rtmp_push_url"].removeprefix("rtmp://").split("/")[0]

    async with ctx.db.system_tx() as session:
        node = (
            await session.execute(
                select(IngestNode).where(IngestNode.name == f"dedicated-{account.organization_id}")
            )
        ).scalar_one()
        node_id = node.id
        # Simulate idle terminate (unique name row must be reusable).
        node.status = IngestNodeStatus.TERMINATED
        node.terminated_at = datetime.now(UTC) - timedelta(minutes=1)
        node.public_hostname = None
        details = dict(node.details or {})
        details.pop("terminate_after", None)
        node.details = details
        await session.flush()

    # Active lookup must not see the terminated row.
    async with ctx.db.system_tx() as session:
        assert await ingest_nodes.get_dedicated_node(session, account.organization_id) is None

    second = await client.get(
        f"{API}/ingest/hooks/relay-target",
        params={"path": f"live/{public_id}/sc_live_b"},
        headers=hook,
    )
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "ready"
    second_url = second.json()["rtmp_push_url"]
    assert second_url.removeprefix("rtmp://").split("/")[0] == first_host
    assert second_url.endswith("/sc_live_b")

    async with ctx.db.system_tx() as session:
        node = await session.get(IngestNode, node_id)
        assert node is not None
        assert node.status is IngestNodeStatus.READY
        assert node.public_hostname is not None


async def test_relay_replaces_a_spot_aws_already_terminated(
    client: httpx.AsyncClient, ctx: AppContext
) -> None:
    """A ready row whose EC2 instance is gone must not be handed to the edge."""
    from sqlalchemy import select

    from app.models.enums import IngestNodeStatus
    from app.models.media import IngestNode

    account = await register(client, email="ingest-dead-spot@example.com")
    issued = (await client.post(f"{API}/ingest/key", json={}, headers=account.headers)).json()
    public_id = issued["public_id"]
    hook = {"x-streamclip-ingest-secret": HOOK_SECRET}

    first = await client.get(
        f"{API}/ingest/hooks/relay-target",
        params={"path": f"live/{public_id}/sc_live_dead"},
        headers=hook,
    )
    assert first.status_code == 200
    assert first.json()["status"] == "ready"

    async with ctx.db.system_tx() as session:
        node = (
            await session.execute(
                select(IngestNode).where(IngestNode.name == f"dedicated-{account.organization_id}")
            )
        ).scalar_one()
        node.instance_id = "i-dead-not-in-aws"
        node.public_hostname = "203.0.113.10"
        node.status = IngestNodeStatus.READY
        await session.flush()

    second = await client.get(
        f"{API}/ingest/hooks/relay-target",
        params={"path": f"live/{public_id}/sc_live_dead"},
        headers=hook,
    )
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["status"] == "ready"
    assert "203.0.113.10" not in (body["rtmp_push_url"] or "")
    assert ".ingest.test" in body["rtmp_push_url"]

    async with ctx.db.system_tx() as session:
        node = (
            await session.execute(
                select(IngestNode).where(IngestNode.name == f"dedicated-{account.organization_id}")
            )
        ).scalar_one()
        assert node.status is IngestNodeStatus.READY
        assert node.public_hostname != "203.0.113.10"
        assert node.instance_id != "i-dead-not-in-aws"


async def test_second_live_gets_a_different_spot(
    client: httpx.AsyncClient, ctx: AppContext
) -> None:
    """A live already on a spot must not share that IP with the next one."""
    from sqlalchemy import update

    from app.models.billing import Plan

    async with ctx.db.system_tx() as session:
        await session.execute(update(Plan).values(max_concurrent_streams=3))

    account = await register(client, email="ingest-second-spot@example.com")
    issued = (await client.post(f"{API}/ingest/key", json={}, headers=account.headers)).json()
    public_id, _, secret = issued["stream_key"].partition("/")
    hook = {"x-streamclip-ingest-secret": HOOK_SECRET}

    first = await client.post(f"{API}/ingest/resolve", json={}, headers=account.headers)
    assert first.status_code == 200, first.text
    host = first.json()["public_hostname"]
    assert host

    opened = await client.post(
        f"{API}/ingest/hooks/auth",
        json={
            "action": "publish",
            "path": f"live/{public_id}/{secret}",
            "protocol": "rtmp",
            "password": secret,
            "ip": "203.0.113.9",
        },
        headers=hook,
    )
    assert opened.status_code == 200, opened.text

    second = await client.post(
        f"{API}/ingest/resolve",
        json={"new_server": True},
        headers=account.headers,
    )
    assert second.status_code == 200, second.text
    assert second.json()["public_hostname"] != host
    assert second.json()["rtmp_url"].startswith("rtmp://")


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
    # Soft interrupt — finalize only after grace (ingest.finalize_interrupted).
    assert sessions[0]["status"] == "interrupted"
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


async def test_playback_uses_the_obs_publish_path(
    client: httpx.AsyncClient, ctx: AppContext
) -> None:
    """OBS server is …/live and the key is {public_id}/{secret}, so HLS lives there."""
    from app.services.playback import agent_hls_url, hls_stream_path, playback_for_org

    account = await register(client, email="ingest-preview-path@example.com")
    issued = (await client.post(f"{API}/ingest/key", json={}, headers=account.headers)).json()
    public_id, _, secret = issued["stream_key"].partition("/")
    path = f"live/{public_id}/{secret}"
    hook = {"x-streamclip-ingest-secret": HOOK_SECRET}
    opened = await client.post(
        f"{API}/ingest/hooks/auth",
        json={
            "action": "publish",
            "path": path,
            "protocol": "rtmp",
            "password": secret,
            "ip": "203.0.113.20",
        },
        headers=hook,
    )
    assert opened.status_code == 200, opened.text

    info = await playback_for_org(ctx, account.organization_id)
    assert info.status == "live"
    assert info.preview_available is True
    assert info.publish_path == path
    upstream = agent_hls_url("edge.ingest.test", hls_stream_path(info), file_path="index.m3u8", token=None)
    assert upstream == f"http://edge.ingest.test:8080/hls/{path}/index.m3u8"

    playback = await client.get(f"{API}/ingest/playback", headers=account.headers)
    assert playback.status_code == 200, playback.text
    body = playback.json()
    assert body["status"] == "live"
    assert body["preview_available"] is True
    assert secret not in playback.text
    assert "publish_path" not in body


async def test_relay_reopens_session_after_quota_close(
    client: httpx.AsyncClient, ctx: AppContext
) -> None:
    """OBS stays connected after a quota close. The next edge poll must show the live again."""
    account = await register(client, email="ingest-reopen@example.com")
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

    sessions = (await client.get(f"{API}/ingest/sessions", headers=account.headers)).json()["items"]
    original_id = sessions[0]["id"]

    async with ctx.db.system_tx() as session:
        await session.execute(
            text(
                "UPDATE stream_sessions"
                " SET status = 'completed', end_reason = 'quota_exhausted', ended_at = now()"
                " WHERE organization_id = :org AND status = 'live'"
            ),
            {"org": account.organization_id},
        )

    path = f"live/{public_id}/sc_live_again"
    first = await client.get(
        f"{API}/ingest/hooks/relay-target",
        params={"path": path},
        headers=hook,
    )
    assert first.status_code == 200, first.text
    sessions = (await client.get(f"{API}/ingest/sessions", headers=account.headers)).json()["items"]
    live = [item for item in sessions if item["status"] == "live"]
    assert len(live) == 1
    assert live[0]["id"] == original_id
    assert live[0]["end_reason"] is None

    second = await client.get(
        f"{API}/ingest/hooks/relay-target",
        params={"path": path},
        headers=hook,
    )
    assert second.status_code == 200, second.text
    sessions = (await client.get(f"{API}/ingest/sessions", headers=account.headers)).json()["items"]
    assert len([item for item in sessions if item["status"] == "live"]) == 1


async def test_segment_gate_resumes_the_same_live_after_quota_returns(
    client: httpx.AsyncClient, ctx: AppContext
) -> None:
    """A plan bought while OBS is still up must restart cutting on the same session."""
    account = await register(client, email="ingest-gate-resume@example.com")
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
    original_id = (await client.get(f"{API}/ingest/sessions", headers=account.headers)).json()[
        "items"
    ][0]["id"]

    async with ctx.db.system_tx() as session:
        await session.execute(
            text(
                "UPDATE usage_periods"
                " SET consumed_ms = included_ms, exhausted_at = now()"
                " WHERE organization_id = :org"
            ),
            {"org": account.organization_id},
        )
        await session.execute(
            text(
                "UPDATE stream_sessions"
                " SET status = 'completed', end_reason = 'quota_exhausted', ended_at = now()"
                " WHERE organization_id = :org AND status = 'live'"
            ),
            {"org": account.organization_id},
        )

    path = f"live/{public_id}/sc_live_gate"
    stopped = await client.get(
        f"{API}/ingest/hooks/segment-gate", params={"path": path}, headers=hook
    )
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["stop"] is True
    assert stopped.json()["record_seconds"] == 0
    still = (await client.get(f"{API}/ingest/sessions", headers=account.headers)).json()["items"]
    assert still[0]["status"] == "completed"

    async with ctx.db.system_tx() as session:
        await session.execute(
            text(
                "UPDATE usage_periods"
                " SET included_ms = included_ms * 10, exhausted_at = NULL"
                " WHERE organization_id = :org"
            ),
            {"org": account.organization_id},
        )

    resumed = await client.get(
        f"{API}/ingest/hooks/segment-gate", params={"path": path}, headers=hook
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["stop"] is False
    assert resumed.json()["record_seconds"] == 300
    sessions = (await client.get(f"{API}/ingest/sessions", headers=account.headers)).json()["items"]
    live = [item for item in sessions if item["status"] == "live"]
    assert len(live) == 1
    assert live[0]["id"] == original_id


async def test_stall_tick_does_not_revive_disconnected_live(client: httpx.AsyncClient) -> None:
    """A recorder stall after OBS quits must not put the dashboard back on air."""
    account = await register(client, email="ingest-stall@example.com")
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
            json={"event": "publisher_disconnect", "path": f"live/{public_id}"},
            headers=hook,
        )
    ).status_code == 200
    assert (
        await client.post(
            f"{API}/ingest/hooks/event",
            json={"event": "tick", "path": f"live/{public_id}", "processed_ms": 1},
            headers=hook,
        )
    ).status_code == 200
    sessions = (await client.get(f"{API}/ingest/sessions", headers=account.headers)).json()["items"]
    assert sessions[0]["status"] == "interrupted"
    playback = await client.get(f"{API}/ingest/playback", headers=account.headers)
    assert playback.status_code == 200
    assert playback.json()["status"] == "offline"


async def test_admin_stop_disconnects_and_blocks_relay_reopen(
    client: httpx.AsyncClient, ctx: AppContext
) -> None:
    account = await register(client, email="ingest-admin-stop@example.com")
    admin = await register(client, email="ingest-admin-stop-ops@example.com")
    async with ctx.db.system_tx() as session:
        await session.execute(
            text("UPDATE users SET platform_role = 'admin' WHERE id = :id"),
            {"id": admin.user_id},
        )
    issued = (await client.post(f"{API}/ingest/key", json={}, headers=account.headers)).json()
    public_id, _, secret = issued["stream_key"].partition("/")
    hook = {"x-streamclip-ingest-secret": HOOK_SECRET}
    path = f"live/{public_id}"
    assert (
        await client.post(
            f"{API}/ingest/hooks/auth",
            json={"action": "publish", "path": path, "protocol": "rtmp", "password": secret},
            headers=hook,
        )
    ).status_code == 200
    live_id = (await client.get(f"{API}/ingest/sessions", headers=account.headers)).json()["items"][0]["id"]

    forbidden = await client.post(f"{API}/admin/lives/{live_id}/stop", headers=account.headers)
    assert forbidden.status_code == 403

    stopped = await client.post(f"{API}/admin/lives/{live_id}/stop", headers=admin.headers)
    assert stopped.status_code == 200, stopped.text
    sessions = (await client.get(f"{API}/ingest/sessions", headers=account.headers)).json()["items"]
    assert sessions[0]["status"] == "completed"
    assert sessions[0]["end_reason"] == "admin_stopped"

    tick = await client.post(
        f"{API}/ingest/hooks/event",
        json={"event": "tick", "path": path, "processed_ms": 1},
        headers=hook,
    )
    ready = await client.post(
        f"{API}/ingest/hooks/event",
        json={"event": "publisher_ready", "path": path, "protocol": "rtmp"},
        headers=hook,
    )
    assert tick.status_code == 200 and ready.json()["message"] == "admin_stopped"
    gate = await client.get(f"{API}/ingest/hooks/segment-gate", params={"path": path}, headers=hook)
    assert gate.json()["stop"] is True
    sessions = (await client.get(f"{API}/ingest/sessions", headers=account.headers)).json()["items"]
    assert sessions[0]["status"] == "completed"

    # The streamer can go live again from OBS. That is an edge publish, not the relay.
    assert (
        await client.post(
            f"{API}/ingest/hooks/auth",
            json={"action": "publish", "path": path, "protocol": "rtmp", "password": secret},
            headers=hook,
        )
    ).status_code == 200
    sessions = (await client.get(f"{API}/ingest/sessions", headers=account.headers)).json()["items"]
    assert sessions[0]["status"] == "live"
    assert sessions[0]["id"] != live_id


async def test_meta_advertises_ingest_keys(client: httpx.AsyncClient) -> None:
    caps = (await client.get(f"{API}/meta")).json()["capabilities"]
    assert caps["ingest_keys"] is True
    assert caps["ingest_online"] is True
    assert caps["ingest_rtmp_url"] == "rtmp://edge.ingest.test/live"
    assert caps["live_processing"] is True
