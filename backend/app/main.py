"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from app.api.v1 import account, admin, auth, billing, ingest, system
from app.context import AppContext, build_context
from app.core.config import Settings, get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None, ctx: AppContext | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(
        settings.log_level, json_logs=settings.environment in ("staging", "production")
    )
    ctx = ctx or build_context(settings)
    import app.tasks.handlers  # noqa: F401 - registers the task handlers

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        await ctx.db.dispose()

    # Interactive documentation is not exposed in production.
    expose_docs = not settings.is_production
    application = FastAPI(
        title="STREAMCLIP AI API",
        version=settings.release[:12],
        lifespan=lifespan,
        docs_url=f"{API_PREFIX}/docs" if expose_docs else None,
        openapi_url=f"{API_PREFIX}/openapi.json" if expose_docs else None,
        redoc_url=None,
    )
    application.state.ctx = ctx
    register_error_handlers(application)
    application.add_middleware(RequestContextMiddleware, settings=settings)

    api = APIRouter(prefix=API_PREFIX)
    for module in (system, auth, account, billing, admin, ingest):
        api.include_router(module.router)
    application.include_router(api)
    return application
