"""Phase 1231 Plan 02 — Full-matrix integration tests for email-verified self-serve signup.

Covers the eight-case behaviour matrix:

(1) signup OFF (REGISTRATION_ENABLED false, default)
    → POST /auth/register returns 403 "Registration is disabled", send_email NOT called.

(2) signup ON + verification required
    → /register 201; send_email called once with data["to"]==registrant email and a
      body containing an absolute verify URL with the token; user row has
      email_verified=false + is_active=false.

(3) verify with the valid token (extracted from captured body)
    → POST /auth/verify-email 200; user now active + verified; subsequent
      POST /auth/login with new creds → 200.

(4) expired/garbage token
    → POST /auth/verify-email 400 with a clear message; account stays inactive.

(5) resend enumeration safety
    → POST /auth/resend-verification returns SAME 200 body for known unverified
      email AND for unknown email; known one triggers a second send.

(6) pre-verification user blocked from protected endpoint
    → GET /auth/me with invalid/pre-verify creds rejected.

(7) no-secret assertion on SMTP failure
    → When send_email raises with a fake "smtp-password" string in the message,
      the HTTP error body does NOT contain the password or a raw stack trace.

(8) cloud-gate regression
    → With has_extension("cloud") → True, POST /auth/register returns 403 (cloud gate
      preserved); smoke that /oauth-providers path is unaffected.
"""

from __future__ import annotations

import re
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STRONG_PASSWORD = "StrongPass1234!"  # meets SEC-S16 policy
_TEST_SMTP_PASSWORD = "smtp-super-secret-pass"


def _unique_username() -> str:
    return f"verifytest_{uuid.uuid4().hex[:8]}"


def _unique_email() -> str:
    return f"verifytest_{uuid.uuid4().hex[:8]}@example.com"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_limiter(monkeypatch):
    """Disable rate limiter for all tests in this module."""
    # The conftest already does this via limiter.enabled = False but
    # re-confirm it here since new endpoints also use the same limiter.
    from app.modules.auth.router import limiter

    monkeypatch.setattr(limiter, "enabled", False)


@pytest.fixture
def smtp_configured(monkeypatch):
    """Fake SMTP host so smtp_configured check passes in the router."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com", raising=False)


@pytest.fixture
def captured_send_email(monkeypatch, smtp_configured):
    """Replace send_email with an AsyncMock that captures calls.

    Also enables smtp_configured so the router's SMTP-check gate passes.
    The mock is installed at the smtp_channel module so the deferred import
    inside verification_email.py picks it up.
    """
    calls: list = []

    async def _fake_send(notification) -> None:
        calls.append(notification)

    monkeypatch.setattr(
        "app.platform.notifications.smtp_channel.send_email",
        _fake_send,
        raising=True,
    )
    return calls


@pytest.fixture
def registration_on(monkeypatch):
    """Turn REGISTRATION_ENABLED on for a single test."""
    monkeypatch.setattr(
        "app.core.persistent_config.REGISTRATION_ENABLED._env_default",
        True,
        raising=False,
    )
    # The PersistentConfig reads from cache or DB; for tests we force the
    # in-process value via the settings attribute that env_default_factory
    # reads.
    from app.core.config import settings

    monkeypatch.setattr(settings, "registration_enabled", True, raising=False)


@pytest.fixture
def verification_required_on(monkeypatch):
    """Turn EMAIL_VERIFICATION_REQUIRED on (it defaults True, but let's be explicit)."""
    from app.core.config import settings as _s

    # EMAIL_VERIFICATION_REQUIRED.env_default is True by default; reinforce.
    monkeypatch.setattr(_s, "email_verification_required", True, raising=False)


@pytest.fixture
def verification_required_off(monkeypatch):
    """Turn EMAIL_VERIFICATION_REQUIRED off."""
    from app.core.config import settings as _s

    monkeypatch.setattr(_s, "email_verification_required", False, raising=False)


# ---------------------------------------------------------------------------
# Helper: force PersistentConfig to bypass its DB cache and return a value
# ---------------------------------------------------------------------------


def _patch_persistent_config(monkeypatch, config_obj, value: bool):
    """Monkeypatch a PersistentConfig[bool] to always return *value* from .get().

    PersistentConfig.get() resolves: env_only → cache → DB → env_default.
    In integration tests the DB starts without an AppSetting row, and the
    in-memory cache is cleared per test, so get() falls through to env_default.

    Strategy:
    - If env_default_factory is set (e.g. REGISTRATION_ENABLED reads settings.registration_enabled):
      patch the settings attribute.
    - If env_default is a static constant (e.g. EMAIL_VERIFICATION_REQUIRED=True):
      patch _env_default_static on the config object.
    """
    from app.core.config import settings

    if config_obj._env_default_factory is not None:
        # Factory reads from settings; patch the settings attribute.
        attr_name = config_obj.key  # e.g. "registration_enabled"
        try:
            monkeypatch.setattr(settings, attr_name, value, raising=False)
        except (AttributeError, TypeError):
            pass
    else:
        # Static env_default; patch the instance attribute.
        monkeypatch.setattr(config_obj, "_env_default_static", value, raising=False)


# ---------------------------------------------------------------------------
# Case (1): signup OFF → 403 byte-identical, no email sent
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_signup_off_returns_403_no_email(
    client: AsyncClient,
    captured_send_email: list,
    monkeypatch,
) -> None:
    """SIGNUP-06: when REGISTRATION_ENABLED is off, register returns 403 and no email is sent."""
    from app.core.persistent_config import REGISTRATION_ENABLED

    _patch_persistent_config(monkeypatch, REGISTRATION_ENABLED, False)

    resp = await client.post(
        "/auth/register/",
        json={
            "username": _unique_username(),
            "password": _STRONG_PASSWORD,
            "email": _unique_email(),
        },
    )
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
    assert "Registration is disabled" in resp.json()["detail"]
    assert captured_send_email == [], "send_email must NOT be called when signup is off"


# ---------------------------------------------------------------------------
# Case (2): signup ON + verification required → 201, send_email called, user inactive
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_signup_on_verification_required_emails_registrant(
    client: AsyncClient,
    captured_send_email: list,
    test_db_session,
    monkeypatch,
) -> None:
    """SIGNUP-03: register with verification on sends 1 email to the registrant."""
    from app.core.persistent_config import (
        EMAIL_VERIFICATION_REQUIRED,
        REGISTRATION_ENABLED,
    )
    from app.modules.auth.models import User

    _patch_persistent_config(monkeypatch, REGISTRATION_ENABLED, True)
    _patch_persistent_config(monkeypatch, EMAIL_VERIFICATION_REQUIRED, True)

    username = _unique_username()
    email = _unique_email()

    resp = await client.post(
        "/auth/register/",
        json={"username": username, "password": _STRONG_PASSWORD, "email": email},
    )
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert "verify" in body["message"].lower(), (
        f"Response message should mention email verification, got: {body['message']!r}"
    )

    # Exactly one send_email call with the registrant's address
    assert len(captured_send_email) == 1, (
        f"Expected exactly 1 send_email call, got {len(captured_send_email)}"
    )
    notification = captured_send_email[0]
    assert notification.data is not None
    assert notification.data.get("to") == email, (
        f"Verification email must go to registrant {email!r}, got {notification.data.get('to')!r}"
    )

    # Body must contain a URL with a token
    assert "verify-email" in notification.body, (
        "Email body must contain a verify-email URL"
    )
    assert "token=" in notification.body, "Email body must include ?token= parameter"

    # User must be inactive / unverified
    result = await test_db_session.execute(
        select(User).where(User.username == username)
    )
    user = result.scalar_one_or_none()
    assert user is not None, f"User {username!r} should exist in DB"
    assert user.email_verified is False, "New user must have email_verified=False"
    assert user.is_active is False, "New user must be inactive until verified"
    assert user.status == "pending", (
        f"New user status should be 'pending', got {user.status!r}"
    )


# ---------------------------------------------------------------------------
# Case (3): valid token → activation + login works
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_verify_email_activates_account_and_login_works(
    client: AsyncClient,
    captured_send_email: list,
    test_db_session,
    monkeypatch,
) -> None:
    """SIGNUP-03/04: verify-email with valid token activates the account; login then succeeds."""
    from app.core.persistent_config import (
        EMAIL_VERIFICATION_REQUIRED,
        REGISTRATION_ENABLED,
    )
    from app.modules.auth.models import User

    _patch_persistent_config(monkeypatch, REGISTRATION_ENABLED, True)
    _patch_persistent_config(monkeypatch, EMAIL_VERIFICATION_REQUIRED, True)

    username = _unique_username()
    email = _unique_email()

    # Register
    resp = await client.post(
        "/auth/register/",
        json={"username": username, "password": _STRONG_PASSWORD, "email": email},
    )
    assert resp.status_code == 201, resp.text

    # Extract token from captured email body
    assert len(captured_send_email) == 1
    email_body = captured_send_email[0].body
    token_match = re.search(r"token=([A-Za-z0-9_\-]+)", email_body)
    assert token_match, f"Could not find token in email body: {email_body!r}"
    raw_token = token_match.group(1)

    # Verify
    verify_resp = await client.post("/auth/verify-email/", json={"token": raw_token})
    assert verify_resp.status_code == 200, (
        f"verify-email expected 200, got {verify_resp.status_code}: {verify_resp.text}"
    )

    # User should now be active + verified
    await test_db_session.refresh(
        (
            await test_db_session.execute(select(User).where(User.username == username))
        ).scalar_one()
    )
    result = await test_db_session.execute(
        select(User).where(User.username == username)
    )
    user = result.scalar_one()
    assert user.email_verified is True, (
        "email_verified should be True after verification"
    )
    assert user.is_active is True, "is_active should be True after verification"
    assert user.status == "active", f"status should be 'active', got {user.status!r}"

    # Login should now work
    login_resp = await client.post(
        "/auth/login",
        data={"username": username, "password": _STRONG_PASSWORD},
    )
    assert login_resp.status_code == 200, (
        f"Login should succeed after verification, got {login_resp.status_code}: {login_resp.text}"
    )
    assert "access_token" in login_resp.json()


# ---------------------------------------------------------------------------
# CR-01: a valid token must not re-activate an admin-suspended account
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_verify_email_does_not_reactivate_suspended_account(
    client: AsyncClient,
    captured_send_email: list,
    test_db_session,
    monkeypatch,
) -> None:
    """CR-01: if an admin suspends a still-pending account within the token's
    validity window, clicking the verification link must consume the token but
    must NOT silently re-activate the account."""
    from sqlalchemy import update

    from app.core.persistent_config import (
        EMAIL_VERIFICATION_REQUIRED,
        REGISTRATION_ENABLED,
    )
    from app.modules.auth.models import User

    _patch_persistent_config(monkeypatch, REGISTRATION_ENABLED, True)
    _patch_persistent_config(monkeypatch, EMAIL_VERIFICATION_REQUIRED, True)

    username = _unique_username()
    email = _unique_email()

    resp = await client.post(
        "/auth/register/",
        json={"username": username, "password": _STRONG_PASSWORD, "email": email},
    )
    assert resp.status_code == 201, resp.text

    assert len(captured_send_email) == 1
    token_match = re.search(r"token=([A-Za-z0-9_\-]+)", captured_send_email[0].body)
    assert token_match, "Could not find token in email body"
    raw_token = token_match.group(1)

    # Admin suspends the still-pending account before the user verifies.
    await test_db_session.execute(
        update(User).where(User.username == username).values(status="suspended")
    )
    await test_db_session.commit()

    # Clicking the link returns 200 (no status leak) but must NOT re-activate.
    verify_resp = await client.post("/auth/verify-email/", json={"token": raw_token})
    assert verify_resp.status_code == 200, verify_resp.text

    user = (
        await test_db_session.execute(select(User).where(User.username == username))
    ).scalar_one()
    await test_db_session.refresh(user)
    assert user.is_active is False, "suspended account must stay inactive (CR-01)"
    assert user.status == "suspended", (
        f"status must stay 'suspended', got {user.status!r} (CR-01)"
    )

    # The token is single-use even though activation was skipped.
    second = await client.post("/auth/verify-email/", json={"token": raw_token})
    assert second.status_code == 400, (
        "token must be single-use even when activation is skipped"
    )


# ---------------------------------------------------------------------------
# Case (4): expired/garbage token → 400, account stays inactive
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_verify_email_invalid_token_returns_400(
    client: AsyncClient,
    captured_send_email: list,
    test_db_session,
    monkeypatch,
) -> None:
    """Expired/garbage token → clear 400, account stays inactive."""
    from app.core.persistent_config import (
        EMAIL_VERIFICATION_REQUIRED,
        REGISTRATION_ENABLED,
    )
    from app.modules.auth.models import User

    _patch_persistent_config(monkeypatch, REGISTRATION_ENABLED, True)
    _patch_persistent_config(monkeypatch, EMAIL_VERIFICATION_REQUIRED, True)

    username = _unique_username()
    email = _unique_email()

    # Register (so there is a user we could potentially tamper with)
    resp = await client.post(
        "/auth/register/",
        json={"username": username, "password": _STRONG_PASSWORD, "email": email},
    )
    assert resp.status_code == 201, resp.text

    # Attempt to verify with a garbage token
    bad_token = "this-is-not-a-real-token-abcdef1234567890"
    verify_resp = await client.post("/auth/verify-email/", json={"token": bad_token})
    assert verify_resp.status_code == 400, (
        f"Invalid token should return 400, got {verify_resp.status_code}: {verify_resp.text}"
    )
    detail = verify_resp.json()["detail"]
    assert detail, "Error response must have a non-empty detail"
    # Detail must be non-leaky and not expose internals
    assert "stack" not in detail.lower()
    assert "traceback" not in detail.lower()

    # Account must still be inactive
    result = await test_db_session.execute(
        select(User).where(User.username == username)
    )
    user = result.scalar_one()
    assert user.email_verified is False, (
        "email_verified must remain False after bad token"
    )
    assert user.is_active is False, "is_active must remain False after bad token"


# ---------------------------------------------------------------------------
# Case (5): resend enumeration safety
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_resend_verification_enumeration_safe(
    client: AsyncClient,
    captured_send_email: list,
    monkeypatch,
) -> None:
    """SIGNUP-05: resend returns same 200 body for known and unknown email."""
    from app.core.persistent_config import (
        EMAIL_VERIFICATION_REQUIRED,
        REGISTRATION_ENABLED,
    )

    _patch_persistent_config(monkeypatch, REGISTRATION_ENABLED, True)
    _patch_persistent_config(monkeypatch, EMAIL_VERIFICATION_REQUIRED, True)

    # Register a real user so there is an unverified account
    username = _unique_username()
    real_email = _unique_email()
    reg_resp = await client.post(
        "/auth/register/",
        json={"username": username, "password": _STRONG_PASSWORD, "email": real_email},
    )
    assert reg_resp.status_code == 201, reg_resp.text

    # Clear captured calls from registration
    initial_calls = len(captured_send_email)

    # Resend for the KNOWN unverified email
    resp_known = await client.post(
        "/auth/resend-verification/",
        json={"email": real_email},
    )
    assert resp_known.status_code == 200, (
        f"Expected 200 for known email, got {resp_known.status_code}: {resp_known.text}"
    )
    known_body = resp_known.json()["message"]

    # Resend for an UNKNOWN email
    unknown_email = _unique_email()
    resp_unknown = await client.post(
        "/auth/resend-verification/",
        json={"email": unknown_email},
    )
    assert resp_unknown.status_code == 200, (
        f"Expected 200 for unknown email, got {resp_unknown.status_code}: {resp_unknown.text}"
    )
    unknown_body = resp_unknown.json()["message"]

    # Same response body regardless of existence (enumeration-safe)
    assert known_body == unknown_body, (
        f"Resend must return identical body for known and unknown email.\n"
        f"  known:   {known_body!r}\n"
        f"  unknown: {unknown_body!r}"
    )

    # The known unverified email must have triggered a send
    calls_after = len(captured_send_email)
    assert calls_after > initial_calls, (
        "Resend for a known unverified email should trigger send_email"
    )

    # The unknown email must NOT have triggered a send
    # (total sends = initial + 1 for the known resend only)
    expected_total = initial_calls + 1
    assert calls_after == expected_total, (
        f"Expected exactly {expected_total} total send_email calls (unknown email must not send), "
        f"got {calls_after}"
    )


# ---------------------------------------------------------------------------
# Case (6): pre-verification user blocked from protected endpoint
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_unverified_user_blocked_from_protected_endpoint(
    client: AsyncClient,
    captured_send_email: list,
    monkeypatch,
) -> None:
    """SIGNUP-04: an inactive/unverified user cannot reach /auth/me."""
    from app.core.persistent_config import (
        EMAIL_VERIFICATION_REQUIRED,
        REGISTRATION_ENABLED,
    )

    _patch_persistent_config(monkeypatch, REGISTRATION_ENABLED, True)
    _patch_persistent_config(monkeypatch, EMAIL_VERIFICATION_REQUIRED, True)

    username = _unique_username()
    email = _unique_email()

    # Register (leaves user inactive/unverified)
    resp = await client.post(
        "/auth/register/",
        json={"username": username, "password": _STRONG_PASSWORD, "email": email},
    )
    assert resp.status_code == 201, resp.text

    # Attempt login — should be rejected because account is pending/inactive
    login_resp = await client.post(
        "/auth/login",
        data={"username": username, "password": _STRONG_PASSWORD},
    )
    assert login_resp.status_code in (401, 403), (
        f"Login for unverified user should be rejected (401 or 403), "
        f"got {login_resp.status_code}: {login_resp.text}"
    )


# ---------------------------------------------------------------------------
# Case (7): SMTP send failure → clear non-leaky error, no secret in response
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_smtp_failure_returns_clear_non_leaky_error(
    client: AsyncClient,
    smtp_configured,
    monkeypatch,
) -> None:
    """T-1231-07: SMTP failure → clear HTTP error, secret never in response body."""
    import smtplib

    from app.core.persistent_config import (
        EMAIL_VERIFICATION_REQUIRED,
        REGISTRATION_ENABLED,
    )

    _patch_persistent_config(monkeypatch, REGISTRATION_ENABLED, True)
    _patch_persistent_config(monkeypatch, EMAIL_VERIFICATION_REQUIRED, True)

    # Inject a fake send_email that raises with a message containing the secret
    async def _raising_send(notification) -> None:
        raise smtplib.SMTPAuthenticationError(
            535,
            f"Authentication failed: password={_TEST_SMTP_PASSWORD}",
        )

    monkeypatch.setattr(
        "app.platform.notifications.smtp_channel.send_email",
        _raising_send,
        raising=True,
    )

    username = _unique_username()
    email = _unique_email()

    resp = await client.post(
        "/auth/register/",
        json={"username": username, "password": _STRONG_PASSWORD, "email": email},
    )

    # Must not be a 500 (unhandled exception)
    assert resp.status_code != 500, (
        f"SMTP failure must not cause a 500; got {resp.status_code}: {resp.text}"
    )

    response_text = resp.text
    # The SMTP password must never appear in the response body
    assert _TEST_SMTP_PASSWORD not in response_text, (
        f"SMTP password leaked in HTTP response body:\n{response_text}"
    )
    # No raw stack trace
    assert "Traceback" not in response_text, (
        "Raw traceback must not appear in HTTP response body"
    )
    assert (
        "traceback" not in response_text.lower()
        or "Traceback (most" not in response_text
    ), "Raw traceback must not appear in HTTP response body"

    # The error should be a 502 (bad gateway) with a clear actionable message
    assert resp.status_code == 502, (
        f"SMTP failure should return 502, got {resp.status_code}"
    )
    detail = resp.json().get("detail", "")
    assert detail, "Error response must have a non-empty detail"
    # Should mention the exception type, not the raw error
    assert _TEST_SMTP_PASSWORD not in detail, (
        f"SMTP password must not appear in error detail: {detail!r}"
    )


# ---------------------------------------------------------------------------
# Case (8): cloud-gate regression + Google SSO smoke
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cloud_gate_preserved(
    client: AsyncClient,
    captured_send_email: list,
    monkeypatch,
) -> None:
    """T-1231-08: cloud mode 403 gate is preserved; global self-signup stays disabled."""
    from app.core.persistent_config import REGISTRATION_ENABLED

    # Turn signup ON so the cloud-gate check is the ONLY reason for the 403
    _patch_persistent_config(monkeypatch, REGISTRATION_ENABLED, True)

    # Monkeypatch has_extension to return True for "cloud"
    monkeypatch.setattr(
        "app.platform.extensions.has_extension",
        lambda name: name == "cloud",
        raising=True,
    )

    resp = await client.post(
        "/auth/register/",
        json={
            "username": _unique_username(),
            "password": _STRONG_PASSWORD,
            "email": _unique_email(),
        },
    )
    assert resp.status_code == 403, (
        f"Cloud gate must return 403 even when REGISTRATION_ENABLED=True; "
        f"got {resp.status_code}: {resp.text}"
    )
    assert "cloud" in resp.json()["detail"].lower(), (
        "403 detail should mention cloud mode"
    )

    # send_email must NOT be called when the cloud gate fires
    assert captured_send_email == [], (
        "send_email must not be called when the cloud gate fires"
    )


@pytest.mark.anyio
async def test_google_sso_oauth_providers_endpoint_unaffected(
    client: AsyncClient,
    admin_auth_header: dict,
) -> None:
    """Google SSO / OAuth-providers endpoint is unaffected by verification wiring."""
    # GET /admin/oauth-providers/ should still return a valid response
    resp = await client.get("/admin/oauth-providers/", headers=admin_auth_header)
    # We only care that the endpoint exists and doesn't error — 200 or 404 (no providers)
    # are both acceptable; 500 would indicate a regression.
    assert resp.status_code in (200, 404), (
        f"OAuth providers endpoint should return 200 or 404, got {resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# config endpoint exposes allow_signup + email_verification_required
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_config_exposes_signup_flags(
    client: AsyncClient,
    monkeypatch,
) -> None:
    """GET /auth/config exposes allow_signup and email_verification_required."""
    from app.core.persistent_config import (
        EMAIL_VERIFICATION_REQUIRED,
        REGISTRATION_ENABLED,
    )

    _patch_persistent_config(monkeypatch, REGISTRATION_ENABLED, True)
    _patch_persistent_config(monkeypatch, EMAIL_VERIFICATION_REQUIRED, True)

    resp = await client.get("/auth/config/")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert "allow_signup" in body, "ConfigResponse must include allow_signup"
    assert "email_verification_required" in body, (
        "ConfigResponse must include email_verification_required"
    )
    assert "smtp_configured" in body, "ConfigResponse must include smtp_configured (M1)"
    # With REGISTRATION_ENABLED=True, allow_signup should be True
    assert body["allow_signup"] is True, (
        f"allow_signup should reflect REGISTRATION_ENABLED; got {body['allow_signup']!r}"
    )


@pytest.mark.anyio
async def test_config_smtp_configured_reflects_settings(
    client: AsyncClient,
    monkeypatch,
) -> None:
    """GET /auth/config → smtp_configured mirrors whether settings.smtp_host is set (M1).

    RegisterPage branches on this to avoid telling a no-SMTP signup to
    "check your email" when the server actually falls back to admin-approval.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com", raising=False)
    resp = await client.get("/auth/config/")
    assert resp.status_code == 200, resp.text
    assert resp.json()["smtp_configured"] is True, (
        "smtp_configured must be True when settings.smtp_host is set"
    )

    monkeypatch.setattr(settings, "smtp_host", None, raising=False)
    resp = await client.get("/auth/config/")
    assert resp.status_code == 200, resp.text
    assert resp.json()["smtp_configured"] is False, (
        "smtp_configured must be False when settings.smtp_host is unset"
    )


@pytest.mark.anyio
async def test_config_allow_signup_false_when_disabled(
    client: AsyncClient,
    monkeypatch,
) -> None:
    """GET /auth/config → allow_signup=false when REGISTRATION_ENABLED is off."""
    from app.core.persistent_config import REGISTRATION_ENABLED

    _patch_persistent_config(monkeypatch, REGISTRATION_ENABLED, False)

    resp = await client.get("/auth/config/")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("allow_signup") is False, (
        f"allow_signup should be False when REGISTRATION_ENABLED is off, got {body.get('allow_signup')!r}"
    )


# ---------------------------------------------------------------------------
# No-email registration + verification required: fallback to admin-approval
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_no_email_registration_falls_back_to_admin_approval(
    client: AsyncClient,
    captured_send_email: list,
    monkeypatch,
) -> None:
    """When verification is required but no email is provided, fall back to admin-approval.

    This preserves backward compat for existing tests that register without an
    email (the 'admin-approval' self-hosted path).  The user is left pending/inactive
    pending manual admin activation.  No verification email is sent.
    """
    from app.core.persistent_config import (
        EMAIL_VERIFICATION_REQUIRED,
        REGISTRATION_ENABLED,
    )

    _patch_persistent_config(monkeypatch, REGISTRATION_ENABLED, True)
    _patch_persistent_config(monkeypatch, EMAIL_VERIFICATION_REQUIRED, True)

    resp = await client.post(
        "/auth/register/",
        json={"username": _unique_username(), "password": _STRONG_PASSWORD},  # no email
    )
    assert resp.status_code == 201, (
        f"No-email registration should fall back to admin-approval (201), "
        f"got {resp.status_code}: {resp.text}"
    )
    # Should mention admin approval, not email verification
    msg = resp.json()["message"].lower()
    assert "awaiting" in msg or "approval" in msg or "admin" in msg, (
        f"No-email response should mention admin approval, got: {resp.json()['message']!r}"
    )
    # No email sent
    assert captured_send_email == [], "No email should be sent when no address provided"


# ---------------------------------------------------------------------------
# verify-email endpoint: notify() is never called (only send_email directly)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_verify_notify_not_called(
    client: AsyncClient,
    captured_send_email: list,
    monkeypatch,
) -> None:
    """Verification email must use send_email DIRECTLY, never notify().

    This test asserts that notify() is NOT called during the register+verify
    flow (only send_email is called, routing only to the registrant).
    """
    from app.core.persistent_config import (
        EMAIL_VERIFICATION_REQUIRED,
        REGISTRATION_ENABLED,
    )

    _patch_persistent_config(monkeypatch, REGISTRATION_ENABLED, True)
    _patch_persistent_config(monkeypatch, EMAIL_VERIFICATION_REQUIRED, True)

    notify_calls: list = []

    async def _fake_notify(notification) -> None:
        notify_calls.append(notification)

    monkeypatch.setattr(
        "app.platform.notifications.events.notify",
        _fake_notify,
        raising=False,
    )

    username = _unique_username()
    email = _unique_email()

    # Register (triggers verification email)
    resp = await client.post(
        "/auth/register/",
        json={"username": username, "password": _STRONG_PASSWORD, "email": email},
    )
    assert resp.status_code == 201, resp.text

    # notify() must not have been called for the verification email
    # (admin EVENT-01 signup notify goes through emit_event_safe which
    # calls notify() only when the toggle is on; in tests notify_on_signup
    # defaults False, so notify_calls should still be empty)
    email_verif_notify_calls = [
        c for c in notify_calls if c.event_type == "email_verification"
    ]
    assert email_verif_notify_calls == [], (
        f"notify() must not be called for email_verification; "
        f"got {len(email_verif_notify_calls)} call(s)"
    )

    # But send_email WAS called directly
    assert len(captured_send_email) == 1, (
        "send_email should have been called exactly once for verification"
    )
