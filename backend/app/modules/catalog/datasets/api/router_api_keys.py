"""Mint, list and revoke API keys bound to one dataset."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_client_ip, get_db
from app.core.identity import Identity
from app.core.record_types import capabilities
from app.modules.audit.service import AuditEvent, audit_emit
from app.modules.auth.dependencies import (
    get_current_active_user,
    require_permission,
    require_session_credential,
)
from app.modules.auth.models import ApiKey
from app.modules.auth.schemas import (
    ApiKeyCreateResponse,
    DatasetApiKeyCreateRequest,
    DatasetApiKeyListItem,
    DatasetApiKeyListResponse,
)
from app.modules.auth.service import create_api_key_for_user
from app.modules.catalog.authorization import (
    check_dataset_access,
    check_dataset_write_access,
    lock_dataset_rows_for_write,
)
from app.modules.catalog.datasets.domain.service import get_dataset
from app.platform.ratelimit import limiter
from app.standards.ogc.errors import ERROR_RESPONSES_WRITE

router = APIRouter(
    prefix="/datasets", tags=["Datasets"], responses=ERROR_RESPONSES_WRITE
)

# Unrevoked keys a dataset may hold, expired ones included. The card lists
# them all in one page of the list endpoint.
DATASET_KEY_LIMIT = 100
DATASET_KEY_LIMIT_REACHED = (
    f"This dataset already has {DATASET_KEY_LIMIT} active keys. "
    "Revoke one to create another."
)


async def _found_dataset(db: AsyncSession, dataset_id: uuid.UUID):
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    return dataset


@router.post(
    "/{dataset_id}/api-keys",
    response_model=ApiKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("30/minute")
async def create_dataset_api_key(
    dataset_id: uuid.UUID,
    body: DatasetApiKeyCreateRequest,
    request: Request,
    user: Identity = Depends(require_session_credential),
    _editor: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyCreateResponse:
    """Create a key that reads and writes this dataset's features only.

    The key has scope ``dataset_write`` and acts as the caller, so the
    caller's own access to the dataset still applies to every request it
    makes. It authenticates the dataset's feature routes and OGC API
    Features items, and is treated as an invalid key everywhere else. Its
    feature writes go through even when the instance has dataset editing
    switched off. It must expire within 365 days. Requires write access to the
    dataset, the ``edit_metadata`` permission the feature writes need, and a
    signed-in session. A dataset that can't take feature edits (no feature
    table or no geometry column) gets 422. A dataset holds at most 100 keys
    that aren't revoked, expired ones included; minting past that gets 409
    until one is revoked. The raw key is returned only in this response.
    """
    dataset = await _found_dataset(db, dataset_id)
    await check_dataset_write_access(db, dataset, dataset_id, user)
    # The feature write handlers refuse these two cases, so a key minted for
    # either could never write.
    if (
        not capabilities(dataset.record.record_type).feature_table
        or dataset.geometry_type is None
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Only a dataset that takes feature edits can have a dataset key",
        )
    # Under the dataset's row lock, so two mints can't both take the last slot.
    await lock_dataset_rows_for_write(db, dataset)
    held = (
        await db.execute(
            select(func.count())
            .select_from(ApiKey)
            .where(
                ApiKey.dataset_id == dataset_id,
                ApiKey.is_active == True,  # noqa: E712
            )
        )
    ).scalar_one()
    if held >= DATASET_KEY_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=DATASET_KEY_LIMIT_REACHED
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


@router.get("/{dataset_id}/api-keys", response_model=DatasetApiKeyListResponse)
async def list_dataset_api_keys(
    dataset_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> DatasetApiKeyListResponse:
    """List the active keys bound to this dataset, newest first.

    Requires write access to the dataset. The dataset's owner and admins see
    every key bound to it, anyone else only their own. Expired keys stay
    listed until revoked.
    """
    dataset = await _found_dataset(db, dataset_id)
    roles = await check_dataset_write_access(db, dataset, dataset_id, user)
    base_stmt = select(ApiKey).where(
        ApiKey.dataset_id == dataset_id,
        ApiKey.is_active == True,  # noqa: E712
    )
    if dataset.record.created_by != user.id and "admin" not in roles:
        base_stmt = base_stmt.where(ApiKey.user_id == user.id)
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
    return DatasetApiKeyListResponse(
        items=[
            DatasetApiKeyListItem(
                id=k.id,
                name=k.name,
                fingerprint=k.fingerprint,
                is_active=k.is_active,
                expires_at=k.expires_at,
                scope=k.scope,
                dataset_id=k.dataset_id,
                created_at=k.created_at,
                last_used_at=k.last_used_at,
                user_id=k.user_id,
                username=k.user.username,
            )
            for k in keys
        ],
        total=total,
    )


@router.delete(
    "/{dataset_id}/api-keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def revoke_dataset_api_key(
    dataset_id: uuid.UUID,
    key_id: uuid.UUID,
    request: Request,
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Revoke a key bound to this dataset.

    The key's creator may revoke it while they can see the dataset, even
    after losing write access to it; anyone with write access may revoke any
    key bound to it, checked again under the dataset's row lock. Answers 404
    when no active key with this id is bound to the dataset.
    """
    dataset = await _found_dataset(db, dataset_id)
    api_key = (
        await db.execute(
            select(ApiKey).where(
                ApiKey.id == key_id,
                ApiKey.dataset_id == dataset_id,
                ApiKey.is_active == True,  # noqa: E712
            )
        )
    ).scalar_one_or_none()
    if api_key is not None and api_key.user_id == user.id:
        await check_dataset_access(db, dataset, dataset_id, user)
    else:
        await check_dataset_write_access(db, dataset, dataset_id, user)
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="API key not found"
        )
    if api_key.user_id != user.id:
        await lock_dataset_rows_for_write(db, dataset)
    api_key.is_active = False
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="api_key.revoke",
            resource_type="api_key",
            resource_id=api_key.id,
            details={
                "name": api_key.name,
                "fingerprint": api_key.fingerprint,
                "dataset_id": str(dataset_id),
                "key_user_id": str(api_key.user_id),
            },
            ip_address=get_client_ip(request),
        ),
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
