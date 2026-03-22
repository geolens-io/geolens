"""Service layer for record sub-resources: contacts, keywords, distributions.

The normalized tables (record_contacts, record_keywords, record_distributions) are
the single authoritative metadata path. No dual-write to legacy JSONB/tags columns.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.datasets.models import (
    Record,
    RecordContact,
    RecordDistribution,
    RecordKeyword,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def get_record(session: AsyncSession, record_id: uuid.UUID) -> Record | None:
    """Fetch a record by ID."""
    result = await session.execute(select(Record).where(Record.id == record_id))
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------


async def list_contacts(
    session: AsyncSession, record_id: uuid.UUID
) -> list[RecordContact]:
    """List all contacts for a record, ordered by sort_order."""
    result = await session.execute(
        select(RecordContact)
        .where(RecordContact.record_id == record_id)
        .order_by(RecordContact.sort_order)
    )
    return list(result.scalars().all())


async def create_contact(
    session: AsyncSession,
    record_id: uuid.UUID,
    *,
    role: str,
    name: str | None = None,
    email: str | None = None,
    organization: str | None = None,
    phone: str | None = None,
    extra_json: dict | None = None,
    sort_order: int = 0,
) -> RecordContact:
    """Create a new contact for a record."""
    record = await get_record(session, record_id)
    if record is None:
        raise ValueError(f"Record {record_id} not found")

    contact = RecordContact(
        record_id=record_id,
        role=role,
        name=name,
        email=email,
        organization=organization,
        phone=phone,
        extra_json=extra_json,
        sort_order=sort_order,
    )
    session.add(contact)
    await session.flush()
    return contact


async def update_contact(
    session: AsyncSession,
    contact_id: uuid.UUID,
    **kwargs,
) -> RecordContact:
    """Update a contact. Only non-None fields are updated."""
    result = await session.execute(
        select(RecordContact).where(RecordContact.id == contact_id)
    )
    contact = result.scalar_one_or_none()
    if contact is None:
        raise ValueError(f"Contact {contact_id} not found")

    for key, value in kwargs.items():
        if value is not None:
            setattr(contact, key, value)

    await session.flush()
    return contact


async def delete_contact(session: AsyncSession, contact_id: uuid.UUID) -> None:
    """Delete a contact by ID."""
    result = await session.execute(
        select(RecordContact).where(RecordContact.id == contact_id)
    )
    contact = result.scalar_one_or_none()
    if contact is None:
        raise ValueError(f"Contact {contact_id} not found")

    await session.delete(contact)
    await session.flush()


# ---------------------------------------------------------------------------
# Keywords
# ---------------------------------------------------------------------------


async def list_keywords(
    session: AsyncSession, record_id: uuid.UUID
) -> list[RecordKeyword]:
    """List all keywords for a record."""
    result = await session.execute(
        select(RecordKeyword).where(RecordKeyword.record_id == record_id)
    )
    return list(result.scalars().all())


async def create_keyword(
    session: AsyncSession,
    record_id: uuid.UUID,
    *,
    keyword: str,
    vocabulary_uri: str | None = None,
    keyword_type: str = "theme",
) -> RecordKeyword:
    """Create a new keyword for a record.

    Normalizes before insert: keyword text stripped and lowercased,
    vocabulary_uri stripped and trailing slashes removed.
    """
    record = await get_record(session, record_id)
    if record is None:
        raise ValueError(f"Record {record_id} not found")

    # Normalize
    keyword = keyword.strip().lower()
    if vocabulary_uri is not None:
        vocabulary_uri = vocabulary_uri.strip().rstrip("/")

    kw = RecordKeyword(
        record_id=record_id,
        keyword=keyword,
        vocabulary_uri=vocabulary_uri,
        keyword_type=keyword_type,
    )
    session.add(kw)
    await session.flush()
    return kw


async def delete_keyword(session: AsyncSession, keyword_id: uuid.UUID) -> None:
    """Delete a keyword by ID."""
    result = await session.execute(
        select(RecordKeyword).where(RecordKeyword.id == keyword_id)
    )
    kw = result.scalar_one_or_none()
    if kw is None:
        raise ValueError(f"Keyword {keyword_id} not found")

    await session.delete(kw)
    await session.flush()


# ---------------------------------------------------------------------------
# Distributions
# ---------------------------------------------------------------------------


async def list_distributions(
    session: AsyncSession, record_id: uuid.UUID
) -> list[RecordDistribution]:
    """List all distributions for a record."""
    result = await session.execute(
        select(RecordDistribution).where(RecordDistribution.record_id == record_id)
    )
    return list(result.scalars().all())


async def create_distribution(
    session: AsyncSession,
    record_id: uuid.UUID,
    *,
    distribution_type: str,
    format: str,
    url: str,
    title: str | None = None,
    description: str | None = None,
    protocol: str | None = None,
    media_type: str | None = None,
    is_primary: bool = False,
) -> RecordDistribution:
    """Create a manual distribution for a record."""
    record = await get_record(session, record_id)
    if record is None:
        raise ValueError(f"Record {record_id} not found")

    dist = RecordDistribution(
        record_id=record_id,
        distribution_type=distribution_type,
        format=format,
        url=url,
        title=title,
        description=description,
        protocol=protocol,
        media_type=media_type,
        is_primary=is_primary,
        auto_generated=False,
    )
    session.add(dist)
    await session.flush()
    return dist


async def update_distribution(
    session: AsyncSession,
    distribution_id: uuid.UUID,
    **kwargs,
) -> RecordDistribution:
    """Update a distribution. Only non-None fields are updated.

    Auto-generated distributions cannot be updated (raises ValueError).
    """
    result = await session.execute(
        select(RecordDistribution).where(RecordDistribution.id == distribution_id)
    )
    dist = result.scalar_one_or_none()
    if dist is None:
        raise ValueError(f"Distribution {distribution_id} not found")

    if dist.auto_generated:
        raise ValueError("Cannot update auto-generated distributions")

    for key, value in kwargs.items():
        if value is not None:
            setattr(dist, key, value)

    await session.flush()
    return dist


async def delete_distribution(
    session: AsyncSession, distribution_id: uuid.UUID
) -> None:
    """Delete a distribution by ID.

    Auto-generated distributions cannot be deleted (raises ValueError).
    """
    result = await session.execute(
        select(RecordDistribution).where(RecordDistribution.id == distribution_id)
    )
    dist = result.scalar_one_or_none()
    if dist is None:
        raise ValueError(f"Distribution {distribution_id} not found")

    if dist.auto_generated:
        raise ValueError("Cannot delete auto-generated distributions")

    await session.delete(dist)
    await session.flush()


# ---------------------------------------------------------------------------
# Distribution generation
# ---------------------------------------------------------------------------

# Standard distribution templates: (distribution_type, format, url_template, title, protocol, media_type, is_primary)
_DISTRIBUTION_TEMPLATES = [
    (
        "download",
        "gpkg",
        "/datasets/{dataset_id}/export?format=gpkg",
        "GeoPackage Download",
        "HTTP",
        "application/geopackage+sqlite3",
        True,
    ),
    (
        "download",
        "geojson",
        "/datasets/{dataset_id}/export?format=geojson",
        "GeoJSON Download",
        "HTTP",
        "application/geo+json",
        False,
    ),
    (
        "download",
        "shp",
        "/datasets/{dataset_id}/export?format=shp",
        "Shapefile Download",
        "HTTP",
        "application/zip",
        False,
    ),
    (
        "download",
        "csv",
        "/datasets/{dataset_id}/export?format=csv",
        "CSV Download",
        "HTTP",
        "text/csv",
        False,
    ),
    (
        "ogc_features",
        "geojson",
        "/collections/{dataset_id}/items",
        "OGC API Features",
        "OGC:OAFeat",
        "application/geo+json",
        False,
    ),
]


async def generate_distributions(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    record_id: uuid.UUID,
    table_name: str,
) -> list[RecordDistribution]:
    """Generate standard distribution records for a dataset.

    Creates 6 distribution rows (4 download formats + OGC features + vector tiles).
    All are marked auto_generated=True. Uses merge semantics: existing rows with
    the same (record_id, distribution_type, format) are left untouched (INSERT ON
    CONFLICT DO NOTHING equivalent via check-then-insert).

    Args:
        dataset_id: Dataset PK (used in URL paths).
        record_id: Record PK (FK in record_distributions).
        table_name: Dataset table name (used in vector tile URL).
    """
    created = []

    for (
        dist_type,
        fmt,
        url_tpl,
        title,
        protocol,
        media_type,
        is_primary,
    ) in _DISTRIBUTION_TEMPLATES:
        url = url_tpl.format(dataset_id=dataset_id)

        # Check if already exists
        existing = await session.execute(
            select(RecordDistribution).where(
                RecordDistribution.record_id == record_id,
                RecordDistribution.distribution_type == dist_type,
                RecordDistribution.format == fmt,
            )
        )
        if existing.scalar_one_or_none() is not None:
            continue

        dist = RecordDistribution(
            record_id=record_id,
            distribution_type=dist_type,
            format=fmt,
            url=url,
            title=title,
            protocol=protocol,
            media_type=media_type,
            is_primary=is_primary,
            auto_generated=True,
        )
        session.add(dist)
        created.append(dist)

    # Vector tiles (uses table_name, not dataset_id)
    existing = await session.execute(
        select(RecordDistribution).where(
            RecordDistribution.record_id == record_id,
            RecordDistribution.distribution_type == "vector_tiles",
            RecordDistribution.format == "pbf",
        )
    )
    if existing.scalar_one_or_none() is None:
        tile_dist = RecordDistribution(
            record_id=record_id,
            distribution_type="vector_tiles",
            format="pbf",
            url=f"/tiles/data.{table_name}/{{z}}/{{x}}/{{y}}.pbf",
            title="Vector Tiles",
            protocol="OGC:WMTS",
            media_type="application/vnd.mapbox-vector-tile",
            is_primary=False,
            auto_generated=True,
        )
        session.add(tile_dist)
        created.append(tile_dist)

    await session.flush()
    return created
