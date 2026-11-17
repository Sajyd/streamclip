"""Profile, organization, notifications and personal-data endpoints."""

import uuid

from fastapi import APIRouter, Request, status
from sqlalchemy import select, update

from app.api.deps import Ctx, CurrentPrincipal, Meta, drain_tasks
from app.api.v1.auth import user_out
from app.api.v1.system import capabilities
from app.core.errors import PermissionDeniedError
from app.models.clips import StorageAsset
from app.models.identity import Organization, User
from app.schemas.api import (
    ExportList,
    ExportOut,
    MarkReadRequest,
    MeResponse,
    Message,
    NotificationList,
    NotificationOut,
    OnboardingOut,
    OrganizationOut,
    PasswordConfirmation,
    UpdateOnboardingRequest,
    UpdateOrganizationRequest,
    UpdateProfileRequest,
    UrlResponse,
    UserOut,
)
from app.services import account_data, notifications
from app.services import onboarding as onboarding_service
from app.services.audit import audit

router = APIRouter(tags=["account"])


def _onboarding_out(data: dict) -> OnboardingOut:
    return OnboardingOut(
        completed=bool(data.get("completed")),
        step=str(data.get("step") or "welcome"),
        referral_source=data.get("referral_source"),
        usage=data.get("usage"),
        software=data.get("software"),
        social_platforms=list(data.get("social_platforms") or []),
        ingest_ready=bool(data.get("ingest_ready")),
        premium_choice=data.get("premium_choice"),
        live_detected=bool(data.get("live_detected")),
        completed_at=data.get("completed_at"),
    )


@router.get("/me", response_model=MeResponse)
async def get_me(principal: CurrentPrincipal, ctx: Ctx) -> MeResponse:
    async with ctx.db.system_tx() as session:
        user = await session.get_one(User, principal.user_id)
        onboarding = await onboarding_service.get_onboarding(session, principal.user_id)
    # Tenant-scoped read: the filter is explicit and row-level security
    # independently guarantees no other organization can be returned.
    async with ctx.db.tenant_tx(principal.tenant) as session:
        organization = (
            await session.execute(
                select(Organization).where(Organization.id == principal.organization_id)
            )
        ).scalar_one()
    return MeResponse(
        user=user_out(user),
        organization=OrganizationOut(
            id=organization.id, name=organization.name, role=principal.membership_role.value
        ),
        capabilities=capabilities(ctx),
        onboarding=_onboarding_out(onboarding),
    )


@router.get("/onboarding", response_model=OnboardingOut)
async def get_onboarding(principal: CurrentPrincipal, ctx: Ctx) -> OnboardingOut:
    async with ctx.db.system_tx() as session:
        data = await onboarding_service.get_onboarding(session, principal.user_id)
    return _onboarding_out(data)


@router.patch("/onboarding", response_model=OnboardingOut)
async def update_onboarding(
    body: UpdateOnboardingRequest, principal: CurrentPrincipal, ctx: Ctx, meta: Meta
) -> OnboardingOut:
    patch = body.model_dump(exclude_unset=True, exclude={"complete"})
    async with ctx.db.system_tx() as session:
        data = await onboarding_service.save_onboarding(
            session,
            user_id=principal.user_id,
            organization_id=principal.organization_id,
            patch=patch,
            meta=meta,
            mark_complete=body.complete,
        )
    return _onboarding_out(data)


@router.patch("/me", response_model=UserOut)
async def update_me(
    body: UpdateProfileRequest, principal: CurrentPrincipal, ctx: Ctx, meta: Meta
) -> UserOut:
    changes = body.model_dump(exclude_unset=True)
    if "locale" in changes and changes["locale"] is None:
        del changes["locale"]
    if "timezone" in changes and changes["timezone"] is None:
        del changes["timezone"]
    if "display_name" in changes:
        changes["display_name"] = (changes["display_name"] or "").strip() or None
    async with ctx.db.system_tx() as session:
        if changes:
            await session.execute(
                update(User).where(User.id == principal.user_id).values(**changes)
            )
            audit(
                session,
                "account.profile_updated",
                meta=meta,
                actor_user_id=principal.user_id,
                organization_id=principal.organization_id,
                details={"fields": sorted(changes)},
            )
        user = await session.get_one(User, principal.user_id, populate_existing=True)
    return user_out(user)


@router.patch("/organization", response_model=OrganizationOut)
async def update_organization(
    body: UpdateOrganizationRequest, principal: CurrentPrincipal, ctx: Ctx, meta: Meta
) -> OrganizationOut:
    if not principal.can_manage_organization:
        raise PermissionDeniedError(
            "Seul un administrateur de l'espace peut le modifier.", code="insufficient_role"
        )
    async with ctx.db.tenant_tx(principal.tenant) as session:
        organization = (
            await session.execute(
                update(Organization)
                .where(Organization.id == principal.organization_id)
                .values(name=body.name)
                .returning(Organization)
            )
        ).scalar_one()
    async with ctx.db.system_tx() as session:
        audit(
            session,
            "organization.updated",
            meta=meta,
            actor_user_id=principal.user_id,
            organization_id=principal.organization_id,
            details={"fields": ["name"]},
        )
    return OrganizationOut(
        id=organization.id, name=organization.name, role=principal.membership_role.value
    )


@router.get("/notifications", response_model=NotificationList)
async def list_notifications(principal: CurrentPrincipal, ctx: Ctx) -> NotificationList:
    async with ctx.db.tenant_tx(principal.tenant) as session:
        items, unread = await notifications.list_notifications(session, principal.organization_id)
    return NotificationList(
        items=[
            NotificationOut(
                id=item.id,
                kind=item.kind,
                severity=item.severity.value,
                title=item.title,
                body=item.body,
                data=item.data,
                created_at=item.created_at,
                read_at=item.read_at,
            )
            for item in items
        ],
        unread_count=unread,
    )


@router.post("/notifications/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_notifications_read(
    body: MarkReadRequest, principal: CurrentPrincipal, ctx: Ctx
) -> None:
    async with ctx.db.tenant_tx(principal.tenant) as session:
        await notifications.mark_read(session, principal.organization_id, body.notification_id)


def _export_out(asset: StorageAsset) -> ExportOut:
    return ExportOut(
        id=asset.id,
        status=asset.status.value,
        size_bytes=asset.size_bytes,
        created_at=asset.created_at,
        expires_at=asset.expires_at,
    )


@router.get("/account/exports", response_model=ExportList)
async def list_exports(principal: CurrentPrincipal, ctx: Ctx) -> ExportList:
    async with ctx.db.tenant_tx(principal.tenant) as session:
        assets = await account_data.list_exports(session, principal.organization_id)
    return ExportList(items=[_export_out(asset) for asset in assets])


@router.post("/account/exports", response_model=ExportList, status_code=status.HTTP_202_ACCEPTED)
async def request_export(
    request: Request, principal: CurrentPrincipal, ctx: Ctx, meta: Meta
) -> ExportList:
    await account_data.request_export(ctx, principal, meta)
    await drain_tasks(ctx, request, kinds=["account.export_data"], time_budget_seconds=20.0)
    async with ctx.db.tenant_tx(principal.tenant) as session:
        assets = await account_data.list_exports(session, principal.organization_id)
    return ExportList(items=[_export_out(asset) for asset in assets])


@router.get("/account/exports/{asset_id}/download-url", response_model=UrlResponse)
async def export_download_url(
    asset_id: uuid.UUID, principal: CurrentPrincipal, ctx: Ctx
) -> UrlResponse:
    return UrlResponse(url=await account_data.export_download_url(ctx, principal, asset_id))


@router.post("/account/delete", response_model=Message, status_code=status.HTTP_202_ACCEPTED)
async def delete_account(
    body: PasswordConfirmation, request: Request, principal: CurrentPrincipal, ctx: Ctx, meta: Meta
) -> Message:
    await account_data.request_account_deletion(ctx, principal, password=body.password, meta=meta)
    await drain_tasks(ctx, request, kinds=["account.delete"], time_budget_seconds=20.0)
    return Message(message="Votre compte est fermé et vos données sont en cours de suppression.")
