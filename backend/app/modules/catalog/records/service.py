"""Service layer for record sub-resources: contacts, keywords, distributions.

The normalized tables (record_contacts, record_keywords, record_distributions) are
the single authoritative metadata path. No dual-write to legacy JSONB/tags columns.
"""

import uuid

from sqlalchemy import func, select, update
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
        # fix(#1778): sort_order server-defaults to 0, so contacts added
        # without an explicit order tie on it -- OFFSET/LIMIT paging over
        # the tie had no defined row order. RecordContact.id is unique.
        .where(RecordContact.record_id == record_id)
        .order_by(RecordContact.sort_order, RecordContact.id)
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

    # fix(#458): kwargs carry only explicitly-set fields (exclude_unset
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
        # fix(#430): deterministic order so paginated reads don't repeat/skip.
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

    fix(#463): scoping by ``record_id`` 404s a keyword belonging to a
    different record, instead of deleting it through a mismatched path.
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
        # fix(#430): deterministic order so paginated reads don't repeat/skip.
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


async def _demote_other_primaries(
    session: AsyncSession,
    record_id: uuid.UUID,
    *,
    keep_id: uuid.UUID | None = None,
    generated_only: bool = False,
) -> None:
    """Clear ``is_primary`` on the record's other distributions (#1383).

    Issued BEFORE the row that claims the flag is written — ordering is the
    point, since ``uq_record_distribution_primary`` is a non-deferrable
    partial unique index that fails at statement time, not at a
    flush-order-dependent COMMIT. ``generated_only`` restricts the demote to
    ``auto_generated`` rows, so ``reconcile_distributions`` never writes a
    user's.
    """
    stmt = update(RecordDistribution).where(
        RecordDistribution.record_id == record_id,
        RecordDistribution.is_primary.is_(True),
    )
    if keep_id is not None:
        stmt = stmt.where(RecordDistribution.id != keep_id)
    if generated_only:
        stmt = stmt.where(RecordDistribution.auto_generated.is_(True))
    await session.execute(
        stmt.values(is_primary=False),
        execution_options={"synchronize_session": "fetch"},
    )


async def _record_has_primary(
    session: AsyncSession,
    record_id: uuid.UUID,
    *,
    user_authored_only: bool = False,
) -> bool:
    stmt = select(RecordDistribution.id).where(
        RecordDistribution.record_id == record_id,
        RecordDistribution.is_primary.is_(True),
    )
    if user_authored_only:
        stmt = stmt.where(RecordDistribution.auto_generated.is_(False))
    return (await session.execute(stmt.limit(1))).scalar_one_or_none() is not None


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
    """Create a manual distribution for a record.

    fix(#1383): last write wins — ``is_primary=True`` demotes every other
    distribution on the record in this transaction (avoids two primaries
    with no tiebreak for OGC/STAC readers). Enforced by
    ``uq_record_distribution_primary`` (migration 0042); the demote just
    keeps well-behaved callers from tripping it.
    """
    if record is None:
        record = await get_record(session, record_id)
    if record is None:
        raise ValueError(f"Record {record_id} not found")

    if is_primary:
        await _demote_other_primaries(session, record_id)

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
    ``is_primary=True`` follows create_distribution's last-write-wins rule
    (#1383); clearing it (``is_primary=False``) promotes nothing — a
    no-primary record is representable, and the next
    ``reconcile_distributions`` fills it.
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

    # Before the setattr loop, so the demote UPDATE is on the wire ahead of
    # the promote this flush will emit — see _demote_other_primaries.
    if kwargs.get("is_primary") is True:
        await _demote_other_primaries(session, record_id, keep_id=distribution_id)

    # fix(#458): apply explicitly-set nulls too — see update_contact.
    for key, value in kwargs.items():
        setattr(dist, key, value)

    await session.flush()
    return dist


async def delete_distribution(
    session: AsyncSession, distribution_id: uuid.UUID, record_id: uuid.UUID
) -> None:
    """Delete a distribution by ID.

    Auto-generated distributions cannot be deleted (raises ValueError).
    Deleting the row holding ``is_primary`` hands the flag back to the
    generated default (#1383): withdrawing a row withdraws its claim.
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

    was_primary = dist.is_primary
    await session.delete(dist)
    await session.flush()

    if was_primary:
        await _restore_generated_primary(session, record_id)


async def _restore_generated_primary(
    session: AsyncSession, record_id: uuid.UUID
) -> RecordDistribution | None:
    """Give ``is_primary`` back to the best generated row, if there is one.

    Same preference order as ``reconcile_distributions`` (GeoPackage, then
    CSV), restricted to rows that exist. Re-checks nothing else holds the
    flag, so it can never trip ``uq_record_distribution_primary``.
    """
    if await _record_has_primary(session, record_id):
        return None

    rows = (
        await session.execute(
            select(RecordDistribution).where(
                RecordDistribution.record_id == record_id,
                RecordDistribution.auto_generated.is_(True),
            )
        )
    ).scalars()
    by_pair = {(row.distribution_type, row.format): row for row in rows}
    for pair in _PRIMARY_PREFERENCE:
        row = by_pair.get(pair)
        if row is not None:
            row.is_primary = True
            await session.flush()
            return row
    return None


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
        "download",
        "fgb",
        "/datasets/{dataset_id}/export?format=fgb",
        "FlatGeobuf Download",
        "HTTP",
        "application/vnd.flatgeobuf",
        False,
    ),
    (
        "download",
        "pmtiles",
        "/datasets/{dataset_id}/export?format=pmtiles",
        "PMTiles Download",
        "HTTP",
        "application/vnd.pmtiles",
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

# fix(#1463): this read ``OGC:WMTS``, which the tile URL does not speak — it is
# a plain XYZ template, no capabilities document and no TileMatrixSet. Bare, to
# match ``HTTP`` above: this vocabulary prefixes ``OGC:`` only for real OGC
# services, and there is no OGC XYZ standard to claim. Payload semantics stay
# in ``format`` and ``media_type``. Migration 0048's WHERE matches both values
# below, so the three move together.
_VECTOR_TILES_PROTOCOL = "XYZ"
_STALE_VECTOR_TILES_PROTOCOL = "OGC:WMTS"

# The four-column unique constraint on ``record_distributions``
# (record_id, distribution_type, format, url) — see RecordDistribution's
# ``__table_args__``. Named here because the generated-row insert has to be
# conflict-tolerant against it; a rename that missed this constant fails loudly
# on the next insert ("constraint ... does not exist") rather than silently.
_DISTRIBUTION_UNIQUE_CONSTRAINT = "uq_record_distribution"

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


# Which generated row carries ``is_primary``, best first. GeoPackage is what
# the template table marks primary; CSV is the fallback, both for a modality
# that generates no GeoPackage row at all and — on reconcile — for a promote
# where no generated GeoPackage row exists to promote because a user's own row
# already sits at the exact url the GeoPackage template would have inserted.
_PRIMARY_PREFERENCE: tuple[tuple[str, str], ...] = (
    ("download", "gpkg"),
    ("download", "csv"),
)


def _primary_pair(geometry_type: str | None) -> tuple[str, str]:
    """The one generated row that carries ``is_primary`` for this modality."""
    for pair in _PRIMARY_PREFERENCE:
        if _pair_applies(*pair, geometry_type):
            return pair
    return _PRIMARY_PREFERENCE[-1]


async def generate_distributions(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    record_id: uuid.UUID,
    table_name: str,
    geometry_type: str | None = None,
) -> list[RecordDistribution]:
    """Generate standard distribution records for a dataset.

    Spatial datasets get 9 rows; non-spatial get 2 (csv + OGC features).
    All auto_generated=True, merged via ``ON CONFLICT DO NOTHING``.

    fix(#1383): ``is_primary`` is inserted only when no row already holds
    it. fix(#1370): the existence probe reads only auto-generated rows, so
    a user's matching row can't block the platform's from being generated.
    """
    # Fetch the pairs this function owns for this record in a single query.
    # Anything a user wrote is deliberately invisible here — see above.
    existing_result = await session.execute(
        select(
            RecordDistribution.distribution_type,
            RecordDistribution.format,
        ).where(
            RecordDistribution.record_id == record_id,
            RecordDistribution.auto_generated.is_(True),
        )
    )
    existing_set = {(row[0], row[1]) for row in existing_result.all()}

    # fix(#1463): repairs a stale `OGC:WMTS` protocol stamped during
    # migration 0048's upgrade window. Partial mitigation — only reached on
    # a modality-flip refresh (not fresh datasets); #1467 removes the window.
    if _VECTOR_TILES_PAIR in existing_set:
        await session.execute(
            update(RecordDistribution)
            .where(
                RecordDistribution.record_id == record_id,
                RecordDistribution.auto_generated.is_(True),
                RecordDistribution.distribution_type == _VECTOR_TILES_PAIR[0],
                RecordDistribution.format == _VECTOR_TILES_PAIR[1],
                RecordDistribution.protocol == _STALE_VECTOR_TILES_PROTOCOL,
            )
            .values(protocol=_VECTOR_TILES_PROTOCOL)
        )

    # fix(#1383): the template's primary flag yields to whoever already
    # holds it — inserting a second would violate
    # `uq_record_distribution_primary` and abort the transaction.
    record_has_primary = await _record_has_primary(session, record_id)

    # Multi-VALUES INSERT rather than one statement per row.
    to_add: list[dict] = []
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

        if (dist_type, fmt) in existing_set:
            continue

        url = url_tpl.format(dataset_id=dataset_id)

        # For non-spatial datasets, CSV download becomes primary (gpkg is filtered out)
        effective_primary = (dist_type, fmt) == primary_pair and not record_has_primary

        to_add.append(
            {
                "record_id": record_id,
                "distribution_type": dist_type,
                "format": fmt,
                "url": url,
                "title": title,
                "protocol": protocol,
                "media_type": media_type,
                "is_primary": effective_primary,
                "auto_generated": True,
            }
        )

    # Vector tiles (uses table_name, not dataset_id) — skip for non-spatial datasets
    if (
        _pair_applies(*_VECTOR_TILES_PAIR, geometry_type)
        and _VECTOR_TILES_PAIR not in existing_set
    ):
        to_add.append(
            {
                "record_id": record_id,
                "distribution_type": "vector_tiles",
                "format": "pbf",
                "url": f"/tiles/data.{table_name}/{{z}}/{{x}}/{{y}}.pbf",
                "title": "Vector Tiles",
                "protocol": _VECTOR_TILES_PROTOCOL,
                "media_type": "application/vnd.mapbox-vector-tile",
                "is_primary": False,
                "auto_generated": True,
            }
        )

    if not to_add:
        return []

    # fix(#1370): ON CONFLICT DO NOTHING, not check-then-insert —
    # IntegrityError would abort the caller's transaction. Skipped rows stay
    # out of RETURNING, so `created` is truthful for is_primary normalization.
    result = await session.execute(
        insert(RecordDistribution)
        .values(to_add)
        .on_conflict_do_nothing(constraint=_DISTRIBUTION_UNIQUE_CONSTRAINT)
        .returning(RecordDistribution)
    )
    created = list(result.scalars().all())
    await session.flush()
    return created


async def reconcile_distributions(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    record_id: uuid.UUID,
    table_name: str,
    geometry_type: str | None = None,
) -> tuple[list[RecordDistribution], list[tuple[str, str]]]:
    """Bring a record's AUTO-GENERATED distributions in line with a modality.

    fix(#1314): merges rather than replaces — inserts what the modality adds
    and DELETES auto-generated rows it excludes, taking user edits with
    them. ``auto_generated=False`` rows and rows outside
    ``_GENERATED_PAIRS`` are untouched. fix(#1383): normalizes
    ``is_primary`` unless a USER-authored primary already holds it. Returns
    ``(created, removed)``.
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

    # fix(#1314): chosen from the rows that ACTUALLY exist, not from the
    # modality alone — naming a pair with no generated row behind it would
    # clear the CSV flag and promote nothing, leaving no primary at all.
    # fix(#1370) narrowed when that happens (a user's own GeoPackage entry
    # no longer suppresses the generated one) but did not remove it: a user
    # row at the exact template url makes the insert a no-op.
    generated = [
        row
        for row in survivors + created
        if (row.distribution_type, row.format) in _GENERATED_PAIRS
    ]
    by_pair = {(row.distribution_type, row.format): row for row in generated}
    primary = next(
        (
            by_pair[pair]
            for pair in _PRIMARY_PREFERENCE
            if _pair_applies(*pair, geometry_type) and pair in by_pair
        ),
        None,
    )
    # fix(#1383): a user's own row holding the flag outranks this
    # normalization, and skipping is what keeps the preservation policy above
    # literally true — the demote below is scoped to generated rows, so it
    # could not clear a user's flag anyway, and promoting beside one would
    # advertise two primaries (now a `uq_record_distribution_primary`
    # violation rather than a silent ambiguity).
    user_primary = await _record_has_primary(
        session, record_id, user_authored_only=True
    )
    # No candidate means every preferred pair is occupied by a row this
    # function does not own, and there is nothing to promote. Leave the flags
    # as they are rather than clearing them: an unchanged primary is a worse
    # answer than the right one and a better answer than none.
    if primary is not None and not user_primary:
        # Demote first, promote second — one statement each, in that order.
        await _demote_other_primaries(
            session, record_id, keep_id=primary.id, generated_only=True
        )
        primary.is_primary = True
    await session.flush()

    return created, removed
