"""HTTP-surface enforcement of the ``allowed_email_domains`` allowlist.

fix(#836): the fetch-check-break-glass-403 block was pasted at four HTTP
endpoints (password login DOMAIN-04, refresh CR-01, self-serve signup
DOMAIN-02, admin-create DOMAIN-04). This helper is that block, once. The two
OAuth-service sites keep their own flow on purpose — they raise
``OAuthDomainNotAllowedError`` into the SSO redirect path and add
verified-claim trust rules (WR-02 / FIX-A) that have no HTTP analogue.

Kept separate from ``domain_validation.py`` so that module stays pure
(pattern matching only, no DB or HTTP concerns).
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

    Semantics (the reconciled superset of the four historical copies):

    - A null/absent email is permitted — no address to gate on (DOMAIN-02).
    - Cache-bypass (``get_uncached``): security enforcement must observe the
      committed setting, not a value a concurrent reader repopulated into the
      cache during a writer's invalidate->commit window.
    - Break-glass: when ``break_glass_user`` holds ``manage_settings``, the
      gate is waived (T-1236-02: server-side capability, never a client
      header). Signup passes no user — a new identity has no principal to
      exempt.
    """
    if not email:
        return
    domains = await ALLOWED_EMAIL_DOMAINS.get_uncached(db)
    if is_email_allowed(email, domains):
        return
    if break_glass_user is not None:
        # Lazy import to avoid adding a DB dep at module top; follows D-17.
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
