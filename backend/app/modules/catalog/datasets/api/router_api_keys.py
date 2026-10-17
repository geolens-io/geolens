"""Mint and list API keys bound to one dataset."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_client_ip, get_db
from app.core.identity import Identity
from app.core.record_types import capabilities
from app.modules.audit.service import AuditEvent, audit_emit
from app.modules.auth.dependencies import (
    get_current_active_user,
    require_session_credential,
)
from app.modules.auth.models import ApiKey
from app.modules.auth.schemas import (
    ApiKeyCreateResponse,
    ApiKeyListItem,
    ApiKeyListResponse,
    DatasetApiKeyCreateRequest,
)
from app.modules.auth.service import create_api_key_for_user
from app.modules.catalog.authorization import check_dataset_write_access
from app.modules.catalog.datasets.domain.service import get_dataset
from app.standards.ogc.errors import ERROR_RESPONSES_WRITE

router = APIRouter(
    prefix="/datasets", tags=["Datasets"], responses=ERROR_RESPONSES_WRITE
)


async def _writable_dataset(db: AsyncSession, dataset_id: uuid.UUID, user: Identity):
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    await check_dataset_write_access(db, dataset, dataset_id, user)
    return dataset


@router.post(
    "/{dataset_id}/api-keys",
    response_model=ApiKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_dataset_api_key(
    dataset_id: uuid.UUID,
    body: DatasetApiKeyCreateRequest,
    request: Request,
    user: Identity = Depends(require_session_credential),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyCreateResponse:
    """Create a key that reads and writes this dataset's features only.

    The key has scope ``dataset_write`` and acts as the caller, so the
    caller's own access to the dataset still applies to every request it
    makes. It authenticates the dataset's feature routes and OGC API
    Features items, and is treated as an invalid key everywhere else. It must
    expire within 365 days. Requires write access to the dataset and a
    signed-in session; the raw key is returned only in this response.
    """
    dataset = await _writable_dataset(db, dataset_id, user)
    if not capabilities(dataset.record.record_type).feature_table:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Only a dataset with features can have a dataset key",
        )
    api_key, raw_key = await create_api_key_for_user(
        db,
        user.id,
        body.name,
        expires_at=body.expires_at,
        scope="dataset_write",
        dataset_id=dataset_id,
    )
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="api_key.create",
            resource_type="api_key",
            resource_id=api_key.id,
            details={
                "name": body.name,
                "fingerprint": api_key.fingerprint,
                "expires_at": body.expires_at.isoformat(),
                "scope": api_key.scope,
                "dataset_id": str(dataset_id),
            },
            ip_address=get_client_ip(request),
        ),
    )
    await db.commit()

    assert api_key.fingerprint is not None  # New keys always receive a fingerprint.
    return ApiKeyCreateResponse(
        id=api_key.id,
        key=raw_key,
        fingerprint=api_key.fingerprint,
        name=api_key.name,
        expires_at=api_key.expires_at,
        scope=api_key.scope,
        dataset_id=api_key.dataset_id,
        created_at=api_key.created_at,
    )


@router.get("/{dataset_id}/api-keys", response_model=ApiKeyListResponse)
async def list_dataset_api_keys(
    dataset_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyListResponse:
    """List the caller's active keys bound to this dataset, newest first.

    Requires write access to the dataset. Revoke a key with
    ``DELETE /auth/api-keys/{key_id}``.
    """
    await _writable_dataset(db, dataset_id, user)
    base_stmt = select(ApiKey).where(
        ApiKey.user_id == user.id,
        ApiKey.dataset_id == dataset_id,
        ApiKey.is_active == True,  # noqa: E712
    )
    total = (
        await db.execute(select(func.count()).select_from(base_stmt.subquery()))
    ).scalar_one()
    keys = (
        (
            await db.execute(
                base_stmt.order_by(ApiKey.created_at.desc(), ApiKey.id.desc())
                .offset(skip)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return ApiKeyListResponse(
        items=[
            ApiKeyListItem(
                id=k.id,
                name=k.name,
                fingerprint=k.fingerprint,
                is_active=k.is_active,
                expires_at=k.expires_at,
                scope=k.scope,
                dataset_id=k.dataset_id,
                created_at=k.created_at,
                last_used_at=k.last_used_at,
            )
            for k in keys
        ],
        total=total,
    )
