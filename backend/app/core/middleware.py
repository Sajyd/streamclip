"""Request context: request id, client address, access log, response headers.

Implemented as a pure ASGI middleware (no BaseHTTPMiddleware) so that it adds
no buffering and works for streaming responses and WebSockets later on.
"""

import hmac
import ipaddress
import time
import uuid
from typing import Any

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import Settings

log = structlog.get_logger("http")

BFF_TOKEN_HEADER = "x-streamclip-bff-token"  # noqa: S105 - header name, not a secret
BFF_CLIENT_IP_HEADER = "x-streamclip-client-ip"
BFF_CLIENT_UA_HEADER = "x-streamclip-client-ua"


def _valid_ip(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.split(",")[0].strip()
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def resolve_client(
    headers: Headers, peer: str | None, settings: Settings
) -> tuple[str | None, str]:
    """Return (client_ip, user_agent) for rate limiting and audit.

    The address forwarded by our own front-end is trusted only when the
    request carries the shared BFF secret. Otherwise we use the header set by
    the platform's edge proxy (clients cannot override it), then the socket.
    """
    user_agent = headers.get("user-agent", "")[:400]
    secret = settings.bff_shared_secret
    token = headers.get(BFF_TOKEN_HEADER)
    if secret is not None and token and hmac.compare_digest(token, secret.get_secret_value()):
        forwarded_ua = headers.get(BFF_CLIENT_UA_HEADER)
        return (
            _valid_ip(headers.get(BFF_CLIENT_IP_HEADER)),
            (forwarded_ua or user_agent)[:400],
        )
    edge_ip = _valid_ip(headers.get("x-real-ip")) or _valid_ip(headers.get("x-forwarded-for"))
    if settings.environment in ("staging", "production"):
        return edge_ip, user_agent
    return edge_ip or _valid_ip(peer), user_agent


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        incoming_id = headers.get("x-request-id", "")
        request_id = incoming_id if 8 <= len(incoming_id) <= 64 and incoming_id.isascii() else ""
        request_id = request_id or uuid.uuid4().hex
        peer = scope["client"][0] if scope.get("client") else None
        client_ip, user_agent = resolve_client(headers, peer, self.settings)

        state: dict[str, Any] = scope.setdefault("state", {})
        state["request_id"] = request_id
        state["client_ip"] = client_ip
        state["user_agent"] = user_agent

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        content_length = headers.get("content-length")
        if (
            content_length
            and content_length.isdigit()
            and int(content_length) > self.settings.max_request_body_bytes
        ):
            response = JSONResponse(
                status_code=413,
                content={
                    "error": {
                        "code": "payload_too_large",
                        "message": "Requête trop volumineuse.",
                        "details": None,
                        "request_id": request_id,
                    }
                },
                headers={"x-request-id": request_id},
            )
            await response(scope, receive, send)
            return

        started = time.perf_counter()
        status_code = 500
        received_bytes = 0
        limit = self.settings.max_request_body_bytes

        async def receive_wrapper() -> Message:
            # Bodies sent without Content-Length (chunked) are counted as they
            # arrive. The exception surfaces in the handler reading the body
            # and is rendered as a regular 413 error.
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > limit:
                    raise HTTPException(status_code=413, detail="Requête trop volumineuse.")
            return message

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                response_headers = MutableHeaders(scope=message)
                response_headers["x-request-id"] = request_id
                response_headers["x-content-type-options"] = "nosniff"
                response_headers["referrer-policy"] = "no-referrer"
                # API responses are per-user and must never be cached by shared caches.
                response_headers.setdefault("cache-control", "no-store")
            await send(message)

        try:
            await self.app(scope, receive_wrapper, send_wrapper)
        finally:
            log.info(
                "request",
                method=scope["method"],
                path=scope["path"],
                status=status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
                client_ip=client_ip,
            )
