"""OAuth/OIDC flow endpoints: login redirect, callback, and public provider list."""

from urllib.parse import quote

import structlog
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.oauth.encryption import decrypt_secret
from app.auth.oauth.schemas import OAuthProviderPublic
from app.auth.oauth.service import get_enabled_providers, get_provider_by_slug
from app.auth.providers import AuthenticatedIdentity
from app.auth.service import AuthService
from app.dependencies import get_db
from app.persistent_config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    REFRESH_TOKEN_EXPIRE_DAYS,
)
from app.public_urls import get_public_api_url, get_public_app_url

logger = structlog.stdlib.get_logger(__name__)

router = APIRouter(prefix="/auth/oauth", tags=["Auth"])


async def build_oauth_client(provider_slug: str, db: AsyncSession):
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


@router.get("/{provider_slug}/login")
async def oauth_login(
    provider_slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Redirect user to the IdP authorization URL with PKCE parameters."""
    client, _provider = await build_oauth_client(provider_slug, db)

    public_api_url = await get_public_api_url(db, request=request)
    redirect_uri = f"{public_api_url}/auth/oauth/{provider_slug}/callback"

    return await client.authorize_redirect(request, redirect_uri)


@router.get("/{provider_slug}/callback")
async def oauth_callback(
    provider_slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Handle IdP callback: exchange code, find/create user, issue JWT, redirect to frontend."""
    from app.auth.oauth.service import find_or_create_oauth_user

    # Compute frontend URL before try block (needed in except for error redirect)
    frontend_url = await get_public_app_url(db, request=request)

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
        return RedirectResponse(url=redirect_url, status_code=302)

    except HTTPException:
        raise  # Let 404s from build_oauth_client pass through
    except Exception as e:
        logger.warning("oauth_callback_error", provider=provider_slug, error=str(e))
        error_url = f"{frontend_url}/oauth/callback#error={quote(str(e))}"
        return RedirectResponse(url=error_url, status_code=302)


@router.get("/providers/", response_model=list[OAuthProviderPublic])
async def list_public_providers(
    db: AsyncSession = Depends(get_db),
) -> list[OAuthProviderPublic]:
    """Return the list of enabled OAuth providers for the login page."""
    providers = await get_enabled_providers(db)
    return [OAuthProviderPublic.model_validate(p) for p in providers]
