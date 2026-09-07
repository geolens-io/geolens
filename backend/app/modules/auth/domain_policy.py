"""HTTP-surface enforcement of the ``allowed_email_domains`` allowlist.

fix(#836): consolidates a fetch-check-403 block duplicated across four HTTP
endpoints. OAuth-service call sites keep their own flow — they raise
``OAuthDomainNotAllowedError`` into the SSO redirect and add verified-claim
trust rules with no HTTP analogue. Kept separate from ``domain_validation.py``
so that module stays pure pattern matching, no DB/HTTP concerns.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.persistent_config import ALLOWED_EMAIL_DOMAINS
from app.modules.auth.domain_validation import is_email_allowed
from app.modules.auth.models import User

EMAIL_DOMAIN_FORBIDDEN_DETAIL = "Email domain is not permitted"


async def enforce_email_domain_gate(
    db: AsyncSession,
    email: str | None,
    *,
    break_glass_user: User | None = None,
) -> None:
    """Raise 403 unless *email* satisfies the allowlist.

    Null/absent email is permitted (no address to gate). Uses
    ``get_uncached`` so enforcement observes the committed setting, not a
    value a concurrent reader repopulated during a writer's invalidate->commit
    window. ``break_glass_user`` waives the gate only via server-side
    ``manage_settings`` capability, never a client header.
    """
    if not email:
        return
    domains = await ALLOWED_EMAIL_DOMAINS.get_uncached(db)
    if is_email_allowed(email, domains):
        return
    if break_glass_user is not None:
        from app.modules.auth.permissions import (  # LAZY — per D-17
            MANAGE_SETTINGS,
            user_has_capability,
        )

        if await user_has_capability(db, break_glass_user, MANAGE_SETTINGS):
            return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=EMAIL_DOMAIN_FORBIDDEN_DETAIL,
    )
