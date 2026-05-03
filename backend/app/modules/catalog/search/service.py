"""Public search service facade and staged implementation module."""

from __future__ import annotations

import json
import uuid as uuid_mod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.platform.storage.provider import StorageProvider

import structlog
from sqlalchemy import Select, case, collate, func, literal, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement, Label

from app.core.identity import Identity
from app.modules.auth.models import User
from app.core.config import settings
from app.modules.catalog.authorization import apply_visibility_filter
from app.modules.catalog.datasets.domain.models import (
    Dataset,
    DatasetGrant,
    Record,
)
from app.modules.catalog.datasets.domain.utils import extract_bbox
from app.standards.ogc.utils import build_url
from app.core.persistent_config import EMBEDDING_MODEL, SEMANTIC_SEARCH_ENABLED
from app.modules.catalog.sources.provenance import derive_last_edited
from app.platform.extensions import get_catalog_port
from app.modules.catalog.search.service_collections import search_collections
from app.modules.catalog.search.service_facets import get_facet_counts
from app.modules.catalog.search.service_filters import (
    FacetCounts,
    SearchFilters,
    _apply_common_filters,
    _build_text_filter,
    parse_ogc_datetime,
)

logger = structlog.stdlib.get_logger(__name__)
EmbeddingUnavailableError = get_catalog_port().embedding_unavailable_error_class()

__all__ = [
    "FacetCounts",
    "SearchFilters",
    "get_facet_counts",
    "search_collections",
    "search_datasets",
    "build_assets",
    "dataset_to_ogc_record",
    "parse_ogc_datetime",
    "_build_text_filter",
    "_apply_common_filters",
    "_compute_rrf_scores",
]

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
    if not await get_catalog_port().has_embeddings(session):
        return {}

    # Generate query embedding
    try:
        query_vector = await get_catalog_port().generate_embedding(
            query_text.strip(), session
        )
    except EmbeddingUnavailableError:
        logger.warning("Embedding unavailable for semantic search, falling back to FTS")
        return {}
    except Exception:
        logger.warning(
            "Failed to generate query embedding, falling back to FTS", exc_info=True
        )
        return {}

    try:
        # Get current model name for filtering
        model_name = await EMBEDDING_MODEL.get(session)

        # Tune HNSW recall — default ef_search=40 may miss relevant results
        await get_catalog_port().set_hnsw_recall(session)
        RecordEmbedding = get_catalog_port().record_embedding_orm_class()

        # Vector similarity query: cosine distance <= 0.7 means similarity >= 0.3
        vector_stmt = (
            select(
                RecordEmbedding.record_id,
                RecordEmbedding.embedding.cosine_distance(query_vector).label(
                    "distance"
                ),
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
    except Exception:
        # pgvector extension missing, HNSW SET error, or DB execute failure —
        # honor the docstring contract and degrade to FTS-only
        logger.warning(
            "Vector similarity query failed, falling back to FTS", exc_info=True
        )
        return {}

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


def _build_fts_rank_col(
    filters: SearchFilters,
) -> tuple[ColumnElement[bool], Label[float]]:
    """Build the FTS composite rank column + matching WHERE clause.

    Returns ``(text_clause, rank_col)``. Caller should attach both to the
    base SELECT via ``.add_columns(rank_col).where(text_clause)``.
    """
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
    return text_clause, rank_col


def _apply_search_only_filters(stmt: Select, filters: SearchFilters) -> Select:
    """Apply filters that belong to /search but NOT to /facets.

    Handles record_type, date_from, date_to, vintage_start, vintage_end,
    and cql2_filter. Spatial / keyword / org / srid filters are already
    applied via _apply_common_filters and stay shared.
    """
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

    # CQL2 structured filter (applied AFTER visibility + facets)
    if filters.cql2_filter:
        from app.standards.ogc.filtering import apply_cql2_filter

        stmt = apply_cql2_filter(stmt, filters.cql2_filter, filters.cql2_filter_lang)
    return stmt


def _resolve_sort_order(
    stmt: Select,
    filters: SearchFilters,
    has_text_search: bool,
    rank_col: Label[float] | None,
) -> Select:
    """Apply ORDER BY clauses for the standard (non-RRF) sort path.

    Handles the 5 sort modes: relevance, date_added, title/name,
    last_updated, and the default fallback. ``rank_col`` may be None
    when no text query is present.
    """
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
    return stmt


async def _run_rrf_merge(
    session: AsyncSession,
    filters: SearchFilters,
    stmt: Select,
    rank_col: Label[float],
    total: int,
) -> tuple[list[Dataset], int] | None:
    """Execute hybrid FTS+vector RRF merge and return paginated results.

    Returns ``None`` when RRF doesn't apply (vector backend empty/failed).
    Caller falls through to the standard sort path on None.

    Returns ``([], total)`` rather than ``None`` when the FTS-cap query
    yields zero ids — caller returns that tuple as-is. Preserved from
    pre-refactor behavior; do not change to ``None`` (would alter
    observable behavior by falling through to the standard sort path).
    """
    if filters.q is None:
        raise ValueError("_run_rrf_merge requires filters.q to be non-None")
    q_stripped = filters.q.strip()
    # Get vector similarity ranks (empty dict on any failure = FTS-only)
    vector_ranks = await _get_vector_ranks(session, q_stripped, filters.limit)

    if not vector_ranks:
        logger.info(
            "rrf_fallback_to_fts",
            extra={"reason": "empty_vector_ranks", "q_prefix": q_stripped[:50]},
        )
        return None

    # Get FTS-ranked record IDs (up to a reasonable cap for merging).
    # Strip the inherited eager-loads — only record_id is needed at
    # this stage, so 4 wasted selectinload queries per request are
    # avoided (PERF-8).
    fts_cap = max(filters.limit * 3, 100)
    fts_stmt = (
        stmt.with_only_columns(Dataset.record_id)
        .order_by(rank_col.desc())
        .limit(fts_cap)
    )
    fts_result = await session.execute(fts_stmt)
    fts_ids = [str(row[0]) for row in fts_result.all()]

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
        datasets = [datasets_by_id[rid] for rid in page_ids if rid in datasets_by_id]
    else:
        datasets = []

    await _attach_updated_actor_identities(session, datasets)
    return datasets, total


async def search_datasets(
    session: AsyncSession,
    user: Identity | None,
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
        text_clause, rank_col = _build_fts_rank_col(filters)
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
    stmt = _apply_search_only_filters(stmt, filters)
    # 5. Count total matches — lightweight query without eager loads or ORDER BY.
    # Re-apply the same WHERE clauses from stmt (stored on the compiled whereclause).
    count_base = (
        select(func.count())
        .select_from(Dataset)
        .join(Record, Dataset.record_id == Record.id)
    )
    if stmt.whereclause is not None:
        count_base = count_base.where(stmt.whereclause)
    total = (await session.execute(count_base)).scalar_one()
    # -- Hybrid semantic search with RRF --
    semantic_enabled = await SEMANTIC_SEARCH_ENABLED.get(session)
    if semantic_enabled and has_text_search and filters.q and filters.q.strip():
        if rrf_result := await _run_rrf_merge(session, filters, stmt, rank_col, total):
            return rrf_result
    # 6. Sort (standard FTS-only path or semantic=False)
    stmt = _resolve_sort_order(stmt, filters, has_text_search, rank_col)
    # 7. Paginate + execute
    stmt = stmt.offset(filters.skip).limit(filters.limit)
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
    spatial_extent_geojson: str | None = None,
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

    # Convert spatial_extent geometry to GeoJSON. When the caller pre-computes
    # ST_AsGeoJSON in the query (PostGIS-side, fast), that string is parsed
    # directly. Otherwise fall back to Python-side WKB deserialization.
    geometry = None
    if spatial_extent_geojson is not None:
        try:
            geometry = json.loads(spatial_extent_geojson)
        except Exception:
            logger.warning(
                "ogc_geometry_geojson_parse_failed",
                extra={"record_id": str(record.id)},
                exc_info=True,
            )
            geometry = None
    elif record.spatial_extent is not None:
        try:
            from geoalchemy2.shape import to_shape

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
            logger.warning(
                "ogc_geometry_wkb_deserialize_failed",
                extra={"record_id": str(record.id)},
                exc_info=True,
            )
            geometry = None

    # STAC 1.0.0 datetime rules: if datetime is null, start_datetime AND
    # end_datetime MUST both be present.  When no temporal extent exists,
    # fall back to created_at so the item always passes STAC validation.
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
        # No temporal extent — use created_at as fallback
        stac_datetime = (
            record.created_at.isoformat().replace("+00:00", "Z")
            if record.created_at
            else None
        )
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
                        "roles": [c.role] if c.role else [],
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
