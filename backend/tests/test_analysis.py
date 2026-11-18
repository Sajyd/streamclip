"""Analysis windows are opened when analyzed media advances (segment billing)."""

from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.context import AppContext
from app.core import release
from app.core.ids import uuid7
from app.models.analysis import AnalysisJob, AnalysisWindow
from app.models.enums import AnalysisJobKind, JobStatus, WindowStatus
from app.models.media import StreamSession
from app.services import ingest as ingest_service
from app.services.analysis import WINDOW_MS
from app.tasks.queue import enqueue, run_due_tasks
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


async def test_analyzed_progress_opens_window_without_api_transcribe(
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

    # A billed segment opens a window. ASR/Luna run on the EC2, so no
    # analysis.transcribe task is queued for the API worker.
    async with ctx.db.system_tx() as session:
        stream = (
            await session.execute(
                select(StreamSession).order_by(StreamSession.created_at.desc()).limit(1)
            )
        ).scalar_one()
        await ingest_service.record_processed_tick(
            session, stream, processed_ms=WINDOW_MS, media_end_ms=WINDOW_MS
        )

    from app.models.system import Task

    async with ctx.db.system_tx() as session:
        windows = list((await session.execute(select(AnalysisWindow))).scalars())
        jobs = list((await session.execute(select(AnalysisJob))).scalars())
        tasks = list(
            (
                await session.execute(select(Task).where(Task.kind == "analysis.transcribe"))
            ).scalars()
        )

    assert len(windows) == 1
    assert windows[0].sequence == 0
    assert windows[0].start_ms == 0
    assert windows[0].end_ms == WINDOW_MS
    assert windows[0].status is WindowStatus.QUEUED
    assert jobs == []
    assert tasks == []

    # A leftover queued transcribe must not downgrade a window Luna already filled.
    async with ctx.db.system_tx() as session:
        window = (await session.execute(select(AnalysisWindow))).scalar_one()
        window.status = WindowStatus.ANALYZED
        job = AnalysisJob(
            id=uuid7(),
            organization_id=window.organization_id,
            stream_session_id=window.stream_session_id,
            analysis_window_id=window.id,
            kind=AnalysisJobKind.TRANSCRIPTION,
            status=JobStatus.QUEUED,
        )
        session.add(job)
        await session.flush()
        await enqueue(
            session,
            "analysis.transcribe",
            {"job_id": str(job.id), "window_id": str(window.id)},
            queue="analysis",
            organization_id=window.organization_id,
            idempotency_key=f"analysis.transcribe:{job.id}",
        )
        job_id = job.id

    await run_due_tasks(
        ctx,
        worker="test-analysis",
        queues=["analysis"],
        kinds=["analysis.transcribe"],
        max_tasks=5,
        time_budget_seconds=10,
    )

    async with ctx.db.system_tx() as session:
        window = (await session.execute(select(AnalysisWindow))).scalar_one()
        job = await session.get(AnalysisJob, job_id)
    assert window.status is WindowStatus.ANALYZED
    assert job is not None
    assert job.status is JobStatus.SKIPPED
    assert job.error_code == "onbox_pipeline"
