"""Security regression tests for OAuth endpoint and credential binding."""

import uuid
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.oauth.encryption import decrypt_secret
from app.modules.auth.oauth.schemas import OAuthProviderCreate, OAuthProviderUpdate
from app.modules.auth.oauth.service import (
    GITHUB_AUTHORIZE_URL,
    GITHUB_TOKEN_URL,
    GITHUB_USERINFO_URL,
    OAuthCredentialDestinationError,
    OAuthProviderConfigurationError,
    create_provider,
    update_provider,
    validate_provider_server_endpoints,
)
from app.platform.config_ops.exceptions import ConfigValidationError
from app.platform.config_ops.service import _apply_oauth_providers


async def _make_oidc_provider(db: AsyncSession, *, host: str = "idp.example.com"):
    suffix = uuid.uuid4().hex[:8]
    return await create_provider(
        db,
        OAuthProviderCreate(
            slug=f"destination-{suffix}",
            display_name="Destination Security",
            provider_type="oidc",
            client_id=f"client-{suffix}",
            client_secret="original-secret",
            authorize_url=f"https://{host}/authorize",
            token_url=f"https://{host}/token",
            userinfo_url=f"https://{host}/userinfo",
        ),
    )


@pytest.mark.anyio
async def test_destination_origin_change_requires_secret_rotation(
    test_db_session: AsyncSession,
) -> None:
    provider = await _make_oidc_provider(test_db_session)
    encrypted_before = provider.client_secret_encrypted

    with pytest.raises(OAuthCredentialDestinationError, match="client_secret"):
        await update_provider(
            test_db_session,
            provider,
            OAuthProviderUpdate(token_url="https://attacker.example.net/token"),
        )

    assert provider.token_url == "https://idp.example.com/token"
    assert provider.client_secret_encrypted == encrypted_before


@pytest.mark.anyio
async def test_same_origin_path_change_retains_existing_secret(
    test_db_session: AsyncSession,
) -> None:
    provider = await _make_oidc_provider(test_db_session)
    encrypted_before = provider.client_secret_encrypted

    updated = await update_provider(
        test_db_session,
        provider,
        OAuthProviderUpdate(
            token_url="https://idp.example.com/oauth/v2/token",
            userinfo_url="https://idp.example.com/oauth/v2/userinfo",
        ),
    )

    assert updated.token_url.endswith("/oauth/v2/token")
    assert updated.client_secret_encrypted == encrypted_before


@pytest.mark.anyio
async def test_destination_change_with_new_secret_rebinds_credential(
    test_db_session: AsyncSession,
) -> None:
    provider = await _make_oidc_provider(test_db_session)

    updated = await update_provider(
        test_db_session,
        provider,
        OAuthProviderUpdate(
            token_url="https://replacement.example.net/token",
            userinfo_url="https://replacement.example.net/userinfo",
            client_secret="replacement-secret",
        ),
    )

    assert updated.token_url == "https://replacement.example.net/token"
    assert decrypt_secret(updated.client_secret_encrypted) == "replacement-secret"


@pytest.mark.anyio
async def test_authorization_origin_alone_is_not_a_credential_destination(
    test_db_session: AsyncSession,
) -> None:
    provider = await _make_oidc_provider(test_db_session)

    updated = await update_provider(
        test_db_session,
        provider,
        OAuthProviderUpdate(authorize_url="https://login.example.net/authorize"),
    )

    assert updated.authorize_url == "https://login.example.net/authorize"
    assert decrypt_secret(updated.client_secret_encrypted) == "original-secret"


@pytest.mark.anyio
async def test_discovery_authority_change_requires_secret_rotation(
    test_db_session: AsyncSession,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    provider = await create_provider(
        test_db_session,
        OAuthProviderCreate(
            slug=f"discovery-{suffix}",
            display_name="Discovery Security",
            provider_type="oidc",
            client_id=f"client-{suffix}",
            client_secret="original-secret",
            discovery_url="https://idp.example.com/.well-known/openid-configuration",
        ),
    )

    with pytest.raises(OAuthCredentialDestinationError, match="client_secret"):
        await update_provider(
            test_db_session,
            provider,
            OAuthProviderUpdate(
                discovery_url="https://other.example.net/.well-known/openid-configuration"
            ),
        )

    # A different metadata path on the same authority remains compatible.
    updated = await update_provider(
        test_db_session,
        provider,
        OAuthProviderUpdate(
            discovery_url="https://idp.example.com/tenant/.well-known/openid-configuration"
        ),
    )
    assert "/tenant/" in updated.discovery_url


@pytest.mark.anyio
async def test_discovery_provider_cannot_rebind_token_via_github_transition(
    test_db_session: AsyncSession,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    provider = await create_provider(
        test_db_session,
        OAuthProviderCreate(
            slug=f"transition-{suffix}",
            display_name="Transition Security",
            provider_type="oidc",
            client_id=f"client-{suffix}",
            client_secret="original-secret",
            discovery_url="https://idp.example.com/.well-known/openid-configuration",
        ),
    )

    update = OAuthProviderUpdate(
        provider_type="github",
        authorize_url="https://capture.example.net/authorize",
        token_url="https://capture.example.net/token",
        userinfo_url="https://capture.example.net/userinfo",
    )
    with pytest.raises(OAuthProviderConfigurationError, match="discovery"):
        await update_provider(test_db_session, provider, update)

    assert provider.provider_type == "oidc"
    assert provider.userinfo_url is None


@pytest.mark.anyio
async def test_provider_type_change_with_explicit_mode_requires_new_secret(
    test_db_session: AsyncSession,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    provider = await create_provider(
        test_db_session,
        OAuthProviderCreate(
            slug=f"transition-clear-{suffix}",
            display_name="Transition Security",
            provider_type="oidc",
            client_id=f"client-{suffix}",
            client_secret="original-secret",
            discovery_url="https://idp.example.com/.well-known/openid-configuration",
        ),
    )

    with pytest.raises(OAuthCredentialDestinationError, match="client_secret"):
        await update_provider(
            test_db_session,
            provider,
            OAuthProviderUpdate(
                provider_type="github",
                discovery_url=None,
                authorize_url="https://capture.example.net/authorize",
                token_url="https://capture.example.net/token",
                userinfo_url="https://capture.example.net/userinfo",
            ),
        )

    assert provider.provider_type == "oidc"


@pytest.mark.anyio
async def test_legacy_mixed_mode_provider_can_clear_unused_endpoints(
    test_db_session: AsyncSession,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    provider = await create_provider(
        test_db_session,
        OAuthProviderCreate(
            slug=f"legacy-mixed-{suffix}",
            display_name="Legacy Mixed",
            provider_type="oidc",
            client_id=f"client-{suffix}",
            client_secret="original-secret",
            discovery_url="https://idp.example.com/.well-known/openid-configuration",
        ),
    )
    provider.authorize_url = "https://legacy.example.net/authorize"
    provider.token_url = "https://legacy.example.net/token"
    provider.userinfo_url = "https://legacy.example.net/userinfo"
    await test_db_session.flush()

    updated = await update_provider(
        test_db_session,
        provider,
        OAuthProviderUpdate(
            authorize_url=None,
            token_url=None,
            userinfo_url=None,
        ),
    )

    assert updated.discovery_url is not None
    assert updated.authorize_url is None
    assert updated.token_url is None
    assert updated.userinfo_url is None
    assert decrypt_secret(updated.client_secret_encrypted) == "original-secret"


@pytest.mark.anyio
async def test_legacy_mixed_mode_cannot_activate_explicit_endpoints_without_secret(
    test_db_session: AsyncSession,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    provider = await create_provider(
        test_db_session,
        OAuthProviderCreate(
            slug=f"legacy-activate-{suffix}",
            display_name="Legacy Activation",
            provider_type="oidc",
            client_id=f"client-{suffix}",
            client_secret="original-secret",
            discovery_url="https://idp.example.com/.well-known/openid-configuration",
        ),
    )
    provider.authorize_url = "https://capture.example.net/authorize"
    provider.token_url = "https://capture.example.net/token"
    provider.userinfo_url = "https://capture.example.net/userinfo"
    await test_db_session.flush()

    with pytest.raises(OAuthCredentialDestinationError, match="client_secret"):
        await update_provider(
            test_db_session,
            provider,
            OAuthProviderUpdate(discovery_url=None),
        )

    assert provider.discovery_url is not None


@pytest.mark.anyio
async def test_public_github_endpoints_are_pinned(
    test_db_session: AsyncSession,
) -> None:
    with pytest.raises(OAuthProviderConfigurationError, match="canonical"):
        await create_provider(
            test_db_session,
            OAuthProviderCreate(
                slug=f"github-pin-{uuid.uuid4().hex[:8]}",
                display_name="Invalid Public GitHub",
                provider_type="github",
                client_id="github-client",
                client_secret="github-secret",
                authorize_url=GITHUB_AUTHORIZE_URL,
                token_url=f"{GITHUB_TOKEN_URL}/redirect",
                userinfo_url=GITHUB_USERINFO_URL,
            ),
        )


@pytest.mark.anyio
async def test_github_enterprise_endpoints_remain_supported(
    test_db_session: AsyncSession,
) -> None:
    provider = await create_provider(
        test_db_session,
        OAuthProviderCreate(
            slug=f"github-enterprise-{uuid.uuid4().hex[:8]}",
            display_name="GitHub Enterprise",
            provider_type="github",
            client_id="ghe-client",
            client_secret="ghe-secret",
            authorize_url="https://ghe.example.com/login/oauth/authorize",
            token_url="https://ghe.example.com/login/oauth/access_token",
            userinfo_url="https://ghe.example.com/api/v3/user",
        ),
    )

    assert provider.token_url == "https://ghe.example.com/login/oauth/access_token"


@pytest.mark.anyio
async def test_literal_internal_endpoint_rejected_during_crud(
    test_db_session: AsyncSession,
) -> None:
    with pytest.raises(OAuthProviderConfigurationError, match="private/internal"):
        await create_provider(
            test_db_session,
            OAuthProviderCreate(
                slug=f"internal-{uuid.uuid4().hex[:8]}",
                display_name="Internal",
                provider_type="oidc",
                client_id="internal-client",
                client_secret="internal-secret",
                token_url="http://127.0.0.1/token",
                userinfo_url="http://127.0.0.1/userinfo",
            ),
        )


@pytest.mark.anyio
async def test_internal_endpoint_returns_validation_error_from_settings_api(
    client: AsyncClient,
    admin_auth_header: dict,
) -> None:
    response = await client.post(
        "/settings/oauth-providers/",
        headers=admin_auth_header,
        json={
            "slug": f"internal-api-{uuid.uuid4().hex[:8]}",
            "display_name": "Internal API",
            "provider_type": "oidc",
            "client_id": "internal-client",
            "client_secret": "internal-secret",
            "token_url": "http://169.254.169.254/token",
            "userinfo_url": "http://169.254.169.254/userinfo",
        },
    )

    assert response.status_code == 422
    assert "private/internal" in response.json()["detail"]


@pytest.mark.anyio
async def test_merge_import_cannot_bypass_destination_binding(
    test_db_session: AsyncSession,
) -> None:
    provider = await _make_oidc_provider(test_db_session)

    with pytest.raises(ConfigValidationError, match="client_secret"):
        await _apply_oauth_providers(
            test_db_session,
            [
                {
                    "slug": provider.slug,
                    "token_url": "https://imported.example.net/token",
                }
            ],
            "merge",
        )

    assert provider.token_url == "https://idp.example.com/token"


@pytest.mark.anyio
async def test_runtime_validation_checks_all_server_endpoints(
    test_db_session: AsyncSession,
) -> None:
    provider = await _make_oidc_provider(test_db_session)

    with patch(
        "app.modules.catalog.sources.security.validate_url_for_ssrf",
        new=AsyncMock(),
    ) as validate:
        await validate_provider_server_endpoints(provider)

    assert {call.args[0] for call in validate.await_args_list} == {
        "https://idp.example.com/authorize",
        "https://idp.example.com/token",
        "https://idp.example.com/userinfo",
    }


@pytest.mark.anyio
async def test_authlib_sessions_receive_fresh_safe_transports(
    test_db_session: AsyncSession,
) -> None:
    from app.modules.auth.oauth.router import build_oauth_client

    provider = await _make_oidc_provider(test_db_session)
    await test_db_session.commit()

    transports: list[httpx.MockTransport] = []

    def make_transport():
        transport = httpx.MockTransport(lambda _request: httpx.Response(200))
        transports.append(transport)
        return transport

    with (
        patch(
            "app.modules.auth.oauth.router.validate_provider_server_endpoints",
            new=AsyncMock(),
        ),
        patch(
            "app.modules.catalog.sources.security.make_safe_transport",
            side_effect=make_transport,
        ),
    ):
        oauth_client, _ = await build_oauth_client(provider.slug, test_db_session)
        first = oauth_client._get_session()
        second = oauth_client._get_session()
        await first.aclose()
        await second.aclose()

    assert len(transports) == 2
    assert transports[0] is not transports[1]


@pytest.mark.anyio
async def test_runtime_rejects_endpoint_before_decrypting_secret(
    test_db_session: AsyncSession,
) -> None:
    from app.modules.auth.oauth.router import build_oauth_client

    provider = await _make_oidc_provider(test_db_session)
    await test_db_session.commit()

    with (
        patch(
            "app.modules.auth.oauth.router.validate_provider_server_endpoints",
            new=AsyncMock(side_effect=ValueError("blocked")),
        ),
        patch("app.modules.auth.oauth.router.decrypt_secret") as decrypt,
        pytest.raises(HTTPException) as exc_info,
    ):
        await build_oauth_client(provider.slug, test_db_session)

    assert exc_info.value.status_code == 503
    decrypt.assert_not_called()
