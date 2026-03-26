"""SAML SSO endpoints: SP-initiated login and Assertion Consumer Service (ACS)."""

from urllib.parse import quote

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from saml2 import BINDING_HTTP_POST
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.oauth.service import find_or_create_oauth_user, get_provider_by_slug
from app.auth.providers import AuthenticatedIdentity
from app.auth.saml.config import build_saml_client
from app.auth.saml.replay import replay_cache
from app.auth.service import AuthService
from app.dependencies import get_db
from app.extensions.guards import require_enterprise
from app.persistent_config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    REFRESH_TOKEN_EXPIRE_DAYS,
)
from app.public_urls import get_public_api_url, get_public_app_url

logger = structlog.stdlib.get_logger(__name__)

router = APIRouter(
    prefix="/auth/saml",
    tags=["Auth"],
    dependencies=[Depends(require_enterprise)],
)


def _extract_attr(attributes: dict, keys: list[str]) -> str | None:
    """Extract first matching attribute from SAML assertion attributes.

    SAML attributes are typically lists, e.g. {"email": ["user@example.com"]}.
    """
    for key in keys:
        val = attributes.get(key)
        if val:
            return val[0] if isinstance(val, list) else val
    return None


@router.get("/{slug}/login")
async def saml_login(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Redirect user to the IdP SSO URL with a SAML AuthnRequest."""
    provider = await get_provider_by_slug(db, slug)
    if not provider or not provider.enabled or provider.provider_type != "saml":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    public_api_url = await get_public_api_url(db, request=request)
    acs_url = f"{public_api_url}/auth/saml/{slug}/acs"
    client = build_saml_client(provider, acs_url)

    reqid, info = client.prepare_for_authenticate()
    redirect_url = dict(info["headers"])["Location"]
    return RedirectResponse(url=redirect_url, status_code=302)


@router.post("/{slug}/acs")
async def saml_acs(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Assertion Consumer Service: validate SAML response and provision user."""
    frontend_url = await get_public_app_url(db, request=request)

    try:
        provider = await get_provider_by_slug(db, slug)
        if not provider or not provider.enabled or provider.provider_type != "saml":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

        # Parse form-encoded SAMLResponse from IdP POST
        form_data = await request.form()
        saml_response = form_data.get("SAMLResponse")
        if not saml_response:
            raise ValueError("Missing SAMLResponse in form data")

        # Build client and validate assertion
        public_api_url = await get_public_api_url(db, request=request)
        acs_url = f"{public_api_url}/auth/saml/{slug}/acs"
        client = build_saml_client(provider, acs_url)

        authn_response = client.parse_authn_request_response(
            saml_response, BINDING_HTTP_POST
        )

        # Check assertion replay
        assertion_id = authn_response.assertion.id
        if not replay_cache.check_and_record(assertion_id):
            raise ValueError("SAML assertion has already been used (replay detected)")

        # Extract user attributes
        subject = authn_response.get_subject().text
        attributes = authn_response.ava

        email = _extract_attr(
            attributes,
            [
                "email",
                "mail",
                "emailAddress",
                "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
            ],
        )
        name = _extract_attr(
            attributes,
            [
                "displayName",
                "name",
                "cn",
                "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name",
            ],
        )

        userinfo = {"sub": subject, "email": email, "name": name}

        # Extract groups if provider has a group_claim configured
        if provider.group_claim:
            groups = _extract_attr(attributes, [provider.group_claim])
            if groups:
                userinfo[provider.group_claim] = groups

        # Provision or find user
        user = await find_or_create_oauth_user(db, provider, userinfo, {})

        # Record login timestamp
        user.last_login_at = func.now()

        # Issue JWT
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
        raise
    except Exception as exc:
        logger.warning("saml_acs_error", provider=slug, error=str(exc))
        error_url = f"{frontend_url}/oauth/callback#error={quote(str(exc))}"
        return RedirectResponse(url=error_url, status_code=302)
