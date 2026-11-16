"""Application-wide dependencies, built once per process."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.core.config import Settings
from app.db.engine import Database
from app.email.mailer import Mailer, build_mailer
from app.security.rate_limit import RateLimiter

if TYPE_CHECKING:
    from app.billing.gateway import StripeGateway
    from app.storage.s3 import ObjectStorage


@dataclass(slots=True)
class AppContext:
    settings: Settings
    db: Database
    rate_limiter: RateLimiter
    mailer: Mailer
    stripe: "StripeGateway | None"
    storage: "ObjectStorage | None"


def build_context(settings: Settings, *, use_null_pool: bool = False) -> AppContext:
    from app.billing.gateway import StripeGateway
    from app.storage.s3 import ObjectStorage

    db = Database(settings, use_null_pool=use_null_pool)
    return AppContext(
        settings=settings,
        db=db,
        rate_limiter=RateLimiter(db),
        mailer=build_mailer(settings),
        stripe=StripeGateway(settings) if settings.billing_enabled else None,
        storage=ObjectStorage(settings) if settings.storage_enabled else None,
    )
