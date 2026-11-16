"""Authentication: registration, sign-in, sessions, e-mail and password flows.

All of this runs in system transactions: it happens before a tenant context
exists, and touches tables the tenant-scoped role is not allowed to see
(password hashes, refresh tokens).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import psycopg.errors
import structlog
from email_validator import EmailNotValidError, validate_email
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext
from app.core.errors import (
    AppError,
    AuthenticationError,
    ConflictError,
    PermissionDeniedError,
    ServiceUnavailableError,
)
from app.db.engine import TenantContext
from app.models.enums import (
    AuditOutcome,
    AuthTokenPurpose,
    MembershipRole,
    PlatformRole,
    SessionRevokeReason,
    UserStatus,
)
from app.models.identity import (
    AuthSession,
    AuthToken,
    Membership,
    Organization,
    OrganizationSettings,
    RefreshToken,
    User,
    UserSettings,
)
from app.security import rate_limit as limits
from app.security.passwords import (
    hash_password,
    needs_rehash,
    validate_password_policy,
    verify_dummy_password,
    verify_password,
)
from app.security.tokens import (
    create_access_token,
    decode_access_token,
    generate_opaque_token,
    hash_opaque_token,
)
from app.services.audit import RequestMeta, audit, audit_independent
from app.services.entitlements import start_free_subscription
from app.tasks.queue import enqueue

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated caller, re-validated against the database."""

    user_id: uuid.UUID
    organization_id: uuid.UUID
    session_id: uuid.UUID
    platform_role: PlatformRole
    membership_role: MembershipRole
    email_verified: bool

    @property
    def tenant(self) -> TenantContext:
        return TenantContext(organization_id=self.organization_id, user_id=self.user_id)

    @property
    def can_manage_organization(self) -> bool:
        return self.membership_role in (MembershipRole.OWNER, MembershipRole.ADMIN)


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime
    session_id: uuid.UUID


def normalize_email(raw: str) -> str:
    try:
        return validate_email(raw.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError as exc:
        raise AppError("Adresse e-mail invalide.", code="invalid_email", status_code=422) from exc


def _is_unique_violation(exc: IntegrityError, constraint: str) -> bool:
    original = exc.orig
    return (
        isinstance(original, psycopg.errors.UniqueViolation)
        and original.diag.constraint_name == constraint
    )


# --- Sessions and tokens -----------------------------------------------------


async def _issue_tokens(
    ctx: AppContext,
    session: AsyncSession,
    auth_session: AuthSession,
    *,
    parent_id: uuid.UUID | None,
    now: datetime,
) -> TokenPair:
    raw_refresh = generate_opaque_token()
    refresh_expires_at = min(
        now + timedelta(days=ctx.settings.refresh_token_ttl_days), auth_session.expires_at
    )
    session.add(
        RefreshToken(
            session_id=auth_session.id,
            token_hash=hash_opaque_token(raw_refresh),
            parent_id=parent_id,
            expires_at=refresh_expires_at,
        )
    )
    access_token, access_expires_at = create_access_token(
        ctx.settings, user_id=auth_session.user_id, session_id=auth_session.id, now=now
    )
    return TokenPair(
        access_token=access_token,
        access_expires_at=access_expires_at,
        refresh_token=raw_refresh,
        refresh_expires_at=refresh_expires_at,
        session_id=auth_session.id,
    )


async def _open_session(
    ctx: AppContext,
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    meta: RequestMeta,
    now: datetime,
) -> TokenPair:
    auth_session = AuthSession(
        user_id=user_id,
        organization_id=organization_id,
        last_seen_at=now,
        expires_at=now + timedelta(days=ctx.settings.session_max_age_days),
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    session.add(auth_session)
    await session.flush()
    return await _issue_tokens(ctx, session, auth_session, parent_id=None, now=now)


async def _revoke_sessions(
    session: AsyncSession,
    user_id: uuid.UUID,
    reason: SessionRevokeReason,
    *,
    now: datetime,
    except_session_id: uuid.UUID | None = None,
    only_session_id: uuid.UUID | None = None,
) -> int:
    statement = (
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now, revoke_reason=reason)
    )
    if except_session_id is not None:
        statement = statement.where(AuthSession.id != except_session_id)
    if only_session_id is not None:
        statement = statement.where(AuthSession.id == only_session_id)
    result = await session.execute(statement)
    return int(getattr(result, "rowcount", 0) or 0)


# --- Registration and sign-in ------------------------------------------------


async def register(
    ctx: AppContext,
    *,
    email: str,
    password: str,
    display_name: str | None,
    accept_terms: bool,
    marketing_opt_in: bool,
    meta: RequestMeta,
) -> tuple[User, TokenPair]:
    if not ctx.settings.registration_open:
        raise PermissionDeniedError(
            "Les inscriptions sont momentanément fermées.", code="registration_closed"
        )
    if not accept_terms:
        raise AppError(
            "Vous devez accepter les conditions d'utilisation.",
            code="terms_required",
            status_code=422,
        )
    email = normalize_email(email)
    await ctx.rate_limiter.check(limits.REGISTER_PER_IP, meta.ip)
    validate_password_policy(password, email=email)
    password_hash = await hash_password(password)
    now = datetime.now(UTC)
    display_name = (display_name or "").strip() or None

    try:
        async with ctx.db.system_tx() as session:
            user = User(
                email=email,
                password_hash=password_hash,
                display_name=display_name,
                terms_version=ctx.settings.terms_version,
                terms_accepted_at=now,
                marketing_opt_in=marketing_opt_in,
                last_login_at=now,
            )
            session.add(user)
            await session.flush()
            # Every account owns a personal organization: the tenant boundary.
            organization = Organization(
                name=(display_name or email.split("@", 1)[0])[:120],
                owner_user_id=user.id,
                billing_email=email,
            )
            session.add(organization)
            await session.flush()
            session.add_all(
                [
                    Membership(
                        organization_id=organization.id,
                        user_id=user.id,
                        role=MembershipRole.OWNER,
                    ),
                    UserSettings(user_id=user.id),
                    OrganizationSettings(organization_id=organization.id),
                ]
            )
            await start_free_subscription(session, organization.id, now)
            tokens = await _open_session(
                ctx, session, user_id=user.id, organization_id=organization.id, meta=meta, now=now
            )
            if ctx.mailer.enabled:
                await enqueue(
                    session,
                    "email.verification",
                    {"user_id": str(user.id)},
                    idempotency_key=f"email.verification:{user.id}:signup",
                    organization_id=organization.id,
                )
            audit(
                session,
                "auth.register",
                meta=meta,
                actor_user_id=user.id,
                organization_id=organization.id,
                target_type="user",
                target_id=user.id,
            )
    except IntegrityError as exc:
        if _is_unique_violation(exc, "uq_users_email"):
            await audit_independent(
                ctx.db,
                "auth.register",
                meta=meta,
                outcome=AuditOutcome.FAILURE,
                details={"reason": "email_already_registered"},
            )
            raise ConflictError(
                "Un compte existe déjà avec cette adresse e-mail.", code="email_already_registered"
            ) from exc
        raise
    return user, tokens


async def login(
    ctx: AppContext, *, email: str, password: str, meta: RequestMeta
) -> tuple[User, TokenPair]:
    # One generic message for every failure: never reveal whether the account exists.
    invalid = AuthenticationError(
        "Adresse e-mail ou mot de passe incorrect.", code="invalid_credentials"
    )
    await ctx.rate_limiter.check(limits.LOGIN_PER_IP, meta.ip)
    try:
        email = normalize_email(email)
    except AppError:
        await verify_dummy_password(password)
        raise invalid from None
    await ctx.rate_limiter.ensure_below(limits.LOGIN_FAILURES_PER_EMAIL, email)

    async with ctx.db.system_tx() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()

    # Hashing happens outside any transaction: no connection is held meanwhile.
    if user is None:
        await verify_dummy_password(password)
        password_ok = False
    else:
        password_ok = await verify_password(user.password_hash, password)

    if not password_ok or user is None:
        await ctx.rate_limiter.hit(limits.LOGIN_FAILURES_PER_EMAIL, email)
        await audit_independent(
            ctx.db,
            "auth.login",
            meta=meta,
            outcome=AuditOutcome.FAILURE,
            actor_user_id=user.id if user else None,
            details={"reason": "invalid_credentials"},
        )
        raise invalid

    if user.status is not UserStatus.ACTIVE:
        await audit_independent(
            ctx.db,
            "auth.login",
            meta=meta,
            outcome=AuditOutcome.FAILURE,
            actor_user_id=user.id,
            details={"reason": f"account_{user.status.value}"},
        )
        if user.status is UserStatus.SUSPENDED:
            raise PermissionDeniedError(
                "Ce compte est suspendu. Contactez le support.", code="account_suspended"
            )
        raise invalid  # account being deleted: it no longer exists for its owner

    upgraded_hash = await hash_password(password) if needs_rehash(user.password_hash) else None
    now = datetime.now(UTC)
    async with ctx.db.system_tx() as session:
        organization_id = (
            await session.execute(
                select(Membership.organization_id)
                .where(Membership.user_id == user.id)
                .order_by(Membership.created_at)
                .limit(1)
            )
        ).scalar_one_or_none()
        if organization_id is None:
            raise PermissionDeniedError(
                "Ce compte n'est rattaché à aucun espace.", code="no_organization"
            )
        values: dict[str, object] = {"last_login_at": now}
        if upgraded_hash:
            values["password_hash"] = upgraded_hash
        await session.execute(update(User).where(User.id == user.id).values(**values))
        tokens = await _open_session(
            ctx, session, user_id=user.id, organization_id=organization_id, meta=meta, now=now
        )
        audit(
            session,
            "auth.login",
            meta=meta,
            actor_user_id=user.id,
            organization_id=organization_id,
            target_type="session",
            target_id=tokens.session_id,
        )
    return user, tokens


async def refresh(ctx: AppContext, *, refresh_token: str, meta: RequestMeta) -> TokenPair:
    """Exchange a refresh token for a new pair (rotation).

    Each refresh token works once. Presenting an already-used token means it
    was copied: the whole session is revoked. A short grace window tolerates
    legitimate concurrent refreshes (several browser tabs).
    """
    await ctx.rate_limiter.check(limits.REFRESH_PER_IP, meta.ip)
    invalid = AuthenticationError(
        "Session expirée. Veuillez vous reconnecter.", code="invalid_refresh_token"
    )
    now = datetime.now(UTC)
    failure: AppError | None = None
    tokens: TokenPair | None = None

    async with ctx.db.system_tx() as session:
        row = (
            await session.execute(
                select(RefreshToken, AuthSession, User)
                .join(AuthSession, AuthSession.id == RefreshToken.session_id)
                .join(User, User.id == AuthSession.user_id)
                .where(RefreshToken.token_hash == hash_opaque_token(refresh_token))
                .with_for_update(of=RefreshToken)
            )
        ).one_or_none()
        if row is None:
            raise invalid
        token, auth_session, user = row
        if (
            auth_session.revoked_at is not None
            or auth_session.expires_at <= now
            or token.expires_at <= now
        ):
            raise invalid

        grace = timedelta(seconds=ctx.settings.refresh_reuse_grace_seconds)
        if user.status is not UserStatus.ACTIVE:
            auth_session.revoked_at = now
            auth_session.revoke_reason = SessionRevokeReason.ACCOUNT_SUSPENDED
            failure = PermissionDeniedError(
                "Ce compte est suspendu. Contactez le support.", code="account_suspended"
            )
        elif token.rotated_at is not None and now - token.rotated_at > grace:
            auth_session.revoked_at = now
            auth_session.revoke_reason = SessionRevokeReason.TOKEN_REUSE
            audit(
                session,
                "auth.refresh_token_reuse",
                meta=meta,
                outcome=AuditOutcome.FAILURE,
                actor_user_id=user.id,
                organization_id=auth_session.organization_id,
                target_type="session",
                target_id=auth_session.id,
            )
            log.warning("refresh_token_reuse", session_id=str(auth_session.id))
            failure = AuthenticationError(
                "Session révoquée par sécurité. Veuillez vous reconnecter.",
                code="refresh_token_reused",
            )
        else:
            if token.rotated_at is None:
                token.rotated_at = now
            auth_session.last_seen_at = now
            tokens = await _issue_tokens(ctx, session, auth_session, parent_id=token.id, now=now)

    # Raised after the transaction so that the revocation above is committed.
    if failure is not None or tokens is None:
        raise failure or invalid
    return tokens


async def authenticate(ctx: AppContext, access_token: str) -> Principal:
    """Validate an access token and re-check the session and account state."""
    claims = decode_access_token(ctx.settings, access_token)
    async with ctx.db.system_tx() as session:
        row = (
            await session.execute(
                select(
                    AuthSession.organization_id,
                    AuthSession.revoked_at,
                    AuthSession.expires_at,
                    User.status,
                    User.platform_role,
                    User.email_verified_at,
                    Membership.role,
                )
                .join(User, User.id == AuthSession.user_id)
                .outerjoin(
                    Membership,
                    (Membership.user_id == AuthSession.user_id)
                    & (Membership.organization_id == AuthSession.organization_id),
                )
                .where(AuthSession.id == claims.session_id, AuthSession.user_id == claims.user_id)
            )
        ).one_or_none()
    if row is None or row.revoked_at is not None or row.expires_at <= datetime.now(UTC):
        raise AuthenticationError("Session expirée ou révoquée.", code="session_revoked")
    if row.status is not UserStatus.ACTIVE:
        raise PermissionDeniedError(
            "Ce compte est suspendu. Contactez le support.", code="account_suspended"
        )
    if row.role is None:
        raise PermissionDeniedError("Vous n'avez plus accès à cet espace.", code="no_organization")
    return Principal(
        user_id=claims.user_id,
        organization_id=row.organization_id,
        session_id=claims.session_id,
        platform_role=row.platform_role,
        membership_role=row.role,
        email_verified=row.email_verified_at is not None,
    )


async def logout(
    ctx: AppContext, principal: Principal, *, everywhere: bool, meta: RequestMeta
) -> None:
    now = datetime.now(UTC)
    async with ctx.db.system_tx() as session:
        await _revoke_sessions(
            session,
            principal.user_id,
            SessionRevokeReason.LOGOUT_ALL if everywhere else SessionRevokeReason.LOGOUT,
            now=now,
            only_session_id=None if everywhere else principal.session_id,
        )
        audit(
            session,
            "auth.logout_all" if everywhere else "auth.logout",
            meta=meta,
            actor_user_id=principal.user_id,
            organization_id=principal.organization_id,
        )


async def list_sessions(ctx: AppContext, principal: Principal) -> list[AuthSession]:
    async with ctx.db.system_tx() as session:
        result = await session.execute(
            select(AuthSession)
            .where(
                AuthSession.user_id == principal.user_id,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > datetime.now(UTC),
            )
            .order_by(AuthSession.last_seen_at.desc().nulls_last())
        )
        return list(result.scalars())


async def revoke_session(
    ctx: AppContext, principal: Principal, session_id: uuid.UUID, meta: RequestMeta
) -> bool:
    async with ctx.db.system_tx() as session:
        revoked = await _revoke_sessions(
            session,
            principal.user_id,  # scoped to the caller: another user's session is never matched
            SessionRevokeReason.USER_REVOKED,
            now=datetime.now(UTC),
            only_session_id=session_id,
        )
        if revoked:
            audit(
                session,
                "auth.session_revoked",
                meta=meta,
                actor_user_id=principal.user_id,
                organization_id=principal.organization_id,
                target_type="session",
                target_id=session_id,
            )
        return bool(revoked)


# --- E-mail verification -----------------------------------------------------


async def issue_auth_token(
    session: AsyncSession, user: User, purpose: AuthTokenPurpose, ttl: timedelta
) -> str:
    """Create a single-use token and invalidate previous ones of that purpose.
    Returns the raw value, which exists only in memory and in the e-mail."""
    await session.execute(
        delete(AuthToken).where(
            AuthToken.user_id == user.id,
            AuthToken.purpose == purpose,
            AuthToken.used_at.is_(None),
        )
    )
    raw = generate_opaque_token()
    session.add(
        AuthToken(
            user_id=user.id,
            purpose=purpose,
            token_hash=hash_opaque_token(raw),
            sent_to=user.email,
            expires_at=datetime.now(UTC) + ttl,
        )
    )
    return raw


async def _load_auth_token(
    session: AsyncSession,
    raw_token: str,
    purpose: AuthTokenPurpose,
    now: datetime,
    *,
    consume: bool,
) -> tuple[AuthToken, User]:
    statement = (
        select(AuthToken, User)
        .join(User, User.id == AuthToken.user_id)
        .where(
            AuthToken.token_hash == hash_opaque_token(raw_token),
            AuthToken.purpose == purpose,
            AuthToken.used_at.is_(None),
            AuthToken.expires_at > now,
        )
    )
    if consume:
        # Row lock: two concurrent submissions cannot both use the token.
        statement = statement.with_for_update(of=AuthToken)
    row = (await session.execute(statement)).one_or_none()
    # A token sent to a previous address must not validate the current one.
    if row is None or row[1].email != row[0].sent_to or row[1].status is not UserStatus.ACTIVE:
        raise AppError(
            "Ce lien est invalide ou a expiré.", code="invalid_or_expired_token", status_code=400
        )
    token, user = row
    if consume:
        token.used_at = now
    return token, user


def _require_email_delivery(ctx: AppContext) -> None:
    if not ctx.mailer.enabled:
        raise ServiceUnavailableError(
            "L'envoi d'e-mails n'est pas encore activé sur cette plateforme.",
            code="email_delivery_unavailable",
        )


async def request_email_verification(ctx: AppContext, principal: Principal) -> None:
    _require_email_delivery(ctx)
    if principal.email_verified:
        raise ConflictError(
            "Votre adresse e-mail est déjà vérifiée.", code="email_already_verified"
        )
    await ctx.rate_limiter.check(limits.VERIFICATION_EMAIL_PER_USER, str(principal.user_id))
    async with ctx.db.system_tx() as session:
        await enqueue(
            session,
            "email.verification",
            {"user_id": str(principal.user_id)},
            organization_id=principal.organization_id,
        )


async def verify_email(ctx: AppContext, *, token: str, meta: RequestMeta) -> None:
    await ctx.rate_limiter.check(limits.TOKEN_SUBMIT_PER_IP, meta.ip)
    now = datetime.now(UTC)
    async with ctx.db.system_tx() as session:
        _, user = await _load_auth_token(
            session, token, AuthTokenPurpose.EMAIL_VERIFICATION, now, consume=True
        )
        if user.email_verified_at is None:
            user.email_verified_at = now
        audit(
            session,
            "auth.email_verified",
            meta=meta,
            actor_user_id=user.id,
            target_type="user",
            target_id=user.id,
        )


# --- Passwords ---------------------------------------------------------------


async def request_password_reset(ctx: AppContext, *, email: str, meta: RequestMeta) -> None:
    """Always succeeds from the caller's point of view: the response never
    tells whether the address belongs to an account."""
    _require_email_delivery(ctx)
    await ctx.rate_limiter.check(limits.PASSWORD_RESET_PER_IP, meta.ip)
    try:
        email = normalize_email(email)
    except AppError:
        return
    if await ctx.rate_limiter.hit(limits.PASSWORD_RESET_PER_EMAIL, email) > (
        limits.PASSWORD_RESET_PER_EMAIL.max_hits
    ):
        return
    async with ctx.db.system_tx() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if user is None or user.status is not UserStatus.ACTIVE:
            return
        await enqueue(session, "email.password_reset", {"user_id": str(user.id)})
        audit(
            session,
            "auth.password_reset_requested",
            meta=meta,
            actor_user_id=user.id,
            target_type="user",
            target_id=user.id,
        )


async def reset_password(
    ctx: AppContext, *, token: str, new_password: str, meta: RequestMeta
) -> None:
    await ctx.rate_limiter.check(limits.TOKEN_SUBMIT_PER_IP, meta.ip)
    purpose = AuthTokenPurpose.PASSWORD_RESET
    # Check the token before spending CPU on hashing; it is consumed below.
    async with ctx.db.system_tx() as session:
        _, user = await _load_auth_token(session, token, purpose, datetime.now(UTC), consume=False)
        email = user.email
    validate_password_policy(new_password, email=email)
    password_hash = await hash_password(new_password)

    now = datetime.now(UTC)
    async with ctx.db.system_tx() as session:
        _, user = await _load_auth_token(session, token, purpose, now, consume=True)
        user.password_hash = password_hash
        if user.email_verified_at is None:
            # Receiving the reset link proves control of the mailbox.
            user.email_verified_at = now
        await _revoke_sessions(session, user.id, SessionRevokeReason.PASSWORD_RESET, now=now)
        if ctx.mailer.enabled:
            await enqueue(session, "email.password_changed", {"user_id": str(user.id)})
        audit(
            session,
            "auth.password_reset",
            meta=meta,
            actor_user_id=user.id,
            target_type="user",
            target_id=user.id,
        )


async def change_password(
    ctx: AppContext,
    principal: Principal,
    *,
    current_password: str,
    new_password: str,
    meta: RequestMeta,
) -> None:
    await ctx.rate_limiter.check(limits.PASSWORD_CHANGE_PER_USER, str(principal.user_id))
    async with ctx.db.system_tx() as session:
        user = await session.get_one(User, principal.user_id)
    if not await verify_password(user.password_hash, current_password):
        await audit_independent(
            ctx.db,
            "auth.password_change",
            meta=meta,
            outcome=AuditOutcome.FAILURE,
            actor_user_id=principal.user_id,
            organization_id=principal.organization_id,
            details={"reason": "invalid_current_password"},
        )
        raise PermissionDeniedError(
            "Le mot de passe actuel est incorrect.", code="invalid_current_password"
        )
    validate_password_policy(new_password, email=user.email)
    password_hash = await hash_password(new_password)
    now = datetime.now(UTC)
    async with ctx.db.system_tx() as session:
        await session.execute(
            update(User).where(User.id == principal.user_id).values(password_hash=password_hash)
        )
        # Every other device is signed out; the current session stays valid.
        await _revoke_sessions(
            session,
            principal.user_id,
            SessionRevokeReason.PASSWORD_CHANGED,
            now=now,
            except_session_id=principal.session_id,
        )
        if ctx.mailer.enabled:
            await enqueue(session, "email.password_changed", {"user_id": str(principal.user_id)})
        audit(
            session,
            "auth.password_change",
            meta=meta,
            actor_user_id=principal.user_id,
            organization_id=principal.organization_id,
        )
