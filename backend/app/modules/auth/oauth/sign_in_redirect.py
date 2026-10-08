"""The redirect that hands a completed SSO sign-in to the SPA's callback page."""

import uuid

from fastapi import Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.persistent_config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    REFRESH_TOKEN_EXPIRE_DAYS,
)
from app.core.public_urls import get_public_api_url
from app.modules.auth.cookies import (
    api_path_is_cookie_scoped,
    is_same_origin,
    set_sso_exchange_cookie,
)
from app.modules.auth.models import User
from app.modules.auth.providers import AuthenticatedIdentity
from app.modules.auth.service import SSO_EXCHANGE_TTL_SECONDS, AuthService


def _callback_redirect(url: str) -> RedirectResponse:
    """A 302 to the SPA callback that never sends this URL on as a referrer.

    The fragment carries a sign-in credential and the query the IdP's code.
    """
    return RedirectResponse(
        url=url, status_code=302, headers={"Referrer-Policy": "no-referrer"}
    )


async def sso_sign_in_redirect(
    db: AsyncSession,
    request: Request,
    user: User,
    *,
    frontend_url: str,
    callback_query: str = "",
) -> RedirectResponse:
    """Redirect *user*'s completed SSO sign-in to ``/oauth/callback``.

    Adds the new session's rows to *db* without committing; the caller commits
    before returning the response.

    A same-origin SPA gets ``#code=``: a one-time code it exchanges at
    ``POST /auth/oauth/exchange/`` inside its cross-tab cookie lock. Setting
    the refresh cookie here instead would let a refresh another tab already
    sent land afterwards and replace it with the previous session's. A
    cross-origin SPA can't use that cookie, so it gets the tokens in the
    fragment.
    """
    family_id = uuid.uuid4()
    service = AuthService(db)
    callback = f"{frontend_url}/oauth/callback{callback_query}"
    api_url = await get_public_api_url(db, request=request, for_external_use=True)
    if is_same_origin(frontend_url, api_url) and api_path_is_cookie_scoped(
        request, api_url
    ):
        code, nonce = await service.stage_sso_sign_in(user.id, family_id=family_id)
        response = _callback_redirect(f"{callback}#code={code}")
        set_sso_exchange_cookie(response, request, nonce, SSO_EXCHANGE_TTL_SECONDS)
        return response

    expire_minutes = await ACCESS_TOKEN_EXPIRE_MINUTES.get(db)
    expire_days = await REFRESH_TOKEN_EXPIRE_DAYS.get(db)
    identity = AuthenticatedIdentity(
        user_id=user.id, username=user.username, email=user.email
    )
    access_token = await service.create_access_token(
        identity, expire_minutes=expire_minutes, family_id=family_id
    )
    refresh_token = service.create_refresh_token(
        user.id, expire_days=expire_days, family_id=family_id
    )
    return _callback_redirect(
        f"{callback}#token={access_token}&refresh_token={refresh_token}"
        f"&expires_in={expire_minutes * 60}"
    )
