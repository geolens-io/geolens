"""Protocol interfaces for GeoLens extension points.

Uses only stdlib types where possible. AsyncSession (Phase 222 / Phase 214
precedent at ``app/core/identity.py:29``) is imported because Protocol method
signatures need the type and SQLAlchemy does not import from ``app.modules.*``.
``AuditEvent`` is forward-referenced via ``TYPE_CHECKING`` to avoid an
``platform.extensions → modules.audit.events`` edge that would invert the
layering Phase 212/214 closed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.modules.audit.events import AuditEvent


@runtime_checkable
class BrandingExtension(Protocol):
    """Extension point for branding customization."""

    def get_branding_defaults(self) -> dict[str, object]: ...


@runtime_checkable
class AuditExtension(Protocol):
    """Extension point for audit export formats."""

    def get_export_formats(self) -> list[str]: ...


@runtime_checkable
class AuthExtension(Protocol):
    """Extension point for additional auth methods."""

    def get_auth_methods(self) -> list[str]: ...


@runtime_checkable
class AuditSink(Protocol):
    """Write-side hook for audit event emission (Phase 222 D-01).

    Sibling to ``AuditExtension`` (read-side export-format gating at
    ``audit/router.py``). Two orthogonal concerns: a SIEM streamer doesn't add
    export formats; a CSV exporter doesn't subscribe to writes. Future overlays
    may implement BOTH on one class (Phase 217 D-13 dual-Protocol pattern), but
    the contracts stay separate.

    Enterprise overlays subscribe by appending instances to
    ``_extensions["audit_sinks"]`` in their ``register_extensions(registry)``
    callback via ``setdefault + append`` (D-09 — overwriting the slot makes
    DefaultAuditSink disappear and breaks AUDIT-05).
    """

    async def emit(self, session: AsyncSession, event: "AuditEvent") -> None: ...


@runtime_checkable
class BillingExtension(Protocol):
    """Startup billing hook (Phase 223 D-06 / D-08 / D-09 / BILLING-01).

    Sibling to ``AuditSink`` (write-side audit emission, Phase 222). Two
    orthogonal concerns: a marketplace metering hook doesn't subscribe to
    audit events; an audit sink doesn't fire on lifespan startup. Future
    overlays may implement BOTH on one class (Phase 217 D-13 dual-Protocol
    pattern), but the contracts stay separate.

    Enterprise overlays subscribe by appending instances to
    ``_extensions["billing_extensions"]`` in their ``register_extensions(registry)``
    callback via ``setdefault + append`` (D-06 — overwriting the slot makes
    DefaultBillingExtension disappear and breaks the iteration shape).

    Core dispatch (api/main.py lifespan) wraps each call with
    ``asyncio.wait_for(timeout=10.0)`` + per-extension try/except (D-10).
    Overlays do NOT need to defend against their own failures — the dispatch
    loop guarantees per-extension isolation.
    """

    async def on_startup(self, app: FastAPI) -> None: ...
