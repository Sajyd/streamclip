"""Onboarding preferences, clip library shell and social listing."""

import httpx
from sqlalchemy import select

from app.context import AppContext
from app.db.engine import TenantContext
from app.models.enums import ContentCategory
from app.models.identity import OrganizationSettings
from tests.helpers import API, register


async def test_onboarding_defaults_then_persists(
    client: httpx.AsyncClient, ctx: AppContext
) -> None:
    account = await register(client)
    me = (await client.get(f"{API}/me", headers=account.headers)).json()
    assert me["onboarding"] == {
        "completed": False,
        "step": "welcome",
        "referral_source": None,
        "usage": None,
        "software": None,
        "social_platforms": [],
        "ingest_ready": False,
        "premium_choice": None,
        "live_detected": False,
        "completed_at": None,
    }

    response = await client.patch(
        f"{API}/onboarding",
        headers=account.headers,
        json={
            "step": "software",
            "referral_source": "youtube",
            "usage": "gaming",
            "software": "obs",
            "social_platforms": ["youtube", "tiktok"],
            "ingest_ready": True,
            "premium_choice": "free",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["referral_source"] == "youtube"
    assert body["usage"] == "gaming"
    assert body["software"] == "obs"
    assert body["social_platforms"] == ["youtube", "tiktok"]
    assert body["ingest_ready"] is True
    assert body["premium_choice"] == "free"
    assert body["completed"] is False

    tenant = TenantContext(organization_id=account.organization_id, user_id=account.user_id)
    async with ctx.db.tenant_tx(tenant) as session:
        settings = (
            await session.execute(
                select(OrganizationSettings).where(
                    OrganizationSettings.organization_id == account.organization_id
                )
            )
        ).scalar_one()
        assert settings.content_category_override is ContentCategory.GAMING

    done = await client.patch(
        f"{API}/onboarding",
        headers=account.headers,
        json={"step": "done", "live_detected": True, "complete": True},
    )
    assert done.status_code == 200
    assert done.json()["completed"] is True
    assert done.json()["live_detected"] is True
    assert done.json()["completed_at"]
    assert (await client.get(f"{API}/me", headers=account.headers)).json()["onboarding"][
        "completed"
    ]


async def test_clips_list_empty_and_social_oauth_closed(client: httpx.AsyncClient) -> None:
    account = await register(client)
    clips = await client.get(f"{API}/clips", headers=account.headers)
    assert clips.status_code == 200
    assert clips.json() == {"items": []}

    social = await client.get(f"{API}/social/accounts", headers=account.headers)
    assert social.status_code == 200
    body = social.json()
    assert body["items"] == []
    assert body["oauth_available"] is False
    assert set(body["platforms"]) == {"youtube", "tiktok", "instagram"}

    connect = await client.post(
        f"{API}/social/accounts/youtube/connect", headers=account.headers
    )
    assert connect.status_code == 503
    assert connect.json()["error"]["code"] == "social_oauth_unavailable"
