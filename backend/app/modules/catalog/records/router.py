"""CRUD API endpoints for record sub-resources: contacts, keywords, distributions."""

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.identity import Identity
from app.modules.auth.dependencies import get_optional_user, require_permission
from app.modules.catalog.authorization import (
    check_dataset_access_or_anonymous,
    get_user_roles,
)
from app.core.dependencies import get_db
from app.platform.cache.tiles import invalidate_catalog_cache
from app.platform.extensions import get_catalog_port
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.catalog.records.schemas import (
    ContactCreate,
    ContactListResponse,
    ContactResponse,
    ContactUpdate,
    DistributionCreate,
    DistributionListResponse,
    DistributionResponse,
    DistributionUpdate,
    KeywordCreate,
    KeywordListResponse,
    KeywordResponse,
)
from app.modules.catalog.records.service import (
    create_contact,
    create_distribution,
    count_contacts,
    count_distributions,
    count_keywords,
    create_keyword,
    delete_contact,
    delete_distribution,
    delete_keyword,
    get_record,
    list_contacts,
    list_distributions,
    list_keywords,
    update_contact,
    update_distribution,
)
from app.standards.ogc.errors import ERROR_RESPONSES_WRITE

logger = structlog.get_logger()

router = APIRouter(prefix="/records", tags=["Records"], responses=ERROR_RESPONSES_WRITE)


async def _propagate_record_write(record_id: uuid.UUID, *, reembed: bool) -> None:
    """Keep downstream surfaces coherent after a record sub-resource write.

    fix(#458 E-15): contacts/keywords/distributions feed the DCAT-US/STAC feeds
    (so bust the catalog cache on every write), and keywords are part of the
    search embedding text (so re-embed when keywords changed). The top-level
    metadata PATCH already does both; these sibling writes did neither. Both
    steps are best-effort — the write is already committed and must not fail on a
    cache/broker hiccup.
    """
    try:
        await invalidate_catalog_cache()
    except Exception:  # broad: cache bust is non-fatal; entries expire on TTL
        logger.warning("record.write catalog-cache invalidation failed", exc_info=True)
    if reembed:
        try:
            await get_catalog_port().defer_embed_record(record_id)
        except Exception:  # broad: embedding catches up on next edit or backfill
            logger.warning(
                "record.write embed defer failed for %s", record_id, exc_info=True
            )


async def _check_record_read_access(
    db: AsyncSession,
    record_id: uuid.UUID,
    user: Identity | None,
) -> None:
    """Verify the record is visible to the caller. Raises 404 on denial.

    Record sub-resources (contacts/keywords/distributions) carry the same
    visibility as the dataset they back, so authorization is delegated to the
    shared per-dataset RBAC the dataset endpoints use — public/private/
    restricted, owner, admin, and anonymous (public+published only), including
    grants. This closes the gap where ANY authenticated user could read a
    private record by gating only `user is None`.
    """
    record = await get_record(db, record_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Record not found"
        )

    # Delegate to the dataset that backs this record, mirroring the dataset
    # read endpoints (get_dataset + check_dataset_access_or_anonymous).
    dataset = (
        (
            await db.execute(
                select(Dataset)
                .options(joinedload(Dataset.record))
                .where(Dataset.record_id == record_id)
            )
        )
        .scalars()
        .first()
    )
    if dataset is not None:
        try:
            await check_dataset_access_or_anonymous(db, dataset, dataset.id, user)
        except HTTPException:
            # Normalize the denial to the record's own 404 (don't leak that a
            # backing dataset exists).
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Record not found"
            )
        return

    # Orphan record with no backing dataset (e.g. mid-ingest): only public +
    # published is world-readable; otherwise owner or admin only.
    if record.visibility == "public" and record.record_status == "published":
        return
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Record not found"
        )
    if record.created_by == user.id:
        return
    if "admin" in await get_user_roles(db, user):
        return
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Record not found"
    )


async def _check_record_ownership(
    db: AsyncSession, record_id: uuid.UUID, user: Identity
) -> Record:
    """Verify the user owns the record or is an admin. Raises 404/403.

    Returns the fetched Record so callers can reuse it without a second query.

    fix(#458 E-14): gate on read-visibility first, so a private record the caller
    can't even see 404s (no existence leak) instead of 403 — matching the dataset
    PATCH IDOR contract (test_dataset_metadata_idor). A record the caller CAN see
    but doesn't own still 403s (an honest "you can't edit this").
    """
    await _check_record_read_access(db, record_id, user)
    record = await get_record(db, record_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Record not found"
        )
    if record.created_by == user.id:
        return record
    user_roles = await get_user_roles(db, user)
    if "admin" in user_roles:
        return record
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Not authorized to modify this record",
    )


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------


@router.get("/{record_id}/contacts/", response_model=ContactListResponse)
async def list_contacts_endpoint(
    record_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> ContactListResponse:
    """List all contacts for a record."""
    await _check_record_read_access(db, record_id, user)
    contacts, total = (
        await list_contacts(db, record_id, skip=skip, limit=limit),
        await count_contacts(db, record_id),
    )
    return ContactListResponse(
        contacts=[ContactResponse.model_validate(c) for c in contacts],
        total=total,
    )


@router.post(
    "/{record_id}/contacts/",
    response_model=ContactResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_contact_endpoint(
    record_id: uuid.UUID,
    body: ContactCreate,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> ContactResponse:
    """Create a new contact for a record."""
    record = await _check_record_ownership(db, record_id, user)
    try:
        contact = await create_contact(
            db,
            record_id,
            role=body.role,
            name=body.name,
            email=body.email,
            organization=body.organization,
            phone=body.phone,
            extra_json=body.extra_json,
            sort_order=body.sort_order,
            record=record,
        )
        await db.commit()
        await db.refresh(contact)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Record not found"
        )
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid contact data (check role value against ISO CI_RoleCode codelist)",
        )
    await _propagate_record_write(record_id, reembed=False)
    return ContactResponse.model_validate(contact)


@router.patch("/{record_id}/contacts/{contact_id}/", response_model=ContactResponse)
async def update_contact_endpoint(
    record_id: uuid.UUID,
    contact_id: uuid.UUID,
    body: ContactUpdate,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> ContactResponse:
    """Update a contact."""
    await _check_record_ownership(db, record_id, user)
    try:
        contact = await update_contact(
            db, contact_id, **body.model_dump(exclude_none=True)
        )
        await db.commit()
        await db.refresh(contact)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found"
        )
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid contact data (check role value against ISO CI_RoleCode codelist)",
        )
    await _propagate_record_write(record_id, reembed=False)
    return ContactResponse.model_validate(contact)


@router.delete(
    "/{record_id}/contacts/{contact_id}/", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_contact_endpoint(
    record_id: uuid.UUID,
    contact_id: uuid.UUID,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete a contact."""
    await _check_record_ownership(db, record_id, user)
    try:
        await delete_contact(db, contact_id)
        await db.commit()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found"
        )
    await _propagate_record_write(record_id, reembed=False)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Keywords
# ---------------------------------------------------------------------------


@router.get("/{record_id}/keywords/", response_model=KeywordListResponse)
async def list_keywords_endpoint(
    record_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> KeywordListResponse:
    """List all keywords for a record."""
    await _check_record_read_access(db, record_id, user)
    keywords, total = (
        await list_keywords(db, record_id, skip=skip, limit=limit),
        await count_keywords(db, record_id),
    )
    return KeywordListResponse(
        keywords=[KeywordResponse.model_validate(k) for k in keywords],
        total=total,
    )


@router.post(
    "/{record_id}/keywords/",
    response_model=KeywordResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_keyword_endpoint(
    record_id: uuid.UUID,
    body: KeywordCreate,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> KeywordResponse:
    """Create a new keyword for a record."""
    record = await _check_record_ownership(db, record_id, user)
    try:
        kw = await create_keyword(
            db,
            record_id,
            keyword=body.keyword,
            vocabulary_uri=body.vocabulary_uri,
            keyword_type=body.keyword_type,
            record=record,
        )
        await db.commit()
        await db.refresh(kw)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Record not found"
        )
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Duplicate keyword for this record",
        )
    await _propagate_record_write(record_id, reembed=True)
    return KeywordResponse.model_validate(kw)


@router.delete(
    "/{record_id}/keywords/{keyword_id}/", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_keyword_endpoint(
    record_id: uuid.UUID,
    keyword_id: uuid.UUID,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete a keyword."""
    await _check_record_ownership(db, record_id, user)
    try:
        await delete_keyword(db, keyword_id)
        await db.commit()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Keyword not found"
        )
    await _propagate_record_write(record_id, reembed=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Distributions
# ---------------------------------------------------------------------------


@router.get("/{record_id}/distributions/", response_model=DistributionListResponse)
async def list_distributions_endpoint(
    record_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> DistributionListResponse:
    """List all distributions for a record."""
    await _check_record_read_access(db, record_id, user)
    distributions, total = (
        await list_distributions(db, record_id, skip=skip, limit=limit),
        await count_distributions(db, record_id),
    )
    return DistributionListResponse(
        distributions=[DistributionResponse.model_validate(d) for d in distributions],
        total=total,
    )


@router.post(
    "/{record_id}/distributions/",
    response_model=DistributionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_distribution_endpoint(
    record_id: uuid.UUID,
    body: DistributionCreate,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> DistributionResponse:
    """Create a manual distribution for a record."""
    record = await _check_record_ownership(db, record_id, user)
    try:
        dist = await create_distribution(
            db,
            record_id,
            distribution_type=body.distribution_type,
            format=body.format,
            url=body.url,
            title=body.title,
            description=body.description,
            protocol=body.protocol,
            media_type=body.media_type,
            is_primary=body.is_primary,
            record=record,
        )
        await db.commit()
        await db.refresh(dist)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Record not found"
        )
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Duplicate distribution (same record, type, and format)",
        )
    await _propagate_record_write(record_id, reembed=False)
    return DistributionResponse.model_validate(dist)


@router.patch(
    "/{record_id}/distributions/{distribution_id}/",
    response_model=DistributionResponse,
)
async def update_distribution_endpoint(
    record_id: uuid.UUID,
    distribution_id: uuid.UUID,
    body: DistributionUpdate,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> DistributionResponse:
    """Update a distribution (manual only; auto-generated distributions are immutable)."""
    await _check_record_ownership(db, record_id, user)
    try:
        dist = await update_distribution(
            db, distribution_id, **body.model_dump(exclude_none=True)
        )
        await db.commit()
        await db.refresh(dist)
    except ValueError as e:
        if "auto-generated" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot update auto-generated distributions",
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Distribution not found"
        )
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Duplicate distribution (same record, type, and format)",
        )
    await _propagate_record_write(record_id, reembed=False)
    return DistributionResponse.model_validate(dist)


@router.delete(
    "/{record_id}/distributions/{distribution_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_distribution_endpoint(
    record_id: uuid.UUID,
    distribution_id: uuid.UUID,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete a distribution (manual only; auto-generated distributions are immutable)."""
    await _check_record_ownership(db, record_id, user)
    try:
        await delete_distribution(db, distribution_id)
        await db.commit()
    except ValueError as e:
        if "auto-generated" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete auto-generated distributions",
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Distribution not found"
        )
    await _propagate_record_write(record_id, reembed=False)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
