"""Public search service facade.

The search service implementation is split across focused sibling modules while
this module preserves the stable import path used by routers, cache, STAC/OGC,
AI, platform defaults, and test callers.
"""

from __future__ import annotations

from app.modules.catalog.search.service_collections import (
    count_collections,
    search_collections,
)
from app.modules.catalog.search.service_datasets import count_datasets, search_datasets
from app.modules.catalog.search.service_facets import get_facet_counts
from app.modules.catalog.search.service_filters import (
    FacetCounts,
    SearchFilters,
    _apply_common_filters,
    _build_text_filter,
    parse_ogc_datetime,
    utc_midnight,
)
from app.modules.catalog.search.record_metadata import (
    build_themes as _build_themes,
    build_time as _build_time,
)
from app.modules.catalog.search.service_records import (
    _build_stac_assets,
    build_assets,
    dataset_to_ogc_record,
)
from app.modules.catalog.search.service_semantic import (
    UNRESOLVED,
    _compute_rrf_scores,
    consume_paired_query_claim,
    record_paired_query_claim,
    resolve_query_embedding,
)

__all__ = [
    "UNRESOLVED",
    "resolve_query_embedding",
    "FacetCounts",
    "SearchFilters",
    "get_facet_counts",
    "count_collections",
    "search_collections",
    "count_datasets",
    "search_datasets",
    "build_assets",
    "dataset_to_ogc_record",
    "parse_ogc_datetime",
    "utc_midnight",
    "consume_paired_query_claim",
    "record_paired_query_claim",
    "_build_text_filter",
    "_apply_common_filters",
    "_compute_rrf_scores",
    "_build_stac_assets",
    "_build_themes",
    "_build_time",
]
