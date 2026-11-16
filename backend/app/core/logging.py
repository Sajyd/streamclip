"""Structured logging: JSON lines in deployed environments, readable locally.

Log records carry the request id and, once authenticated, the user and
organization ids. Secrets, tokens and request bodies are never logged.
"""

import logging
import sys
from typing import Any

import structlog

_SENSITIVE_KEYS = ("password", "secret", "token", "authorization", "cookie", "api_key")


def _redact(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    for key in list(event_dict):
        lowered = key.lower()
        if any(marker in lowered for marker in _SENSITIVE_KEYS):
            event_dict[key] = "[redacted]"
    return event_dict


def configure_logging(level: str = "INFO", *, json_logs: bool = True) -> None:
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _redact,
        structlog.processors.StackInfoRenderer(),
    ]
    renderer: Any
    if json_logs:
        shared.append(structlog.processors.format_exc_info)
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
    # Third-party libraries: keep warnings and errors only.
    logging.basicConfig(level=logging.WARNING, stream=sys.stdout, format="%(message)s")
    logging.getLogger("uvicorn.access").disabled = True
