"""Typed event payload for audit emission (Phase 222 D-02).

Sibling to log_action() parameter surface; mirrors fields 1:1.
Frozen so sinks cannot mutate the event between subscribers.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class AuditEvent:
    """Immutable audit event passed to every registered AuditSink.

    user_id is required at emit-time (every emit names an actor), even though
    the AuditLog.user_id column is nullable to allow post-hoc user deletion to
    NULL-out the FK (ondelete=SET NULL — backend/app/modules/audit/models.py).
    The two are different concerns: emit-time actor naming vs row-storage
    nullability.

    Sink implementations MUST NOT mutate event.details (Pitfall F): frozen=True
    prevents attribute reassignment but NOT dict-content mutation; trust the
    contract.
    """

    user_id: uuid.UUID
    action: str
    resource_type: str
    resource_id: uuid.UUID | None = None
    details: dict | None = None
    ip_address: str | None = None
