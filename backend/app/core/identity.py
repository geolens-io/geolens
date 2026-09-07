"""Cross-domain identity contract.

Structural Protocols downstream code uses to type a request's authenticated
user without importing the concrete SQLAlchemy ORM (PEP 544; the concrete
``app.modules.auth.models.User`` satisfies ``IdentityProtocol`` implicitly).
Uses only stdlib types plus ``fastapi.Request``/``AsyncSession`` (allowed
infrastructure types) to avoid a ``core -> modules.auth`` import edge
(Phase 214, IDENT-01..03).

An enterprise auth overlay is the first concrete consumer of
``IdentityExtension``: it registers under the ``geolens.extensions``
entry-point group with key ``"identity"``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Protocol, Sequence, runtime_checkable

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession


@runtime_checkable
class RoleProtocol(Protocol):
    """Slim role contract — ``name`` is the only attribute cross-domain code reads.

    Keeps ``core/`` free of the ``core -> modules.auth`` edge; the concrete
    ``Role`` ORM satisfies this structurally.
    """

    name: str


@runtime_checkable
class IdentityProtocol(Protocol):
    """Comprehensive identity surface read by cross-domain call sites.

    The 6-field surface (D-01) covers every read of the concrete ``User`` ORM
    made outside ``auth/`` and ``admin/``. Sensitive fields (``password_hash``,
    ``auth_provider``, ``last_login_at``, ``status``) are deliberately NOT
    exposed — admin endpoints that need them keep importing the concrete
    ``User`` (allowlisted in the Phase 214 architecture guard).
    """

    id: uuid.UUID
    username: str
    email: str | None
    is_active: bool
    roles: Sequence[RoleProtocol]
    created_at: datetime


# Shorter alias for caller annotations (Phase 214 D-05); ``IdentityProtocol``
# is preferred in conformance assertions / runtime ``isinstance`` checks.
Identity = IdentityProtocol


@runtime_checkable
class IdentityExtension(Protocol):
    """Enterprise overlay registration contract for alternate identity backends.

    The default (``DefaultIdentityExtension``) returns ``None``, meaning
    "fall through to the existing JWT path." An overlay implements this to
    validate its own session token, JIT-provision via
    ``find_or_create_oauth_user()``, and return an ``Identity``. Async is
    mandatory (Pitfall 8): overlay implementations may hit the DB.
    """

    async def resolve_identity_from_token(
        self, token: str, request: Request, db: AsyncSession
    ) -> Identity | None: ...
