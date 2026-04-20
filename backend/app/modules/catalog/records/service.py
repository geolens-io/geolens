"""Service layer for record sub-resources: contacts, keywords, distributions.

The normalized tables (record_contacts, record_keywords, record_distributions) are
the single authoritative metadata path. No dual-write to legacy JSONB/tags columns.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.domain.models import (
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
    session: AsyncSession,
    record_id: uuid.UUID,
    *,
    skip: int = 0,
    limit: int = 100,
) -> list[RecordContact]:
    """List contacts for a record, ordered by sort_order, with pagination."""
    result = await session.execute(
        select(RecordContact)
        .where(RecordContact.record_id == record_id)
        .order_by(RecordContact.sort_order)
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def count_contacts(session: AsyncSession, record_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(RecordContact)
        .where(RecordContact.record_id == record_id)
    )
    return result.scalar_one()


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
    record: Record | None = None,
) -> RecordContact:
    """Create a new contact for a record."""
    if record is None:
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
    session: AsyncSession,
    record_id: uuid.UUID,
    *,
    skip: int = 0,
    limit: int = 100,
) -> list[RecordKeyword]:
    """List keywords for a record, with pagination."""
    result = await session.execute(
        select(RecordKeyword)
        .where(RecordKeyword.record_id == record_id)
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def count_keywords(session: AsyncSession, record_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(RecordKeyword)
        .where(RecordKeyword.record_id == record_id)
    )
    return result.scalar_one()


async def create_keyword(
    session: AsyncSession,
    record_id: uuid.UUID,
    *,
    keyword: str,
    vocabulary_uri: str | None = None,
    keyword_type: str = "theme",
    record: Record | None = None,
) -> RecordKeyword:
    """Create a new keyword for a record.

    Normalizes before insert: keyword text stripped and lowercased,
    vocabulary_uri stripped and trailing slashes removed.
    """
    if record is None:
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
    session: AsyncSession,
    record_id: uuid.UUID,
    *,
    skip: int = 0,
    limit: int = 100,
) -> list[RecordDistribution]:
    """List distributions for a record, with pagination."""
    result = await session.execute(
        select(RecordDistribution)
        .where(RecordDistribution.record_id == record_id)
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def count_distributions(session: AsyncSession, record_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(RecordDistribution)
        .where(RecordDistribution.record_id == record_id)
    )
    return result.scalar_one()


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
    record: Record | None = None,
) -> RecordDistribution:
    """Create a manual distribution for a record."""
    if record is None:
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
    geometry_type: str | None = None,
) -> list[RecordDistribution]:
    """Generate standard distribution records for a dataset.

    For spatial datasets (geometry_type is not None): creates 6 distribution rows
    (4 download formats + OGC features + vector tiles).
    For non-spatial datasets (geometry_type is None): creates only csv download
    + OGC features (2 rows).

    All are marked auto_generated=True. Uses merge semantics: existing rows with
    the same (record_id, distribution_type, format) are left untouched (INSERT ON
    CONFLICT DO NOTHING equivalent via check-then-insert).

    Args:
        dataset_id: Dataset PK (used in URL paths).
        record_id: Record PK (FK in record_distributions).
        table_name: Dataset table name (used in vector tile URL).
        geometry_type: Geometry type string, or None for non-spatial datasets.
    """
    # Fetch all existing distributions for this record in a single query
    existing_result = await session.execute(
        select(
            RecordDistribution.distribution_type,
            RecordDistribution.format,
        ).where(RecordDistribution.record_id == record_id)
    )
    existing_set = {(row[0], row[1]) for row in existing_result.all()}

    # Build all new distributions in one list so they can be flushed in a
    # single batch rather than as individual INSERT statements. SQLAlchemy 2.0
    # batches `add_all()` + `flush()` via insertmanyvalues when supported.
    to_add: list[RecordDistribution] = []

    for (
        dist_type,
        fmt,
        url_tpl,
        title,
        protocol,
        media_type,
        is_primary,
    ) in _DISTRIBUTION_TEMPLATES:
        # Non-spatial datasets: only csv download + ogc_features
        if geometry_type is None:
            if not (
                (dist_type == "download" and fmt == "csv")
                or dist_type == "ogc_features"
            ):
                continue

        # Skip if already exists
        if (dist_type, fmt) in existing_set:
            continue

        url = url_tpl.format(dataset_id=dataset_id)

        # For non-spatial datasets, CSV download becomes primary (gpkg is filtered out)
        effective_primary = is_primary
        if geometry_type is None and dist_type == "download" and fmt == "csv":
            effective_primary = True

        to_add.append(
            RecordDistribution(
                record_id=record_id,
                distribution_type=dist_type,
                format=fmt,
                url=url,
                title=title,
                protocol=protocol,
                media_type=media_type,
                is_primary=effective_primary,
                auto_generated=True,
            )
        )

    # Vector tiles (uses table_name, not dataset_id) — skip for non-spatial datasets
    if geometry_type is not None and ("vector_tiles", "pbf") not in existing_set:
        to_add.append(
            RecordDistribution(
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
        )

    if to_add:
        session.add_all(to_add)
        await session.flush()
    return to_add
