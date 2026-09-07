"""OAuth/OIDC flow endpoints: login redirect, callback, and public provider list."""

import uuid
from urllib.parse import urlparse

import structlog
from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.integrations.starlette_client import OAuth
from authlib.integrations.starlette_client.apps import StarletteOAuth2App
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.cookies import (
    api_path_is_cookie_scoped,
    is_same_origin,
    issue_browser_session,
)
from app.modules.auth.oauth.encryption import decrypt_secret
from app.modules.auth.oauth.schemas import OAuthProviderPublic
from app.modules.auth.oauth.service import (
    _resolve_github_identity,
    get_enabled_providers,
    get_provider_by_slug,
    is_azure_multitenant,
    validate_provider_server_endpoints,
    verify_azure_multitenant_issuer,
)
from app.modules.auth.providers import AuthenticatedIdentity
from app.modules.auth.service import AuthService
from app.core.dependencies import get_client_ip, get_db
from app.core.persistent_config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    REFRESH_TOKEN_EXPIRE_DAYS,
)
from app.core.public_urls import get_public_api_url, get_public_app_url
from app.platform.audit import AuditEvent, audit_emit
from app.standards.ogc.errors import ERROR_RESPONSES_AUTH

logger = structlog.stdlib.get_logger(__name__)

router = APIRouter(prefix="/auth/oauth", tags=["Auth"], responses=ERROR_RESPONSES_AUTH)


class _SSRFSafeOAuth2Client(AsyncOAuth2Client):
    """Authlib's HTTP client, with the transport decided here and not by a caller.

    fix(#1861): the app class below installed the IP-pinning transport in
    ``_get_session`` alone, which covers discovery and JWKS but NOT the token
    exchange or userinfo fetch (built via ``_get_oauth_client``) — the two
    requests carrying the client secret and access token. All four hooks
    construct ``self.client_cls``, so this is the single place that reaches
    every one of them.

    ``_get_oauth_client`` also merges the discovery document into the httpx
    client kwargs, so a document carrying a ``transport``/``mounts``/``proxy``/
    ``follow_redirects`` key would otherwise choose the transport security of
    the secret-carrying request. These are set here, AFTER that merge.
    """

    def __init__(self, *args, **kwargs):
        from app.platform.security import make_safe_transport

        kwargs["transport"] = make_safe_transport()
        # httpx consults a per-scheme mount before ``transport`` and builds
        # one from ``proxy``; both pin the transport (an empty ``mounts``
        # doesn't clear what ``proxy`` added). Passing a transport already
        # stops httpx reading env proxies, so operator proxy config is
        # unaffected.
        kwargs["mounts"] = {}
        kwargs["proxy"] = None
        # httpx's own default, pinned so it stays the default: nothing here
        # follows a redirect, so neither the client secret nor the access
        # token can cross an origin behind a 302.
        kwargs["follow_redirects"] = False
        super().__init__(*args, **kwargs)


# Endpoints authlib reads from a discovery document and then fetches:
# token_endpoint, userinfo_endpoint, jwks_uri, and authorization_endpoint
# (handed to the browser). A provider configured by discovery URL leaves the
# matching row columns empty, so validate_provider_server_endpoints never
# sees the address a request actually goes to — this list must stay matched
# to the calls that exist, or a route with no fetch gets falsely refused.
_DISCOVERY_ENDPOINT_KEYS = (
    "authorization_endpoint",
    "token_endpoint",
    "userinfo_endpoint",
    "jwks_uri",
)

_ENDPOINT_REFUSED_DETAIL = "OAuth provider endpoint is not permitted"


def _endpoint_refused(
    provider_slug: str,
    exc: Exception,
    *,
    endpoint: str | None = None,
    host: str | None = None,
) -> HTTPException:
    """Log the operator-facing detail and return the refusal for the caller to raise.

    fix(#1861): one helper for both sources (provider row and discovery
    document), so they can't drift into different status codes/disclosure.
    The response names no host — these routes are unauthenticated; the
    operator log gets the provider, endpoint, and hostname.
    """
    logger.warning(
        "OAuth provider endpoint rejected",
        provider=provider_slug,
        endpoint=endpoint,
        host=host,
        error_type=type(exc).__name__,
    )
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=_ENDPOINT_REFUSED_DETAIL,
    )


def _loggable_hostname(url: str) -> str | None:
    """The hostname for the operator log, or None when the URL will not parse.

    fix(#1861): urlparse rejects a malformed authority with
    ValueError before validate_url_for_ssrf's own checks run, so parsing it
    again here would raise inside the handler — replacing the sanitized 503
    with an unhandled 500 on an unauthenticated route. None reads as
    unparseable in the log line.
    """
    try:
        return urlparse(url).hostname
    except ValueError:
        return None


async def _validate_discovery_endpoints(
    provider_slug: str, metadata: dict[str, object]
) -> None:
    """Refuse a discovery document that aims an OAuth request at a private address."""
    from app.platform.security import validate_url_for_ssrf

    for key in _DISCOVERY_ENDPOINT_KEYS:
        url = metadata.get(key)
        if not isinstance(url, str) or not url:
            continue
        try:
            await validate_url_for_ssrf(url)
        except ValueError as exc:
            # SSRFError/SSRFResolutionError are both ValueError, matching
            # the row-level check and the plain ValueError urlparse raises.
            raise _endpoint_refused(
                provider_slug, exc, endpoint=key, host=_loggable_hostname(url)
            ) from exc


class _SSRFSafeOAuth2App(StarletteOAuth2App):
    """Every Authlib session this app builds goes through the safe transport."""

    client_cls = _SSRFSafeOAuth2Client

    # One validation per app instance; build_oauth_client builds one per
    # request. Nothing rewrites the endpoints after they're read.
    _endpoints_validated = False

    async def load_server_metadata(self) -> dict:
        """Validate the endpoints the discovery document supplies, once.

        fix(#1861): this is the policy half, deciding whether an address is
        one this deployment will talk to at all. The pinning transport on
        _SSRFSafeOAuth2Client is the enforcement half: it re-resolves at
        connect time, so a document that passes here and rebinds afterwards
        still reaches nothing internal.
        """
        metadata = await super().load_server_metadata()
        # Only a discovery document introduces an endpoint the row-level
        # check hasn't already resolved; without one, re-resolving here would
        # refuse a provider that check just passed.
        if self._server_metadata_url and not self._endpoints_validated:
            await _validate_discovery_endpoints(self.name, metadata)
            self._endpoints_validated = True
        return metadata


def _id_token_claims_options(
    provider_type: str, discovery_url: str | None
) -> dict | None:
    """id_token claim-validation overrides passed to ``authorize_access_token``.

    Azure multitenant authorities (/common/, /organizations/) publish a
    TEMPLATED issuer in their discovery document, but issued id_tokens carry
    the resolved per-tenant issuer. authlib's default pins ``iss`` by exact
    match and rejects every login; joserfc supports no callable validator, so
    for multitenant Microsoft this relaxes ``iss`` to required-but-unpinned.
    JWKS signature check and the PKCE + client_secret exchange still bind the
    token to Microsoft and this app.

    Tenant-specific Microsoft providers have a FIXED issuer authlib can and
    must pin, so they keep the default — relaxing them would drop
    cross-tenant ``iss`` isolation (geolens#303). Returns None otherwise.
    """
    if is_azure_multitenant(provider_type, discovery_url):
        return {"iss": {"essential": True}}
    return None


async def build_oauth_client(provider_slug: str, db: AsyncSession) -> tuple:
    """Build an authlib OAuth client for the given provider slug.

    Raises 404 if provider not found or not enabled.
    Returns (client, provider) tuple.
    """
    provider = await get_provider_by_slug(db, provider_slug)
    if provider is None or not provider.enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="OAuth provider not found or not enabled",
        )

    # Validate every persisted endpoint before decrypting the client secret,
    # covering legacy rows and CRUD/config-import writes. fix(#1861): covers
    # only the four row columns; a discovery-URL provider is checked in
    # _SSRFSafeOAuth2App.load_server_metadata instead. Either way every
    # Authlib session then connects through the IP-pinning transport, closing
    # the DNS-rebinding gap between check and dispatch.
    try:
        await validate_provider_server_endpoints(provider)
    except ValueError as exc:
        raise _endpoint_refused(provider_slug, exc) from exc

    client_secret = decrypt_secret(provider.client_secret_encrypted)

    oauth = OAuth()

    register_kwargs: dict = {
        "client_cls": _SSRFSafeOAuth2App,
        "client_id": provider.client_id,
        "client_secret": client_secret,
        "client_kwargs": {
            "scope": provider.scopes,
            "code_challenge_method": "S256",
        },
    }

    if provider.discovery_url:
        register_kwargs["server_metadata_url"] = provider.discovery_url
    else:
        # Generic OIDC / GitHub without discovery -- explicit URLs. GitHub's
        # token endpoint returns form-encoded unless Accept: application/json
        # is requested, hence token_endpoint_auth_method below (SSO-05).
        register_kwargs["authorize_url"] = provider.authorize_url
        register_kwargs["access_token_url"] = provider.token_url
        register_kwargs["userinfo_endpoint"] = provider.userinfo_url
        if provider.provider_type == "github":
            register_kwargs["client_kwargs"].update(
                {
                    "token_endpoint_auth_method": "client_secret_post",
                }
            )

    oauth.register(name=provider.slug, **register_kwargs)
    client = oauth.create_client(provider.slug)
    return client, provider


@router.get("/{provider_slug}/login", response_class=RedirectResponse)
async def oauth_login(
    provider_slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Redirect user to the IdP authorization URL with PKCE parameters.

    Phase 268 H-27: the redirect_uri is handed to the IdP, where an
    attacker-controlled origin (via ``X-Forwarded-Host``) would otherwise
    enable auth-code theft. We force explicit-config resolution by
    passing ``for_external_use=True``; falling back to the request-origin
    is refused.
    """
    client, _provider = await build_oauth_client(provider_slug, db)

    from app.core.public_urls import PublicUrlNotConfiguredError

    try:
        public_api_url = await get_public_api_url(
            db, request=request, for_external_use=True
        )
    except PublicUrlNotConfiguredError as exc:
        logger.error(
            "OAuth login refused: PUBLIC_APP_URL / PUBLIC_API_URL not configured",
            provider=provider_slug,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    redirect_uri = f"{public_api_url}/auth/oauth/{provider_slug}/callback"

    # HARDEN-04 (T-1238-05): generate a correlation_id at login-init so the
    # matching callback audit entry shares it, linking initiation to outcome.
    # Stored in session keyed by provider slug; authlib already uses the
    # session for PKCE `state`. Details carry only provider_slug +
    # correlation_id — no secrets, tokens, or email addresses (T-1238-06).
    correlation_id = uuid.uuid4().hex[:12]
    request.session[f"_oauth_correlation_{provider_slug}"] = correlation_id

    await audit_emit(
        db,
        AuditEvent(
            user_id=None,
            action="oauth.login.init",
            resource_type="oauth_provider",
            details={"provider_slug": provider_slug, "correlation_id": correlation_id},
            ip_address=get_client_ip(request),
        ),
    )
    try:
        await db.commit()
    except Exception:  # broad: defensive log-and-continue — an audit/rollback write must never break the OAuth redirect flow
        logger.exception(
            "Failed to commit oauth.login.init audit row; continuing",
            provider=provider_slug,
            correlation_id=correlation_id,
        )

    return await client.authorize_redirect(request, redirect_uri)


@router.get("/{provider_slug}/callback", response_class=Response)
async def oauth_callback(
    provider_slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Handle IdP callback: exchange code, find/create user, issue JWT, redirect to frontend.

    Phase 268 H-27: the frontend redirect carries access tokens in the URL
    fragment. Without explicit-config resolution, an attacker controlling
    ``X-Forwarded-Host`` could steer the post-callback redirect to
    attacker.com and capture the tokens. Force explicit-config resolution
    by passing ``for_external_use=True``.
    """
    from app.modules.auth.oauth.service import find_or_create_oauth_user
    from app.core.public_urls import PublicUrlNotConfiguredError

    # Compute frontend URL before try block (needed in except for error redirect)
    try:
        frontend_url = await get_public_app_url(
            db, request=request, for_external_use=True
        )
    except PublicUrlNotConfiguredError as exc:
        logger.error(
            "OAuth callback refused: PUBLIC_APP_URL / PUBLIC_API_URL not configured",
            provider=provider_slug,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    # HARDEN-04 (T-1238-05): read back the correlation_id from login-init so
    # every callback audit entry shares it; falls back to a fresh id (e.g.
    # cross-process restart). Details never carry secrets/tokens/email (T-1238-06).
    correlation_id: str = (
        request.session.get(f"_oauth_correlation_{provider_slug}")
        or uuid.uuid4().hex[:12]
    )

    try:
        client, provider = await build_oauth_client(provider_slug, db)

        # Exchange authorization code for tokens. Azure multitenant authorities
        # advertise a templated issuer, so relax the id_token iss check there only
        # (see _id_token_claims_options; geolens#303).
        authorize_kwargs: dict = {}
        claims_options = _id_token_claims_options(
            provider.provider_type, provider.discovery_url
        )
        if claims_options is not None:
            authorize_kwargs["claims_options"] = claims_options
        token = await client.authorize_access_token(request, **authorize_kwargs)

        # GitHub is plain OAuth2 (not OIDC), no id_token/userinfo endpoint
        # authlib knows automatically; resolve primary+verified email via
        # /user/emails instead (T-1237-01, SSO-05). Other providers use
        # authlib's userinfo path unchanged.
        if provider.provider_type == "github":
            # Pass the provider's configured user endpoint so GitHub Enterprise
            # providers resolve identity against their own API, not api.github.com.
            userinfo = await _resolve_github_identity(
                dict(token), userinfo_url=provider.userinfo_url
            )
        else:
            userinfo = token.get("userinfo")
            if userinfo is None:
                userinfo = await client.userinfo(token=token)
            userinfo = dict(userinfo)

        # Azure multitenant: the templated-issuer pin was relaxed at parse time,
        # so re-assert the resolved per-tenant issuer here before the identity is
        # trusted (geolens#303).
        verify_azure_multitenant_issuer(
            provider.provider_type, provider.discovery_url, userinfo
        )

        user = await find_or_create_oauth_user(db, provider, userinfo, dict(token))

        user.last_login_at = func.now()

        expire_minutes = await ACCESS_TOKEN_EXPIRE_MINUTES.get(db)
        expire_days = await REFRESH_TOKEN_EXPIRE_DAYS.get(db)

        identity = AuthenticatedIdentity(
            user_id=user.id, username=user.username, email=user.email
        )
        service = AuthService(db)
        access_token = await service.create_access_token(
            identity, expire_minutes=expire_minutes
        )
        refresh_token = service.create_refresh_token(user.id, expire_days=expire_days)

        # HARDEN-04: emit success audit entry before the commit so it persists
        # in the same transaction. Details carry no secrets, tokens, or email.
        await audit_emit(
            db,
            AuditEvent(
                user_id=user.id,
                action="oauth.login.success",
                resource_type="oauth_provider",
                details={
                    "provider_slug": provider_slug,
                    "correlation_id": correlation_id,
                    "outcome": "success",
                },
                ip_address=get_client_ip(request),
            ),
        )
        await db.commit()

        # GH-1302: same-origin SPA gets the refresh token as an httpOnly
        # cookie instead of in the fragment (readable by any script on the
        # landing page, the same exfiltration surface as localStorage).
        # `auth_mode=cookie` tells the callback page not to expect a body
        # token; a cross-origin SPA can't send that cookie back, so it keeps
        # pre-GH-1302 fragment delivery.
        api_url = await get_public_api_url(db, request=request, for_external_use=True)
        cookie_mode = is_same_origin(
            frontend_url, api_url
        ) and api_path_is_cookie_scoped(request, api_url)
        redirect_url = (
            f"{frontend_url}/oauth/callback"
            f"#token={access_token}"
            + ("" if cookie_mode else f"&refresh_token={refresh_token}")
            + f"&expires_in={expire_minutes * 60}"
            + ("&auth_mode=cookie" if cookie_mode else "")
        )
        # SEC-13/L-67: the redirect URL carries access_token (and, on the
        # cross-origin fallback, refresh_token) in the fragment. Without
        # Referrer-Policy: no-referrer, the browser may leak the full
        # callback URL (with the IdP's code= param) to third-party assets on
        # the post-redirect page. Per-redirect override of the global
        # strict-origin-when-cross-origin from SecurityHeadersMiddleware.
        redirect = RedirectResponse(
            url=redirect_url,
            status_code=302,
            headers={"Referrer-Policy": "no-referrer"},
        )
        if cookie_mode:
            issue_browser_session(redirect, request, refresh_token, expire_days)
        return redirect

    except HTTPException:
        raise  # Let 404s from build_oauth_client pass through
    except Exception as exc:  # broad: OAuth provider can return arbitrary errors; map to redirect with correlation_id
        # Refusals told to the caller by name rather than the generic
        # "OAuth callback failed" below: H-30's email-not-verified collision,
        # DOMAIN-03's allowlist rejection, and fix(#1778)'s
        # registration-disabled gate. All three do the same thing, so they
        # share one loop. DOMAIN-03 (T-1236-04): the log records provider
        # slug and correlation_id ONLY, never the attempted email/subject.
        from app.modules.auth.oauth.service import (
            OAuthDomainNotAllowedError,
            OAuthEmailUnverifiedError,
            OAuthRegistrationDisabledError,
        )

        named_refusals: tuple[tuple[type[Exception], str, str], ...] = (
            (
                OAuthEmailUnverifiedError,
                "email_not_verified",
                "OAuth callback refused: unverified email collision",
            ),
            (
                OAuthDomainNotAllowedError,
                "domain_not_allowed",
                "OAuth callback refused: email domain not in allowlist",
            ),
            (
                OAuthRegistrationDisabledError,
                "registration_disabled",
                "OAuth callback refused: self-serve registration is disabled",
            ),
        )
        for refusal_type, outcome, log_message in named_refusals:
            if not isinstance(exc, refusal_type):
                continue
            # Reuse the threaded correlation_id — do NOT mint a new one.
            logger.warning(
                log_message,
                provider=provider_slug,
                correlation_id=correlation_id,
            )
            # HARDEN-04: emit failure audit entry; commit in its own try/except
            # so a commit error is logged and does not mask the redirect.
            await audit_emit(
                db,
                AuditEvent(
                    user_id=None,
                    action="oauth.login.failure",
                    resource_type="oauth_provider",
                    details={
                        "provider_slug": provider_slug,
                        "correlation_id": correlation_id,
                        "outcome": outcome,
                    },
                    ip_address=get_client_ip(request),
                ),
            )
            try:
                await db.commit()
            except Exception:  # broad: defensive log-and-continue — an audit/rollback write must never break the OAuth redirect flow
                logger.exception(
                    "Failed to commit oauth.login.failure audit row; continuing",
                    provider=provider_slug,
                    correlation_id=correlation_id,
                )
            error_url = (
                f"{frontend_url}/oauth/callback"
                f"#error={outcome}&correlation_id={correlation_id}"
            )
            # SEC-13: same Referrer-Policy override as success path
            return RedirectResponse(
                url=error_url,
                status_code=302,
                headers={"Referrer-Policy": "no-referrer"},
            )
        # Reuse the threaded correlation_id — do NOT mint a new one.
        logger.exception(
            "OAuth callback failed",
            provider=provider_slug,
            correlation_id=correlation_id,
        )
        # FIX-C: discard any partial JIT side effects (flushed User/
        # OAuthAccount/refresh token) before writing the audit row — the
        # rollback + audit_emit + commit sequence ensures ONLY the
        # failure-audit row reaches the DB.
        try:
            await db.rollback()
        except Exception:  # broad: defensive log-and-continue — an audit/rollback write must never break the OAuth redirect flow
            logger.exception(
                "Failed to roll back DB after generic OAuth error; continuing",
                provider=provider_slug,
                correlation_id=correlation_id,
            )
        # HARDEN-04: emit failure audit entry for generic OAuth error.
        await audit_emit(
            db,
            AuditEvent(
                user_id=None,
                action="oauth.login.failure",
                resource_type="oauth_provider",
                details={
                    "provider_slug": provider_slug,
                    "correlation_id": correlation_id,
                    "outcome": "oauth_failed",
                },
                ip_address=get_client_ip(request),
            ),
        )
        try:
            await db.commit()
        except Exception:  # broad: defensive log-and-continue — an audit/rollback write must never break the OAuth redirect flow
            logger.exception(
                "Failed to commit oauth.login.failure audit row; continuing",
                provider=provider_slug,
                correlation_id=correlation_id,
            )
        error_url = f"{frontend_url}/oauth/callback#error=oauth_failed&correlation_id={correlation_id}"
        # SEC-13: same Referrer-Policy override as success path
        return RedirectResponse(
            url=error_url,
            status_code=302,
            headers={"Referrer-Policy": "no-referrer"},
        )


# ROUTE-01 (Phase 1092): dual-shape decorator — both trailing-slash and
# no-trailing-slash variants register against the same handler. Slash form
# stays canonical (already in OpenAPI); no-slash is a hidden alias closing
# the 404 regression introduced by redirect_slashes=False (api/main.py).
@router.get(
    "/providers",
    response_model=list[OAuthProviderPublic],
    include_in_schema=False,
)
@router.get("/providers/", response_model=list[OAuthProviderPublic])
async def list_public_providers(
    db: AsyncSession = Depends(get_db),
) -> list[OAuthProviderPublic]:
    """Return the list of enabled OAuth providers for the login page."""
    providers = await get_enabled_providers(db)
    return [OAuthProviderPublic.model_validate(p) for p in providers]
