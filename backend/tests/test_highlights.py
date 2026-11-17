"""Highlights API after persisting a Luna segment analysis."""

from __future__ import annotations

from uuid import UUID

import httpx
import pytest
from sqlalchemy import select

from app.context import AppContext
from app.core.ids import uuid7
from app.models.enums import IngestProtocol, StreamSessionStatus
from app.models.media import StreamSession
from app.services.bedrock_luna import CameraBox, ViralMoment
from app.services.segment_pipeline import persist_segment_analysis
from tests.helpers import API, register


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
            model="amazon.nova-lite-v1:0",
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
