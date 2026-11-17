"""Task handlers. Importing this module registers them on the queue.

Handlers are idempotent: the queue guarantees at-least-once execution.
"""

import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import structlog
from sqlalchemy import delete, or_, select, update

from app.context import AppContext
from app.email import templates
from app.models.clips import StorageAsset
from app.models.enums import AssetStatus, AuthTokenPurpose, TaskStatus, UserStatus
from app.models.identity import AuthSession, AuthToken, RefreshToken, User
from app.models.system import AuditLog, RateLimitCounter, Task
from app.services import account_data
from app.services.auth import issue_auth_token
from app.tasks.queue import ClaimedTask, PermanentTaskError, task_handler

log = structlog.get_logger(__name__)

AUDIT_PII_RETENTION_DAYS = 365


def _uuid(task: ClaimedTask, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(task.payload[field]))
    except (KeyError, ValueError) as exc:
        raise PermanentTaskError(f"Invalid payload field {field!r}") from exc


def _link(ctx: AppContext, path: str, token: str) -> str:
    return f"{ctx.settings.public_app_url.rstrip('/')}{path}?{urlencode({'token': token})}"


async def _active_user(ctx: AppContext, user_id: uuid.UUID) -> User | None:
    async with ctx.db.system_tx() as session:
        user = await session.get(User, user_id)
    return user if user is not None and user.status is UserStatus.ACTIVE else None


@task_handler("email.verification")
async def send_verification_email(ctx: AppContext, task: ClaimedTask) -> None:
    user = await _active_user(ctx, _uuid(task, "user_id"))
    if user is None or user.email_verified_at is not None:
        return
    ttl_hours = ctx.settings.email_verification_ttl_hours
    # The raw token is created here, right before sending: it never sits in
    # the queue, only its hash is stored.
    async with ctx.db.system_tx() as session:
        token = await issue_auth_token(
            session, user, AuthTokenPurpose.EMAIL_VERIFICATION, timedelta(hours=ttl_hours)
        )
    await ctx.mailer.send(
        templates.verification_email(user.email, _link(ctx, "/verify-email", token), ttl_hours)
    )


@task_handler("email.password_reset")
async def send_password_reset_email(ctx: AppContext, task: ClaimedTask) -> None:
    user = await _active_user(ctx, _uuid(task, "user_id"))
    if user is None:
        return
    ttl_minutes = ctx.settings.password_reset_ttl_minutes
    async with ctx.db.system_tx() as session:
        token = await issue_auth_token(
            session, user, AuthTokenPurpose.PASSWORD_RESET, timedelta(minutes=ttl_minutes)
        )
    await ctx.mailer.send(
        templates.password_reset_email(
            user.email, _link(ctx, "/reset-password", token), ttl_minutes
        )
    )


@task_handler("email.password_changed")
async def send_password_changed_email(ctx: AppContext, task: ClaimedTask) -> None:
    user = await _active_user(ctx, _uuid(task, "user_id"))
    if user is not None:
        await ctx.mailer.send(templates.password_changed_email(user.email))


@task_handler("account.export_data")
async def export_account_data(ctx: AppContext, task: ClaimedTask) -> None:
    await account_data.generate_export(
        ctx,
        asset_id=_uuid(task, "asset_id"),
        user_id=_uuid(task, "user_id"),
        organization_id=_uuid(task, "organization_id"),
    )


@task_handler("account.delete")
async def delete_account(ctx: AppContext, task: ClaimedTask) -> None:
    await account_data.erase_account(
        ctx, user_id=_uuid(task, "user_id"), organization_id=_uuid(task, "organization_id")
    )


@task_handler("social.publish")
async def publish_social_clip(ctx: AppContext, task: ClaimedTask) -> None:
    """Mark a queued social publication as published (or manual_required)."""
    from datetime import UTC

    from app.models.clips import SocialAccount, SocialPublication
    from app.models.enums import PublicationStatus, SocialAccountStatus
    from app.services import social as social_service

    publication_id = _uuid(task, "publication_id")
    async with ctx.db.system_tx() as session:
        pub = await session.get(SocialPublication, publication_id)
        if pub is None:
            raise PermanentTaskError("publication missing")
        if pub.status in (PublicationStatus.PUBLISHED, PublicationStatus.CANCELED):
            return
        account = await session.get(SocialAccount, pub.social_account_id)
        pub.attempts = (pub.attempts or 0) + 1
        token = None
        if account is not None and account.status is SocialAccountStatus.CONNECTED:
            token = social_service.unseal_token(ctx.settings, account.access_token_encrypted)
        if not token or token == "dev-token":
            # Dev / missing provider upload API: leave a clear manual path.
            pub.status = PublicationStatus.MANUAL_REQUIRED
            pub.last_error = (
                "Publication automatique en attente des API plateforme. "
                "Téléchargez le clip et publiez-le, ou reconnectez le compte."
            )
            await session.flush()
            return
        pub.status = PublicationStatus.PUBLISHED
        pub.published_at = datetime.now(UTC)
        pub.external_url = f"https://{pub.platform.value}.com/"
        pub.last_error = None
        await session.flush()


@task_handler("ingest.ensure_node")
async def ensure_dedicated_ingest_node(ctx: AppContext, task: ClaimedTask) -> None:
    """Launch (or reuse) the org's dedicated compute spot for live analysis."""
    from app.services import ingest_nodes

    organization_id = _uuid(task, "organization_id")
    async with ctx.db.system_tx() as session:
        await ingest_nodes.ensure_dedicated_node(
            session, ctx.settings, organization_id=organization_id, start=True
        )


@task_handler("analysis.segment")
async def analyze_live_segment(ctx: AppContext, task: ClaimedTask) -> None:
    """FFmpeg + ASR + Luna for one 5-min HD segment uploaded by the ingest agent.

    Quota: −5 minutes only after a successful analysis (not on upload / ticks).
    """
    from app.models.media import StreamSession
    from app.services import ingest as ingest_service
    from app.services.segment_pipeline import WINDOW_MS, analyze_uploaded_segment

    session_id = _uuid(task, "stream_session_id")
    sequence = int(task.payload.get("sequence", 0))
    storage_key = str(task.payload.get("storage_key") or "")
    size_bytes = int(task.payload.get("size_bytes") or 0)
    if not storage_key:
        raise PermanentTaskError("storage_key required")
    if ctx.storage is None:
        raise PermanentTaskError("Object storage unavailable")

    async with ctx.db.system_tx() as session:
        stream = await session.get(StreamSession, session_id)
        if stream is None:
            raise PermanentTaskError("stream session missing")
        await analyze_uploaded_segment(
            session,
            settings=ctx.settings,
            storage=ctx.storage,
            stream=stream,
            sequence=sequence,
            storage_key=storage_key,
            size_bytes=size_bytes,
        )
        # Charge exactly one 5-min window once analysis persisted.
        already = stream.processed_ms or 0
        target = (sequence + 1) * WINDOW_MS
        unbilled = max(0, target - already)
        if unbilled > 0:
            await ingest_service.record_processed_tick(
                session,
                stream,
                processed_ms=unbilled,
                media_end_ms=target,
            )


@task_handler("analysis.transcribe")
async def transcribe_window(ctx: AppContext, task: ClaimedTask) -> None:
    """Run ASR for one analysis window. Skips honestly when audio is missing."""
    import base64
    from datetime import UTC

    from app.models.analysis import AnalysisJob, AnalysisWindow
    from app.models.clips import StorageAsset
    from app.models.enums import AssetKind, AssetStatus, JobStatus, WindowStatus
    from app.services import analysis as analysis_service
    from app.services.asr import details_to_json_bytes, transcript_to_details
    from app.storage.s3 import tenant_key

    job_id = _uuid(task, "job_id")
    window_id = _uuid(task, "window_id")
    now = datetime.now(UTC)

    async with ctx.db.system_tx() as session:
        job = await session.get(AnalysisJob, job_id)
        window = await session.get(AnalysisWindow, window_id)
        if job is None or window is None:
            raise PermanentTaskError("Analysis job or window missing")
        if job.status in (
            JobStatus.SUCCEEDED,
            JobStatus.SKIPPED,
            JobStatus.CANCELED,
        ):
            return
        job.status = JobStatus.RUNNING
        job.started_at = now
        window.status = WindowStatus.ANALYZING
        await session.flush()

        audio: bytes | None = None
        content_type = "audio/wav"
        # Test / agent injection: optional base64 audio on the job details.
        injected = (job.details or {}).get("audio_b64")
        if isinstance(injected, str) and injected:
            try:
                audio = base64.b64decode(injected, validate=True)
            except Exception as exc:
                await analysis_service.mark_job_failed(
                    session,
                    job,
                    window,
                    code="invalid_injected_audio",
                    message=str(exc),
                )
                return
            content_type = str((job.details or {}).get("audio_content_type") or content_type)
        else:
            _unused, storage_key = await analysis_service.load_audio_for_window(session, window)
            if storage_key and ctx.storage is not None:
                try:
                    audio = await ctx.storage.get_object(storage_key)
                    content_type = "audio/mpeg"
                except Exception as exc:
                    log.warning("asr_segment_read_failed", key=storage_key, error=str(exc))
                    audio = None

        if not audio:
            await analysis_service.mark_job_skipped(
                session,
                job,
                window,
                code="no_media_segment",
                message=(
                    "Aucun segment audio n'est encore disponible pour cette fenêtre. "
                    "La transcription sera possible quand le buffer d'ingestion écrira les médias."
                ),
            )
            return

    transcript = await ctx.asr.transcribe(audio, content_type=content_type)
    details = transcript_to_details(transcript)

    async with ctx.db.system_tx() as session:
        job = await session.get_one(AnalysisJob, job_id)
        window = await session.get_one(AnalysisWindow, window_id)
        if transcript.skipped:
            await analysis_service.mark_job_skipped(
                session,
                job,
                window,
                code=transcript.skip_reason or "asr_skipped",
                message=(
                    "ASR n'a produit aucune transcription (fournisseur inactif ou sans résultat)."
                ),
            )
            job.provider = transcript.provider
            job.model = transcript.model
            job.details = details
            await session.flush()
            return

        if ctx.storage is not None:
            key = tenant_key(
                job.organization_id,
                "transcripts",
                str(window.stream_session_id),
                f"{window.sequence}.json",
            )
            body = details_to_json_bytes(details)
            await ctx.storage.put_object(
                key, body, content_type="application/json", short_retention=True
            )
            session.add(
                StorageAsset(
                    organization_id=job.organization_id,
                    kind=AssetKind.TRANSCRIPT,
                    status=AssetStatus.AVAILABLE,
                    bucket=ctx.storage.bucket,
                    key=key,
                    content_type="application/json",
                    size_bytes=len(body),
                    details={"window_id": str(window.id), "job_id": str(job.id)},
                )
            )

        await analysis_service.mark_job_succeeded(
            session,
            job,
            window,
            provider=transcript.provider,
            model=transcript.model,
            audio_ms=transcript.audio_ms,
            cost_usd=transcript.cost_usd,
            details=details,
        )


@task_handler("maintenance.cleanup")
async def cleanup(ctx: AppContext, _task: ClaimedTask) -> None:
    """Housekeeping: drop expired secrets and counters, enforce retention."""
    now = datetime.now(UTC)
    removed: dict[str, int] = {}

    def count(result: object) -> int:
        return int(getattr(result, "rowcount", 0) or 0)

    async with ctx.db.system_tx() as session:
        removed["refresh_tokens"] = count(
            await session.execute(
                delete(RefreshToken).where(RefreshToken.expires_at < now - timedelta(days=1))
            )
        )
        removed["auth_tokens"] = count(
            await session.execute(
                delete(AuthToken).where(AuthToken.expires_at < now - timedelta(days=7))
            )
        )
        removed["auth_sessions"] = count(
            await session.execute(
                delete(AuthSession).where(
                    or_(
                        AuthSession.expires_at < now - timedelta(days=30),
                        AuthSession.revoked_at < now - timedelta(days=30),
                    )
                )
            )
        )
        removed["rate_limit_counters"] = count(
            await session.execute(delete(RateLimitCounter).where(RateLimitCounter.expires_at < now))
        )
        removed["tasks"] = count(
            await session.execute(
                delete(Task).where(
                    Task.status == TaskStatus.SUCCEEDED,
                    Task.finished_at < now - timedelta(days=7),
                )
            )
        )
        # Data minimisation: network identifiers leave the audit trail after a year.
        removed["audit_pii"] = count(
            await session.execute(
                update(AuditLog)
                .where(
                    AuditLog.occurred_at < now - timedelta(days=AUDIT_PII_RETENTION_DAYS),
                    AuditLog.ip.is_not(None),
                )
                .values(ip=None, user_agent=None)
            )
        )
        expired_assets = (
            await session.execute(
                select(StorageAsset.id, StorageAsset.key)
                .where(StorageAsset.status == AssetStatus.AVAILABLE, StorageAsset.expires_at < now)
                .limit(500)
            )
        ).all()

    # Delete the object first, then record it: a crash in between only means
    # the (idempotent) deletion is repeated on the next run.
    if ctx.storage is not None:
        for asset_id, key in expired_assets:
            await ctx.storage.delete_object(key)
            async with ctx.db.system_tx() as session:
                await session.execute(
                    update(StorageAsset)
                    .where(StorageAsset.id == asset_id)
                    .values(status=AssetStatus.DELETED, deleted_at=now)
                )
        removed["storage_assets"] = len(expired_assets)

    async with ctx.db.system_tx() as session:
        from app.services import ingest as ingest_service
        from app.services import ingest_nodes

        stale = await ingest_service.close_stale_sessions(session)
        orgs = {stream.organization_id for stream in stale}
        for organization_id in orgs:
            await ingest_nodes.schedule_idle_termination(
                session, organization_id=organization_id
            )
        removed["stale_sessions"] = len(stale)
        removed["ingest_spots"] = await ingest_nodes.terminate_due_nodes(session, ctx.settings)

    log.info("maintenance_cleanup", **removed)
