"""Service layer for record sub-resources: contacts, keywords, distributions.

The normalized tables (record_contacts, record_keywords, record_distributions) are
the single authoritative metadata path. No dual-write to legacy JSONB/tags columns.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.domain.models import (
    Record,
    RecordContact,
    RecordDistribution,
    RecordKeyword,
    RecordTranslation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def get_record(session: AsyncSession, record_id: uuid.UUID) -> Record | None:
    """Fetch a record by ID."""
    result = await session.execute(select(Record).where(Record.id == record_id))
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Localized record text
# ---------------------------------------------------------------------------


async def list_translations(
    session: AsyncSession, record_id: uuid.UUID
) -> list[RecordTranslation]:
    result = await session.execute(
        select(RecordTranslation)
        .where(RecordTranslation.record_id == record_id)
        .order_by(RecordTranslation.language)
    )
    return list(result.scalars().all())


async def upsert_translation(
    session: AsyncSession,
    record_id: uuid.UUID,
    *,
    language: str,
    title: str,
    summary: str | None,
    record: Record | None = None,
) -> RecordTranslation:
    if record is None:
        record = await get_record(session, record_id)
    if record is None:
        raise ValueError(f"Record {record_id} not found")
    primary_language = (record.language or "en").replace("_", "-").casefold()
    if primary_language == language.casefold():
        raise ValueError("Translation language duplicates the primary language")

    result = await session.execute(
        insert(RecordTranslation)
        .values(
            record_id=record_id,
            language=language,
            title=title,
            summary=summary,
        )
        .on_conflict_do_update(
            index_elements=[
                RecordTranslation.record_id,
                func.lower(RecordTranslation.language),
            ],
            set_={"title": title, "summary": summary},
        )
        .returning(RecordTranslation)
    )
    translation = result.scalar_one()
    await session.flush()
    return translation


async def delete_translation(
    session: AsyncSession, record_id: uuid.UUID, language: str
) -> None:
    result = await session.execute(
        select(RecordTranslation).where(
            RecordTranslation.record_id == record_id,
            RecordTranslation.language == language,
        )
    )
    translation = result.scalar_one_or_none()
    if translation is None:
        raise ValueError(f"Translation {language} not found")
    await session.delete(translation)
    await session.flush()


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
    record_id: uuid.UUID,
    **kwargs,
) -> RecordContact:
    """Update a contact through its owning record path."""
    result = await session.execute(
        select(RecordContact).where(
            RecordContact.id == contact_id,
            RecordContact.record_id == record_id,
        )
    )
    contact = result.scalar_one_or_none()
    if contact is None:
        raise ValueError(f"Contact {contact_id} not found")

    # fix(#458 E-46): kwargs carry only explicitly-set fields (exclude_unset
    # at the router), so apply nulls too — that's how a field is cleared.
    for key, value in kwargs.items():
        setattr(contact, key, value)

    await session.flush()
    return contact


async def delete_contact(
    session: AsyncSession, contact_id: uuid.UUID, record_id: uuid.UUID
) -> None:
    """Delete a contact through its owning record path."""
    result = await session.execute(
        select(RecordContact).where(
            RecordContact.id == contact_id,
            RecordContact.record_id == record_id,
        )
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
        # fix(#430 BA-34): deterministic order so paginated reads don't repeat/skip.
        .order_by(RecordKeyword.id)
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


async def delete_keyword(
    session: AsyncSession, keyword_id: uuid.UUID, record_id: uuid.UUID
) -> None:
    """Delete a keyword by ID, scoped to its owning record.

    fix(#463 review): scoping by ``record_id`` keeps the delete addressable only
    through its real owner, so a keyword whose id belongs to a different record
    404s here instead of being deleted through a mismatched path — which also
    kept the caller's re-embed (``_propagate_record_write``) pointed at the wrong
    record while the keyword's real owner drifted.
    """
    result = await session.execute(
        select(RecordKeyword).where(
            RecordKeyword.id == keyword_id,
            RecordKeyword.record_id == record_id,
        )
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
        # fix(#430 BA-34): deterministic order so paginated reads don't repeat/skip.
        .order_by(RecordDistribution.id)
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
    record_id: uuid.UUID,
    **kwargs,
) -> RecordDistribution:
    """Update a distribution. Explicitly-set fields are applied, nulls included.

    Auto-generated distributions cannot be updated (raises ValueError).
    """
    result = await session.execute(
        select(RecordDistribution).where(
            RecordDistribution.id == distribution_id,
            RecordDistribution.record_id == record_id,
        )
    )
    dist = result.scalar_one_or_none()
    if dist is None:
        raise ValueError(f"Distribution {distribution_id} not found")

    if dist.auto_generated:
        raise ValueError("Cannot update auto-generated distributions")

    # fix(#458 E-46): apply explicitly-set nulls too — see update_contact.
    for key, value in kwargs.items():
        setattr(dist, key, value)

    await session.flush()
    return dist


async def delete_distribution(
    session: AsyncSession, distribution_id: uuid.UUID, record_id: uuid.UUID
) -> None:
    """Delete a distribution by ID.

    Auto-generated distributions cannot be deleted (raises ValueError).
    """
    result = await session.execute(
        select(RecordDistribution).where(
            RecordDistribution.id == distribution_id,
            RecordDistribution.record_id == record_id,
        )
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
        "parquet",
        "/datasets/{dataset_id}/export?format=parquet",
        "GeoParquet Download",
        "HTTP",
        "application/vnd.apache.parquet",
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

# Vector tiles are not in the template table because their URL is built from
# ``table_name`` rather than ``dataset_id``. The pair still belongs to the
# generated set, so reconcile has to see it.
_VECTOR_TILES_PAIR = ("vector_tiles", "pbf")

# Every (distribution_type, format) pair this module owns. A row outside this
# set was written by something else — the raster and VRT ingest tails add their
# own ``download`` rows — and reconcile must leave those alone even when they
# are flagged auto-generated.
_GENERATED_PAIRS: frozenset[tuple[str, str]] = frozenset(
    {(tpl[0], tpl[1]) for tpl in _DISTRIBUTION_TEMPLATES} | {_VECTOR_TILES_PAIR}
)


def _pair_applies(dist_type: str, fmt: str, geometry_type: str | None) -> bool:
    """Whether the modality implied by ``geometry_type`` advertises this pair.

    One spelling of the modality filter, so the set a promote INSERTS and the
    set a demote REMOVES cannot drift apart.
    """
    if geometry_type is not None:
        return True
    return (dist_type == "download" and fmt == "csv") or dist_type == "ogc_features"


def _primary_pair(geometry_type: str | None) -> tuple[str, str]:
    """The one generated row that carries ``is_primary`` for this modality.

    The templates mark GeoPackage primary; without geometry that row is not
    generated at all, and CSV is the richest download left.
    """
    for dist_type, fmt, *_rest, is_primary in _DISTRIBUTION_TEMPLATES:
        if is_primary and _pair_applies(dist_type, fmt, geometry_type):
            return dist_type, fmt
    return "download", "csv"


async def generate_distributions(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    record_id: uuid.UUID,
    table_name: str,
    geometry_type: str | None = None,
) -> list[RecordDistribution]:
    """Generate standard distribution records for a dataset.

    For spatial datasets (geometry_type is not None): creates 7 distribution rows
    (5 download formats incl. GeoParquet + OGC features + vector tiles).
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
    primary_pair = _primary_pair(geometry_type)

    for (
        dist_type,
        fmt,
        url_tpl,
        title,
        protocol,
        media_type,
        _is_primary,
    ) in _DISTRIBUTION_TEMPLATES:
        # Non-spatial datasets: only csv download + ogc_features
        if not _pair_applies(dist_type, fmt, geometry_type):
            continue

        # Skip if already exists
        if (dist_type, fmt) in existing_set:
            continue

        url = url_tpl.format(dataset_id=dataset_id)

        # For non-spatial datasets, CSV download becomes primary (gpkg is filtered out)
        effective_primary = (dist_type, fmt) == primary_pair

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
    if (
        _pair_applies(*_VECTOR_TILES_PAIR, geometry_type)
        and _VECTOR_TILES_PAIR not in existing_set
    ):
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


async def reconcile_distributions(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    record_id: uuid.UUID,
    table_name: str,
    geometry_type: str | None = None,
) -> tuple[list[RecordDistribution], list[tuple[str, str]]]:
    """Bring a record's AUTO-GENERATED distributions in line with a modality.

    fix(#1314): ``generate_distributions`` runs once, at dataset creation, and
    merges rather than replaces — so a registered table that later gains a
    geometry column never starts advertising vector tiles, and one that loses
    its geometry goes on advertising GeoPackage, GeoJSON, Shapefile,
    GeoParquet and tiles against a relation that cannot serve any of them.
    This is the write that closes both directions: it inserts what the new
    modality adds (by delegating to ``generate_distributions``) and removes
    what the new modality excludes.

    **Preservation policy.** Deliberately narrow, and the reason is that
    ``record_distributions`` carries a single ``auto_generated`` boolean and no
    per-field provenance — there is no ``user_modified_fields`` here the way
    ``attribute_metadata`` has one:

    - Rows with ``auto_generated=False`` ALWAYS survive, in both directions.
      Those are the rows a user authored through ``create_distribution``, and
      nothing in this function reads or writes them.
    - Rows outside ``_GENERATED_PAIRS`` always survive, even when flagged
      auto-generated. The raster and VRT ingest tails write their own
      ``download`` rows (geotiff, vrt) and this function does not own them.
    - Auto-generated rows the new modality excludes are DELETED. Any user edit
      to such a row — title, media type, ``is_primary`` — is lost with it, and
      the row is recreated from the template if the modality flips back.
    - ``is_primary`` is NORMALIZED across the surviving generated rows, so
      exactly one of them is primary for the new modality (GeoPackage when
      there is geometry, CSV when there is not). A promote that left the old
      CSV primary beside a new primary GeoPackage would advertise two.

    The lost-edit case is narrower than it reads: ``update_distribution`` and
    ``delete_distribution`` both refuse to touch a row with
    ``auto_generated=True``, so the API offers no way to edit one in the first
    place. An edit could only exist from a direct database write, or from a
    future path that relaxes that refusal — which is when this policy needs
    revisiting, not before.

    Returns ``(created, removed)``: the rows inserted, and the
    ``(distribution_type, format)`` pairs deleted.
    """
    result = await session.execute(
        select(RecordDistribution).where(
            RecordDistribution.record_id == record_id,
            RecordDistribution.auto_generated.is_(True),
        )
    )
    existing = list(result.scalars().all())

    removed: list[tuple[str, str]] = []
    survivors: list[RecordDistribution] = []
    for row in existing:
        pair = (row.distribution_type, row.format)
        if pair in _GENERATED_PAIRS and not _pair_applies(*pair, geometry_type):
            await session.delete(row)
            removed.append(pair)
        else:
            survivors.append(row)

    # Before the insert, so the existence probe inside generate_distributions
    # sees the post-delete state rather than the rows this call just retired.
    if removed:
        await session.flush()

    created = await generate_distributions(
        session, dataset_id, record_id, table_name, geometry_type=geometry_type
    )

    primary_pair = _primary_pair(geometry_type)
    for row in survivors + created:
        pair = (row.distribution_type, row.format)
        if pair not in _GENERATED_PAIRS:
            continue
        should_be_primary = pair == primary_pair
        if row.is_primary != should_be_primary:
            row.is_primary = should_be_primary
    await session.flush()

    return created, removed
