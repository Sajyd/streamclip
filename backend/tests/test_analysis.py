"""Analysis windows are opened when analyzed media advances (segment billing)."""

from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.context import AppContext
from app.core import release
from app.models.analysis import AnalysisJob, AnalysisWindow
from app.models.enums import JobStatus, WindowStatus
from app.models.media import StreamSession
from app.services import ingest as ingest_service
from app.services.analysis import WINDOW_MS
from app.tasks.queue import run_due_tasks
from tests.helpers import API, register

HOOK_SECRET = "ingest-hook-analysis-secret-32bxx"


@pytest.fixture(autouse=True)
def _configure_ingest(ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(release, "INGEST_KEYS_AVAILABLE", True)
    ctx.settings.ingest_public_host = "ingest.test.local"
    ctx.settings.ingest_hook_secret = SecretStr(HOOK_SECRET)
    yield
    ctx.settings.ingest_public_host = None
    ctx.settings.ingest_hook_secret = None


async def test_analyzed_progress_opens_window_and_skips_without_audio(
    client: httpx.AsyncClient, ctx: AppContext
) -> None:
    account = await register(client, email="analysis@example.com")
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

    # Heartbeat tick must not open analysis windows or bill quota.
    assert (
        await client.post(
            f"{API}/ingest/hooks/event",
            json={
                "event": "tick",
                "path": f"live/{public_id}",
                "processed_ms": WINDOW_MS,
            },
            headers=hook,
        )
    ).status_code == 200

    async with ctx.db.system_tx() as session:
        windows_before = list((await session.execute(select(AnalysisWindow))).scalars())
    assert windows_before == []

    # Successful segment analysis advances processed_ms → schedule windows.
    async with ctx.db.system_tx() as session:
        stream = (
            await session.execute(
                select(StreamSession).order_by(StreamSession.created_at.desc()).limit(1)
            )
        ).scalar_one()
        await ingest_service.record_processed_tick(
            session, stream, processed_ms=WINDOW_MS, media_end_ms=WINDOW_MS
        )

    await run_due_tasks(
        ctx,
        worker="test-analysis",
        queues=["analysis"],
        kinds=["analysis.transcribe"],
        max_tasks=5,
        time_budget_seconds=10,
    )

    async with ctx.db.system_tx() as session:
        windows = list((await session.execute(select(AnalysisWindow))).scalars())
        jobs = list((await session.execute(select(AnalysisJob))).scalars())

    assert len(windows) == 1
    assert windows[0].sequence == 0
    assert windows[0].start_ms == 0
    assert windows[0].end_ms == WINDOW_MS
    assert windows[0].status is WindowStatus.SKIPPED
    assert len(jobs) == 1
    assert jobs[0].status is JobStatus.SKIPPED
    assert jobs[0].error_code == "no_media_segment"
