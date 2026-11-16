"""Password hashing (Argon2id) and password policy."""

import asyncio
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.errors import AppError

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128

# OWASP-recommended Argon2id profile (m=19 MiB, t=2, p=1) raised to 46 MiB.
_hasher = PasswordHasher(time_cost=2, memory_cost=46 * 1024, parallelism=1, hash_len=32)

# Hashing is CPU and memory bound: bound the concurrency so that a burst of
# logins cannot exhaust the instance's memory.
_HASH_CONCURRENCY = 4
_semaphores: dict[int, asyncio.Semaphore] = {}

# The passwords attackers try first. A full breach corpus check (k-anonymity
# HIBP API) can be added behind this function without changing callers.
_COMMON_PASSWORDS = frozenset(
    {
        "1234567890",
        "12345678910",
        "123456789a",
        "0123456789",
        "0987654321",
        "1q2w3e4r5t",
        "1qaz2wsx3edc",
        "qwertyuiop",
        "azertyuiop",
        "qwerty12345",
        "azerty12345",
        "password12",
        "password123",
        "password1234",
        "motdepasse1",
        "motdepasse123",
        "iloveyou123",
        "administrator",
        "adminadmin1",
        "abcdefghij",
        "abcd123456",
        "aaaaaaaaaa",
        "1111111111",
        "0000000000",
        "letmein12345",
        "welcome12345",
        "streamclip1",
        "streamclip123",
        "changeme123",
    }
)


class WeakPasswordError(AppError):
    status_code = 422
    code = "weak_password"


def _semaphore() -> asyncio.Semaphore:
    loop_id = id(asyncio.get_running_loop())
    semaphore = _semaphores.get(loop_id)
    if semaphore is None:
        semaphore = _semaphores[loop_id] = asyncio.Semaphore(_HASH_CONCURRENCY)
    return semaphore


def validate_password_policy(password: str, *, email: str | None = None) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError(
            f"Le mot de passe doit contenir au moins {MIN_PASSWORD_LENGTH} caractères."
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise WeakPasswordError(
            f"Le mot de passe ne peut pas dépasser {MAX_PASSWORD_LENGTH} caractères."
        )
    lowered = password.lower()
    if lowered in _COMMON_PASSWORDS or len(set(lowered)) < 4:
        raise WeakPasswordError("Ce mot de passe est trop courant. Choisissez-en un autre.")
    if email:
        local_part = email.split("@", 1)[0].lower()
        if lowered == email.lower() or (len(local_part) >= 4 and lowered.startswith(local_part)):
            raise WeakPasswordError("Le mot de passe ne doit pas reprendre votre adresse e-mail.")


async def hash_password(password: str) -> str:
    async with _semaphore():
        return await asyncio.to_thread(_hasher.hash, password)


def _verify(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


async def verify_password(password_hash: str, password: str) -> bool:
    # Reject absurd inputs before spending CPU on them.
    if len(password) > MAX_PASSWORD_LENGTH * 4:
        return False
    async with _semaphore():
        return await asyncio.to_thread(_verify, password_hash, password)


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return _hasher.hash("streamclip-timing-equalizer")


async def verify_dummy_password(password: str) -> None:
    """Spend the same time as a real verification when the account does not
    exist, so response times do not reveal which e-mails are registered."""
    await verify_password(_dummy_hash(), password)
