"""Sign-in methods a login page or desktop client may offer."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.edition import is_enterprise
from app.core.persistent_config import PASSWORD_LOGIN_ENABLED
from app.modules.auth.oauth.models import OAuthProvider
from app.modules.auth.oauth.service import get_enabled_providers


async def get_public_providers(db: AsyncSession) -> list[OAuthProvider]:
    """Enabled providers a sign-in page may offer."""
    # The SAML sign-in route ships with the Enterprise runtime only.
    saml_available = is_enterprise()
    return [
        p
        for p in await get_enabled_providers(db)
        if p.provider_type != "saml" or saml_available
    ]


async def list_sign_in_methods(db: AsyncSession) -> list[str]:
    """Password when enabled, then each provider type, then extension methods."""
    from app.platform.extensions import get_auth_extension

    methods = ["password"] if await PASSWORD_LOGIN_ENABLED.get(db) else []
    offered = [p.provider_type for p in await get_public_providers(db)]
    offered.extend(get_auth_extension().get_auth_methods())
    methods.extend(dict.fromkeys(m for m in offered if m not in methods))
    return methods
