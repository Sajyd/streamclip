"""Authentication endpoints."""

import asyncio
import uuid

from fastapi import APIRouter, Request, status

from app.api.deps import Ctx, CurrentPrincipal, Meta, ResponseTimePadder, drain_tasks
from app.models.identity import User
from app.schemas.api import (
    AuthResponse,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    Message,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    SessionOut,
    TokenRequest,
    Tokens,
    UserOut,
)
from app.services import auth as auth_service
from app.services.auth import TokenPair

router = APIRouter(prefix="/auth", tags=["auth"])


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        locale=user.locale,
        timezone=user.timezone,
        email_verified=user.email_verified_at is not None,
        platform_role=user.platform_role.value,
        created_at=user.created_at,
    )


def tokens_out(tokens: TokenPair) -> Tokens:
    return Tokens(
        access_token=tokens.access_token,
        access_expires_at=tokens.access_expires_at,
        refresh_token=tokens.refresh_token,
        refresh_expires_at=tokens.refresh_expires_at,
        session_id=tokens.session_id,
    )


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, request: Request, ctx: Ctx, meta: Meta) -> AuthResponse:
    user, tokens = await auth_service.register(
        ctx,
        email=body.email,
        password=body.password,
        display_name=body.display_name,
        accept_terms=body.accept_terms,
        marketing_opt_in=body.marketing_opt_in,
        meta=meta,
    )
    if ctx.mailer.enabled:
        await drain_tasks(ctx, request, kinds=["email.verification"])
    return AuthResponse(user=user_out(user), tokens=tokens_out(tokens))


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest, ctx: Ctx, meta: Meta) -> AuthResponse:
    user, tokens = await auth_service.login(
        ctx, email=body.email, password=body.password, meta=meta
    )
    return AuthResponse(user=user_out(user), tokens=tokens_out(tokens))


@router.post("/refresh", response_model=Tokens)
async def refresh(body: RefreshRequest, ctx: Ctx, meta: Meta) -> Tokens:
    return tokens_out(await auth_service.refresh(ctx, refresh_token=body.refresh_token, meta=meta))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(principal: CurrentPrincipal, ctx: Ctx, meta: Meta) -> None:
    await auth_service.logout(ctx, principal, everywhere=False, meta=meta)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(principal: CurrentPrincipal, ctx: Ctx, meta: Meta) -> None:
    await auth_service.logout(ctx, principal, everywhere=True, meta=meta)


@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(principal: CurrentPrincipal, ctx: Ctx) -> list[SessionOut]:
    sessions = await auth_service.list_sessions(ctx, principal)
    return [
        SessionOut(
            id=item.id,
            created_at=item.created_at,
            last_seen_at=item.last_seen_at,
            ip=str(item.ip) if item.ip else None,
            user_agent=item.user_agent,
            current=item.id == principal.session_id,
        )
        for item in sessions
    ]


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(
    session_id: uuid.UUID, principal: CurrentPrincipal, ctx: Ctx, meta: Meta
) -> None:
    # Idempotent: revoking an unknown or already revoked session is not an error,
    # and does not reveal whether the id exists for another user.
    await auth_service.revoke_session(ctx, principal, session_id, meta)


@router.post("/verify-email", response_model=Message)
async def verify_email(body: TokenRequest, ctx: Ctx, meta: Meta) -> Message:
    await auth_service.verify_email(ctx, token=body.token, meta=meta)
    return Message(message="Adresse e-mail vérifiée.")


@router.post("/resend-verification", response_model=Message, status_code=status.HTTP_202_ACCEPTED)
async def resend_verification(request: Request, principal: CurrentPrincipal, ctx: Ctx) -> Message:
    await auth_service.request_email_verification(ctx, principal)
    await drain_tasks(ctx, request, kinds=["email.verification"])
    return Message(message="E-mail de vérification envoyé.")


@router.post("/forgot-password", response_model=Message, status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(
    body: ForgotPasswordRequest, request: Request, ctx: Ctx, meta: Meta
) -> Message:
    padder = ResponseTimePadder(minimum=ctx.settings.password_reset_response_floor_seconds)
    await auth_service.request_password_reset(ctx, email=body.email, meta=meta)
    await drain_tasks(ctx, request, kinds=["email.password_reset"], time_budget_seconds=5.0)
    # Same answer and same duration whether or not the address has an account.
    await asyncio.sleep(padder.remaining)
    return Message(
        message=(
            "Si un compte existe pour cette adresse, un e-mail de réinitialisation a été envoyé."
        )
    )


@router.post("/reset-password", response_model=Message)
async def reset_password(
    body: ResetPasswordRequest, request: Request, ctx: Ctx, meta: Meta
) -> Message:
    await auth_service.reset_password(
        ctx, token=body.token, new_password=body.new_password, meta=meta
    )
    if ctx.mailer.enabled:
        await drain_tasks(ctx, request, kinds=["email.password_changed"])
    return Message(message="Mot de passe modifié. Vous pouvez vous connecter.")


@router.post("/change-password", response_model=Message)
async def change_password(
    body: ChangePasswordRequest, request: Request, principal: CurrentPrincipal, ctx: Ctx, meta: Meta
) -> Message:
    await auth_service.change_password(
        ctx,
        principal,
        current_password=body.current_password,
        new_password=body.new_password,
        meta=meta,
    )
    if ctx.mailer.enabled:
        await drain_tasks(ctx, request, kinds=["email.password_changed"])
    return Message(message="Mot de passe modifié.")
