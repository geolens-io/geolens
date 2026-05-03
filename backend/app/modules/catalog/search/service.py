"""Public search service facade.

The search service implementation is split across focused sibling modules while
this module preserves the stable import path used by routers, cache, STAC/OGC,
AI, platform defaults, and test callers.
"""

from __future__ import annotations

from app.modules.catalog.search.service_collections import search_collections
from app.modules.catalog.search.service_datasets import search_datasets
from app.modules.catalog.search.service_facets import get_facet_counts
from app.modules.catalog.search.service_filters import (
    FacetCounts,
    SearchFilters,
    _apply_common_filters,
    _build_text_filter,
    parse_ogc_datetime,
)
from app.modules.catalog.search.service_records import (
    _build_stac_assets,
    _build_themes,
    _build_time,
    build_assets,
    dataset_to_ogc_record,
)
from app.modules.catalog.search.service_semantic import _compute_rrf_scores

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
    "_build_stac_assets",
    "_build_themes",
    "_build_time",
]
