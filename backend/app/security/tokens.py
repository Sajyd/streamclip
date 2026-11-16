"""Access tokens (short-lived JWT) and opaque single-purpose tokens.

Access tokens only carry identifiers. Authorization data (role, account
status, session validity) is re-read from the database on every request, so a
revoked session or a suspended account stops working immediately.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import Settings
from app.core.errors import AuthenticationError

_ALGORITHM = "HS256"
_ISSUER = "streamclip"
_ACCESS_TYPE = "access"


@dataclass(frozen=True, slots=True)
class AccessClaims:
    user_id: uuid.UUID
    session_id: uuid.UUID
    expires_at: datetime


def create_access_token(
    settings: Settings, *, user_id: uuid.UUID, session_id: uuid.UUID, now: datetime | None = None
) -> tuple[str, datetime]:
    issued_at = now or datetime.now(UTC)
    expires_at = issued_at + timedelta(seconds=settings.access_token_ttl_seconds)
    keyring = settings.jwt_keyring()
    kid = next(iter(keyring))
    token = jwt.encode(
        {
            "iss": _ISSUER,
            "typ": _ACCESS_TYPE,
            "sub": str(user_id),
            "sid": str(session_id),
            "iat": int(issued_at.timestamp()),
            "exp": int(expires_at.timestamp()),
            "jti": secrets.token_hex(8),
        },
        keyring[kid],
        algorithm=_ALGORITHM,
        headers={"kid": kid},
    )
    return token, expires_at


def decode_access_token(settings: Settings, token: str) -> AccessClaims:
    invalid = AuthenticationError("Jeton d'accès invalide ou expiré.", code="invalid_access_token")
    try:
        kid = jwt.get_unverified_header(token).get("kid")
        secret = settings.jwt_keyring().get(kid) if isinstance(kid, str) else None
        if secret is None:
            raise invalid
        payload = jwt.decode(
            token,
            secret,
            algorithms=[_ALGORITHM],  # pinned: never trust the token's own "alg"
            issuer=_ISSUER,
            options={"require": ["exp", "iat", "sub", "sid", "typ"]},
        )
        if payload.get("typ") != _ACCESS_TYPE:
            raise invalid
        return AccessClaims(
            user_id=uuid.UUID(payload["sub"]),
            session_id=uuid.UUID(payload["sid"]),
            expires_at=datetime.fromtimestamp(payload["exp"], UTC),
        )
    except (jwt.PyJWTError, ValueError, KeyError, TypeError) as exc:
        raise invalid from exc


def generate_opaque_token() -> str:
    """256 bits of entropy, URL-safe. Used for refresh, verification and reset."""
    return secrets.token_urlsafe(32)


def hash_opaque_token(token: str) -> str:
    """Only this digest is stored. A fast hash is appropriate here: the input
    is a 256-bit random value, not a human-chosen secret."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
