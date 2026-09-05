"""Security regression tests for OAuth endpoint and credential binding."""

import ssl
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
from app.platform import security
from app.platform.config_ops.exceptions import ConfigValidationError
from app.platform.config_ops.service import _apply_oauth_providers
from app.platform.security import SSRFError, _SSRFGuardTransport


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


DISCOVERY_URL = "https://idp.example.com/.well-known/openid-configuration"
TOKEN_URL = "https://idp.example.com/token"
ELSEWHERE_TOKEN_URL = "https://elsewhere.example.net/token"
# A literal address resolves without DNS, so the tests that use the real
# validator stay hermetic.
LOOPBACK_TOKEN_URL = "http://127.0.0.1:9/token"
LOOPBACK_USERINFO_URL = "http://127.0.0.1:9/userinfo"
# An unclosed bracket in the authority: urlparse refuses this outright, so
# validate_url_for_ssrf raises before reaching any of its own checks.
MALFORMED_TOKEN_URL = "http://[invalid/token"
CALLBACK_URL = "https://app.example.com/callback"
ISSUER = "https://idp.example.com"
DISCOVERY_DOCUMENT = {
    "issuer": "https://idp.example.com",
    "authorization_endpoint": "https://idp.example.com/authorize",
    "token_endpoint": TOKEN_URL,
    "userinfo_endpoint": "https://idp.example.com/userinfo",
    "jwks_uri": "https://idp.example.com/jwks",
}


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
async def test_merge_import_applies_null_endpoint_clears(
    test_db_session: AsyncSession,
) -> None:
    provider = await _make_oidc_provider(test_db_session)
    discovery_url = "https://idp.example.com/.well-known/openid-configuration"

    counts = await _apply_oauth_providers(
        test_db_session,
        [
            {
                "slug": provider.slug,
                "display_name": None,
                "client_secret": "replacement-secret",
                "discovery_url": discovery_url,
                "authorize_url": None,
                "token_url": None,
                "userinfo_url": None,
            }
        ],
        "merge",
    )

    assert counts == (0, 1, 0, 0)
    assert provider.display_name == "Destination Security"
    assert provider.discovery_url == discovery_url
    assert provider.authorize_url is None
    assert provider.token_url is None
    assert provider.userinfo_url is None
    assert decrypt_secret(provider.client_secret_encrypted) == "replacement-secret"


@pytest.mark.anyio
async def test_merge_import_mode_switch_requires_secret_rotation(
    test_db_session: AsyncSession,
) -> None:
    provider = await _make_oidc_provider(test_db_session)

    with pytest.raises(ConfigValidationError, match="client_secret"):
        await _apply_oauth_providers(
            test_db_session,
            [
                {
                    "slug": provider.slug,
                    "discovery_url": (
                        "https://idp.example.com/.well-known/openid-configuration"
                    ),
                    "authorize_url": None,
                    "token_url": None,
                    "userinfo_url": None,
                }
            ],
            "merge",
        )

    assert provider.discovery_url is None
    assert provider.authorize_url == "https://idp.example.com/authorize"
    assert provider.token_url == "https://idp.example.com/token"
    assert provider.userinfo_url == "https://idp.example.com/userinfo"


@pytest.mark.anyio
async def test_merge_import_clears_discovery_for_explicit_mode(
    test_db_session: AsyncSession,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    provider = await create_provider(
        test_db_session,
        OAuthProviderCreate(
            slug=f"discovery-{suffix}",
            display_name="Discovery Provider",
            provider_type="oidc",
            client_id=f"client-{suffix}",
            client_secret="original-secret",
            discovery_url="https://idp.example.com/.well-known/openid-configuration",
        ),
    )

    counts = await _apply_oauth_providers(
        test_db_session,
        [
            {
                "slug": provider.slug,
                "client_secret": "replacement-secret",
                "discovery_url": None,
                "authorize_url": "https://idp.example.com/authorize",
                "token_url": "https://idp.example.com/token",
                "userinfo_url": "https://idp.example.com/userinfo",
            }
        ],
        "merge",
    )

    assert counts == (0, 1, 0, 0)
    assert provider.discovery_url is None
    assert provider.authorize_url == "https://idp.example.com/authorize"
    assert provider.token_url == "https://idp.example.com/token"
    assert provider.userinfo_url == "https://idp.example.com/userinfo"
    assert decrypt_secret(provider.client_secret_encrypted) == "replacement-secret"


@pytest.mark.anyio
async def test_runtime_validation_checks_all_server_endpoints(
    test_db_session: AsyncSession,
) -> None:
    provider = await _make_oidc_provider(test_db_session)

    with patch(
        "app.platform.security.validate_url_for_ssrf",
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
    """Both client hooks, not just the one discovery uses.

    fix(#1861): ``_get_session`` serves discovery and JWKS;
    ``_get_oauth_client`` serves the token exchange and the userinfo fetch,
    which are the two requests carrying the client secret and the access
    token. Before this fix only the first hook was covered, and the assertion
    below called only that hook, so the gap was invisible here.
    """
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
            "app.platform.security.make_safe_transport",
            side_effect=make_transport,
        ),
    ):
        oauth_client, _ = await build_oauth_client(provider.slug, test_db_session)
        sessions = [
            oauth_client._get_session(),
            oauth_client._get_session(),
            oauth_client._get_oauth_client(),
            oauth_client._get_oauth_client(token_endpoint=TOKEN_URL),
        ]
        for session in sessions:
            await session.aclose()

    assert len(transports) == 4
    assert len(set(id(transport) for transport in transports)) == 4


async def _client_for(db: AsyncSession, provider) -> tuple:
    """Build the router's authlib client with the row-level check stubbed out.

    The stored endpoints are the subject of the tests above; these ones are
    about what happens after that check has passed.
    """
    from app.modules.auth.oauth.router import build_oauth_client

    with patch(
        "app.modules.auth.oauth.router.validate_provider_server_endpoints",
        new=AsyncMock(),
    ):
        return await build_oauth_client(provider.slug, db)


async def _make_discovery_provider(db: AsyncSession):
    suffix = uuid.uuid4().hex[:8]
    return await create_provider(
        db,
        OAuthProviderCreate(
            slug=f"discovery-{suffix}",
            display_name="Discovery Security",
            provider_type="oidc",
            client_id=f"client-{suffix}",
            client_secret=uuid.uuid4().hex,
            discovery_url=DISCOVERY_URL,
        ),
    )


@pytest.fixture
def authlib_transport(monkeypatch):
    """Answer every authlib request from a mock transport the factory returns.

    Patching ``make_safe_transport`` rather than reaching into the client keeps
    the client under test the one the router actually builds: a hook that
    stopped calling the factory would get a real transport, nothing here would
    answer it, and the test would fail rather than pass quietly.
    """

    def install(handler) -> list[httpx.Request]:
        recorded: list[httpx.Request] = []

        def handle(request: httpx.Request) -> httpx.Response:
            recorded.append(request)
            return handler(request)

        monkeypatch.setattr(
            security, "make_safe_transport", lambda: httpx.MockTransport(handle)
        )
        return recorded

    return install


@pytest.mark.anyio
async def test_token_exchange_refuses_a_private_address(
    test_db_session: AsyncSession,
) -> None:
    """The finding: this request carries the client secret.

    The endpoint validators are stubbed out so the refusal can only come from
    the transport the client dialled with, which is the half that survives a
    DNS answer changing between validation and connect.
    """
    provider = await _make_oidc_provider(test_db_session)
    await test_db_session.commit()
    client, _ = await _client_for(test_db_session, provider)
    client.access_token_url = LOOPBACK_TOKEN_URL

    with (
        patch("app.platform.security.validate_url_for_ssrf", new=AsyncMock()),
        pytest.raises(SSRFError) as raised,
    ):
        await client.fetch_access_token(
            code=uuid.uuid4().hex, redirect_uri="https://app.example.com/callback"
        )

    assert "private/internal networks" in str(raised.value)


@pytest.mark.anyio
async def test_userinfo_fetch_refuses_a_private_address(
    test_db_session: AsyncSession,
) -> None:
    """The same finding for the request that carries the access token."""
    provider = await _make_oidc_provider(test_db_session)
    await test_db_session.commit()
    client, _ = await _client_for(test_db_session, provider)
    client.server_metadata["userinfo_endpoint"] = LOOPBACK_USERINFO_URL

    with (
        patch("app.platform.security.validate_url_for_ssrf", new=AsyncMock()),
        pytest.raises(SSRFError) as raised,
    ):
        await client.userinfo(
            token={"access_token": uuid.uuid4().hex, "token_type": "Bearer"}
        )

    assert "private/internal networks" in str(raised.value)


@pytest.mark.anyio
async def test_every_discovered_endpoint_is_ssrf_validated(
    test_db_session: AsyncSession, authlib_transport
) -> None:
    """The four endpoints authlib reads out of the document and then fetches.

    None of them is on the provider row, so ``validate_provider_server_
    endpoints`` never sees the address any request actually goes to.
    """
    provider = await _make_discovery_provider(test_db_session)
    await test_db_session.commit()
    authlib_transport(lambda _request: httpx.Response(200, json=DISCOVERY_DOCUMENT))
    client, _ = await _client_for(test_db_session, provider)

    with patch(
        "app.platform.security.validate_url_for_ssrf", new=AsyncMock()
    ) as validate:
        await client.load_server_metadata()

    assert {call.args[0] for call in validate.await_args_list} == {
        DISCOVERY_DOCUMENT["authorization_endpoint"],
        DISCOVERY_DOCUMENT["token_endpoint"],
        DISCOVERY_DOCUMENT["userinfo_endpoint"],
        DISCOVERY_DOCUMENT["jwks_uri"],
    }


async def _discovery_refusal(
    db: AsyncSession, authlib_transport, token_endpoint: str
) -> tuple:
    """Drive one login against a document naming *token_endpoint*.

    Returns the refusal, the warning the operator log received, and every
    request the client actually made. The real validator runs: both addresses
    used here are literals that need no DNS, so these assert the shipped policy
    rather than a stand-in for it.
    """
    from app.modules.auth.oauth import router as router_module

    provider = await _make_discovery_provider(db)
    await db.commit()
    recorded = authlib_transport(
        lambda _request: httpx.Response(
            200, json={"issuer": ISSUER, "token_endpoint": token_endpoint}
        )
    )
    client, _ = await _client_for(db, provider)

    with (
        patch.object(router_module, "logger") as logger,
        pytest.raises(HTTPException) as exc_info,
    ):
        await client.fetch_access_token(
            code=uuid.uuid4().hex, redirect_uri=CALLBACK_URL
        )

    return exc_info.value, logger.warning.call_args, recorded


@pytest.mark.anyio
async def test_a_private_discovered_token_endpoint_refuses_the_login(
    test_db_session: AsyncSession, authlib_transport
) -> None:
    """A refusal before the exchange, so the client secret is never sent."""
    refusal, warning, recorded = await _discovery_refusal(
        test_db_session, authlib_transport, LOOPBACK_TOKEN_URL
    )

    assert refusal.status_code == 503
    # The route is unauthenticated, so the refusal names no address.
    assert "127.0.0.1" not in refusal.detail
    # Only the discovery document was fetched; nothing was posted to the
    # endpoint the document named.
    assert [str(request.url) for request in recorded] == [DISCOVERY_URL]
    assert warning.args == ("OAuth provider endpoint rejected",)
    assert warning.kwargs["endpoint"] == "token_endpoint"
    assert warning.kwargs["host"] == "127.0.0.1"


@pytest.mark.anyio
async def test_a_malformed_discovered_endpoint_refuses_without_reparsing(
    test_db_session: AsyncSession, authlib_transport
) -> None:
    """fix(#1861 codex r1): the refusal path itself must not raise.

    urlparse rejects a malformed authority with ValueError, so
    validate_url_for_ssrf raises before reaching its own checks and the refusal
    branch receives exactly the string that will not parse. Deriving a hostname
    for the log from it a second time raised inside the handler, which turned
    the sanitized 503 into an unhandled 500 on an unauthenticated route.
    """
    refusal, warning, recorded = await _discovery_refusal(
        test_db_session, authlib_transport, MALFORMED_TOKEN_URL
    )
    private, private_warning, _ = await _discovery_refusal(
        test_db_session, authlib_transport, LOOPBACK_TOKEN_URL
    )

    assert refusal.status_code == private.status_code == 503
    assert refusal.detail == private.detail
    # Nothing of the offending URL reaches the caller.
    assert "invalid" not in refusal.detail
    assert [str(request.url) for request in recorded] == [DISCOVERY_URL]
    # The same log line as every other refusal, with the one field that cannot
    # be derived left empty rather than raised over.
    assert warning.args == private_warning.args
    assert set(warning.kwargs) == set(private_warning.kwargs)
    assert warning.kwargs["endpoint"] == "token_endpoint"
    assert warning.kwargs["host"] is None
    assert warning.kwargs["error_type"] == "ValueError"


@pytest.mark.anyio
async def test_a_discovery_document_cannot_weaken_the_client(
    test_db_session: AsyncSession,
) -> None:
    """authlib merges the document into the httpx client kwargs.

    ``_get_oauth_client`` does ``client_kwargs.update(metadata)``, so every key
    in the document is a candidate httpx client argument. A document choosing
    ``verify``, ``mounts`` or ``follow_redirects`` would be choosing the
    transport security of the request that carries the client secret.
    """
    provider = await _make_oidc_provider(test_db_session)
    await test_db_session.commit()
    client, _ = await _client_for(test_db_session, provider)

    built = client._get_oauth_client(
        token_endpoint=TOKEN_URL,
        verify=False,
        follow_redirects=True,
        max_redirects=20,
        mounts={"all://": httpx.MockTransport(lambda _r: httpx.Response(200))},
        proxy="http://elsewhere.example.net:3128",
    )
    try:
        # httpx internals, asserted directly because the claim is about the
        # client that gets dialled, not about what was passed to it. A mount
        # and a proxy both take precedence over ``transport``, so the question
        # is which transport the token endpoint resolves to.
        assert isinstance(built._transport, _SSRFGuardTransport)
        assert built._mounts == {}
        assert built._transport_for_url(httpx.URL(TOKEN_URL)) is built._transport
        assert built.follow_redirects is False
        assert built._transport._pool._ssl_context.verify_mode == ssl.CERT_REQUIRED
        assert built._transport._pool._ssl_context.check_hostname is True
    finally:
        await built.aclose()


@pytest.mark.anyio
async def test_the_token_exchange_client_does_not_follow_a_redirect(
    test_db_session: AsyncSession, authlib_transport
) -> None:
    """No hop, so nothing the exchange sends can reach the origin a 302 names.

    httpx drops ``Authorization`` across an origin change by itself, but under
    ``client_secret_post`` the secret travels in the request body and a 307
    repeats that body. Not following at all is what makes the question moot,
    and it is also httpx's default: the assertion is that the default cannot be
    turned back on from outside, including by the discovery document that
    authlib merges into these very kwargs.

    The client here is the one ``fetch_access_token`` builds; the positive
    control below shows the exchange going through it.
    """
    provider = await _make_oidc_provider(test_db_session)
    await test_db_session.commit()
    recorded = authlib_transport(
        lambda _request: httpx.Response(302, headers={"Location": ELSEWHERE_TOKEN_URL})
    )
    client, _ = await _client_for(test_db_session, provider)

    built = client._get_oauth_client(token_endpoint=TOKEN_URL, follow_redirects=True)
    try:
        response = await built.request(
            "POST", TOKEN_URL, withhold_token=True, data={"code": uuid.uuid4().hex}
        )
    finally:
        await built.aclose()

    assert response.status_code == 302
    assert [request.url.host for request in recorded] == ["idp.example.com"]


@pytest.mark.anyio
async def test_a_normal_exchange_still_succeeds_through_the_safe_client(
    test_db_session: AsyncSession, authlib_transport
) -> None:
    """Positive control: the transport is pinned, not broken.

    Every request here is answered by a transport the factory produced, so a
    hook that skipped the factory would reach the network instead and fail.
    """
    provider = await _make_discovery_provider(test_db_session)
    await test_db_session.commit()
    issued = uuid.uuid4().hex

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("openid-configuration"):
            return httpx.Response(200, json=DISCOVERY_DOCUMENT)
        return httpx.Response(
            200,
            json={"access_token": issued, "token_type": "Bearer", "expires_in": 3600},
        )

    recorded = authlib_transport(handle)
    client, _ = await _client_for(test_db_session, provider)

    with patch("app.platform.security.validate_url_for_ssrf", new=AsyncMock()):
        token = await client.fetch_access_token(
            code=uuid.uuid4().hex, redirect_uri="https://app.example.com/callback"
        )

    assert token["access_token"] == issued
    assert [str(request.url) for request in recorded] == [
        DISCOVERY_URL,
        DISCOVERY_DOCUMENT["token_endpoint"],
    ]


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
