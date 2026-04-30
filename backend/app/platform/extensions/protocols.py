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
