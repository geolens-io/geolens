"""Validated query parameters shared by GeoLens search endpoints."""

from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Literal

from fastapi import HTTPException, Query, status
from pydantic import BaseModel

from app.modules.catalog.features.service import parse_bbox
from app.modules.catalog.search.service import SearchFilters

_ALLOWED_RECORD_TYPES = {
    "vector_dataset",
    "raster_dataset",
    "vrt_dataset",
    "map",
    "service",
    "collection",
    "table",
}
_ALLOWED_SORT_BY = {"relevance", "date_added", "name", "title", "last_updated"}


def parse_spatial_params(
    geometry: str | None, bbox: str | None
) -> tuple[str | None, list[float] | None]:
    """Parse and validate geometry GeoJSON and bbox query parameters.

    Geometry takes precedence over bbox when both are provided.
    """
    geometry_geojson: str | None = None
    if geometry:
        try:
            parsed = json.loads(geometry)
            if "type" not in parsed or "coordinates" not in parsed:
                raise ValueError("missing type or coordinates")
            geometry_geojson = geometry
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid geometry GeoJSON: {exc}",
            ) from exc

    bbox_parsed: list[float] | None = None
    if bbox and not geometry_geojson:
        try:
            bbox_parsed = parse_bbox(bbox)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid bbox: {exc}",
            ) from exc

    return geometry_geojson, bbox_parsed


class SearchQueryParams(BaseModel):
    """Raw search query parameters converted through one validation choke point."""

    q: str | None = Query(None, max_length=1000, description="Full-text search query")
    bbox: str | None = Query(None, description="Bounding box: minx,miny,maxx,maxy")
    keywords: list[str] | None = Query(None, description="Filter by keywords")
    geometry_type: str | None = Query(None, description="Filter by geometry type")
    srid: int | None = Query(None, description="Filter by SRID")
    source_organization: str | None = Query(
        None, description="Filter by source organization"
    )
    record_type: str | None = Query(
        None, description="Filter by record type (vector_dataset, raster_dataset)"
    )
    date_from: date | None = Query(None, description="Filter created_at >=")
    date_to: date | None = Query(None, description="Filter created_at <=")
    vintage_start: date | None = Query(None, description="Filter data_vintage_start >=")
    vintage_end: date | None = Query(None, description="Filter data_vintage_end <=")
    sort_by: str = Query(
        "relevance",
        description="Sort: relevance, date_added, name, last_updated",
    )
    sort_desc: bool | None = Query(None, description="Sort direction override")
    offset: int = Query(0, ge=0, description="Pagination offset")
    limit: int = Query(10, ge=1, le=200, description="Page size")
    cql2_filter: str | None = Query(
        None,
        max_length=10000,
        alias="filter",
        validation_alias="filter",
        description="CQL2 filter expression",
    )
    cql2_filter_lang: str = Query(
        "cql2-text",
        alias="filter-lang",
        validation_alias="filter-lang",
        description="Filter language: cql2-text or cql2-json",
    )
    datetime_param: str | None = Query(
        None,
        alias="datetime",
        validation_alias="datetime",
        description="OGC datetime interval: instant, start/end, ../end, start/..",
    )
    exclude_synthetic: bool = Query(True, description="Exclude synthetic/test datasets")
    spatial_predicate: Literal["intersects", "within"] = Query(
        "intersects", description="Spatial predicate: intersects or within"
    )
    geometry: str | None = Query(
        None, max_length=50000, description="GeoJSON geometry for spatial filter"
    )
    collection_id: uuid.UUID | None = Query(
        None, description="Filter by collection membership"
    )

    model_config = {"extra": "ignore", "populate_by_name": True}

    def to_filters(self) -> SearchFilters:
        """Convert raw query parameters into service-layer filters."""
        if (
            self.record_type is not None
            and self.record_type not in _ALLOWED_RECORD_TYPES
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"record_type must be one of: {sorted(_ALLOWED_RECORD_TYPES)}",
            )
        if self.sort_by not in _ALLOWED_SORT_BY:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"sort_by must be one of: {sorted(_ALLOWED_SORT_BY)}",
            )
        geometry_geojson, bbox_parsed = parse_spatial_params(self.geometry, self.bbox)
        return SearchFilters(
            q=self.q,
            bbox=bbox_parsed,
            keywords=self.keywords,
            geometry_type=self.geometry_type,
            srid=self.srid,
            source_organization=self.source_organization,
            record_type=self.record_type,
            date_from=self.date_from,
            date_to=self.date_to,
            vintage_start=self.vintage_start,
            vintage_end=self.vintage_end,
            sort_by=self.sort_by,
            sort_desc=self.sort_desc,
            skip=self.offset,
            limit=self.limit,
            cql2_filter=self.cql2_filter,
            cql2_filter_lang=self.cql2_filter_lang,
            datetime_param=self.datetime_param,
            exclude_synthetic=self.exclude_synthetic,
            spatial_predicate=self.spatial_predicate,
            geometry_geojson=geometry_geojson,
            collection_id=self.collection_id,
        )

    def active_pagination_params(self) -> dict[str, str | list[str]]:
        """Return non-default query parameters for pagination URLs."""
        optional: dict[str, str | list[str] | None] = {
            "q": self.q,
            "geometry": self.geometry,
            "bbox": self.bbox,
            "keywords": self.keywords,
            "geometry_type": self.geometry_type,
            "srid": str(self.srid) if self.srid is not None else None,
            "source_organization": self.source_organization,
            "record_type": self.record_type,
            "collection_id": str(self.collection_id) if self.collection_id else None,
            "date_from": self.date_from.isoformat() if self.date_from else None,
            "date_to": self.date_to.isoformat() if self.date_to else None,
            "vintage_start": self.vintage_start.isoformat()
            if self.vintage_start
            else None,
            "vintage_end": self.vintage_end.isoformat() if self.vintage_end else None,
            "sort_by": self.sort_by if self.sort_by != "relevance" else None,
            "datetime": self.datetime_param,
            "exclude_synthetic": "false" if not self.exclude_synthetic else None,
            "filter": self.cql2_filter,
            "filter-lang": self.cql2_filter_lang
            if self.cql2_filter_lang != "cql2-text"
            else None,
        }
        return {key: value for key, value in optional.items() if value}
