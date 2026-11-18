"""Highlights API after persisting a Luna segment analysis."""

from __future__ import annotations

from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.context import AppContext
from app.core import release
from app.core.ids import uuid7
from app.models.enums import IngestProtocol, StreamSessionStatus
from app.models.media import StreamSession
from app.services.bedrock_luna import CameraBox, ViralMoment
from app.services.segment_pipeline import persist_segment_analysis
from tests.helpers import API, register

HOOK_SECRET = "ingest-hook-highlights-secret-32bx"


async def _seed_session(ctx: AppContext, organization_id: UUID) -> StreamSession:
    async with ctx.db.system_tx() as session:
        stream = StreamSession(
            id=uuid7(),
            organization_id=organization_id,
            status=StreamSessionStatus.LIVE,
            protocol=IngestProtocol.RTMP,
            processing_profile="standard",
        )
        session.add(stream)
        await session.flush()
        return stream


@pytest.mark.asyncio
async def test_onbox_segment_analysis_hook_persists_highlights(
    client: httpx.AsyncClient, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EC2 :8080 posts finished analysis JSON; API only writes DB rows."""
    monkeypatch.setattr(release, "INGEST_KEYS_AVAILABLE", True)
    ctx.settings.ingest_hook_secret = SecretStr(HOOK_SECRET)
    account = await register(client, email="onbox-hook@example.com")
    stream = await _seed_session(ctx, account.organization_id)
    hook = {"x-streamclip-ingest-secret": HOOK_SECRET}

    posted = await client.post(
        f"{API}/ingest/hooks/segment-analysis",
        headers=hook,
        json={
            "stream_session_id": str(stream.id),
            "sequence": 0,
            "storage_key": f"tmp/lives/{stream.id}/seg_0000.mp4",
            "size_bytes": 5_000_000,
            "frames": 60,
            "model": "us.openai.gpt-6-luna",
            "provider": "onbox",
            "transcript_text": "moment fort en live",
            "transcript_words": [
                {"text": "moment", "start_ms": 1000, "end_ms": 1400},
                {"text": "fort", "start_ms": 1400, "end_ms": 1800},
            ],
            "moments": [
                {
                    "start_ms": 10_000,
                    "end_ms": 70_000,
                    "score": 0.88,
                    "title": "Clip on-box",
                    "description": "Extrait #live",
                    "hashtags": ["#live"],
                    "category": "punchline",
                    "words": [{"text": "moment", "start_ms": 1000, "end_ms": 1400}],
                    "camera": {"detected": True, "x": 1600, "y": 200},
                }
            ],
        },
    )
    assert posted.status_code == 200, posted.text
    assert posted.json()["moments"] == 1

    listed = await client.get(
        f"{API}/highlights",
        params={"stream_session_id": str(stream.id)},
        headers=account.headers,
    )
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "Clip on-box"
    assert items[0]["media_available"] is True
    assert items[0]["stream_session_id"] == str(stream.id)

    async with ctx.db.system_tx() as session:
        refreshed = await session.get(StreamSession, stream.id)
        assert refreshed is not None
        assert refreshed.processed_ms == 300_000


@pytest.mark.asyncio
async def test_persist_and_list_highlights(client: httpx.AsyncClient, ctx: AppContext) -> None:
    account = await register(client, email="highlights@example.com")
    stream = await _seed_session(ctx, account.organization_id)
    moments = [
        ViralMoment(
            start_ms=5_000,
            end_ms=65_000,
            score=0.91,
            title="Moment viral",
            description="Une punchline #live",
            hashtags=["#live"],
            words=[{"text": "wow", "start_ms": 5_000, "end_ms": 5_300}],
            camera=CameraBox(True, 1500, 220),
            category="punchline",
        )
    ]
    async with ctx.db.system_tx() as session:
        loaded = (
            await session.execute(select(StreamSession).where(StreamSession.id == stream.id))
        ).scalar_one()
        await persist_segment_analysis(
            session,
            stream=loaded,
            sequence=0,
            storage_key=f"tmp/lives/{stream.id}/seg_0000.mp4",
            size_bytes=12345,
            moments=moments,
            transcript_text="wow c etait fort",
            frames=12,
            model="us.openai.gpt-6-luna",
            provider="bedrock",
        )

    listed = await client.get(f"{API}/highlights", headers=account.headers)
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item["title"] == "Moment viral"
    assert item["score"] == pytest.approx(0.91)
    assert item["relative_start_ms"] == 5_000
    assert item["relative_end_ms"] == 65_000
    assert item["camera"]["detected"] is True
    assert item["camera"]["x"] == 1500
    assert item["words"][0]["text"] == "wow"
    assert item["media_available"] is True

    detail = await client.get(f"{API}/highlights/{item['id']}", headers=account.headers)
    assert detail.status_code == 200
    assert detail.json()["hashtags"] == ["#live"]
