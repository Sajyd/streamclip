"""Operator commands.

    python -m app.cli migrate
    python -m app.cli promote-admin --email someone@example.com
    python -m app.cli stripe-sync --webhook-url https://.../api/v1/billing/webhooks/stripe
    python -m app.cli worker [--once]
    python -m app.cli segment-analyze --session-id ... --video path.mp4
    python -m app.cli live-loop --session-id ... --input-url rtmp://127.0.0.1/live/...

Configuration comes from the environment, exactly like the API.
"""

import argparse
import asyncio
import json
import os
import socket
import stat
import sys
from pathlib import Path

from sqlalchemy import select

from app.context import AppContext, build_context
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db import migrations
from app.models.enums import ActorType, PlatformRole
from app.models.identity import User
from app.services.audit import audit
from app.services.auth import normalize_email
from app.tasks.queue import run_due_tasks


def _migrate(_args: argparse.Namespace) -> int:
    settings = get_settings()
    url = settings.database_migration_url or settings.database_url
    migrations.upgrade(url.get_secret_value())
    print(f"Database is at revision {migrations.expected_revision()}")
    return 0


async def _promote_admin(ctx: AppContext, args: argparse.Namespace) -> int:
    email = normalize_email(args.email)
    async with ctx.db.system_tx() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if user is None:
            print(f"No account for {email}: register it in the application first.")
            return 1
        user.platform_role = PlatformRole.ADMIN
        audit(
            session,
            "admin.role_granted",
            actor_type=ActorType.SYSTEM,
            target_type="user",
            target_id=user.id,
            details={"role": PlatformRole.ADMIN.value, "via": "cli"},
        )
    print(f"{email} is now a platform administrator.")
    return 0


def _write_private_file(path: str, content: str) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Created with owner-only permissions from the start (no readable window).
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(content)
    target.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return str(target)


async def _stripe_sync(ctx: AppContext, args: argparse.Namespace) -> int:
    from app.billing.catalog import sync_catalog

    if ctx.stripe is None:
        print("STRIPE_SECRET_KEY is not set.")
        return 1
    async with ctx.db.system_tx() as session:
        result = await sync_catalog(
            session,
            ctx.stripe.client,
            app_url=args.app_url or ctx.settings.public_app_url,
            livemode=ctx.stripe.livemode,
            webhook_url=args.webhook_url,
            rotate_webhook_secret=args.rotate_webhook_secret,
        )
    summary = {
        "account": result.account_id,
        "livemode": result.livemode,
        "plans": result.plans,
        "portal_configuration": result.portal_configuration_id,
        "webhook_endpoint": result.webhook_endpoint_id,
        "actions": result.actions or ["nothing to change"],
    }
    if result.webhook_secret:
        # The signing secret is shown by Stripe only once. It is written to a
        # private file, never printed, so it cannot end up in a terminal log.
        summary["webhook_secret_file"] = _write_private_file(
            args.webhook_secret_file, result.webhook_secret
        )
    print(json.dumps(summary, indent=2))
    return 0


async def _worker(ctx: AppContext, args: argparse.Namespace) -> int:
    worker = f"worker-{socket.gethostname()}-{os.getpid()}"
    while True:
        summary = await run_due_tasks(ctx, worker=worker, max_tasks=50, time_budget_seconds=30)
        if args.once:
            print(json.dumps(summary))
            return 0
        if not any(summary.values()):
            await asyncio.sleep(args.poll_interval)


async def _segment_analyze(ctx: AppContext, args: argparse.Namespace) -> int:
    """Analyze one local 5-minute MP4 for an existing stream session."""
    from pathlib import Path
    from uuid import UUID

    from app.services.segment_pipeline import analyze_local_segment, load_live_session

    session_id = UUID(args.session_id)
    video = Path(args.video)
    exists = await asyncio.to_thread(video.is_file)
    if not exists:
        print(f"Video not found: {video}")
        return 1
    async with ctx.db.system_tx() as session:
        stream = await load_live_session(session, session_id)
        if stream is None:
            print(f"Unknown stream session {session_id}")
            return 1
        result = await analyze_local_segment(
            session,
            settings=ctx.settings,
            storage=ctx.storage,
            stream=stream,
            sequence=args.sequence,
            video_path=video,
        )
    print(
        json.dumps(
            {
                "sequence": result.sequence,
                "moments": result.moments,
                "key": result.storage_key,
            }
        )
    )
    return 0


async def _live_loop(ctx: AppContext, args: argparse.Namespace) -> int:
    """Record then analyze every 5 minutes on the ingest instance until live ends."""
    from pathlib import Path
    from uuid import UUID

    from app.models.enums import StreamSessionStatus
    from app.services.segment_pipeline import (
        load_live_session,
        record_and_analyze,
        session_still_live,
    )

    session_id = UUID(args.session_id)
    work_dir = Path(args.work_dir)
    sequence = args.start_sequence
    while True:
        async with ctx.db.system_tx() as session:
            stream = await load_live_session(session, session_id)
            if stream is None:
                print(json.dumps({"error": "session_not_found", "session_id": str(session_id)}))
                return 1
            if stream.status is StreamSessionStatus.COMPLETED:
                print(
                    json.dumps(
                        {"done": True, "sequence": sequence, "status": stream.status.value}
                    )
                )
                return 0
            if stream.status is StreamSessionStatus.FAILED:
                print(json.dumps({"done": True, "failed": True, "status": stream.status.value}))
                return 1
            if not session_still_live(stream):
                print(json.dumps({"done": True, "status": stream.status.value}))
                return 0
            try:
                result = await record_and_analyze(
                    session,
                    settings=ctx.settings,
                    storage=ctx.storage,
                    stream=stream,
                    sequence=sequence,
                    input_url=args.input_url,
                    work_dir=work_dir,
                )
            except Exception as exc:
                print(json.dumps({"error": str(exc), "sequence": sequence}))
                if args.stop_on_error:
                    return 1
                await asyncio.sleep(5)
                continue
        print(
            json.dumps(
                {
                    "sequence": result.sequence,
                    "moments": len(result.moments),
                    "key": result.storage_key,
                    "frames": result.frames,
                }
            )
        )
        sequence += 1
        if args.max_sequences and sequence >= args.start_sequence + args.max_sequences:
            return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("migrate", help="apply database migrations")

    promote = commands.add_parser("promote-admin", help="grant the platform admin role")
    promote.add_argument("--email", required=True)

    sync = commands.add_parser("stripe-sync", help="provision Stripe from the plans table")
    sync.add_argument("--app-url", help="public URL of the web app (default: PUBLIC_APP_URL)")
    sync.add_argument("--webhook-url", help="create or update the webhook endpoint for this URL")
    sync.add_argument("--rotate-webhook-secret", action="store_true")
    sync.add_argument("--webhook-secret-file", default=".localdev/stripe_webhook_secret")

    worker = commands.add_parser("worker", help="run queued tasks")
    worker.add_argument("--once", action="store_true", help="drain due tasks and exit")
    worker.add_argument("--poll-interval", type=float, default=2.0)

    seg = commands.add_parser("segment-analyze", help="analyze one 5-min MP4 for a live session")
    seg.add_argument("--session-id", required=True)
    seg.add_argument("--video", required=True)
    seg.add_argument("--sequence", type=int, default=0)

    loop = commands.add_parser(
        "live-loop",
        help="record+analyze 5-min segments on the ingest node until the live ends",
    )
    loop.add_argument("--session-id", required=True)
    loop.add_argument("--input-url", required=True, help="local MediaMTX URL, e.g. rtmp://127.0.0.1/live/ID")
    loop.add_argument("--work-dir", default="/var/lib/streamclip/segments")
    loop.add_argument("--start-sequence", type=int, default=0)
    loop.add_argument("--max-sequences", type=int, default=0, help="0 = until live ends")
    loop.add_argument("--stop-on-error", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "migrate":
        return _migrate(args)

    settings = get_settings()
    configure_logging(settings.log_level, json_logs=settings.environment != "local")
    import app.tasks.handlers  # noqa: F401 - registers the task handlers

    handlers = {
        "promote-admin": _promote_admin,
        "stripe-sync": _stripe_sync,
        "worker": _worker,
        "segment-analyze": _segment_analyze,
        "live-loop": _live_loop,
    }

    async def run() -> int:
        ctx = build_context(settings, use_null_pool=True)
        try:
            return await handlers[args.command](ctx, args)
        finally:
            await ctx.db.dispose()

    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
