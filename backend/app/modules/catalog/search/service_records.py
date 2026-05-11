"""OGC/STAC asset and record conversion helpers."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.platform.storage.provider import StorageProvider

import structlog

from app.core.config import settings
from app.modules.catalog.datasets.domain.models import Dataset
from app.modules.catalog.datasets.domain.utils import extract_bbox
from app.modules.catalog.sources.provenance import derive_last_edited
from app.standards.ogc.utils import build_url

logger = structlog.stdlib.get_logger(__name__)

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

# Non-spatial table formats -- shapefile excluded (geometry-specific)
_TABLE_FORMAT_MEDIA = {
    "csv": "text/csv",
    "gpkg": "application/geopackage+sqlite3",
    "geojson": "application/geo+json",
}


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
                    f"/collections/{dataset.id}/items",
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
        except (
            Exception
        ):  # broad: GeoJSON string from DB may be malformed; degrade to None geometry
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
        except Exception:  # broad: WKB deserialize — geoalchemy/shapely errors fall back to None geometry
            logger.warning(
                "ogc_geometry_wkb_deserialize_failed",
                extra={"record_id": str(record.id)},
                exc_info=True,
            )
            geometry = None

    # STAC 1.0.0 datetime rules: if datetime is null, start_datetime AND
    # end_datetime MUST both be present. When no temporal extent exists,
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
        # No temporal extent -- use created_at as fallback
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
