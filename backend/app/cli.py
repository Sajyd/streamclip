"""Operator commands.

    python -m app.cli migrate
    python -m app.cli promote-admin --email someone@example.com
    python -m app.cli stripe-sync --webhook-url https://.../api/v1/billing/webhooks/stripe
    python -m app.cli worker [--once]

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

    args = parser.parse_args(argv)
    if args.command == "migrate":
        return _migrate(args)

    settings = get_settings()
    configure_logging(settings.log_level, json_logs=settings.environment != "local")
    import app.tasks.handlers  # noqa: F401 - registers the task handlers

    handlers = {"promote-admin": _promote_admin, "stripe-sync": _stripe_sync, "worker": _worker}

    async def run() -> int:
        ctx = build_context(settings, use_null_pool=True)
        try:
            return await handlers[args.command](ctx, args)
        finally:
            await ctx.db.dispose()

    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
