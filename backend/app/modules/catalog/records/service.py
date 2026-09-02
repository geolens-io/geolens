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


async def _demote_other_primaries(
    session: AsyncSession,
    record_id: uuid.UUID,
    *,
    keep_id: uuid.UUID | None = None,
    generated_only: bool = False,
) -> None:
    """Clear ``is_primary`` on the record's other distributions (#1383).

    One UPDATE, issued BEFORE the row that claims the flag is written, and the
    ordering is the whole point. ``uq_record_distribution_primary`` (migration
    0042) is a plain, non-deferrable partial unique index, so a second primary
    fails at statement time rather than at COMMIT; leaving the demote to the
    ORM's unit of work would make that failure depend on flush ordering
    between an UPDATE and an INSERT that SQLAlchemy is free to choose.

    ``generated_only`` restricts the demote to ``auto_generated`` rows. It is
    what lets ``reconcile_distributions`` normalize its own rows without
    writing a user's — see the preservation policy on its docstring.
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
    """Whether some row on the record already holds ``is_primary``."""
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

    **Primary semantics (#1383): the last write wins.** A row written with
    ``is_primary=True`` demotes every other distribution on the record, the
    generated ones included, in this transaction. Before this, the flag was
    stored verbatim and every dataset already carries a generated primary
    (GeoPackage when it has geometry, CSV when it does not), so one POST left
    the record advertising two primaries with no tiebreak for the OGC Record
    and STAC consumers that read ``properties.distributions``.

    Rejecting the write with a 409 while another row holds the flag was the
    alternative. It was not taken: the API has no demote verb, so "make this
    one primary" would become a two-request dance with an unavoidable window
    where the record has no primary at all, and every existing caller sending
    ``is_primary=true`` would start failing. Demoting keeps the request
    meaning what it says.

    Enforcement does not live here. ``uq_record_distribution_primary``
    (migration 0042) is the invariant — at most one primary row per record,
    in the database, where no API path can route around it. The demote is
    what keeps well-behaved callers from ever meeting it.
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

    ``is_primary=True`` follows the same last-write-wins rule
    ``create_distribution`` states (#1383): the record's other distributions
    are demoted here, in this transaction. Clearing the flag
    (``is_primary=False``) promotes nothing — a caller saying "this is not the
    primary" is not saying which one is, and a record with no primary is a
    representable state that the next ``reconcile_distributions`` fills.
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

    Deleting the row that holds ``is_primary`` hands the flag back to the
    generated default (#1383). Without that, the demote-on-write rule would
    make "no primary at all" reachable in one more request than it used to
    be: the user's row took the flag off the generated GeoPackage when it was
    created, and deleting it would leave nothing holding it. Withdrawing a
    row withdraws its claim; the platform's own default is what the record
    had before the claim.
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

    Same preference order ``reconcile_distributions`` normalizes with
    (GeoPackage, then CSV), restricted to generated rows that actually exist —
    a record whose modality generates neither is simply left without a
    primary, the state it was in before. Called only after the flush that
    removed the previous holder, and it re-checks that nothing else holds the
    flag, so it can never be the write that trips
    ``uq_record_distribution_primary``.
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

    For spatial datasets (geometry_type is not None): creates 9 distribution rows
    (7 download formats incl. GeoParquet, FlatGeobuf, and PMTiles + OGC
    features + vector tiles).
    For non-spatial datasets (geometry_type is None): creates only csv download
    + OGC features (2 rows).

    All are marked auto_generated=True. Merge semantics: an AUTO-GENERATED row
    already holding a (distribution_type, format) pair is left untouched, and
    the insert itself is ``ON CONFLICT DO NOTHING`` against
    ``uq_record_distribution``.

    fix(#1383): the template's ``is_primary`` is inserted only when no row on
    the record already holds the flag. At creation none does; on a reconcile
    the holder is a survivor or a user's own row, and the caller's
    normalization step is what moves the flag afterwards.

    fix(#1370): the existence probe reads only auto-generated rows. It used to
    read every row, so a distribution a user authored through
    ``create_distribution`` counted as "the pair is taken" — and once somebody
    added their own ``download``/``gpkg`` entry, the built-in
    ``/datasets/{id}/export?format=gpkg`` row could never be generated for that
    record again, by this call or by a later ``reconcile_distributions``
    promote. The export endpoint kept working; the catalog record, the DCAT
    feeds and the STAC assets simply stopped naming it. Two rows advertising
    one format is the intended end state: one the user's, one the platform's.

    Args:
        dataset_id: Dataset PK (used in URL paths).
        record_id: Record PK (FK in record_distributions).
        table_name: Dataset table name (used in vector tile URL).
        geometry_type: Geometry type string, or None for non-spatial datasets.
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

    # fix(#1463, codex round 2): repair a surviving row the OLD template wrote.
    # Migration 0048 is one-shot and the scripted upgrade migrates while the
    # previous app containers still serve (it migrates first, replaces the app
    # after), so a dataset created in that window is stamped `OGC:WMTS` after
    # the UPDATE commits — and the pair-existence skip below means the template
    # never rewrites it. Scoped like the migration's WHERE plus this record;
    # a user's own row is not visible to this function at all.
    #
    # fix(#1463, codex round 4): this is a partial mitigation, not a closer, and
    # the earlier comment here overstated it. Both refresh callers gate
    # `reconcile_distributions` on a modality FLIP (`tasks_postgis_refresh` and
    # `tasks_common`, each deliberately, so an unchanged refresh cannot
    # renormalize `is_primary`), and creation cannot meet a stale row. So the
    # reach is: a dataset that gains or loses geometry, plus any future caller
    # that regenerates. Everything else created in the window keeps the wrong
    # label until #1467 removes the window itself, which is the actual fix.
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

    # fix(#1383): the template's primary flag yields to whoever already holds
    # it. At dataset creation nothing does and the GeoPackage (or CSV) row
    # takes it exactly as before; on a reconcile the holder is a surviving
    # generated row or a user's own, and inserting a second primary would
    # violate `uq_record_distribution_primary` — aborting the refresh
    # transaction the caller runs inside, which is the failure mode the
    # ON CONFLICT clause below exists to avoid for the other unique index.
    # Moving the flag afterwards is reconcile's normalization step, which
    # demotes before it promotes.
    record_has_primary = await _record_has_primary(session, record_id)

    # Build all new distributions in one list so they go out as a single
    # multi-VALUES INSERT rather than one statement per row.
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

        # Skip if already exists
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

    # fix(#1370): ON CONFLICT DO NOTHING, not check-then-insert. Now that a
    # user's row no longer hides its pair from the probe above, a user row
    # whose url happens to equal the template's is a live collision on
    # `uq_record_distribution` rather than a skipped pair — and
    # `/datasets/{id}/export?format=gpkg` is a guessable thing to type. Catching
    # IntegrityError instead would be a worse mechanism than it looks: the
    # reconcile caller runs inside the write transaction of a registered-PostGIS
    # refresh or a reupload swap, and a raised constraint violation aborts that
    # whole transaction, turning a metadata correction into a failed job. A
    # conflict resolved in the statement never opens that hole.
    #
    # Skipped rows are absent from RETURNING, so `created` stays a truthful
    # list of what was inserted — which is what reconcile's is_primary
    # normalization picks the primary from.
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
      CSV primary beside a new primary GeoPackage would advertise two. The
      winner is picked from the rows that exist rather than from the modality
      alone — a generated row the conflict-tolerant insert skipped is not
      there to promote, and the fallback takes it.

    **Where the primary flag fits the policy (#1383).** ``is_primary`` is a
    per-RECORD invariant, not a per-row field: ``uq_record_distribution_primary``
    (migration 0042) allows one primary row per record, and
    ``create_distribution``/``update_distribution`` hold it up by demoting
    everything else when a user claims the flag. That crosses this function's
    boundary in exactly one place, and the boundary holds:

    - The demote this normalization issues is scoped to ``auto_generated``
      rows, so a user's row is still never written here. It does span
      generated rows OUTSIDE ``_GENERATED_PAIRS`` — those survive, as the
      bullet above promises, but they cannot keep a primary flag the record's
      new winner needs, because the invariant is per record.
    - A USER-authored primary outranks this normalization entirely: when one
      exists, no generated row is promoted and the flags are left alone. The
      explicit choice wins over the platform default, and a background
      refresh never takes back what a user asked for.

    Deleting that user row is what hands the flag back — see
    ``delete_distribution`` — so the record does not sit primary-less waiting
    for a refresh that may never come.

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

    # fix(#1314 review round 1): chosen from the rows that ACTUALLY exist, not
    # from the modality alone. Naming a pair with no generated row behind it
    # cleared the CSV flag and promoted nothing, leaving the record with no
    # primary distribution at all. fix(#1370) narrowed when that happens — a
    # user's own GeoPackage entry no longer suppresses the generated one — but
    # did not remove it: a user row sitting at the exact template url makes the
    # insert a no-op, and then there is again no GeoPackage row to name.
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
