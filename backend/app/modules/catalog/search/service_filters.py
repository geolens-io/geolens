"""Shared search filters and filter query helpers."""

from __future__ import annotations

import uuid as uuid_mod
from dataclasses import dataclass
from datetime import date
from typing import Literal, TypedDict

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import aliased

from app.core.geo import make_bbox_filter
from app.modules.catalog.collections.models import CollectionDataset
from app.modules.catalog.datasets.domain.models import (
    Dataset,
    Record,
    RecordContact,
    RecordKeyword,
)


class FacetCounts(TypedDict):
    record_type: dict
    keywords: list[dict]
    source_organization: list[dict]
    srid: list[dict]
    collections: list[dict]


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


def _build_text_filter(q: str):
    """Build the full-text OR clause for a query string.

    Returns a SQLAlchemy ``or_()`` clause combining:
      - tsvector match on Record.search_vector
      - ILIKE on Record.title
      - ILIKE on Record.summary
      - FTS + ILIKE on RecordKeyword
      - FTS + ILIKE on RecordContact (name + organization)
    """
    query_text = q.strip()
    # Use 'simple' regconfig for non-Latin scripts that 'english' can't tokenize;
    # combine both so accented/stemmed English still works alongside CJK/Arabic/etc.
    ts_query_en = func.websearch_to_tsquery("english", query_text)
    ts_query_simple = func.websearch_to_tsquery("simple", query_text)
    ts_query = ts_query_en.bool_op("||")(ts_query_simple)
    record_simple_vector = func.to_tsvector(
        "simple",
        func.concat_ws(
            " ",
            func.coalesce(Record.title, ""),
            func.coalesce(Record.summary, ""),
            func.coalesce(Record.lineage_summary, ""),
            func.coalesce(func.array_to_string(Record.theme_category, " "), ""),
        ),
    )

    # unaccent both sides of ILIKE for accent-insensitive matching (cafe = cafe)
    unaccented_like = func.concat("%", func.unaccent(query_text.lower()), "%")
    english_vector_match = Record.search_vector.bool_op("@@")(ts_query)
    simple_vector_match = record_simple_vector.bool_op("@@")(ts_query_simple)
    vector_match = or_(english_vector_match, simple_vector_match)
    title_match = func.lower(func.unaccent(Record.title)).like(unaccented_like)
    summary_match = func.lower(func.unaccent(func.coalesce(Record.summary, ""))).like(
        unaccented_like
    )

    kw_fts_sel = select(RecordKeyword.id).where(
        RecordKeyword.record_id == Record.id,
        (
            func.to_tsvector("english", RecordKeyword.keyword).bool_op("||")(
                func.to_tsvector("simple", RecordKeyword.keyword)
            )
        ).bool_op("@@")(ts_query),
    )
    kw_like_sel = select(RecordKeyword.id).where(
        RecordKeyword.record_id == Record.id,
        func.lower(func.unaccent(RecordKeyword.keyword)).like(unaccented_like),
    )
    ct_fts_sel = select(RecordContact.id).where(
        RecordContact.record_id == Record.id,
        (
            func.to_tsvector(
                "english",
                func.coalesce(RecordContact.name, "")
                + " "
                + func.coalesce(RecordContact.organization, ""),
            ).bool_op("||")(
                func.to_tsvector(
                    "simple",
                    func.coalesce(RecordContact.name, "")
                    + " "
                    + func.coalesce(RecordContact.organization, ""),
                )
            )
        ).bool_op("@@")(ts_query),
    )
    ct_like_sel = select(RecordContact.id).where(
        RecordContact.record_id == Record.id,
        func.lower(
            func.unaccent(
                func.coalesce(RecordContact.name, "")
                + " "
                + func.coalesce(RecordContact.organization, "")
            )
        ).like(unaccented_like),
    )

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

    # Return individual parts too -- search_datasets needs them for ranking.
    return clause, {
        "ts_query": ts_query,
        "ts_query_simple": ts_query_simple,
        "vector_match": vector_match,
        "english_vector_match": english_vector_match,
        "simple_vector_match": simple_vector_match,
        "record_simple_vector": record_simple_vector,
        "title_match": title_match,
        "summary_match": summary_match,
        "keyword_exists": keyword_exists,
        "keyword_partial_exists": keyword_partial_exists,
        "contact_exists": contact_exists,
        "contact_partial_exists": contact_partial_exists,
    }


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
