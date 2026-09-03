"""OGC/STAC asset and record conversion helpers."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.platform.storage.provider import StorageProvider

import structlog

from app.core.config import settings
from app.core.raster_bands import band_display_name, stac_band_nodata
from app.core.record_types import RASTER_FAMILY_RECORD_TYPES
from app.modules.catalog.datasets.domain.models import Dataset
from app.modules.catalog.datasets.domain.source_freshness import (
    compute_source_freshness,
)
from app.modules.catalog.records.localization import select_localized_record_text
from app.modules.catalog.datasets.domain.utils import extract_bbox
from app.modules.catalog.search.record_metadata import (
    build_contacts,
    build_external_ids,
    build_themes,
    build_time,
)
from app.modules.catalog.sources.provenance import derive_last_edited
from app.platform.dataset_origin import classify_origin, project_unknown
from app.standards.distributions import is_publishable_url
from app.standards.ogc.utils import build_url

logger = structlog.stdlib.get_logger(__name__)

# Media types for each download format
_FORMAT_MEDIA = {
    "gpkg": "application/geopackage+sqlite3",
    "geojson": "application/geo+json",
    "shp": "application/x-shapefile",
    "csv": "text/csv",
    "parquet": "application/vnd.apache.parquet",
    "fgb": "application/vnd.flatgeobuf",
    "pmtiles": "application/vnd.pmtiles",
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
    public_app_url: str | None = None,
) -> dict:
    """Build a modality-aware unified assets dict for a dataset.

    fix(#315 follow-up): the raster/VRT ``raster_tiles`` asset is served at the
    public APP origin (``/raster-tiles/...``, nginx-rewritten to the tile proxy),
    NOT the ``/api`` origin (which has no such route). Callers thread
    ``public_app_url`` so that one href uses the app origin; every other
    asset/link (vector_tiles at ``/tiles/...``, downloads, ogc_features) stays on
    ``public_api_url``. The ``or public_api_url`` fallback preserves prior
    behavior when a caller omits it.
    """
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

    elif record_type in RASTER_FAMILY_RECORD_TYPES:
        # Raster tile endpoint -- served at the public APP origin, not /api.
        # fix(#1372 codex r2): versioned like every rendered template — these
        # documents are generated per request, so a refetching STAC/OGC client
        # gets a fresh v and stops sharing the unversioned cache entry.
        raster_tiles_path = f"/raster-tiles/{dataset.id}/tiles/{{z}}/{{x}}/{{y}}.png"
        tile_version = getattr(dataset, "tile_cache_version", None)
        if tile_version:
            raster_tiles_path = f"{raster_tiles_path}?v={tile_version}"
        assets["raster_tiles"] = {
            "href": build_url(
                raster_tiles_path,
                base_url=(public_app_url or public_api_url),
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

    from app.platform.assets.keys import is_public_asset_key

    result = {}
    for row in asset_rows:
        # fix(#1290 review): the one shared boundary — see
        # app/platform/assets/keys.py for why it is an allowlist and which
        # paths cross it.
        if not is_public_asset_key(row["key"]):
            continue
        resolved_href = resolve_asset_url(
            row["href"],
            storage_backend=storage_backend,
            record_status=record_status,
            roles=row.get("roles"),
            public_api_url=public_api_url,
            storage_provider=storage_provider,
        )
        # GAP-031: resolve_asset_url returns None when no safe authorized URL
        # exists (e.g. local-storage proxy path that has no backend route).
        # Skip the asset entry rather than publishing a dead/colliding href.
        if resolved_href is None:
            continue
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


def dataset_to_ogc_record(
    dataset: Dataset,
    public_api_url: str,
    *,
    stac_asset_rows: list[dict] | None = None,
    raster_meta: dict | None = None,
    spatial_extent_geojson: str | None = None,
    public_app_url: str | None = None,
    preferred_languages: Sequence[str] | None = None,
    lineage_summary: str | None = None,
) -> dict:
    """Convert a Dataset ORM object to an OGC Record GeoJSON Feature dict.

    ``public_app_url`` is threaded to :func:`build_assets` so the raster/VRT
    ``raster_tiles`` asset href uses the app origin (see that function's
    docstring); all other assets/links remain on ``public_api_url``.

    fix(#1103): ``lineage_summary`` arrives access-checked from the caller
    (``visible_lineage_summary``) rather than being read off the record, because
    an analysis output's lineage names the titles of the datasets it was derived
    from and this function has no requester to check them against. Omitted when
    the caller does not supply it: a missing sentence is recoverable, a leaked
    one is not.
    """
    record = dataset.record
    localized = select_localized_record_text(record, preferred_languages)
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
            from shapely.geometry import mapping

            # fix(#430 BA-16): mapping() emits valid GeoJSON for any geometry type;
            # the old .exterior path built {"coordinates": []} for Point extents.
            geometry = mapping(to_shape(record.spatial_extent))
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
    record_time = build_time(dataset)
    description = (
        localized.summary.strip()
        if localized.summary and localized.summary.strip()
        else localized.title.strip()
    )
    keywords = [keyword.keyword for keyword in record.keywords]
    if not keywords:
        keywords = list(record.theme_category or [])
    license_value = record.license or "proprietary"

    # Resolve record_type once; used both for has_quicklook dispatch (below)
    # and for the STAC raster properties block at the end of this function.
    record_type = getattr(record, "record_type", "vector_dataset") or "vector_dataset"

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
            "title": localized.title,
            "description": description,
            "keywords": keywords,
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
            "license": license_value,
            "source_organization": record.source_organization,
            # Dataset origin for catalog cards: file format for uploads,
            # service/stac identifiers for remote registrations, 'created'
            # for empty layers, null for registered PostGIS tables and VRTs.
            "source_format": dataset.source_format,
            "quality_detail": dataset.quality_detail,
            "quality_statement": dataset.quality_statement,
            "record_status": record.record_status,
            # has_quicklook source depends on record_type:
            # - vector_dataset / table: Dataset.quicklook_256_uri (set by vector ingest)
            # - raster_dataset / vrt_dataset: RasterAsset.quicklook_256_uri, surfaced via
            #   raster_meta (internal-only storage key — never forwarded to response properties)
            "has_quicklook": (
                raster_meta is not None
                and raster_meta.get("quicklook_256_uri") is not None
            )
            if record_type in RASTER_FAMILY_RECORD_TYPES
            else (dataset.quicklook_256_uri is not None),
            # Enriched OGC properties (Phase 10-02)
            "formats": (
                list(_RASTER_FORMAT_MEDIA.values())
                if (
                    getattr(record, "record_type", "vector_dataset") or "vector_dataset"
                )
                in RASTER_FAMILY_RECORD_TYPES
                else list(_TABLE_FORMAT_MEDIA.values())
                if getattr(record, "record_type", None) == "table"
                else list(_FORMAT_MEDIA.values())
            ),
            "language": localized.language,
            "externalIds": build_external_ids(dataset),
            "themes": build_themes(record.theme_category, record.keywords),
            "rights": license_value,
            "contacts": build_contacts(dataset),
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
            "lineage": lineage_summary,
            "update_frequency": record.update_frequency,
            # feat(#1224): the same read-time computation dataset_to_response
            # serves, so a catalog card and a dataset detail page cannot
            # disagree about how late a dataset is. Search responses cache for
            # SEARCH_CACHE_TTL (30s), which is far below the shortest declared
            # period (one day), so a cached value can only lag a transition by
            # that window. Named source_freshness, not freshness: the frontend's
            # quality-freshness.ts answers a different question under that word.
            "source_freshness": compute_source_freshness(
                dataset.last_refreshed_at,
                record.update_frequency,
                datetime.now(timezone.utc),
                origin=classify_origin(dataset.source_format, record_type),
            ),
            # These values are projected only after search_datasets applies
            # the caller's visibility filter to the Dataset query. Keep the
            # wire spelling of an unprobed health state aligned with dataset
            # detail responses while preserving nullable timestamps.
            "source_health": project_unknown(dataset.source_health),
            # ``dataset_to_ogc_record`` also feeds JSONResponse-backed OGC
            # item and STAC routes, so these must be wire values rather than
            # raw ORM datetimes (Pydantic does not encode this plain dict).
            "last_checked_at": (
                dataset.last_checked_at.isoformat() if dataset.last_checked_at else None
            ),
            "last_refreshed_at": (
                dataset.last_refreshed_at.isoformat()
                if dataset.last_refreshed_at
                else None
            ),
            "constraints": (
                {"usage": record.usage_constraints, "access": record.access_constraints}
                if record.usage_constraints or record.access_constraints
                else None
            ),
            # Distributions from record_distributions table (API-01).
            # fix(#1469): the raster/VRT ingest tails write a row whose url is
            # the COG's object-storage KEY — unresolvable by a consumer, and it
            # exposes the storage layout. Dropped rather than replaced: this
            # profile already publishes the raster access surface above, as
            # build_assets' raster_tiles asset.
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
                for d in (record.distributions or ())
                if is_publishable_url(d.url)
            ],
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
            public_app_url=public_app_url,
        ),
    }

    # STAC properties for raster/VRT records (record_type already resolved above)
    if raster_meta and record_type in RASTER_FAMILY_RECORD_TYPES:
        if raster_meta.get("epsg") is not None:
            ogc_record["properties"]["proj:code"] = f"EPSG:{raster_meta['epsg']}"
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
            # fix(#1805 review round 5): gsd is a lossy min(abs(res_x),
            # abs(res_y)) -- two band-stack sources at (res_x=10, res_y=20)
            # and (res_x=10, res_y=30) collapse to the identical gsd=10, so
            # the client's gsd-only comparison silently passed a pair the
            # backend's _check_grid_alignment (which compares res_x and
            # res_y independently) rejects. Expose both axes so the client
            # can compare them the same way the backend does.
            ogc_record["properties"]["res_x"] = raster_meta["res_x"]
            ogc_record["properties"]["res_y"] = raster_meta["res_y"]
            # fix(#569): gsd is in CRS units — geographic CRSs deliver degrees,
            # and without this flag the UI formatted them as meters ("2 cm"
            # for a 60-arc-second global DEM).
            if raster_meta.get("crs_is_geographic") is not None:
                ogc_record["properties"]["crs_is_geographic"] = raster_meta[
                    "crs_is_geographic"
                ]
        if raster_meta.get("band_count"):
            ogc_record["properties"]["band_count"] = raster_meta["band_count"]

        # Build bands array from band_info.
        # fix(#1778): through the same two normalisers the STAC serializer
        # uses (`app.core.raster_bands`), so one dataset cannot report a band
        # one way here and another way there. `name` used to be read directly, a key no producer writes,
        # so the colour interpretation of every locally ingested raster was
        # dropped from this representation alone. Empty entries are skipped for
        # the reason given in `to_stac_properties`.
        bands = []
        band_info = raster_meta.get("band_info")
        if band_info and isinstance(band_info, list):
            for bi in band_info:
                if not isinstance(bi, dict):
                    continue
                band_entry: dict = {}
                band_name = band_display_name(bi)
                if band_name:
                    band_entry["name"] = band_name
                if bi.get("dtype"):
                    band_entry["data_type"] = bi["dtype"]
                nodata = stac_band_nodata(bi.get("nodata"))
                if nodata is not None:
                    band_entry["nodata"] = nodata
                elif raster_meta.get("nodata") is None:
                    # fix(#1805 review round 4 P2): kept across the move to
                    # the shared normaliser. This band's own stats don't
                    # carry a value `stac_band_nodata` can parse, but the
                    # asset WAS probed (band_info exists) and its
                    # authoritative RasterAsset.nodata column is None --
                    # NoData is confirmed absent, not merely unrecorded for
                    # this band. Emit the key explicitly so the client can
                    # tell "absent" from "unavailable" (nodata omitted below
                    # means the latter -- e.g. a remote COG whose band-level
                    # stats carry only min/max/mean even though the
                    # asset-level column IS set).
                    band_entry["nodata"] = None
                if bi.get("description"):
                    band_entry["description"] = bi["description"]
                if band_entry:
                    bands.append(band_entry)
        if bands:
            ogc_record["properties"]["raster:bands"] = bands

        # VRT-specific fields
        if raster_meta.get("vrt_type"):
            ogc_record["properties"]["vrt_type"] = raster_meta["vrt_type"]
        if raster_meta.get("source_count") is not None:
            ogc_record["properties"]["source_count"] = raster_meta["source_count"]

    bbox = extract_bbox(dataset)
    if bbox is not None:
        ogc_record["bbox"] = bbox

    return ogc_record
