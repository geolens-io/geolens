"""CRUD API endpoints for record sub-resources: contacts, keywords, distributions."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_optional_user, require_permission
from app.auth.models import User
from app.dependencies import get_db
from app.records.schemas import (
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
from app.records.service import (
    create_contact,
    create_distribution,
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

router = APIRouter(prefix="/records", tags=["Records"])


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------


@router.get("/{record_id}/contacts/", response_model=ContactListResponse)
async def list_contacts_endpoint(
    record_id: uuid.UUID,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> ContactListResponse:
    """List all contacts for a record."""
    record = await get_record(db, record_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Record not found"
        )
    if user is None and (
        record.visibility != "public" or record.record_status != "published"
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Record not found"
        )
    contacts = await list_contacts(db, record_id)
    return ContactListResponse(
        contacts=[ContactResponse.model_validate(c) for c in contacts],
        total=len(contacts),
    )


@router.post(
    "/{record_id}/contacts/",
    response_model=ContactResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_contact_endpoint(
    record_id: uuid.UUID,
    body: ContactCreate,
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> ContactResponse:
    """Create a new contact for a record."""
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
    return ContactResponse.model_validate(contact)


@router.patch("/{record_id}/contacts/{contact_id}/", response_model=ContactResponse)
async def update_contact_endpoint(
    record_id: uuid.UUID,
    contact_id: uuid.UUID,
    body: ContactUpdate,
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> ContactResponse:
    """Update a contact."""
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
    return ContactResponse.model_validate(contact)


@router.delete(
    "/{record_id}/contacts/{contact_id}/", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_contact_endpoint(
    record_id: uuid.UUID,
    contact_id: uuid.UUID,
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete a contact."""
    try:
        await delete_contact(db, contact_id)
        await db.commit()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found"
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Keywords
# ---------------------------------------------------------------------------


@router.get("/{record_id}/keywords/", response_model=KeywordListResponse)
async def list_keywords_endpoint(
    record_id: uuid.UUID,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> KeywordListResponse:
    """List all keywords for a record."""
    record = await get_record(db, record_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Record not found"
        )
    if user is None and (
        record.visibility != "public" or record.record_status != "published"
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Record not found"
        )
    keywords = await list_keywords(db, record_id)
    return KeywordListResponse(
        keywords=[KeywordResponse.model_validate(k) for k in keywords],
        total=len(keywords),
    )


@router.post(
    "/{record_id}/keywords/",
    response_model=KeywordResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_keyword_endpoint(
    record_id: uuid.UUID,
    body: KeywordCreate,
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> KeywordResponse:
    """Create a new keyword for a record."""
    try:
        kw = await create_keyword(
            db,
            record_id,
            keyword=body.keyword,
            vocabulary_uri=body.vocabulary_uri,
            keyword_type=body.keyword_type,
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
    return KeywordResponse.model_validate(kw)


@router.delete(
    "/{record_id}/keywords/{keyword_id}/", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_keyword_endpoint(
    record_id: uuid.UUID,
    keyword_id: uuid.UUID,
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete a keyword."""
    try:
        await delete_keyword(db, keyword_id)
        await db.commit()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Keyword not found"
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Distributions
# ---------------------------------------------------------------------------


@router.get("/{record_id}/distributions/", response_model=DistributionListResponse)
async def list_distributions_endpoint(
    record_id: uuid.UUID,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> DistributionListResponse:
    """List all distributions for a record."""
    record = await get_record(db, record_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Record not found"
        )
    if user is None and (
        record.visibility != "public" or record.record_status != "published"
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Record not found"
        )
    distributions = await list_distributions(db, record_id)
    return DistributionListResponse(
        distributions=[DistributionResponse.model_validate(d) for d in distributions],
        total=len(distributions),
    )


@router.post(
    "/{record_id}/distributions/",
    response_model=DistributionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_distribution_endpoint(
    record_id: uuid.UUID,
    body: DistributionCreate,
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> DistributionResponse:
    """Create a manual distribution for a record."""
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
    return DistributionResponse.model_validate(dist)


@router.patch(
    "/{record_id}/distributions/{distribution_id}/",
    response_model=DistributionResponse,
)
async def update_distribution_endpoint(
    record_id: uuid.UUID,
    distribution_id: uuid.UUID,
    body: DistributionUpdate,
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> DistributionResponse:
    """Update a distribution (manual only; auto-generated distributions are immutable)."""
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
    return DistributionResponse.model_validate(dist)


@router.delete(
    "/{record_id}/distributions/{distribution_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_distribution_endpoint(
    record_id: uuid.UUID,
    distribution_id: uuid.UUID,
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete a distribution (manual only; auto-generated distributions are immutable)."""
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
    return Response(status_code=status.HTTP_204_NO_CONTENT)
