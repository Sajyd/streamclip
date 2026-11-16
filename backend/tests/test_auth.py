"""Registration, sign-in, sessions, token rotation, e-mail and password flows."""

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import jwt
from sqlalchemy import select, text

from app.context import AppContext
from app.core.config import Settings
from app.models.billing import Subscription, UsagePeriod
from app.models.enums import SessionRevokeReason
from app.models.identity import AuthSession, AuthToken, RefreshToken, User
from app.models.system import AuditLog
from app.security.tokens import create_access_token, hash_opaque_token
from tests.helpers import API, PASSWORD, CapturingMailer, error_code, register, unique_email


async def _login(client: httpx.AsyncClient, email: str, password: str = PASSWORD) -> httpx.Response:
    return await client.post(f"{API}/auth/login", json={"email": email, "password": password})


# --- Registration --------------------------------------------------------------


async def test_register_creates_account_personal_organization_and_free_plan(
    client: httpx.AsyncClient, ctx: AppContext
) -> None:
    account = await register(client, email="  New.User@Example.COM ")
    assert account.email == "new.user@example.com"  # normalised

    async with ctx.db.system_tx() as session:
        user = await session.get_one(User, account.user_id)
        subscription = (
            await session.execute(
                select(Subscription).where(Subscription.organization_id == account.organization_id)
            )
        ).scalar_one()
        period = (
            await session.execute(
                select(UsagePeriod).where(UsagePeriod.organization_id == account.organization_id)
            )
        ).scalar_one()
        audit_actions = (await session.execute(select(AuditLog.action))).scalars().all()
    assert user.password_hash.startswith("$argon2id$")
    assert PASSWORD not in user.password_hash
    assert user.email_verified_at is None
    assert subscription.stripe_subscription_id is None
    assert period.included_ms == 3_600_000 and period.consumed_ms == 0
    assert "auth.register" in audit_actions


async def test_register_rejects_duplicate_email_case_insensitively(
    client: httpx.AsyncClient,
) -> None:
    account = await register(client)
    response = await client.post(
        f"{API}/auth/register",
        json={"email": account.email.upper(), "password": PASSWORD, "accept_terms": True},
    )
    assert response.status_code == 409
    assert error_code(response) == "email_already_registered"


async def test_register_enforces_password_policy_and_terms(client: httpx.AsyncClient) -> None:
    email = unique_email()
    cases = {
        "short": ("weak_password", {"password": "short1"}),
        "common": ("weak_password", {"password": "password123"}),
        "email": ("weak_password", {"password": email.split("@")[0] + "-2026"}),
        "terms": ("terms_required", {"password": PASSWORD, "accept_terms": False}),
        "address": ("invalid_email", {"password": PASSWORD, "email": "not-an-address"}),
    }
    for expected, overrides in cases.values():
        payload = {"email": email, "password": PASSWORD, "accept_terms": True, **overrides}
        response = await client.post(f"{API}/auth/register", json=payload)
        assert response.status_code == 422, (expected, response.text)
        assert error_code(response) == expected
    # Submitted values are never echoed back in validation errors.
    secret = "Sup3r-Secret-Value-Never-Echoed"
    response = await client.post(
        f"{API}/auth/register",
        json={"email": email, "password": secret, "accept_terms": "maybe", "unknown": secret},
    )
    assert response.status_code == 422 and error_code(response) == "validation_error"
    assert secret not in response.text and "maybe" not in response.text


async def test_passwords_are_taken_verbatim_including_surrounding_spaces(
    client: httpx.AsyncClient,
) -> None:
    spaced = "  spaces are part of it  "
    account = await register(client, password=spaced)
    assert (await _login(client, account.email, spaced)).status_code == 200
    assert (await _login(client, account.email, spaced.strip())).status_code == 401


async def test_registration_can_be_closed(client: httpx.AsyncClient, settings: Settings) -> None:
    settings.registration_open = False
    try:
        response = await client.post(
            f"{API}/auth/register",
            json={"email": unique_email(), "password": PASSWORD, "accept_terms": True},
        )
    finally:
        settings.registration_open = True
    assert response.status_code == 403 and error_code(response) == "registration_closed"


# --- Sign-in -------------------------------------------------------------------


async def test_login_succeeds_and_failures_are_indistinguishable(
    client: httpx.AsyncClient, ctx: AppContext
) -> None:
    account = await register(client)
    ok = await _login(client, account.email.upper())
    assert ok.status_code == 200 and ok.json()["tokens"]["access_token"]

    wrong_password = await _login(client, account.email, "not-the-password")
    unknown_account = await _login(client, unique_email(), PASSWORD)
    assert wrong_password.status_code == unknown_account.status_code == 401
    # Same code and same message: an attacker cannot tell which accounts exist.
    assert wrong_password.json()["error"]["message"] == unknown_account.json()["error"]["message"]
    assert error_code(wrong_password) == "invalid_credentials"

    async with ctx.db.system_tx() as session:
        outcomes = (
            await session.execute(
                select(AuditLog.outcome, AuditLog.ip).where(AuditLog.action == "auth.login")
            )
        ).all()
    assert sorted(o.value for o, _ in outcomes) == ["failure", "failure", "success"]
    assert {str(ip) for _, ip in outcomes} == {"203.0.113.10"}


async def test_repeated_failures_lock_the_account_temporarily(client: httpx.AsyncClient) -> None:
    account = await register(client)
    for _ in range(8):
        assert (await _login(client, account.email, "wrong-password")).status_code == 401
    locked = await _login(client, account.email, PASSWORD)  # even the right password
    assert locked.status_code == 429 and error_code(locked) == "rate_limited"
    assert int(locked.headers["retry-after"]) > 0


# --- Access tokens -------------------------------------------------------------


async def test_access_token_is_required_and_verified(
    client: httpx.AsyncClient, settings: Settings
) -> None:
    account = await register(client)
    assert (await client.get(f"{API}/me")).status_code == 401
    assert (
        await client.get(f"{API}/me", headers={"Authorization": "Basic abc"})
    ).status_code == 401

    header, payload, signature = account.access_token.split(".")
    tampered = f"{header}.{payload}.{signature[:-2]}xx"
    forged = jwt.encode(
        {
            "sub": str(account.user_id),
            "sid": str(account.session_id),
            "typ": "access",
            "iss": "streamclip",
            "iat": 1,
            "exp": 9999999999,
        },
        "attacker-secret-attacker-secret-attacker",
        algorithm="HS256",
        headers={"kid": "new"},
    )
    unsigned = jwt.encode(
        {
            "sub": str(account.user_id),
            "sid": str(account.session_id),
            "typ": "access",
            "iss": "streamclip",
            "iat": 1,
            "exp": 9999999999,
        },
        None,
        algorithm="none",
        headers={"kid": "new"},
    )
    expired, _ = create_access_token(
        settings,
        user_id=account.user_id,
        session_id=account.session_id,
        now=datetime.now(UTC) - timedelta(hours=1),
    )
    for token in (tampered, forged, unsigned, expired, "garbage"):
        response = await client.get(f"{API}/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401, token
        assert error_code(response) == "invalid_access_token"


async def test_tokens_signed_with_a_rotated_out_key_remain_valid(
    client: httpx.AsyncClient, settings: Settings
) -> None:
    account = await register(client)
    old_secret = settings.jwt_keyring()["old"]
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "iss": "streamclip",
            "typ": "access",
            "sub": str(account.user_id),
            "sid": str(account.session_id),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
        },
        old_secret,
        algorithm="HS256",
        headers={"kid": "old"},
    )
    response = await client.get(f"{API}/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200


# --- Refresh tokens ------------------------------------------------------------


async def test_refresh_rotates_tokens_and_stores_only_hashes(
    client: httpx.AsyncClient, ctx: AppContext
) -> None:
    account = await register(client)
    response = await client.post(
        f"{API}/auth/refresh", json={"refresh_token": account.refresh_token}
    )
    assert response.status_code == 200
    rotated = response.json()
    assert rotated["refresh_token"] != account.refresh_token
    assert rotated["session_id"] == str(account.session_id)
    me = await client.get(
        f"{API}/me", headers={"Authorization": f"Bearer {rotated['access_token']}"}
    )
    assert me.status_code == 200

    async with ctx.db.system_tx() as session:
        hashes = (await session.execute(select(RefreshToken.token_hash))).scalars().all()
    assert set(hashes) == {
        hash_opaque_token(account.refresh_token),
        hash_opaque_token(rotated["refresh_token"]),
    }
    assert account.refresh_token not in hashes


async def test_reusing_a_rotated_refresh_token_revokes_the_session(
    client: httpx.AsyncClient, ctx: AppContext
) -> None:
    account = await register(client)
    first = await client.post(f"{API}/auth/refresh", json={"refresh_token": account.refresh_token})
    assert first.status_code == 200
    # Simulate the grace window having passed since the rotation.
    async with ctx.db.system_tx() as session:
        await session.execute(
            text("UPDATE refresh_tokens SET rotated_at = rotated_at - interval '1 minute'")
        )

    replay = await client.post(f"{API}/auth/refresh", json={"refresh_token": account.refresh_token})
    assert replay.status_code == 401 and error_code(replay) == "refresh_token_reused"

    # The legitimate holder of the newest token is signed out too: the session is dead.
    newest = first.json()
    after = await client.post(
        f"{API}/auth/refresh", json={"refresh_token": newest["refresh_token"]}
    )
    assert after.status_code == 401
    me = await client.get(
        f"{API}/me", headers={"Authorization": f"Bearer {newest['access_token']}"}
    )
    assert me.status_code == 401 and error_code(me) == "session_revoked"
    async with ctx.db.system_tx() as session:
        auth_session = await session.get_one(AuthSession, account.session_id)
    assert auth_session.revoke_reason is SessionRevokeReason.TOKEN_REUSE


async def test_concurrent_refreshes_within_the_grace_window_all_succeed(
    client: httpx.AsyncClient,
) -> None:
    account = await register(client)
    responses = await asyncio.gather(
        *(
            client.post(f"{API}/auth/refresh", json={"refresh_token": account.refresh_token})
            for _ in range(4)
        )
    )
    assert [r.status_code for r in responses] == [200] * 4
    assert len({r.json()["refresh_token"] for r in responses}) == 4


async def test_unknown_and_expired_refresh_tokens_are_rejected(
    client: httpx.AsyncClient, ctx: AppContext
) -> None:
    account = await register(client)
    unknown = await client.post(f"{API}/auth/refresh", json={"refresh_token": "x" * 43})
    assert unknown.status_code == 401 and error_code(unknown) == "invalid_refresh_token"
    async with ctx.db.system_tx() as session:
        await session.execute(text("UPDATE refresh_tokens SET expires_at = now() - interval '1 s'"))
    expired = await client.post(
        f"{API}/auth/refresh", json={"refresh_token": account.refresh_token}
    )
    assert expired.status_code == 401 and error_code(expired) == "invalid_refresh_token"


# --- Sessions ------------------------------------------------------------------


async def test_logout_revokes_only_the_current_session(client: httpx.AsyncClient) -> None:
    account = await register(client)
    second = (await _login(client, account.email)).json()["tokens"]
    second_headers = {"Authorization": f"Bearer {second['access_token']}"}

    assert (await client.post(f"{API}/auth/logout", headers=account.headers)).status_code == 204
    # The access token stops working at once, well before its own expiry.
    assert (await client.get(f"{API}/me", headers=account.headers)).status_code == 401
    refresh = await client.post(
        f"{API}/auth/refresh", json={"refresh_token": account.refresh_token}
    )
    assert refresh.status_code == 401
    assert (await client.get(f"{API}/me", headers=second_headers)).status_code == 200


async def test_logout_all_and_session_management(client: httpx.AsyncClient) -> None:
    account = await register(client)
    other = (await _login(client, account.email)).json()["tokens"]
    stranger = await register(client)

    sessions = (await client.get(f"{API}/auth/sessions", headers=account.headers)).json()
    assert len(sessions) == 2 and sum(item["current"] for item in sessions) == 1

    # A user cannot revoke somebody else's session, even knowing its id.
    response = await client.delete(
        f"{API}/auth/sessions/{account.session_id}", headers=stranger.headers
    )
    assert response.status_code == 204
    assert (await client.get(f"{API}/me", headers=account.headers)).status_code == 200

    response = await client.delete(
        f"{API}/auth/sessions/{other['session_id']}", headers=account.headers
    )
    assert response.status_code == 204
    other_headers = {"Authorization": f"Bearer {other['access_token']}"}
    assert (await client.get(f"{API}/me", headers=other_headers)).status_code == 401

    third = (await _login(client, account.email)).json()["tokens"]
    assert (await client.post(f"{API}/auth/logout-all", headers=account.headers)).status_code == 204
    for token in (account.access_token, third["access_token"]):
        response = await client.get(f"{API}/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401
    assert (await client.get(f"{API}/me", headers=stranger.headers)).status_code == 200


# --- E-mail verification -------------------------------------------------------


async def test_email_verification_flow(
    client: httpx.AsyncClient, ctx: AppContext, mailer: CapturingMailer
) -> None:
    account = await register(client)
    assert [m.to for m in mailer.outbox] == [account.email]
    token = mailer.last_token(account.email)

    async with ctx.db.system_tx() as session:
        stored = (await session.execute(select(AuthToken))).scalar_one()
    assert stored.token_hash == hash_opaque_token(token) and token not in stored.token_hash

    response = await client.post(f"{API}/auth/verify-email", json={"token": token})
    assert response.status_code == 200
    me = (await client.get(f"{API}/me", headers=account.headers)).json()
    assert me["user"]["email_verified"] is True

    # Single use.
    again = await client.post(f"{API}/auth/verify-email", json={"token": token})
    assert again.status_code == 400 and error_code(again) == "invalid_or_expired_token"
    resend = await client.post(f"{API}/auth/resend-verification", headers=account.headers)
    assert resend.status_code == 409 and error_code(resend) == "email_already_verified"


async def test_resending_verification_invalidates_the_previous_link(
    client: httpx.AsyncClient, mailer: CapturingMailer
) -> None:
    account = await register(client)
    first = mailer.last_token(account.email)
    response = await client.post(f"{API}/auth/resend-verification", headers=account.headers)
    assert response.status_code == 202
    second = mailer.last_token(account.email)
    assert first != second
    stale = await client.post(f"{API}/auth/verify-email", json={"token": first})
    assert stale.status_code == 400
    assert (
        await client.post(f"{API}/auth/verify-email", json={"token": second})
    ).status_code == 200


async def test_expired_verification_token_is_rejected(
    client: httpx.AsyncClient, ctx: AppContext, mailer: CapturingMailer
) -> None:
    account = await register(client)
    async with ctx.db.system_tx() as session:
        await session.execute(text("UPDATE auth_tokens SET expires_at = now() - interval '1 s'"))
    response = await client.post(
        f"{API}/auth/verify-email", json={"token": mailer.last_token(account.email)}
    )
    assert response.status_code == 400 and error_code(response) == "invalid_or_expired_token"


async def test_email_features_report_unavailable_when_delivery_is_not_configured(
    client: httpx.AsyncClient, mailer: CapturingMailer
) -> None:
    mailer.enabled = False
    account = await register(client)  # sign-up itself must still work
    assert mailer.outbox == []
    meta = (await client.get(f"{API}/meta")).json()
    assert meta["capabilities"]["email_delivery"] is False

    for response in (
        await client.post(f"{API}/auth/forgot-password", json={"email": account.email}),
        await client.post(f"{API}/auth/resend-verification", headers=account.headers),
    ):
        assert response.status_code == 503
        assert error_code(response) == "email_delivery_unavailable"


# --- Passwords -----------------------------------------------------------------


async def test_password_reset_flow_revokes_sessions_and_is_single_use(
    client: httpx.AsyncClient, mailer: CapturingMailer
) -> None:
    account = await register(client)
    new_password = "a-brand-new-passphrase"

    response = await client.post(f"{API}/auth/forgot-password", json={"email": account.email})
    assert response.status_code == 202
    token = mailer.last_token(account.email)

    weak = await client.post(
        f"{API}/auth/reset-password", json={"token": token, "new_password": "short"}
    )
    assert weak.status_code == 422  # and the token is not burnt by a rejected attempt
    done = await client.post(
        f"{API}/auth/reset-password", json={"token": token, "new_password": new_password}
    )
    assert done.status_code == 200

    assert (await client.get(f"{API}/me", headers=account.headers)).status_code == 401
    assert (await _login(client, account.email, PASSWORD)).status_code == 401
    signed_in = await _login(client, account.email, new_password)
    assert signed_in.status_code == 200
    # Receiving the link proved ownership of the mailbox.
    assert signed_in.json()["user"]["email_verified"] is True
    assert mailer.outbox[-1].subject.startswith("Votre mot de passe a été modifié")

    replay = await client.post(
        f"{API}/auth/reset-password", json={"token": token, "new_password": "another-passphrase-1"}
    )
    assert replay.status_code == 400 and error_code(replay) == "invalid_or_expired_token"


async def test_forgot_password_does_not_reveal_whether_an_account_exists(
    client: httpx.AsyncClient, mailer: CapturingMailer
) -> None:
    account = await register(client)
    mailer.outbox.clear()
    known = await client.post(f"{API}/auth/forgot-password", json={"email": account.email})
    unknown = await client.post(f"{API}/auth/forgot-password", json={"email": unique_email()})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert [m.to for m in mailer.outbox] == [account.email]


async def test_password_reset_requests_are_rate_limited_per_address(
    client: httpx.AsyncClient, mailer: CapturingMailer
) -> None:
    account = await register(client)
    mailer.outbox.clear()
    for _ in range(5):
        response = await client.post(f"{API}/auth/forgot-password", json={"email": account.email})
        assert response.status_code == 202  # silently capped: still no information leak
    assert len(mailer.outbox) == 3


async def test_change_password_keeps_current_session_and_revokes_the_others(
    client: httpx.AsyncClient,
) -> None:
    account = await register(client)
    other = (await _login(client, account.email)).json()["tokens"]
    new_password = "yet-another-passphrase"

    wrong = await client.post(
        f"{API}/auth/change-password",
        headers=account.headers,
        json={"current_password": "nope-nope-nope", "new_password": new_password},
    )
    assert wrong.status_code == 403 and error_code(wrong) == "invalid_current_password"

    changed = await client.post(
        f"{API}/auth/change-password",
        headers=account.headers,
        json={"current_password": PASSWORD, "new_password": new_password},
    )
    assert changed.status_code == 200
    assert (await client.get(f"{API}/me", headers=account.headers)).status_code == 200
    other_headers = {"Authorization": f"Bearer {other['access_token']}"}
    assert (await client.get(f"{API}/me", headers=other_headers)).status_code == 401
    assert (await _login(client, account.email, new_password)).status_code == 200


async def test_failed_email_delivery_is_retried_by_the_queue(
    client: httpx.AsyncClient, ctx: AppContext, mailer: CapturingMailer
) -> None:
    mailer.failures_to_inject = 1
    account = await register(client)  # the request succeeds although the e-mail failed
    assert mailer.outbox == []
    async with ctx.db.system_tx() as session:
        status, attempts = (await session.execute(text("SELECT status, attempts FROM tasks"))).one()
        assert (status, attempts) == ("queued", 1)
        await session.execute(text("UPDATE tasks SET run_at = now()"))  # skip the backoff

    from app.tasks.queue import run_due_tasks

    summary = await run_due_tasks(ctx, worker="test-worker")
    assert summary["succeeded"] == 1
    assert [m.to for m in mailer.outbox] == [account.email]
