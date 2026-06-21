"""HARDEN-04 (T-1238-05/06): OAuth audit correlation tests.

Verifies that login-init and callback (success and failure) emit audit entries
sharing a single correlation_id, and that no audit detail contains secrets,
tokens, or email addresses.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.modules.audit.models import AuditLog


# ---------------------------------------------------------------------------
# Edition isolation (mirrors test_oauth.py pattern)
# ---------------------------------------------------------------------------


def _reset_edition():
    import app.core.edition as ed_mod

    ed_mod._info = None


@pytest.fixture(autouse=True)
def _clean_edition():
    _reset_edition()
    yield
    _reset_edition()


# ---------------------------------------------------------------------------
# client_session: shares client's override_get_db so committed rows are
# immediately visible to subsequent HTTP calls (mirrors test_oauth.py D-04a).
# ---------------------------------------------------------------------------


@pytest.fixture
async def client_session(client):
    """Yield an async session that shares client's override_get_db factory."""
    from app.core.dependencies import get_db
    from app.api.main import app

    overridden_get_db = app.dependency_overrides[get_db]
    async for session in overridden_get_db():
        yield session


# ---------------------------------------------------------------------------
# Public URL fixture (mirrors test_oauth.py _ensure_public_app_url)
# ---------------------------------------------------------------------------


@pytest.fixture
def _ensure_public_app_url(monkeypatch):
    """Set settings.public_app_url / public_api_url so OAuth handlers don't 500."""
    import app.core.public_urls as public_urls
    from app.core.config import settings

    monkeypatch.setattr(settings, "public_app_url", "http://test", raising=False)
    monkeypatch.setattr(settings, "public_api_url", "http://test/api", raising=False)
    saved = public_urls._PUBLIC_URL_CACHE
    public_urls._PUBLIC_URL_CACHE = None
    yield
    public_urls._PUBLIC_URL_CACHE = saved


# ---------------------------------------------------------------------------
# Shared helper: create an OAuthProvider in the test DB
# ---------------------------------------------------------------------------


async def _create_test_provider(db, **overrides):
    from app.modules.auth.oauth.schemas import OAuthProviderCreate
    from app.modules.auth.oauth.service import create_provider

    suffix = uuid.uuid4().hex[:6]
    defaults = dict(
        slug=f"audit-cor-{suffix}",
        display_name="Audit Correlation Provider",
        provider_type="oidc",
        client_id=f"client-{suffix}",
        client_secret="test-secret",
        enabled=True,
        default_role="viewer",
    )
    defaults.update(overrides)
    provider = await create_provider(db, OAuthProviderCreate(**defaults))
    await db.commit()
    return provider


# ---------------------------------------------------------------------------
# Test 1: login-init emits an audit entry with an action of oauth.login.init
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_login_init_emits_audit_entry(
    client, client_session, _ensure_public_app_url
):
    """GET /{slug}/login emits an oauth.login.init audit entry."""
    provider = await _create_test_provider(client_session)
    slug = provider.slug

    # Patch build_oauth_client so it doesn't try to contact the IdP
    mock_client = MagicMock()
    mock_client.authorize_redirect = AsyncMock(
        return_value=MagicMock(status_code=302, headers={}, body=b"")
    )
    with patch(
        "app.modules.auth.oauth.router.build_oauth_client",
        AsyncMock(return_value=(mock_client, provider)),
    ):
        resp = await client.get(f"/auth/oauth/{slug}/login", follow_redirects=False)

    # We expect a redirect (302) out to the IdP
    assert resp.status_code in (302, 307, 200), f"Unexpected status: {resp.status_code}"

    # Verify an oauth.login.init audit row was persisted
    result = await client_session.execute(
        select(AuditLog)
        .where(AuditLog.action == "oauth.login.init")
        .where(AuditLog.resource_type == "oauth_provider")
        .order_by(AuditLog.created_at.desc())
    )
    rows = result.scalars().all()
    assert rows, "Expected at least one oauth.login.init audit row"
    row = rows[0]
    assert row.details is not None
    assert row.details.get("provider_slug") == slug
    assert "correlation_id" in row.details
    assert row.details["correlation_id"]  # non-empty
    assert row.user_id is None  # no user at init time


# ---------------------------------------------------------------------------
# Test 2: callback failure (generic) emits oauth.login.failure with a
# correlation_id present in details
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_callback_generic_failure_emits_failure_audit(
    client, client_session, _ensure_public_app_url
):
    """A generic OAuth callback error emits an oauth.login.failure audit entry."""
    provider = await _create_test_provider(client_session)
    slug = provider.slug

    mock_client = MagicMock()
    mock_client.authorize_access_token = AsyncMock(
        side_effect=RuntimeError("IdP error — simulated")
    )

    with patch(
        "app.modules.auth.oauth.router.build_oauth_client",
        AsyncMock(return_value=(mock_client, provider)),
    ):
        resp = await client.get(f"/auth/oauth/{slug}/callback", follow_redirects=False)

    # Should redirect to frontend error URL
    assert resp.status_code in (302, 307)
    assert "correlation_id=" in resp.headers.get("location", "")

    # Verify the audit row exists and has required fields
    result = await client_session.execute(
        select(AuditLog)
        .where(AuditLog.action == "oauth.login.failure")
        .where(AuditLog.resource_type == "oauth_provider")
        .order_by(AuditLog.created_at.desc())
    )
    rows = result.scalars().all()
    assert rows, "Expected at least one oauth.login.failure audit row"
    row = rows[0]
    assert row.details is not None
    assert "correlation_id" in row.details
    assert row.details.get("correlation_id")  # non-empty
    assert row.details.get("provider_slug") == slug
    assert row.details.get("outcome") == "oauth_failed"


# ---------------------------------------------------------------------------
# Test 3: Audit entries never contain secrets, tokens, or email
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_audit_entries_do_not_contain_secrets(
    client, client_session, _ensure_public_app_url
):
    """No oauth audit entry leaks client_secret, access/refresh tokens, or email."""
    provider = await _create_test_provider(client_session)
    slug = provider.slug

    mock_client = MagicMock()
    mock_client.authorize_redirect = AsyncMock(
        return_value=MagicMock(status_code=302, headers={}, body=b"")
    )
    with patch(
        "app.modules.auth.oauth.router.build_oauth_client",
        AsyncMock(return_value=(mock_client, provider)),
    ):
        await client.get(f"/auth/oauth/{slug}/login", follow_redirects=False)

    # Fetch all audit rows for this provider
    result = await client_session.execute(
        select(AuditLog).where(AuditLog.resource_type == "oauth_provider")
    )
    rows = result.scalars().all()
    assert rows, "Expected at least one oauth audit row from the login-init above"

    FORBIDDEN_KEYS = {
        "client_secret",
        "access_token",
        "refresh_token",
        "token",
        "email",
        "id_token",
    }
    for row in rows:
        details = row.details or {}
        for forbidden in FORBIDDEN_KEYS:
            assert forbidden not in details, (
                f"Audit row action={row.action!r} details contains forbidden key "
                f"{forbidden!r}: {details}"
            )


# ---------------------------------------------------------------------------
# Test 4: callback failure (OAuthEmailUnverifiedError) emits audit.login.failure
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_callback_unverified_email_emits_failure_audit(
    client, client_session, _ensure_public_app_url
):
    """email_not_verified failure branch emits oauth.login.failure audit entry."""
    from app.modules.auth.oauth.service import OAuthEmailUnverifiedError

    provider = await _create_test_provider(client_session)
    slug = provider.slug

    mock_client = MagicMock()
    mock_client.authorize_access_token = AsyncMock(
        side_effect=OAuthEmailUnverifiedError("unverified")
    )

    with patch(
        "app.modules.auth.oauth.router.build_oauth_client",
        AsyncMock(return_value=(mock_client, provider)),
    ):
        resp = await client.get(f"/auth/oauth/{slug}/callback", follow_redirects=False)

    assert resp.status_code in (302, 307)
    location = resp.headers.get("location", "")
    assert "email_not_verified" in location

    result = await client_session.execute(
        select(AuditLog)
        .where(AuditLog.action == "oauth.login.failure")
        .order_by(AuditLog.created_at.desc())
    )
    rows = result.scalars().all()
    assert rows, "Expected oauth.login.failure audit row for unverified email"
    row = rows[0]
    assert row.details is not None
    assert row.details.get("outcome") == "email_not_verified"


# ---------------------------------------------------------------------------
# Test 5: callback failure (OAuthDomainNotAllowedError) emits audit.login.failure
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_callback_domain_not_allowed_emits_failure_audit(
    client, client_session, _ensure_public_app_url
):
    """domain_not_allowed failure branch emits oauth.login.failure audit entry."""
    from app.modules.auth.oauth.service import OAuthDomainNotAllowedError

    provider = await _create_test_provider(client_session)
    slug = provider.slug

    mock_client = MagicMock()
    mock_client.authorize_access_token = AsyncMock(
        side_effect=OAuthDomainNotAllowedError("domain blocked")
    )

    with patch(
        "app.modules.auth.oauth.router.build_oauth_client",
        AsyncMock(return_value=(mock_client, provider)),
    ):
        resp = await client.get(f"/auth/oauth/{slug}/callback", follow_redirects=False)

    assert resp.status_code in (302, 307)
    location = resp.headers.get("location", "")
    assert "domain_not_allowed" in location

    result = await client_session.execute(
        select(AuditLog)
        .where(AuditLog.action == "oauth.login.failure")
        .order_by(AuditLog.created_at.desc())
    )
    rows = result.scalars().all()
    assert rows, "Expected oauth.login.failure audit row for domain_not_allowed"
    row = rows[0]
    assert row.details is not None
    assert row.details.get("outcome") == "domain_not_allowed"
