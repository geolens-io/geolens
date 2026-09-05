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
    ``_get_session`` alone. In authlib 1.7.2 that hook serves discovery
    (``base_client/async_app.py:78``) and JWKS
    (``base_client/async_openid.py:25``); the token exchange
    (``async_app.py:126``) and the userinfo fetch (``async_app.py:90``, reached
    from ``async_openid.py:36``) build their client through
    ``_get_oauth_client`` (``base_client/sync_app.py:236``), which returned a
    stock httpx transport. Those two requests are the ones carrying the client
    secret and the access token. All four hooks construct ``self.client_cls``,
    so this is the single place that reaches every one of them.

    ``_get_oauth_client`` also merges the discovery document into the httpx
    client kwargs (``sync_app.py:239``, ``client_kwargs.update(metadata)``), so
    a document carrying a ``transport``, ``mounts``, ``proxy``, ``verify`` or
    ``follow_redirects`` key would otherwise be choosing the transport security
    of the request that carries the secret. They are set here, after that
    merge; ``verify`` and ``cert`` need no entry because httpx reads them only
    when it builds the transport itself.
    """

    def __init__(self, *args, **kwargs):
        from app.platform.security import make_safe_transport

        kwargs["transport"] = make_safe_transport()
        # httpx consults a per-scheme mount before ``transport``, and builds
        # one from ``proxy``. Both are part of pinning the transport rather
        # than separate rules, and an empty ``mounts`` does not clear what
        # ``proxy`` added, so both are set. Passing a transport at all already
        # stops httpx reading proxies from the environment
        # (``_client.py``: ``allow_env_proxies = trust_env and transport is None``),
        # which is why an operator's proxy configuration is unaffected.
        kwargs["mounts"] = {}
        kwargs["proxy"] = None
        # httpx's own default, pinned so that it stays the default: nothing
        # here follows a redirect, so neither the client secret nor the access
        # token can cross an origin behind a 302. That is the strongest form of
        # the rule ``_ALWAYS_CREDENTIAL_HEADERS`` in platform/security.py
        # applies to the hops that do happen.
        kwargs["follow_redirects"] = False
        super().__init__(*args, **kwargs)


# The endpoints authlib reads out of a discovery document and then fetches:
# ``token_endpoint`` (async_app.py:125), ``userinfo_endpoint``
# (async_openid.py:36), ``jwks_uri`` (async_openid.py:21) and
# ``authorization_endpoint`` (async_app.py:101, which is handed to the
# browser). A provider configured by discovery URL leaves the matching columns
# empty on its row, so validate_provider_server_endpoints never sees the
# address a request actually goes to. This list stays matched to the calls that
# exist: refusing a login over an endpoint nothing fetches is a false refusal
# rather than a defence.
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

    fix(#1861): one helper for both sources of an endpoint, the provider row
    and the discovery document, so the two cannot drift into different status
    codes or different disclosure. The response names no host: these routes are
    unauthenticated and an SSRFError message carries the hostname it was asked
    to resolve. The operator log gets the provider, which endpoint was refused
    and its hostname, which is what fixing the configuration needs.
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
            # SSRFError and SSRFResolutionError are both ValueError, which is
            # also what the row-level check raises.
            raise _endpoint_refused(
                provider_slug, exc, endpoint=key, host=urlparse(url).hostname
            ) from exc


class _SSRFSafeOAuth2App(StarletteOAuth2App):
    """Every Authlib session this app builds goes through the safe transport."""

    client_cls = _SSRFSafeOAuth2Client

    # One validation per app instance, and build_oauth_client builds one per
    # request. Nothing rewrites the endpoints after they are read: authlib
    # caches the document under ``_loaded_at`` and only ever adds ``jwks``.
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
        # Only a discovery document introduces an endpoint the row-level check
        # in build_oauth_client has not already resolved. Without one, authlib
        # keeps the registered columns in server_metadata, and re-resolving
        # them here would refuse a provider that check just passed.
        if self._server_metadata_url and not self._endpoints_validated:
            await _validate_discovery_endpoints(self.name, metadata)
            self._endpoints_validated = True
        return metadata


def _id_token_claims_options(
    provider_type: str, discovery_url: str | None
) -> dict | None:
    """id_token claim-validation overrides passed to ``authorize_access_token``.

    Azure *multitenant* authorities (``/common/``, ``/organizations/``) publish a
    TEMPLATED issuer ``https://login.microsoftonline.com/{tenantid}/v2.0`` in
    their OIDC discovery document, but issued id_tokens carry the resolved
    per-tenant issuer (e.g. ``.../9188040d-.../v2.0`` for personal accounts).
    authlib's default pins ``iss`` to that templated string via an exact
    value-match and rejects every login; joserfc (no callable validator) only
    supports value/values matching, so for multitenant Microsoft we relax ``iss``
    to required-but-not-value-pinned. The JWKS signature check and the PKCE +
    client_secret code exchange still bind the token to Microsoft and to this app.

    Tenant-specific Microsoft providers (concrete ``/{tenant_id}/`` discovery URL,
    as the admin UI builds) have a FIXED issuer that authlib can and must pin, so
    they keep the default — relaxing them would drop cross-tenant ``iss`` isolation
    (geolens#303 review). Returns None for every other case so authlib keeps its
    default iss pin.
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

    # Validate every persisted endpoint before decrypting the client secret.
    # This protects legacy rows as well as configurations written through CRUD
    # or config import. fix(#1861): it covers the four columns on the row and
    # nothing else, so a provider configured by discovery URL has its endpoints
    # checked in _SSRFSafeOAuth2App.load_server_metadata instead. Either way
    # every Authlib session, whichever hook builds it, then connects through
    # the IP-pinning transport, which closes the DNS-rebinding gap between the
    # check and request dispatch.
    try:
        await validate_provider_server_endpoints(provider)
    except ValueError as exc:
        raise _endpoint_refused(provider_slug, exc) from exc

    client_secret = decrypt_secret(provider.client_secret_encrypted)

    oauth = OAuth()

    # Build registration kwargs
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
        # Generic OIDC / GitHub without discovery -- explicit URLs.
        # GitHub's token endpoint returns form-encoded unless Accept: application/json
        # is sent. We request JSON via the token_endpoint_auth_method kwarg and by
        # adding the Accept header to client_kwargs so authlib sends it during
        # token exchange (SSO-05, Phase 1237).
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
    # matching callback audit entry (success OR failure) shares the same id,
    # giving a non-repudiable trail linking initiation to outcome.
    # Store in session keyed by provider slug; authlib already uses the session
    # for its PKCE `state` parameter, so the middleware is already active.
    # Details carry only provider_slug + correlation_id — no secrets, tokens,
    # or email addresses (T-1238-06).
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

    # HARDEN-04 (T-1238-05): read back the correlation_id stored at login-init so
    # every callback audit entry (success or failure) shares the same id.
    # Fall back to a fresh id when the session value is absent (e.g. cross-process
    # restart between login-init and callback). Details carry only provider_slug,
    # correlation_id, and an outcome string — never client_secret, tokens, or email
    # (T-1238-06).
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

        # Extract userinfo.
        # GitHub is plain OAuth2 (not OIDC) with no id_token / userinfo endpoint
        # that authlib knows about automatically. Its /user endpoint omits email
        # when set to private, so we resolve the primary+verified email via a
        # separate /user/emails call (T-1237-01 ASVS guard, SSO-05, Phase 1237).
        # All other providers use the existing authlib userinfo path unchanged.
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

        # Find or create the GeoLens user
        user = await find_or_create_oauth_user(db, provider, userinfo, dict(token))

        # Record login timestamp
        user.last_login_at = func.now()

        # Issue GeoLens JWT
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

        # GH-1302: when the SPA shares this request's origin, the refresh token
        # is delivered as an httpOnly cookie and never enters the fragment —
        # the fragment is readable by any script on the landing page and was
        # the same exfiltration surface as localStorage. The `auth_mode=cookie`
        # marker tells the callback page not to expect a body token. A
        # cross-origin SPA cannot send that cookie back, so it keeps the
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
        # SEC-13 / L-67: the redirect URL carries the access_token (and, on the
        # cross-origin fallback, the refresh_token) in the fragment. Without
        # `Referrer-Policy: no-referrer`, the browser may include the FULL
        # callback URL (which contains the IdP's `code=` query param) in
        # subsequent Referer headers to third-party assets loaded by the
        # post-redirect page — leaking the auth code. Per-redirect override of
        # the global `strict-origin-when-cross-origin` from
        # SecurityHeadersMiddleware.
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
        # Refusals the caller is told about by name, rather than through the
        # generic "OAuth callback failed" below: Phase 268 H-30's
        # email-not-verified collision, DOMAIN-03's allowlist rejection, and
        # fix(#1778)'s registration-disabled gate.
        #
        # Each of the three does exactly the same thing, so they share one loop
        # (fix(#1778): they were three copies of this block, and the third would
        # have been a fourth). DOMAIN-03 (T-1236-04): the log records the
        # provider slug and correlation_id ONLY -- never the attempted email
        # address or subject (information-disclosure mitigation).
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
        # FIX-C (Codex P2): discard any partial JIT side effects (flushed User /
        # OAuthAccount / refresh token) before writing the audit row.  Without
        # this rollback, a generic exception mid-provisioning can persist a
        # half-created user row.  The rollback + audit_emit + commit sequence
        # means ONLY the failure-audit row reaches the DB.
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
