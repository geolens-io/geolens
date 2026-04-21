"""Search service: full-text, spatial, and faceted dataset search."""

from __future__ import annotations

import logging
import uuid as uuid_mod
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Literal, TypedDict

if TYPE_CHECKING:
    from app.platform.storage.provider import StorageProvider

from geoalchemy2.shape import to_shape
from sqlalchemy import (
    String as SAString,
    case,
    collate,
    exists,
    func,
    literal,
    or_,
    select,
    text,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from app.modules.auth.models import User
from app.core.config import settings
from app.modules.auth.visibility import apply_visibility_filter
from app.modules.catalog.collections.models import Collection, CollectionDataset
from app.modules.catalog.datasets.domain.models import (
    Dataset,
    DatasetGrant,
    Record,
    RecordContact,
    RecordKeyword,
)
from app.modules.catalog.datasets.domain.utils import extract_bbox
from app.processing.embeddings.helpers import has_embeddings
from app.processing.embeddings.models import RecordEmbedding
from app.processing.embeddings.service import (
    EmbeddingUnavailableError,
    generate_embedding,
)
from app.standards.ogc.utils import build_url
from app.core.persistent_config import EMBEDDING_MODEL, SEMANTIC_SEARCH_ENABLED
from app.modules.catalog.sources.provenance import derive_last_edited
from app.core.geo import make_bbox_filter

logger = logging.getLogger(__name__)


class FacetCounts(TypedDict):
    record_type: dict
    keywords: list[dict]
    source_organization: list[dict]
    srid: list[dict]
    collections: list[dict]


# Media types for each download format
_FORMAT_MEDIA = {
    "gpkg": "application/geopackage+sqlite3",
    "geojson": "application/geo+json",
    "shp": "application/x-shapefile",
    "csv": "text/csv",
}

_RASTER_FORMAT_MEDIA = {
    "geotiff": "image/tiff; application=geotiff",
    "cog": "image/tiff; application=geotiff; profile=cloud-optimized",
}

# Non-spatial table formats — shapefile excluded (geometry-specific)
_TABLE_FORMAT_MEDIA = {
    "csv": "text/csv",
    "gpkg": "application/geopackage+sqlite3",
    "geojson": "application/geo+json",
}


# ---------------------------------------------------------------------------
# SearchFilters dataclass — bundles common filter parameters for
# search_datasets() and get_facet_counts()
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SearchFilters:
    """Common filter parameters shared by search and facet queries."""

    # Text / spatial
    q: str | None = None
    bbox: list[float] | None = None
    keywords: list[str] | None = None
    geometry_type: str | None = None
    srid: int | None = None
    source_organization: str | None = None
    record_type: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    vintage_start: date | None = None
    vintage_end: date | None = None
    datetime_param: str | None = None
    exclude_synthetic: bool = True
    collection_id: uuid_mod.UUID | None = None
    spatial_predicate: Literal["intersects", "within"] = "intersects"
    geometry_geojson: str | None = None

    # search_datasets-only fields
    cql2_filter: str | None = None
    cql2_filter_lang: str = "cql2-text"
    sort_by: str = "relevance"
    sort_desc: bool | None = None
    skip: int = 0
    limit: int = 10


# ---------------------------------------------------------------------------
# _build_text_filter — single source of truth for the 7-clause OR filter
# ---------------------------------------------------------------------------


def _build_text_filter(q: str, *, use_alias: bool = False):
    """Build the full-text OR clause for a query string.

    Returns a SQLAlchemy ``or_()`` clause combining:
      - tsvector match on Record.search_vector
      - ILIKE on Record.title
      - ILIKE on Record.summary
      - FTS + ILIKE on RecordKeyword
      - FTS + ILIKE on RecordContact (name + organization)

    When *use_alias* is True the keyword/contact sub-selects use aliased
    models so they don't auto-correlate with an outer join on RecordKeyword.
    """
    query_text = q.strip()
    query_like = f"%{query_text.lower()}%"
    # Use 'simple' regconfig for non-Latin scripts that 'english' can't tokenize;
    # combine both so accented/stemmed English still works alongside CJK/Arabic/etc.
    ts_query_en = func.websearch_to_tsquery("english", query_text)
    ts_query_simple = func.websearch_to_tsquery("simple", query_text)
    ts_query = ts_query_en.bool_op("||")(ts_query_simple)

    # unaccent both sides of ILIKE for accent-insensitive matching (café = cafe)
    unaccented_like = func.concat("%", func.unaccent(query_text.lower()), "%")
    vector_match = Record.search_vector.bool_op("@@")(ts_query)
    title_match = func.lower(func.unaccent(Record.title)).like(unaccented_like)
    summary_match = func.lower(func.unaccent(func.coalesce(Record.summary, ""))).like(
        unaccented_like
    )

    # Choose model references for sub-selects
    RK = aliased(RecordKeyword) if use_alias else RecordKeyword
    RC = aliased(RecordContact) if use_alias else RecordContact

    kw_fts_sel = select(RK.id).where(
        RK.record_id == Record.id,
        func.to_tsvector("english", RK.keyword).bool_op("@@")(ts_query),
    )
    kw_like_sel = select(RK.id).where(
        RK.record_id == Record.id,
        func.lower(RK.keyword).like(query_like),
    )
    ct_fts_sel = select(RC.id).where(
        RC.record_id == Record.id,
        func.to_tsvector(
            "english",
            func.coalesce(RC.name, "") + " " + func.coalesce(RC.organization, ""),
        ).bool_op("@@")(ts_query),
    )
    ct_like_sel = select(RC.id).where(
        RC.record_id == Record.id,
        func.lower(
            func.coalesce(RC.name, "") + " " + func.coalesce(RC.organization, ""),
        ).like(query_like),
    )

    if use_alias:
        kw_fts_sel = kw_fts_sel.correlate(Record)
        kw_like_sel = kw_like_sel.correlate(Record)
        ct_fts_sel = ct_fts_sel.correlate(Record)
        ct_like_sel = ct_like_sel.correlate(Record)

    keyword_exists = exists(kw_fts_sel)
    keyword_partial_exists = exists(kw_like_sel)
    contact_exists = exists(ct_fts_sel)
    contact_partial_exists = exists(ct_like_sel)

    clause = or_(
        vector_match,
        title_match,
        summary_match,
        keyword_exists,
        keyword_partial_exists,
        contact_exists,
        contact_partial_exists,
    )

    # Return individual parts too — search_datasets needs them for ranking
    return clause, {
        "ts_query": ts_query,
        "vector_match": vector_match,
        "title_match": title_match,
        "summary_match": summary_match,
        "keyword_exists": keyword_exists,
        "keyword_partial_exists": keyword_partial_exists,
        "contact_exists": contact_exists,
        "contact_partial_exists": contact_partial_exists,
    }


async def _attach_updated_actor_identities(
    session: AsyncSession,
    datasets: list[Dataset],
) -> None:
    actor_ids = {
        dataset.record.updated_by
        for dataset in datasets
        if dataset.record.updated_by is not None
    }
    if not actor_ids:
        return

    result = await session.execute(select(User).where(User.id.in_(actor_ids)))
    users_by_id = {user.id: user for user in result.scalars().all()}

    for dataset in datasets:
        record = dataset.record
        actor_id = record.updated_by
        if actor_id is None:
            continue
        # Attach the optional row once so serializers don't need extra DB lookups.
        setattr(record, "_provenance_updated_user", users_by_id.get(actor_id))


async def _get_vector_ranks(
    session: AsyncSession,
    query_text: str,
    limit: int,
) -> dict[str, int]:
    """Run vector similarity search and return {record_id_hex: rank} mapping.

    Returns an empty dict on any failure (silent fallback).
    """
    # Check if any embeddings exist at all
    if not await has_embeddings(session):
        return {}

    # Generate query embedding
    try:
        query_vector = await generate_embedding(query_text.strip(), session)
    except EmbeddingUnavailableError:
        logger.warning("Embedding unavailable for semantic search, falling back to FTS")
        return {}
    except Exception:
        logger.warning(
            "Failed to generate query embedding, falling back to FTS", exc_info=True
        )
        return {}

    # Get current model name for filtering
    model_name = await EMBEDDING_MODEL.get(session)

    # Tune HNSW recall — default ef_search=40 may miss relevant results
    await session.execute(text("SET LOCAL hnsw.ef_search = 100"))

    # Vector similarity query: cosine distance <= 0.7 means similarity >= 0.3
    vector_stmt = (
        select(
            RecordEmbedding.record_id,
            RecordEmbedding.embedding.cosine_distance(query_vector).label("distance"),
        )
        .where(
            RecordEmbedding.model_name == model_name,
            RecordEmbedding.embedding.cosine_distance(query_vector) <= 0.7,
        )
        .order_by("distance")
        .limit(limit)
    )

    result = await session.execute(vector_stmt)
    rows = result.all()

    # Assign positional ranks (1-based)
    return {str(row.record_id): rank + 1 for rank, row in enumerate(rows)}


def _compute_rrf_scores(
    fts_ids: list[str],
    vector_ranks: dict[str, int],
    k: int = 60,
) -> list[str]:
    """Merge FTS and vector results using Reciprocal Rank Fusion.

    Returns record IDs sorted by RRF score descending.
    """
    scores: dict[str, float] = {}

    # FTS contribution (positional rank 1-based)
    for rank, record_id in enumerate(fts_ids, start=1):
        scores[record_id] = scores.get(record_id, 0.0) + 1.0 / (k + rank)

    # Vector contribution
    for record_id, v_rank in vector_ranks.items():
        scores[record_id] = scores.get(record_id, 0.0) + 1.0 / (k + v_rank)

    # Sort by RRF score descending
    return sorted(scores.keys(), key=lambda rid: scores[rid], reverse=True)


def parse_ogc_datetime(datetime_str: str) -> tuple[date | None, date | None]:
    """Parse an OGC datetime interval string into (start, end) dates.

    Supports:
    - Single instant: "2024-01-15" or "2024-01-15T00:00:00Z"
    - Bounded interval: "2024-01-01/2024-12-31"
    - Open start: "../2024-12-31"
    - Open end: "2024-01-01/.."
    """
    if "/" in datetime_str:
        left, right = datetime_str.split("/", 1)
        dt_start = None if left == ".." else date.fromisoformat(left[:10])
        dt_end = None if right == ".." else date.fromisoformat(right[:10])
        return dt_start, dt_end
    # Single instant
    instant = date.fromisoformat(datetime_str[:10])
    return instant, instant


def _apply_common_filters(stmt, filters: SearchFilters, *, skip_text: bool = False):
    """Apply the shared filter stack used by both search and facets.

    Handles: text search, spatial, keywords, geometry_type, srid,
    source_organization, datetime_param, collection_id, exclude_synthetic.

    Pass ``skip_text=True`` when the caller already handles text search
    with custom ranking (e.g. ``search_datasets``).
    """
    if not skip_text and filters.q and filters.q.strip():
        text_clause, _parts = _build_text_filter(filters.q)
        stmt = stmt.where(text_clause)
    if filters.geometry_geojson:
        geom = func.ST_SetSRID(func.ST_GeomFromGeoJSON(filters.geometry_geojson), 4326)
        spatial_fn = (
            func.ST_Within
            if filters.spatial_predicate == "within"
            else func.ST_Intersects
        )
        stmt = stmt.where(
            Record.spatial_extent.op("&&")(func.ST_Envelope(geom)),
            spatial_fn(Record.spatial_extent, geom),
        )
    elif filters.bbox and len(filters.bbox) == 4:
        stmt = stmt.where(
            make_bbox_filter(
                Record.spatial_extent,
                filters.bbox,
                predicate=filters.spatial_predicate,
            )
        )
    if filters.keywords:
        _RK = aliased(RecordKeyword)
        for kw in filters.keywords:
            stmt = stmt.where(
                exists(
                    select(_RK.id)
                    .where(
                        _RK.record_id == Record.id,
                        func.lower(_RK.keyword) == kw.lower(),
                    )
                    .correlate(Record)
                )
            )
    if filters.geometry_type:
        stmt = stmt.where(Dataset.geometry_type == filters.geometry_type)
    if filters.srid:
        stmt = stmt.where(Dataset.srid == filters.srid)
    if filters.source_organization:
        stmt = stmt.where(Record.source_organization == filters.source_organization)
    if filters.datetime_param:
        dt_start, dt_end = parse_ogc_datetime(filters.datetime_param)
        if dt_start is not None:
            stmt = stmt.where(
                or_(Record.temporal_end >= dt_start, Record.temporal_end.is_(None))
            )
        if dt_end is not None:
            stmt = stmt.where(
                or_(Record.temporal_start <= dt_end, Record.temporal_start.is_(None))
            )
    if filters.collection_id is not None:
        stmt = stmt.where(
            exists(
                select(CollectionDataset.dataset_id).where(
                    CollectionDataset.dataset_id == Dataset.id,
                    CollectionDataset.collection_id == filters.collection_id,
                )
            )
        )
    if filters.exclude_synthetic:
        _RKS = aliased(RecordKeyword)
        stmt = stmt.where(
            ~exists(
                select(_RKS.id)
                .where(
                    _RKS.record_id == Record.id,
                    func.lower(_RKS.keyword) == "synthetic",
                )
                .correlate(Record)
            )
        )
    return stmt


async def get_facet_counts(
    session: AsyncSession,
    user: User | None,
    user_roles: set[str],
    filters: SearchFilters,
) -> FacetCounts:
    """Return multi-group facet counts for datasets matching the given filters.

    Returns dict with keys: record_type, keywords, source_organization, srid.
    Does NOT filter by record_type itself (facets show counts for all types).
    Separately counts matching collections from the collections table.
    """
    # Build a CTE that materializes the filtered (dataset_id, record_id) pairs
    # once. Both the record_type counts and per-facet queries join against it
    # instead of each independently re-evaluating the full filter stack.
    filtered_base = (
        select(Dataset.id.label("dataset_id"), Record.id.label("record_id"))
        .select_from(Dataset)
        .join(Record, Dataset.record_id == Record.id)
    )
    filtered_base = apply_visibility_filter(
        filtered_base, user, user_roles, Record, DatasetGrant
    )
    filtered_base = _apply_common_filters(filtered_base, filters)
    filtered_cte = filtered_base.cte("filtered_ids")

    # Record-type counts from the CTE (replaces duplicate filter stack)
    type_stmt = (
        select(Record.record_type, func.count().label("count"))
        .select_from(filtered_cte)
        .join(Record, Record.id == filtered_cte.c.record_id)
        .group_by(Record.record_type)
    )
    result = await session.execute(type_stmt)
    counts = {row.record_type: row.count for row in result.all()}

    # Separately count collections from the collections table
    coll_stmt = select(func.count()).select_from(Collection)
    if filters.q and filters.q.strip():
        q_like = f"%{filters.q.strip().lower()}%"
        coll_stmt = coll_stmt.where(
            or_(
                func.lower(Collection.name).like(q_like),
                func.lower(func.coalesce(Collection.description, "")).like(q_like),
            )
        )
    coll_count = (await session.execute(coll_stmt)).scalar_one()
    if coll_count > 0:
        counts["collection"] = coll_count

    # Facet queries are intentionally sequential — SQLAlchemy AsyncSession
    # is not safe for concurrent execute() on a shared connection.
    # Each query joins the CTE instead of re-applying all filters.

    # --- Keyword facets (top 20) ---
    kw_stmt = (
        select(RecordKeyword.keyword, func.count().label("count"))
        .select_from(filtered_cte)
        .join(RecordKeyword, RecordKeyword.record_id == filtered_cte.c.record_id)
        .group_by(RecordKeyword.keyword)
        .order_by(func.count().desc())
        .limit(20)
    )
    kw_result = await session.execute(kw_stmt)
    keyword_facets = [
        {"value": row.keyword, "count": row.count} for row in kw_result.all()
    ]

    # --- Source organization facets ---
    org_stmt = (
        select(Record.source_organization, func.count().label("count"))
        .select_from(filtered_cte)
        .join(Record, Record.id == filtered_cte.c.record_id)
        .where(Record.source_organization.isnot(None), Record.source_organization != "")
        .group_by(Record.source_organization)
        .order_by(func.count().desc())
        .limit(50)
    )
    org_result = await session.execute(org_stmt)
    org_facets = [
        {"value": row.source_organization, "count": row.count}
        for row in org_result.all()
    ]

    # --- SRID facets ---
    srid_stmt = (
        select(
            func.cast(Dataset.srid, SAString).label("srid_str"),
            func.count().label("count"),
        )
        .select_from(filtered_cte)
        .join(Dataset, Dataset.id == filtered_cte.c.dataset_id)
        .where(Dataset.srid.isnot(None))
        .group_by(Dataset.srid)
        .order_by(func.count().desc())
        .limit(50)
    )
    srid_result = await session.execute(srid_stmt)
    srid_facets = [
        {"value": row.srid_str, "count": row.count} for row in srid_result.all()
    ]

    # --- Collections facet (lightweight: id, name, visible member count) ---
    coll_facet_stmt = (
        select(
            Collection.id,
            Collection.name,
            func.count(CollectionDataset.dataset_id).label("dataset_count"),
        )
        .select_from(Collection)
        .join(CollectionDataset, CollectionDataset.collection_id == Collection.id)
        .join(filtered_cte, filtered_cte.c.dataset_id == CollectionDataset.dataset_id)
        .group_by(Collection.id, Collection.name)
        .order_by(func.count(CollectionDataset.dataset_id).desc())
    )
    coll_facet_result = await session.execute(coll_facet_stmt)
    collections_facet = [
        {"id": str(row.id), "name": row.name, "dataset_count": row.dataset_count}
        for row in coll_facet_result.all()
    ]

    return {
        "record_type": counts,
        "keywords": keyword_facets,
        "source_organization": org_facets,
        "srid": srid_facets,
        "collections": collections_facet,
    }


async def search_collections(
    session: AsyncSession,
    q: str,
    user: User | None,
    user_roles: set[str],
    *,
    limit: int = 10,
) -> list[dict]:
    """Search collections by text and return with visible member counts.

    When q is empty, returns all collections (up to limit).
    """
    coll_stmt = select(Collection).limit(limit)

    if q and q.strip():
        q_like = f"%{q.strip().lower()}%"
        coll_stmt = coll_stmt.where(
            or_(
                func.lower(Collection.name).like(q_like),
                func.lower(func.coalesce(Collection.description, "")).like(q_like),
            )
        )
    coll_result = await session.execute(coll_stmt)
    collections = coll_result.scalars().all()

    if not collections:
        return []

    # Get visible member counts in a single query
    coll_ids = [c.id for c in collections]
    member_stmt = (
        select(
            CollectionDataset.collection_id,
            func.count().label("cnt"),
        )
        .select_from(CollectionDataset)
        .join(Dataset, CollectionDataset.dataset_id == Dataset.id)
        .join(Record, Dataset.record_id == Record.id)
        .where(CollectionDataset.collection_id.in_(coll_ids))
    )
    member_stmt = apply_visibility_filter(
        member_stmt, user, user_roles, Record, DatasetGrant
    )
    member_stmt = member_stmt.group_by(CollectionDataset.collection_id)
    member_result = await session.execute(member_stmt)
    count_map = {row.collection_id: row.cnt for row in member_result.all()}

    return [
        {
            "id": str(c.id),
            "name": c.name,
            "description": c.description,
            "dataset_count": count_map.get(c.id, 0),
            "created_at": c.created_at.isoformat(),
        }
        for c in collections
    ]


async def search_datasets(
    session: AsyncSession,
    user: User | None,
    user_roles: set[str],
    filters: SearchFilters,
) -> tuple[list[Dataset], int]:
    """Search datasets with combined FTS + spatial + faceted filtering.

    When SEMANTIC_SEARCH_ENABLED is on and a text query is provided,
    automatically augments FTS results with vector similarity via
    Reciprocal Rank Fusion (k=60).

    Returns a tuple of (matching_datasets, total_count).
    """
    has_text_search = False
    rank_col = None

    # Base query always joins Record with eager-loaded keywords/contacts/distributions
    base_join = (
        select(Dataset)
        .join(Record, Dataset.record_id == Record.id)
        .options(
            selectinload(Dataset.record).selectinload(Record.keywords),
            selectinload(Dataset.record).selectinload(Record.contacts),
            selectinload(Dataset.record).selectinload(Record.distributions),
        )
    )

    # 1. Full-text search (search_vector now on Record + child-table EXISTS)
    if filters.q and filters.q.strip():
        text_clause, parts = _build_text_filter(filters.q)

        ts_query = parts["ts_query"]
        vector_match = parts["vector_match"]
        title_match = parts["title_match"]
        summary_match = parts["summary_match"]
        keyword_exists = parts["keyword_exists"]
        keyword_partial_exists = parts["keyword_partial_exists"]
        contact_exists = parts["contact_exists"]
        contact_partial_exists = parts["contact_partial_exists"]

        # Composite ranking: ts_rank_cd for vector matches + fixed boosts for child-table matches
        rank_col = (
            func.coalesce(
                case(
                    (vector_match, func.ts_rank_cd(Record.search_vector, ts_query)),
                    else_=literal(0.0),
                ),
                literal(0.0),
            )
            + case((keyword_exists, literal(0.1)), else_=literal(0.0))
            + case((contact_exists, literal(0.05)), else_=literal(0.0))
            + case((title_match, literal(0.3)), else_=literal(0.0))
            + case((summary_match, literal(0.12)), else_=literal(0.0))
            + case((keyword_partial_exists, literal(0.08)), else_=literal(0.0))
            + case((contact_partial_exists, literal(0.04)), else_=literal(0.0))
        ).label("rank")

        # Combine: match if any path hits
        stmt = base_join.add_columns(rank_col).where(text_clause)
        has_text_search = True
    else:
        stmt = base_join

    # 2. RBAC visibility filter (uses Record.visibility/created_by)
    stmt = apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)

    # 3. Shared filters (spatial, keywords, geometry_type, srid, org, datetime, etc.)
    # skip_text=True because text search is already applied above with ranking
    stmt = _apply_common_filters(stmt, filters, skip_text=True)

    # 4. Search-only filters (not applied to facet counts)
    if filters.record_type:
        stmt = stmt.where(Record.record_type == filters.record_type)
    if filters.date_from:
        stmt = stmt.where(Record.created_at >= filters.date_from)
    if filters.date_to:
        stmt = stmt.where(Record.created_at <= filters.date_to)
    if filters.vintage_start:
        stmt = stmt.where(Record.temporal_start >= filters.vintage_start)
    if filters.vintage_end:
        stmt = stmt.where(Record.temporal_end <= filters.vintage_end)

    # 4c. CQL2 structured filter (applied AFTER visibility + facets)
    if filters.cql2_filter:
        from app.standards.ogc.filtering import apply_cql2_filter

        stmt = apply_cql2_filter(stmt, filters.cql2_filter, filters.cql2_filter_lang)

    # 5. Count total matches — lightweight query without eager loads or ORDER BY.
    # Build a stripped-down count statement that reuses the same WHERE filters
    # but avoids the overhead of selectinload and rank expressions.
    count_base = (
        select(func.count())
        .select_from(Dataset)
        .join(Record, Dataset.record_id == Record.id)
    )
    # Re-apply the same WHERE clauses from stmt (stored on the compiled whereclause)
    if stmt.whereclause is not None:
        count_base = count_base.where(stmt.whereclause)
    total = (await session.execute(count_base)).scalar_one()

    # -- Hybrid semantic search with RRF --
    semantic_enabled = await SEMANTIC_SEARCH_ENABLED.get(session)
    use_rrf = semantic_enabled and has_text_search and filters.q and filters.q.strip()

    if use_rrf:
        # Get vector similarity ranks (empty dict on any failure = FTS-only)
        vector_ranks = await _get_vector_ranks(
            session, filters.q.strip(), filters.limit
        )

        if vector_ranks:
            # Get FTS-ranked record IDs (up to a reasonable cap for merging)
            fts_cap = max(filters.limit * 3, 100)
            fts_stmt = stmt.order_by(rank_col.desc()).limit(fts_cap)
            fts_result = await session.execute(fts_stmt)
            fts_rows = fts_result.unique().all()
            fts_ids = [str(row[0].record_id) for row in fts_rows]

            # Compute RRF-ranked order (only includes IDs from FTS results + vector results)
            # Filter vector_ranks to only include IDs that appear in FTS results
            # (vector-only results are excluded to keep it simple per plan)
            fts_id_set = set(fts_ids)
            filtered_vector_ranks = {
                rid: rank for rid, rank in vector_ranks.items() if rid in fts_id_set
            }

            rrf_ordered = _compute_rrf_scores(fts_ids, filtered_vector_ranks)

            # Apply pagination to RRF-ordered list
            page_ids = rrf_ordered[filters.skip : filters.skip + filters.limit]

            if page_ids:
                # Fetch full Dataset objects for the final page
                fetch_stmt = (
                    select(Dataset)
                    .join(Record, Dataset.record_id == Record.id)
                    .options(
                        selectinload(Dataset.record).selectinload(Record.keywords),
                        selectinload(Dataset.record).selectinload(Record.contacts),
                        selectinload(Dataset.record).selectinload(Record.distributions),
                    )
                    .where(Record.id.in_([uuid_mod.UUID(rid) for rid in page_ids]))
                )
                fetch_result = await session.execute(fetch_stmt)
                datasets_by_id = {
                    str(d.record_id): d for d in fetch_result.unique().scalars().all()
                }
                # Preserve RRF order
                datasets = [
                    datasets_by_id[rid] for rid in page_ids if rid in datasets_by_id
                ]
            else:
                datasets = []

            await _attach_updated_actor_identities(session, datasets)
            return datasets, total

    # 6. Sort (standard FTS-only path or semantic=False)
    # Ranking boosts: published status + freshness (last 30 days)
    # Only applied when sort_by == "relevance"; explicit sorts are unchanged.
    published_boost = case(
        (Record.record_status == "published", literal(2.0)),
        else_=literal(1.0),
    )
    freshness_boost = case(
        (Record.updated_at >= func.now() - text("interval '30 days'"), literal(1.5)),
        else_=literal(1.0),
    )

    if filters.sort_by == "relevance" and has_text_search:
        boosted_rank = rank_col * published_boost * freshness_boost
        stmt = stmt.order_by(boosted_rank.desc())
    elif filters.sort_by == "relevance":
        # No text search -- use boost factors with updated_at tiebreaker
        stmt = stmt.order_by(
            (published_boost * freshness_boost).desc(),
            Record.updated_at.desc(),
        )
    elif filters.sort_by == "date_added":
        _desc = filters.sort_desc if filters.sort_desc is not None else True
        stmt = stmt.order_by(
            Record.created_at.desc() if _desc else Record.created_at.asc()
        )
    elif filters.sort_by in {"title", "name"}:
        _desc = filters.sort_desc if filters.sort_desc is not None else False
        if _desc:
            stmt = stmt.order_by(
                collate(func.lower(Record.title), "C").desc(),
                collate(Record.title, "C").desc(),
            )
        else:
            # Keep title ordering deterministic and case-insensitive across collations.
            stmt = stmt.order_by(
                collate(func.lower(Record.title), "C").asc(),
                collate(Record.title, "C").asc(),
            )
    elif filters.sort_by == "last_updated":
        _desc = filters.sort_desc if filters.sort_desc is not None else True
        stmt = stmt.order_by(
            Record.updated_at.desc() if _desc else Record.updated_at.asc()
        )
    else:
        stmt = stmt.order_by(Record.created_at.desc())

    # 7. Paginate
    stmt = stmt.offset(filters.skip).limit(filters.limit)

    # 8. Execute
    result = await session.execute(stmt)
    if has_text_search:
        rows = result.unique().all()
        datasets = [row[0] for row in rows]
    else:
        datasets = list(result.unique().scalars().all())

    await _attach_updated_actor_identities(session, datasets)

    return datasets, total


def build_assets(
    dataset: Dataset,
    public_api_url: str,
    *,
    stac_asset_rows: list[dict] | None = None,
    record_status: str = "draft",
    storage_backend: str = "local",
    storage_provider: "StorageProvider | None" = None,
) -> dict:
    """Build a modality-aware unified assets dict for a dataset."""
    record_type = (
        getattr(dataset.record, "record_type", "vector_dataset") or "vector_dataset"
    )

    if record_type == "collection":
        return {}

    assets: dict = {}

    if record_type == "vector_dataset":
        # Vector download links
        for fmt, media_type in _FORMAT_MEDIA.items():
            assets[f"download_{fmt}"] = {
                "href": build_url(
                    f"/datasets/{dataset.id}/export?format={fmt}",
                    base_url=public_api_url,
                ),
                "type": media_type,
                "title": f"Download as {fmt.upper()}",
                "roles": ["data"],
            }
        # Vector tiles and OGC features (require table_name)
        if dataset.table_name is not None:
            assets["vector_tiles"] = {
                "href": build_url(
                    f"/tiles/data.{dataset.table_name}/{{z}}/{{x}}/{{y}}.pbf",
                    base_url=public_api_url,
                ),
                "type": "application/vnd.mapbox-vector-tile",
                "title": "Vector tiles",
                "roles": ["visual"],
            }
            assets["ogc_features"] = {
                "href": build_url(
                    f"/datasets/{dataset.id}/features/",
                    base_url=public_api_url,
                ),
                "type": "application/geo+json",
                "title": "OGC Features",
                "roles": ["data"],
            }

    elif record_type in ("raster_dataset", "vrt_dataset"):
        # Raster tile endpoint
        assets["raster_tiles"] = {
            "href": build_url(
                f"/raster-tiles/{dataset.id}/tiles/{{z}}/{{x}}/{{y}}.png",
                base_url=public_api_url,
            ),
            "type": "image/png",
            "title": "Raster tiles",
            "roles": ["visual"],
        }

    # Merge DatasetAsset rows -- takes precedence on key conflict
    stac_built = _build_stac_assets(
        stac_asset_rows,
        record_status=record_status,
        storage_backend=storage_backend,
        public_api_url=public_api_url,
        storage_provider=storage_provider,
    )
    assets.update(stac_built)

    return assets


def _build_stac_assets(
    asset_rows: list[dict] | None,
    *,
    record_status: str = "draft",
    storage_backend: str = "local",
    public_api_url: str = "",
    storage_provider: "StorageProvider | None" = None,
) -> dict:
    """Build STAC assets dict from pre-fetched DatasetAsset row dicts."""
    if not asset_rows:
        return {}

    from app.platform.assets.urls import resolve_asset_url

    result = {}
    for row in asset_rows:
        resolved_href = resolve_asset_url(
            row["href"],
            storage_backend=storage_backend,
            record_status=record_status,
            roles=row.get("roles"),
            public_api_url=public_api_url,
            storage_provider=storage_provider,
        )
        entry: dict = {"href": resolved_href}
        if row.get("media_type"):
            entry["type"] = row["media_type"]
        if row.get("roles"):
            entry["roles"] = row["roles"]
        if row.get("title"):
            entry["title"] = row["title"]
        if row.get("description"):
            entry["description"] = row["description"]
        result[row["key"]] = entry
    return result


def _build_themes(
    theme_category: list[str] | None,
    keywords: list | None = None,
) -> list[dict] | None:
    """Convert theme_category + keyword vocabulary data to OGC themes."""
    themes: list[dict] = []
    # Group keywords by vocabulary_uri
    if keywords:
        by_vocab: dict[str | None, list[str]] = {}
        for kw in keywords:
            uri = getattr(kw, "vocabulary_uri", None)
            by_vocab.setdefault(uri, []).append(kw.keyword)
        for uri, kws in by_vocab.items():
            entry: dict = {"concepts": [{"id": k} for k in kws]}
            if uri:
                entry["scheme"] = uri
            themes.append(entry)
    # Fallback: theme_category without vocabulary info
    if not themes and theme_category:
        themes.append({"concepts": [{"id": cat} for cat in theme_category]})
    return themes or None


def _build_time(dataset: Dataset) -> dict | None:
    """Build OGC time extent from record temporal_start/end."""
    record = dataset.record
    start = record.temporal_start
    end = record.temporal_end
    if start is None and end is None:
        return None
    return {
        "interval": [
            [
                start.isoformat() if start else "..",
                end.isoformat() if end else "..",
            ]
        ]
    }


def dataset_to_ogc_record(
    dataset: Dataset,
    public_api_url: str,
    *,
    stac_asset_rows: list[dict] | None = None,
    raster_meta: dict | None = None,
) -> dict:
    """Convert a Dataset ORM object to an OGC Record GeoJSON Feature dict."""
    record = dataset.record
    updated_user = getattr(record, "_provenance_updated_user", None)
    last_edited = derive_last_edited(
        created_at=record.created_at,
        updated_at=record.updated_at,
        updated_by=record.updated_by,
        updated_user=updated_user,
    )

    # Convert spatial_extent geometry to GeoJSON (6 decimal places ≈ 0.11m)
    geometry = None
    if record.spatial_extent is not None:
        try:
            shape = to_shape(record.spatial_extent)
            geometry = {
                "type": shape.geom_type,
                "coordinates": [
                    [(round(x, 6), round(y, 6)) for x, y in shape.exterior.coords]
                ]
                if hasattr(shape, "exterior")
                else [],
            }
        except Exception:
            geometry = None

    # STAC 1.0.0 datetime rules
    _ts = record.temporal_start
    _te = record.temporal_end
    if _ts is not None and _te is None:
        stac_datetime = f"{_ts.isoformat()}T00:00:00Z"
        stac_start_datetime = None
        stac_end_datetime = None
    elif _ts is not None and _te is not None:
        stac_datetime = None
        stac_start_datetime = f"{_ts.isoformat()}T00:00:00Z"
        stac_end_datetime = f"{_te.isoformat()}T00:00:00Z"
    else:
        stac_datetime = None
        stac_start_datetime = None
        stac_end_datetime = None

    # OGC Records puts "time" at the record root (alongside geometry)
    # AND in properties for STAC consumer compatibility.
    record_time = _build_time(dataset)

    ogc_record: dict = {
        "type": "Feature",
        "id": str(dataset.id),
        "conformsTo": [
            "http://www.opengis.net/spec/ogcapi-records-1/1.0/conf/record-core",
            "http://www.opengis.net/spec/ogcapi-records-1/1.0/conf/json",
        ],
        "time": record_time,
        "geometry": geometry,
        "properties": {
            "type": "dataset",
            "title": record.title,
            "description": record.summary,
            "keywords": [kw.keyword for kw in record.keywords]
            if record.keywords
            else None,
            "created": record.created_at.isoformat() if record.created_at else None,
            "updated": record.updated_at.isoformat() if record.updated_at else None,
            "updated_by_display": last_edited.display,
            "never_edited": last_edited.never_edited,
            "crs": f"EPSG:{dataset.srid}" if dataset.srid else None,
            "record_type": getattr(record, "record_type", "vector_dataset"),
            "band_count": None,
            "geometry_type": dataset.geometry_type,
            "feature_count": dataset.feature_count,
            "row_count": dataset.feature_count
            if getattr(record, "record_type", None) == "table"
            else None,
            "column_count": len(dataset.column_info) if dataset.column_info else None,
            "license": record.license,
            "source_organization": record.source_organization,
            "quality_detail": dataset.quality_detail,
            "quality_statement": dataset.quality_statement,
            "record_status": record.record_status,
            "has_quicklook": dataset.quicklook_256_uri is not None,
            # Enriched OGC properties (Phase 10-02)
            "formats": (
                list(_RASTER_FORMAT_MEDIA.values())
                if (
                    getattr(record, "record_type", "vector_dataset") or "vector_dataset"
                )
                in ("raster_dataset", "vrt_dataset")
                else list(_TABLE_FORMAT_MEDIA.values())
                if getattr(record, "record_type", None) == "table"
                else list(_FORMAT_MEDIA.values())
            ),
            "language": record.language or "en",
            "themes": _build_themes(record.theme_category, record.keywords),
            "rights": record.license,
            "contacts": [
                {
                    k: v
                    for k, v in {
                        "name": c.name,
                        "organization": c.organization,
                        "role": c.role,
                        "email": c.email,
                        "phone": c.phone,
                    }.items()
                    if v is not None
                }
                for c in record.contacts
            ]
            if record.contacts
            else None,
            "datetime": stac_datetime,
            **(
                {
                    "start_datetime": stac_start_datetime,
                    "end_datetime": stac_end_datetime,
                }
                if stac_start_datetime
                else {}
            ),
            "time": record_time,
            # ISO governance fields (API-01)
            "lineage": record.lineage_summary,
            "update_frequency": record.update_frequency,
            "constraints": (
                {"usage": record.usage_constraints, "access": record.access_constraints}
                if record.usage_constraints or record.access_constraints
                else None
            ),
            # Distributions from record_distributions table (API-01)
            "distributions": [
                {
                    "type": d.distribution_type,
                    "format": d.format,
                    "url": (
                        build_url(d.url, base_url=public_api_url)
                        if d.url.startswith("/")
                        else d.url
                    ),
                    "title": d.title,
                    "media_type": d.media_type,
                    "is_primary": d.is_primary,
                }
                for d in record.distributions
            ]
            if record.distributions
            else [],
        },
        "links": [
            {
                "rel": "self",
                "href": build_url(
                    f"/collections/datasets/items/{dataset.id}",
                    base_url=public_api_url,
                ),
                "type": "application/geo+json",
            },
            {
                "rel": "collection",
                "href": build_url("/collections/datasets", base_url=public_api_url),
                "type": "application/json",
            },
            {
                "rel": "root",
                "href": build_url("/", base_url=public_api_url),
                "type": "application/json",
            },
        ],
        "assets": build_assets(
            dataset,
            public_api_url,
            stac_asset_rows=stac_asset_rows,
            record_status=record.record_status or "draft",
            storage_backend=settings.storage_provider,
        ),
    }

    # STAC properties for raster/VRT records
    record_type = getattr(record, "record_type", "vector_dataset") or "vector_dataset"
    if raster_meta and record_type in ("raster_dataset", "vrt_dataset"):
        if raster_meta.get("epsg") is not None:
            ogc_record["properties"]["proj:epsg"] = raster_meta["epsg"]
        if raster_meta.get("width") and raster_meta.get("height"):
            ogc_record["properties"]["proj:shape"] = [
                raster_meta["height"],
                raster_meta["width"],
            ]
        if (
            raster_meta.get("res_x") is not None
            and raster_meta.get("res_y") is not None
        ):
            ogc_record["properties"]["gsd"] = min(
                abs(raster_meta["res_x"]), abs(raster_meta["res_y"])
            )
        if raster_meta.get("band_count"):
            ogc_record["properties"]["band_count"] = raster_meta["band_count"]

        # Build bands array from band_info
        bands = []
        band_info = raster_meta.get("band_info")
        if band_info and isinstance(band_info, list):
            for bi in band_info:
                band_entry: dict = {}
                if isinstance(bi, dict):
                    if bi.get("name"):
                        band_entry["name"] = bi["name"]
                    if bi.get("dtype"):
                        band_entry["data_type"] = bi["dtype"]
                    if bi.get("nodata") is not None:
                        band_entry["nodata"] = bi["nodata"]
                    if bi.get("description"):
                        band_entry["description"] = bi["description"]
                bands.append(band_entry)
        if bands:
            ogc_record["properties"]["bands"] = bands

        # VRT-specific fields
        if raster_meta.get("vrt_type"):
            ogc_record["properties"]["vrt_type"] = raster_meta["vrt_type"]
        if raster_meta.get("source_count") is not None:
            ogc_record["properties"]["source_count"] = raster_meta["source_count"]

    bbox = extract_bbox(dataset)
    if bbox is not None:
        ogc_record["bbox"] = bbox

    return ogc_record
