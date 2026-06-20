"""Tests for the GitHub OAuth2 provider (SSO-05, Phase 1237 Plan 01).

Three test groups:
  1. POST /settings/oauth-providers/ with provider_type='github' auto-populates
     GitHub's fixed endpoints and a read:user/user:email scope (success criterion 1).
  2. _resolve_github_identity selects ONLY the primary+verified email from /user/emails
     and raises when none exists (T-1237-01 ASVS account-takeover guard, criterion 2).
  3. Disallowed-domain GitHub email is rejected by find_or_create_oauth_user (Phase 1236
     reuse); allowed-domain GitHub email JIT-provisions a new user (criterion 4).

Run with:
    cd backend && set -a && source ../.env.test && set +a &&
    uv run pytest tests/test_oauth_github_provider.py -x -q
"""

import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.auth.oauth.encryption import encrypt_secret
from app.modules.auth.oauth.models import OAuthProvider
from app.modules.auth.oauth.service import (
    GITHUB_AUTHORIZE_URL,
    GITHUB_DEFAULT_SCOPE,
    GITHUB_TOKEN_URL,
    GITHUB_USERINFO_URL,
    OAuthDomainNotAllowedError,
    _resolve_github_identity,
    find_or_create_oauth_user,
)


# ---------------------------------------------------------------------------
# Group 1: Provider-create auto-populate
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestGithubProviderCreate:
    """POST /settings/oauth-providers/ with provider_type='github' auto-populates
    GitHub's three fixed endpoints and a native GitHub scope."""

    async def test_create_github_provider_201(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
    ) -> None:
        """POST with provider_type='github' returns 201 with auto-populated endpoints."""
        slug = f"gh-{uuid.uuid4().hex[:8]}"
        resp = await client.post(
            "/settings/oauth-providers/",
            json={
                "slug": slug,
                "display_name": "GitHub",
                "provider_type": "github",
                "client_id": "gh-client-id-test",
                "client_secret": "gh-client-secret-test",
                # Intentionally omit authorize_url, token_url, userinfo_url, scopes
                # so that auto-populate fills them in.
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, (
            f"Expected 201, got {resp.status_code}: {resp.text}"
        )
        data = resp.json()
        assert data["provider_type"] == "github"
        assert data["authorize_url"] == GITHUB_AUTHORIZE_URL
        assert data["token_url"] == GITHUB_TOKEN_URL
        assert data["userinfo_url"] == GITHUB_USERINFO_URL
        # Scope must include both read:user and user:email
        assert "read:user" in data["scopes"]
        assert "user:email" in data["scopes"]

    async def test_create_github_provider_explicit_scope_preserved(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
    ) -> None:
        """Admin-supplied scopes are NOT clobbered by the github auto-populate."""
        slug = f"gh-custom-{uuid.uuid4().hex[:8]}"
        custom_scope = "read:user user:email read:org"
        resp = await client.post(
            "/settings/oauth-providers/",
            json={
                "slug": slug,
                "display_name": "GitHub Custom Scope",
                "provider_type": "github",
                "client_id": "gh-client-id-custom",
                "client_secret": "gh-client-secret-custom",
                "scopes": custom_scope,
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, (
            f"Expected 201, got {resp.status_code}: {resp.text}"
        )
        data = resp.json()
        # The admin's custom scope must be preserved exactly.
        assert data["scopes"] == custom_scope

    async def test_create_github_provider_explicit_authorize_url_preserved(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
    ) -> None:
        """Admin-supplied authorize_url is NOT clobbered by the github auto-populate."""
        slug = f"gh-custom-url-{uuid.uuid4().hex[:8]}"
        custom_url = "https://github.example.com/login/oauth/authorize"
        resp = await client.post(
            "/settings/oauth-providers/",
            json={
                "slug": slug,
                "display_name": "GitHub Enterprise",
                "provider_type": "github",
                "client_id": "gh-ghe-client-id",
                "client_secret": "gh-ghe-client-secret",
                "authorize_url": custom_url,
                "token_url": "https://github.example.com/login/oauth/access_token",
                "userinfo_url": "https://api.github.example.com/user",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, (
            f"Expected 201, got {resp.status_code}: {resp.text}"
        )
        data = resp.json()
        assert data["authorize_url"] == custom_url


# ---------------------------------------------------------------------------
# Group 2: _resolve_github_identity — email resolution + security guard
# ---------------------------------------------------------------------------


def _make_fake_httpx_response(json_data: Any, status_code: int = 200):
    """Build a minimal mock response with .json() and a no-op .raise_for_status()."""
    from unittest.mock import MagicMock

    resp = MagicMock()
    resp.status_code = status_code
    resp.json = MagicMock(return_value=json_data)
    resp.raise_for_status = MagicMock()  # no-op for 200 responses
    return resp


@pytest.mark.anyio
class TestResolveGithubIdentity:
    """Unit tests for _resolve_github_identity via mocked httpx calls.

    These tests do NOT hit the real GitHub API — httpx.AsyncClient is patched.
    """

    _USER_PAYLOAD = {
        "id": 12345678,
        "login": "octocat",
        "name": "The Octocat",
        "email": None,  # private — typical GitHub user
    }

    _EMAIL_PRIMARY_VERIFIED = {
        "email": "octocat@github.com",
        "primary": True,
        "verified": True,
    }
    _EMAIL_VERIFIED_NOT_PRIMARY = {
        "email": "other@work.com",
        "primary": False,
        "verified": True,
    }
    _EMAIL_PRIMARY_NOT_VERIFIED = {
        "email": "unverified@home.net",
        "primary": True,
        "verified": False,
    }

    def _mock_client(self, user_json: Any, emails_json: Any):
        """Return a context-manager-compatible async mock for httpx.AsyncClient."""
        mock_client = AsyncMock()
        user_resp = _make_fake_httpx_response(user_json)
        emails_resp = _make_fake_httpx_response(emails_json)
        mock_client.get = AsyncMock(side_effect=[user_resp, emails_resp])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        return mock_client

    async def test_selects_primary_and_verified_email(self) -> None:
        """Returns the entry that is BOTH primary=True AND verified=True."""
        emails = [
            self._EMAIL_VERIFIED_NOT_PRIMARY,
            self._EMAIL_PRIMARY_NOT_VERIFIED,
            self._EMAIL_PRIMARY_VERIFIED,  # the correct one
        ]
        token = {"access_token": "ghs_test_token"}
        mock = self._mock_client(self._USER_PAYLOAD, emails)

        with patch(
            "app.modules.auth.oauth.service.httpx.AsyncClient", return_value=mock
        ):
            result = await _resolve_github_identity(token)

        assert result["email"] == "octocat@github.com"
        assert result["sub"] == "12345678"
        assert result["name"] == "The Octocat"
        assert result["email_verified"] is True

    async def test_ignores_verified_but_not_primary(self) -> None:
        """An email that is verified-but-not-primary is NEVER selected."""
        # Only decoy entries — no primary+verified combo.
        emails = [
            self._EMAIL_VERIFIED_NOT_PRIMARY,
        ]
        token = {"access_token": "ghs_test_token"}
        mock = self._mock_client(self._USER_PAYLOAD, emails)

        with patch(
            "app.modules.auth.oauth.service.httpx.AsyncClient", return_value=mock
        ):
            with pytest.raises(ValueError, match=r"no primary\+verified email"):
                await _resolve_github_identity(token)

    async def test_ignores_primary_but_not_verified(self) -> None:
        """An email that is primary-but-not-verified is NEVER selected."""
        emails = [
            self._EMAIL_PRIMARY_NOT_VERIFIED,
        ]
        token = {"access_token": "ghs_test_token"}
        mock = self._mock_client(self._USER_PAYLOAD, emails)

        with patch(
            "app.modules.auth.oauth.service.httpx.AsyncClient", return_value=mock
        ):
            with pytest.raises(ValueError, match=r"no primary\+verified email"):
                await _resolve_github_identity(token)

    async def test_raises_when_no_primary_verified_email(self) -> None:
        """Raises ValueError when /user/emails has no primary+verified entry."""
        emails: list = []
        token = {"access_token": "ghs_test_token"}
        mock = self._mock_client(self._USER_PAYLOAD, emails)

        with patch(
            "app.modules.auth.oauth.service.httpx.AsyncClient", return_value=mock
        ):
            with pytest.raises(ValueError, match=r"no primary\+verified email"):
                await _resolve_github_identity(token)

    async def test_falls_back_to_login_when_name_is_none(self) -> None:
        """When the GitHub user has no name, the login is used as the display name."""
        user_no_name = {**self._USER_PAYLOAD, "name": None}
        emails = [self._EMAIL_PRIMARY_VERIFIED]
        token = {"access_token": "ghs_test_token"}
        mock = self._mock_client(user_no_name, emails)

        with patch(
            "app.modules.auth.oauth.service.httpx.AsyncClient", return_value=mock
        ):
            result = await _resolve_github_identity(token)

        assert result["name"] == "octocat"  # login fallback

    async def test_raises_when_access_token_missing(self) -> None:
        """Raises ValueError immediately when access_token is absent from token dict."""
        with pytest.raises(ValueError, match="missing access_token"):
            await _resolve_github_identity({})


# ---------------------------------------------------------------------------
# Group 3: Disallowed-domain rejection + allowed-domain JIT provisioning
# ---------------------------------------------------------------------------

_ALLOWED_DOMAIN = "allowed-gh.example.com"
_DISALLOWED_DOMAIN = "evil-gh.example.net"
_ALLOWLIST = [_ALLOWED_DOMAIN]


async def _set_allowed_domains(
    client: AsyncClient, header: dict, domains: list[str]
) -> None:
    resp = await client.put(
        "/settings/",
        json={"settings": {"allowed_email_domains": domains}},
        headers=header,
    )
    assert resp.status_code == 200, f"Failed to set allowed_email_domains: {resp.text}"


async def _clear_allowed_domains(client: AsyncClient, header: dict) -> None:
    await _set_allowed_domains(client, header, [])


@pytest.mark.anyio
class TestGithubDomainEnforcement:
    """Proves Phase 1236 domain enforcement applies to GitHub JIT provisioning.

    The normalized GitHub userinfo dict feeds the EXISTING find_or_create_oauth_user,
    which runs the is_email_allowed check before any provisioning — so disallowed-domain
    GitHub emails are rejected and no user is created (T-1237-02).
    """

    async def _make_github_provider(self, db: AsyncSession) -> OAuthProvider:
        """Insert a minimal github-typed OAuthProvider for tests."""
        provider = OAuthProvider(
            slug=f"test-github-{uuid.uuid4().hex[:8]}",
            display_name="Test GitHub",
            provider_type="github",
            client_id="gh-test-client-id",
            client_secret_encrypted=encrypt_secret("gh-test-secret"),
            authorize_url=GITHUB_AUTHORIZE_URL,
            token_url=GITHUB_TOKEN_URL,
            userinfo_url=GITHUB_USERINFO_URL,
            scopes=GITHUB_DEFAULT_SCOPE,
            default_role="viewer",
            enabled=True,
        )
        db.add(provider)
        await db.flush()
        await db.refresh(provider)
        return provider

    async def _user_count(self, db: AsyncSession) -> int:
        result = await db.execute(select(func.count()).select_from(User))
        return result.scalar_one()

    async def test_disallowed_domain_raises_no_user_created(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ) -> None:
        """A GitHub email at a disallowed domain raises OAuthDomainNotAllowedError
        and no user is provisioned (T-1237-02, DOMAIN-03 reuse)."""
        await _set_allowed_domains(client, admin_auth_header, _ALLOWLIST)
        try:
            provider = await self._make_github_provider(test_db_session)
            before_count = await self._user_count(test_db_session)

            # Build the normalized userinfo dict as _resolve_github_identity would.
            userinfo = {
                "sub": f"gh-disallowed-{uuid.uuid4().hex[:8]}",
                "email": f"user@{_DISALLOWED_DOMAIN}",
                "name": "Attacker",
                "email_verified": True,
            }

            with pytest.raises(OAuthDomainNotAllowedError):
                await find_or_create_oauth_user(test_db_session, provider, userinfo, {})

            after_count = await self._user_count(test_db_session)
            assert after_count == before_count, (
                f"User count changed despite domain not being allowed: "
                f"{before_count} → {after_count}"
            )
        finally:
            await _clear_allowed_domains(client, admin_auth_header)

    async def test_allowed_domain_jit_provisions_user(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ) -> None:
        """A GitHub email at an allowed domain JIT-provisions a new user."""
        await _set_allowed_domains(client, admin_auth_header, _ALLOWLIST)
        try:
            provider = await self._make_github_provider(test_db_session)
            before_count = await self._user_count(test_db_session)

            unique_sub = f"gh-allowed-{uuid.uuid4().hex[:8]}"
            userinfo = {
                "sub": unique_sub,
                "email": f"developer-{unique_sub}@{_ALLOWED_DOMAIN}",
                "name": "Allowed Dev",
                "email_verified": True,
            }

            user = await find_or_create_oauth_user(
                test_db_session, provider, userinfo, {}
            )
            assert user is not None
            after_count = await self._user_count(test_db_session)
            assert after_count == before_count + 1, (
                "New user should have been provisioned for allowed domain"
            )
            assert user.email == userinfo["email"]
            assert user.auth_provider == "oauth"
        finally:
            await _clear_allowed_domains(client, admin_auth_header)
