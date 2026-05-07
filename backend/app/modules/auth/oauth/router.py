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
from app.modules.auth.oauth.service import get_enabled_providers, get_provider_by_slug
from app.modules.auth.providers import AuthenticatedIdentity
from app.modules.auth.service import AuthService
from app.core.dependencies import get_db
from app.core.persistent_config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    REFRESH_TOKEN_EXPIRE_DAYS,
)
from app.core.public_urls import get_public_api_url, get_public_app_url
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
        # Generic OIDC without discovery -- explicit URLs
        register_kwargs["authorize_url"] = provider.authorize_url
        register_kwargs["access_token_url"] = provider.token_url
        register_kwargs["userinfo_endpoint"] = provider.userinfo_url

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

    try:
        client, provider = await build_oauth_client(provider_slug, db)

        # Exchange authorization code for tokens
        token = await client.authorize_access_token(request)

        # Extract userinfo
        userinfo = token.get("userinfo")
        if userinfo is None:
            userinfo = await client.userinfo(token=token)

        # Find or create the GeoLens user
        user = await find_or_create_oauth_user(
            db, provider, dict(userinfo), dict(token)
        )

        # Record login timestamp
        user.last_login_at = func.now()

        # Issue GeoLens JWT
        expire_minutes = await ACCESS_TOKEN_EXPIRE_MINUTES.get(db)
        expire_days = await REFRESH_TOKEN_EXPIRE_DAYS.get(db)

        identity = AuthenticatedIdentity(
            user_id=user.id, username=user.username, email=user.email
        )
        service = AuthService(db)
        access_token = service.create_access_token(
            identity, expire_minutes=expire_minutes
        )
        refresh_token = service.create_refresh_token(user.id, expire_days=expire_days)
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
        from app.modules.auth.oauth.service import OAuthEmailUnverifiedError

        if isinstance(exc, OAuthEmailUnverifiedError):
            correlation_id = uuid.uuid4().hex[:12]
            logger.warning(
                "OAuth callback refused: unverified email collision",
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
        correlation_id = uuid.uuid4().hex[:12]
        logger.exception(
            "OAuth callback failed",
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


@router.get("/providers/", response_model=list[OAuthProviderPublic])
async def list_public_providers(
    db: AsyncSession = Depends(get_db),
) -> list[OAuthProviderPublic]:
    """Return the list of enabled OAuth providers for the login page."""
    providers = await get_enabled_providers(db)
    return [OAuthProviderPublic.model_validate(p) for p in providers]
