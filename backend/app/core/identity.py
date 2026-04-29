"""Cross-domain identity contract.

Defines structural Protocols that downstream code uses to type a request's
authenticated user without importing the concrete SQLAlchemy ORM. The
concrete ``app.modules.auth.models.User`` satisfies ``IdentityProtocol``
implicitly (structural subtyping / PEP 544); no inheritance is required.

Uses only stdlib types (plus ``fastapi.Request`` and SQLAlchemy's
``AsyncSession`` for the extension method signature) to avoid the
``core -> modules.auth`` import edge this milestone (Phase 214,
IDENT-01..03) is closing. ``Request`` and ``AsyncSession`` are
infrastructure types that do NOT live under ``app.modules.*`` so they
do not violate the layering rule.

An enterprise auth overlay (e.g., the ``geolens-enterprise`` package) is
the first concrete consumer of ``IdentityExtension``: it registers an
alternate backend under the ``geolens.extensions`` entry-point group
with key ``"identity"`` and ``get_identity_extension()`` returns it on
subsequent requests.
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

    Mirrors the discipline of ``platform/extensions/protocols.py``:
    typing ``IdentityProtocol.roles`` against this Protocol (instead of the
    concrete ``app.modules.auth.models.Role`` ORM class) keeps ``core/``
    free of the ``core -> modules.auth`` edge. The concrete ``Role`` ORM
    satisfies this Protocol structurally (``Role.name: Mapped[str]``).
    """

    name: str


@runtime_checkable
class IdentityProtocol(Protocol):
    """Comprehensive identity surface read by ~42 cross-domain call sites.

    The 6-field surface (D-01) covers every read of the concrete ``User``
    ORM made outside the ``auth/`` and ``admin/`` modules: ``id`` and
    ``email`` (audit + admin views), ``username`` (admin/router.py:52,
    audit/router.py:72,153,189, catalog/maps/router.py:252,
    catalog/datasets/api/router.py:450, catalog/sources/provenance.py:54,77),
    ``is_active`` (the ``get_current_active_user`` gate), ``roles`` (RBAC
    matrix), and ``created_at`` (admin/router.py:57). Sensitive fields
    (``password_hash``, ``auth_provider``, ``last_login_at``, ``status``)
    are deliberately NOT exposed — admin endpoints that read them keep
    importing the concrete ``User`` (allowlisted in the Phase 214
    architecture guard).
    """

    id: uuid.UUID
    username: str
    email: str | None
    is_active: bool
    roles: Sequence[RoleProtocol]
    created_at: datetime


# Shorter alias for caller annotations (Phase 214 D-05).
# Both names are exported; ``Identity`` reads cleaner in parameter
# annotations (matches the existing project convention of one-word type
# names) and ``IdentityProtocol`` is preferred in conformance assertions
# / runtime ``isinstance`` checks.
Identity = IdentityProtocol


@runtime_checkable
class IdentityExtension(Protocol):
    """Enterprise overlay registration contract for alternate identity backends.

    The default community implementation (``DefaultIdentityExtension`` at
    ``platform/extensions/defaults.py``) returns ``None``, signalling
    "I don't recognize this token; fall through to the existing JWT path."
    An enterprise auth overlay implements this method to validate an
    overlay-issued session token, run JIT provisioning through the
    existing ``find_or_create_oauth_user()`` pathway, and return an
    ``Identity``. The async signature is mandatory (Pitfall 8) — overlay
    implementations may perform DB lookups; ``await`` is required in the
    wire-in.
    """

    async def resolve_identity_from_token(
        self, token: str, request: Request, db: AsyncSession
    ) -> Identity | None: ...
