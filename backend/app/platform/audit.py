"""Audit event emission facade shared by core, modules, and extensions."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.extensions import get_audit_sinks

logger = structlog.stdlib.get_logger(__name__)


@dataclass(frozen=True)
class AuditEvent:
    """Immutable audit event passed to every registered AuditSink."""

    user_id: uuid.UUID
    action: str
    resource_type: str
    resource_id: uuid.UUID | None = None
    details: dict | None = None
    ip_address: str | None = None


async def audit_emit(session: AsyncSession, event: AuditEvent) -> None:
    """Dispatch an audit event to every registered sink with failure isolation."""
    for sink in get_audit_sinks():
        try:
            await sink.emit(session, event)
        except Exception:  # noqa: BLE001 - audit sinks must not break callers
            logger.exception(
                "Audit sink raised; suppressed per AUDIT-03",
                sink=type(sink).__name__,
                action=event.action,
                resource_type=event.resource_type,
                resource_id=str(event.resource_id) if event.resource_id else None,
            )
