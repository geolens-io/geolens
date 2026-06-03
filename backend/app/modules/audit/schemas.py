import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    # Phase 279 ADMIN-05 (L-02 / Rule 1): user_id is nullable in the AuditLog
    # model (ondelete='SET NULL' on the FK) — when a user is hard-deleted,
    # their audit rows survive with user_id=None. The previous non-nullable
    # uuid.UUID typing raised pydantic ValidationError when the response
    # serializer hit a NULL'd row. Surfaced once Phase 279 added a
    # `user.register` audit emit, which created register rows whose user
    # later got deleted by the admin-delete tests, producing NULL user_id
    # rows that subsequent date-range queries would try to serialize.
    user_id: uuid.UUID | None
    username: str | None = None
    action: str
    resource_type: str
    resource_id: uuid.UUID | None
    details: dict | None
    ip_address: str | None
    created_at: datetime


class AuditLogListResponse(BaseModel):
    logs: list[AuditLogResponse]
    total: int


# ---------------------------------------------------------------------------
# SEC-FU-08: Column DDL feed response models
# ---------------------------------------------------------------------------


class ColumnDdlEntry(BaseModel):
    """A single column-DDL audit event for the owner-facing feed endpoint.

    Omits PII beyond the actor's username (no email or sensitive details).
    Mirrors AuditLogResponse shape, scoped to column-DDL events only.
    """

    model_config = ConfigDict(from_attributes=True)

    action: str
    created_at: datetime
    details: dict[str, Any] | None
    user_id: uuid.UUID | None
    username: str | None = None


class ColumnDdlFeedResponse(BaseModel):
    """Paginated response for GET /api/audit/datasets/{dataset_id}/column-ddl."""

    items: list[ColumnDdlEntry]
    total: int
    limit: int
    offset: int
