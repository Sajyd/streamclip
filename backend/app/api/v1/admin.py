"""Back-office endpoints (platform staff only)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import Admin, Ctx, Meta, Staff
from app.schemas.api import AdminUserList, AdminUserOut, SuspendRequest
from app.services import admin as admin_service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_model=AdminUserList)
async def list_users(
    _staff: Staff,
    ctx: Ctx,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: uuid.UUID | None = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
) -> AdminUserList:
    items, next_cursor = await admin_service.list_users(
        ctx, limit=limit, cursor=cursor, search=search
    )
    return AdminUserList(items=[AdminUserOut(**item) for item in items], next_cursor=next_cursor)


@router.post("/users/{user_id}/suspend", status_code=status.HTTP_204_NO_CONTENT)
async def suspend_user(
    user_id: uuid.UUID, body: SuspendRequest, admin: Admin, ctx: Ctx, meta: Meta
) -> None:
    await admin_service.set_user_suspended(
        ctx, admin, user_id, suspended=True, reason=body.reason, meta=meta
    )


@router.post("/users/{user_id}/reactivate", status_code=status.HTTP_204_NO_CONTENT)
async def reactivate_user(user_id: uuid.UUID, admin: Admin, ctx: Ctx, meta: Meta) -> None:
    await admin_service.set_user_suspended(
        ctx, admin, user_id, suspended=False, reason=None, meta=meta
    )
