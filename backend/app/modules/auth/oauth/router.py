"""OAuth/OIDC flow endpoints: login redirect, callback, and public provider list."""

import uuid

import structlog
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.oauth.encryption import decrypt_secret
from app.modules.auth.oauth.schemas import OAuthProviderPublic
from app.modules.auth.oauth.service import (
    _resolve_github_identity,
    get_enabled_providers,
    get_provider_by_slug,
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

    client_secret = decrypt_secret(provider.client_secret_encrypted)

    oauth = OAuth()

    # Build registration kwargs
    register_kwargs: dict = {
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
    except Exception:
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

        # Exchange authorization code for tokens
        token = await client.authorize_access_token(request)

        # Extract userinfo.
        # GitHub is plain OAuth2 (not OIDC) with no id_token / userinfo endpoint
        # that authlib knows about automatically. Its /user endpoint omits email
        # when set to private, so we resolve the primary+verified email via a
        # separate /user/emails call (T-1237-01 ASVS guard, SSO-05, Phase 1237).
        # All other providers use the existing authlib userinfo path unchanged.
        if provider.provider_type == "github":
            userinfo = await _resolve_github_identity(dict(token))
        else:
            userinfo = token.get("userinfo")
            if userinfo is None:
                userinfo = await client.userinfo(token=token)
            userinfo = dict(userinfo)

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

        redirect_url = (
            f"{frontend_url}/oauth/callback"
            f"#token={access_token}"
            f"&refresh_token={refresh_token}"
            f"&expires_in={expire_minutes * 60}"
        )
        # SEC-13 / L-67: the redirect URL carries access_token + refresh_token
        # in the fragment (#token=...&refresh_token=...). Without
        # `Referrer-Policy: no-referrer`, the browser may include the FULL
        # callback URL (which contains the IdP's `code=` query param) in
        # subsequent Referer headers to third-party assets loaded by the
        # post-redirect page — leaking the auth code. Per-redirect override of
        # the global `strict-origin-when-cross-origin` from
        # SecurityHeadersMiddleware.
        return RedirectResponse(
            url=redirect_url,
            status_code=302,
            headers={"Referrer-Policy": "no-referrer"},
        )

    except HTTPException:
        raise  # Let 404s from build_oauth_client pass through
    except Exception as exc:  # broad: OAuth provider can return arbitrary errors; map to redirect with correlation_id
        # Phase 268 H-30: surface email-not-verified collisions explicitly.
        from app.modules.auth.oauth.service import (
            OAuthDomainNotAllowedError,
            OAuthEmailUnverifiedError,
        )

        if isinstance(exc, OAuthEmailUnverifiedError):
            # Reuse the threaded correlation_id — do NOT mint a new one.
            logger.warning(
                "OAuth callback refused: unverified email collision",
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
                        "outcome": "email_not_verified",
                    },
                    ip_address=get_client_ip(request),
                ),
            )
            try:
                await db.commit()
            except Exception:
                logger.exception(
                    "Failed to commit oauth.login.failure audit row; continuing",
                    provider=provider_slug,
                    correlation_id=correlation_id,
                )
            error_url = (
                f"{frontend_url}/oauth/callback"
                f"#error=email_not_verified&correlation_id={correlation_id}"
            )
            # SEC-13: same Referrer-Policy override as success path
            return RedirectResponse(
                url=error_url,
                status_code=302,
                headers={"Referrer-Policy": "no-referrer"},
            )
        # DOMAIN-03 (T-1236-04): log provider + correlation_id only — do NOT
        # log the attempted email address (information-disclosure mitigation).
        if isinstance(exc, OAuthDomainNotAllowedError):
            # Reuse the threaded correlation_id — do NOT mint a new one.
            logger.warning(
                "OAuth callback refused: email domain not in allowlist",
                provider=provider_slug,
                correlation_id=correlation_id,
            )
            # HARDEN-04: emit failure audit entry for domain rejection.
            await audit_emit(
                db,
                AuditEvent(
                    user_id=None,
                    action="oauth.login.failure",
                    resource_type="oauth_provider",
                    details={
                        "provider_slug": provider_slug,
                        "correlation_id": correlation_id,
                        "outcome": "domain_not_allowed",
                    },
                    ip_address=get_client_ip(request),
                ),
            )
            try:
                await db.commit()
            except Exception:
                logger.exception(
                    "Failed to commit oauth.login.failure audit row; continuing",
                    provider=provider_slug,
                    correlation_id=correlation_id,
                )
            error_url = (
                f"{frontend_url}/oauth/callback"
                f"#error=domain_not_allowed&correlation_id={correlation_id}"
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
        except Exception:
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
