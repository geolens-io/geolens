import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

# Sortable columns for the admin audit-log list -- the OUTER half of a
# two-layer allowlist: FastAPI 422s anything outside it before the service
# runs, and _audit_sort_columns() (service.py) resolves the survivor to a
# mapped column, so a caller string never reaches ORDER BY.
#
# `resource_name` is absent: resolve_resource_names() runs after the query
# returns, so the database has nothing to order by.
AuditSortField = Literal[
    "created_at", "action", "resource_type", "ip_address", "username"
]

# Declared here rather than imported from the admin module: audit is a peer
# domain, and a two-value literal is not worth a cross-module dependency.
SortDirection = Literal["asc", "desc"]


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    # Phase 279 ADMIN-05 (L-02/Rule 1): nullable (FK ondelete='SET NULL') --
    # a hard-deleted user's audit rows survive with user_id=None. The
    # previous non-nullable typing raised a ValidationError serializing
    # those rows.
    user_id: uuid.UUID | None
    username: str | None = None
    action: str
    resource_type: str
    resource_id: uuid.UUID | None
    # fix(#620): display name of the target resource (dataset/map/collection
    # title, user username), resolved at query time. None when the resource
    # was deleted or its type has no canonical name.
    resource_name: str | None = None
    details: dict | None
    ip_address: str | None
    created_at: datetime


class AuditLogListResponse(BaseModel):
    logs: list[AuditLogResponse]
    total: int


# SEC-FU-08: Column DDL feed response models.


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
