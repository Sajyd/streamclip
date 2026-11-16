"""Fixed-window rate limiting backed by PostgreSQL.

Counters are incremented in their own short transaction so that they persist
even when the request they protect fails or is rolled back. The store is an
UNLOGGED table: cheap writes, and losing counters after a crash is harmless.
"""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.core.errors import RateLimitedError
from app.db.engine import Database


@dataclass(frozen=True, slots=True)
class Limit:
    name: str
    max_hits: int
    window_seconds: int


# Authentication
LOGIN_PER_IP = Limit("login_ip", 30, 300)
LOGIN_FAILURES_PER_EMAIL = Limit("login_fail_email", 8, 900)
REGISTER_PER_IP = Limit("register_ip", 10, 3600)
REFRESH_PER_IP = Limit("refresh_ip", 300, 300)
PASSWORD_RESET_PER_EMAIL = Limit("pwreset_email", 3, 3600)
PASSWORD_RESET_PER_IP = Limit("pwreset_ip", 10, 3600)
VERIFICATION_EMAIL_PER_USER = Limit("verify_email_user", 3, 3600)
TOKEN_SUBMIT_PER_IP = Limit("token_submit_ip", 30, 600)
PASSWORD_CHANGE_PER_USER = Limit("pwchange_user", 10, 3600)
# Billing and account
CHECKOUT_PER_ORG = Limit("checkout_org", 20, 3600)
DATA_EXPORT_PER_ORG = Limit("export_org", 5, 86400)


def _key(limit: Limit, subject: str) -> str:
    # Subjects may be e-mail addresses or IPs: store a digest, not the value.
    digest = hashlib.sha256(subject.encode("utf-8")).hexdigest()[:32]
    return f"{limit.name}:{digest}"


def _window_start(limit: Limit, now: datetime) -> datetime:
    epoch = int(now.timestamp())
    return datetime.fromtimestamp(epoch - epoch % limit.window_seconds, UTC)


class RateLimiter:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def hit(self, limit: Limit, subject: str | None) -> int:
        """Record one event and return the count in the current window."""
        if not subject:
            return 0
        now = datetime.now(UTC)
        window_start = _window_start(limit, now)
        async with self._db.system_tx() as session:
            result = await session.execute(
                text(
                    "INSERT INTO rate_limit_counters (key, window_start, count, expires_at)"
                    " VALUES (:key, :window_start, 1, :expires_at)"
                    " ON CONFLICT (key, window_start)"
                    " DO UPDATE SET count = rate_limit_counters.count + 1"
                    " RETURNING count"
                ),
                {
                    "key": _key(limit, subject),
                    "window_start": window_start,
                    "expires_at": window_start + timedelta(seconds=limit.window_seconds * 2),
                },
            )
            return int(result.scalar_one())

    async def count(self, limit: Limit, subject: str | None) -> int:
        if not subject:
            return 0
        window_start = _window_start(limit, datetime.now(UTC))
        async with self._db.system_tx() as session:
            result = await session.execute(
                text(
                    "SELECT count FROM rate_limit_counters"
                    " WHERE key = :key AND window_start = :window_start"
                ),
                {"key": _key(limit, subject), "window_start": window_start},
            )
            return int(result.scalar_one_or_none() or 0)

    def _too_many(self, limit: Limit) -> RateLimitedError:
        now = datetime.now(UTC)
        retry_after = limit.window_seconds - int(now.timestamp()) % limit.window_seconds
        return RateLimitedError(
            "Trop de tentatives. Réessayez dans quelques minutes.",
            details={"retry_after_seconds": retry_after},
            headers={"Retry-After": str(retry_after)},
        )

    async def check(self, limit: Limit, subject: str | None) -> None:
        """Count this event and refuse it when the window is exhausted."""
        if await self.hit(limit, subject) > limit.max_hits:
            raise self._too_many(limit)

    async def ensure_below(self, limit: Limit, subject: str | None) -> None:
        """Refuse when the window is already exhausted, without counting.
        Used with `hit` for limits that only count failures."""
        if await self.count(limit, subject) >= limit.max_hits:
            raise self._too_many(limit)
