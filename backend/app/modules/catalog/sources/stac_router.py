"""STAC catalog import endpoints.

Allows users to connect to external STAC APIs, browse collections,
search items, and import selected items as raster datasets.
"""

import asyncio
import uuid
from datetime import date, datetime
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.standards.ogc.errors import ERROR_RESPONSES_WRITE

from app.modules.audit.service import AuditEvent, audit_emit
from app.core.identity import Identity
from app.modules.auth.dependencies import require_permission
from app.modules.catalog.datasets.domain.models import (
    Dataset,
    Record,
    RecordKeyword,
)
from app.core.dependencies import get_db
from app.platform.extensions import get_catalog_port
from app.modules.catalog.sources.adapters.stac import (
    connect_stac_api,
    list_stac_collections,
    search_stac_items,
)
from app.modules.catalog.sources.security import SSRFError, validate_url_for_ssrf
from app.platform.storage.titiler_url import build_titiler_cog_url

import httpx

logger = structlog.stdlib.get_logger(__name__)
Visibility = Literal["private", "restricted", "internal", "public"]


async def _fetch_cog_info(url: str) -> dict | None:
    """Fetch COG metadata + statistics from Titiler for a remote asset URL.

    Returns dict with band_count, dtype, width, height, band_info (with
    min/max per band for rescaling), or None on failure.

    SEC-OBSV-02 (sec-audit 2026-05-21): SSRF protection here is a DUAL GATE.
    Both gates MUST be preserved when adding new callers -- bypassing either
    is an SSRF regression:

    Gate 1 (caller-side): EVERY caller of _fetch_cog_info MUST first call
    app.modules.catalog.sources.security.validate_url_for_ssrf(url) before
    passing the URL here. The import-flow call at line 454 satisfies this;
    any new caller MUST add the same pre-validation.

    Gate 2 (Titiler-side): docker-compose's Titiler service sets
    CPL_VSIL_CURL_ALLOWED_EXTENSIONS=.tif,.tiff,.cog,.vrt -- even if a
    malicious URL slips past Gate 1, Titiler's own GDAL VSI clamp rejects
    non-raster file extensions.

    Removing Gate 1 OR loosening Gate 2 must be a deliberate audit-tracked
    decision, not a refactor side-effect.
    """
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0)
        ) as client:
            # Fetch structural info
            info_resp = await client.get(
                build_titiler_cog_url("info", query={"url": url})
            )
            if info_resp.status_code != 200:
                return None
            info = info_resp.json()

            band_count = info.get("count", 1)
            dtype = info.get("dtype")

            # Fetch statistics for rescaling
            band_info = []
            try:
                stats_resp = await client.get(
                    build_titiler_cog_url("statistics", query={"url": url})
                )
                if stats_resp.status_code == 200:
                    stats = stats_resp.json()
                    for key in sorted(k for k in stats if k.startswith("b")):
                        band_info.append(
                            {
                                "min": stats[key].get("min"),
                                "max": stats[key].get("max"),
                                "mean": stats[key].get("mean"),
                            }
                        )
            except Exception:  # broad: per-band stats optional — Titiler payload shape varies; defaults are fine
                pass  # stats are optional — rendering will fall back to defaults

            return {
                "band_count": band_count,
                "dtype": dtype,
                "width": info.get("width"),
                "height": info.get("height"),
                "nodata": info.get("nodata"),
                "band_info": band_info or None,
            }
    except Exception as exc:  # broad: Titiler info call — httpx/JSON parse can throw varied errors; degrade to None
        logger.debug("Failed to fetch COG info from Titiler", url=url, error=str(exc))
        return None


router = APIRouter(
    prefix="/services/stac", tags=["STAC Import"], responses=ERROR_RESPONSES_WRITE
)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class StacConnectRequest(BaseModel):
    url: str = Field(
        min_length=1,
        max_length=2048,
        description="STAC API root URL to connect to.",
    )


class StacConnectResponse(BaseModel):
    url: str = Field(description="Normalized STAC API URL.")
    catalog_id: str = Field(description="Catalog identifier from the landing page.")
    title: str = Field(description="Catalog title.")
    description: str = Field(description="Catalog description.")
    stac_version: str = Field(description="STAC specification version.")


class StacCollectionSummary(BaseModel):
    id: str = Field(description="Collection identifier.")
    title: str = Field(description="Collection title.")
    description: str = Field(description="Collection description.")
    license: str | None = Field(default=None, description="SPDX license identifier.")
    keywords: list[str] = Field(default=[], description="Collection keywords.")
    bbox: list[float] | None = Field(
        default=None, description="Spatial extent as [west, south, east, north]."
    )
    temporal_start: str | None = Field(
        default=None, description="Start of temporal extent (ISO 8601)."
    )
    temporal_end: str | None = Field(
        default=None, description="End of temporal extent (ISO 8601)."
    )
    item_count: int | None = Field(
        default=None, description="Number of items if reported by the API."
    )


class StacCollectionsResponse(BaseModel):
    url: str = Field(description="STAC API URL that was queried.")
    collections: list[StacCollectionSummary] = Field(
        description="Available collections."
    )


class StacSearchRequest(BaseModel):
    url: str = Field(
        min_length=1,
        max_length=2048,
        description="STAC API root URL.",
    )
    collections: list[str] | None = Field(
        default=None, description="Filter by collection IDs."
    )
    bbox: list[float] | None = Field(
        default=None,
        min_length=4,
        max_length=4,
        description="Bounding box filter as [west, south, east, north].",
    )
    datetime_range: str | None = Field(
        default=None,
        description="Temporal filter in STAC datetime format (e.g. '2023-01-01/2023-12-31').",
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum items to return.",
    )


class StacItemSummary(BaseModel):
    id: str = Field(description="Item identifier.")
    collection: str | None = Field(default=None, description="Parent collection ID.")
    title: str = Field(description="Item title (falls back to ID).")
    bbox: list[float] | None = Field(default=None, description="Item bounding box.")
    datetime: str | None = Field(
        default=None, description="Primary datetime (ISO 8601)."
    )
    datetime_start: str | None = Field(
        default=None, description="Start datetime for ranges."
    )
    datetime_end: str | None = Field(
        default=None, description="End datetime for ranges."
    )
    epsg: int | None = Field(default=None, description="EPSG code from proj extension.")
    gsd: float | None = Field(
        default=None, description="Ground sample distance in meters."
    )
    cloud_cover: float | None = Field(
        default=None, description="Cloud cover percentage (eo extension)."
    )
    data_asset_href: str | None = Field(
        default=None, description="URL of the primary data asset (COG)."
    )
    data_asset_type: str | None = Field(
        default=None, description="Media type of the data asset."
    )
    data_asset_size_bytes: int | None = Field(
        default=None,
        description="Size of the primary data asset in bytes (from STAC file:size). None when not in manifest.",
    )
    thumbnail_href: str | None = Field(
        default=None, description="Thumbnail URL if available."
    )
    asset_count: int = Field(description="Number of assets on this item.")


class StacSearchResponse(BaseModel):
    items: list[StacItemSummary] = Field(description="Matching items.")
    matched: int | None = Field(
        default=None, description="Total matches (if reported by API)."
    )
    returned: int = Field(description="Number of items in this response.")


class StacImportItem(BaseModel):
    id: str = Field(max_length=2048, description="STAC item ID.")
    collection: str | None = Field(
        default=None, max_length=255, description="Parent collection ID."
    )
    title: str = Field(
        max_length=500, description="Title to use for the GeoLens dataset."
    )
    data_asset_href: str = Field(
        max_length=4096, description="URL of the COG asset to reference."
    )
    bbox: list[float] | None = Field(default=None, description="Item bounding box.")
    epsg: int | None = Field(default=None, description="EPSG code.")
    datetime_start: str | None = Field(
        default=None, max_length=50, description="Temporal start."
    )
    datetime_end: str | None = Field(
        default=None, max_length=50, description="Temporal end."
    )
    keywords: list[str] = Field(
        default=[], max_length=100, description="Keywords from STAC collection."
    )


class StacImportRequest(BaseModel):
    url: str = Field(
        min_length=1,
        max_length=2048,
        description="STAC API URL for provenance.",
    )
    items: list[StacImportItem] = Field(
        min_length=1,
        max_length=50,
        description="Items to import (max 50 per request).",
    )
    visibility: Visibility = Field(
        default="private",
        description="Visibility for imported datasets.",
    )


class StacImportResult(BaseModel):
    item_id: str = Field(description="STAC item ID that was processed.")
    dataset_id: uuid.UUID | None = Field(
        default=None, description="Created GeoLens dataset ID."
    )
    status: Literal["created", "skipped", "error"] = Field(
        description="Import result status."
    )
    error: str | None = Field(default=None, description="Error message if failed.")


class StacImportResponse(BaseModel):
    results: list[StacImportResult] = Field(description="Per-item import results.")
    created: int = Field(description="Number of datasets created.")
    skipped: int = Field(description="Number of items skipped (duplicates).")
    errors: int = Field(description="Number of items that failed.")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/connect", response_model=StacConnectResponse)
async def stac_connect(
    request: StacConnectRequest,
    user: Identity = Depends(require_permission("create_layers")),
    db: AsyncSession = Depends(get_db),
) -> StacConnectResponse:
    """Connect to a STAC API and validate the endpoint."""
    try:
        await validate_url_for_ssrf(request.url)
    except SSRFError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    result = await connect_stac_api(request.url)
    if result is None:
        await audit_emit(
            db,
            AuditEvent(
                user_id=user.id,
                action="stac_connect",
                resource_type="stac_api",
                details={"url": request.url, "result": "not_stac"},
            ),
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL does not appear to be a valid STAC API. Check the URL and try again.",
        )

    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="stac_connect",
            resource_type="stac_api",
            details={
                "url": request.url,
                "result": "success",
                "stac_version": result["stac_version"],
            },
        ),
    )
    await db.commit()

    return StacConnectResponse(
        url=request.url.rstrip("/"),
        catalog_id=result["id"],
        title=result["title"],
        description=result["description"],
        stac_version=result["stac_version"],
    )


@router.post("/collections", response_model=StacCollectionsResponse)
async def stac_collections(
    request: StacConnectRequest,
    user: Identity = Depends(require_permission("create_layers")),
) -> StacCollectionsResponse:
    """List collections from a connected STAC API."""
    try:
        await validate_url_for_ssrf(request.url)
    except SSRFError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    try:
        collections = await list_stac_collections(request.url)
    except Exception as exc:  # broad: STAC client/HTTP/parse can throw varied errors; map to 502 for the user
        logger.warning("STAC collections fetch failed", url=request.url, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch collections from STAC API.",
        )

    return StacCollectionsResponse(
        url=request.url.rstrip("/"),
        collections=[StacCollectionSummary(**c) for c in collections],
    )


@router.post("/search", response_model=StacSearchResponse)
async def stac_search(
    request: StacSearchRequest,
    user: Identity = Depends(require_permission("create_layers")),
) -> StacSearchResponse:
    """Search items in a STAC API with spatial/temporal filters."""
    try:
        await validate_url_for_ssrf(request.url)
    except SSRFError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    try:
        result = await search_stac_items(
            request.url,
            collections=request.collections,
            bbox=request.bbox,
            datetime_range=request.datetime_range,
            limit=request.limit,
        )
    except Exception as exc:  # broad: STAC /search client/HTTP/parse can throw varied errors; map to 502 for the user
        logger.warning("STAC search failed", url=request.url, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to search STAC API. The endpoint may be unavailable or does not support /search.",
        )

    return StacSearchResponse(
        items=[StacItemSummary(**item) for item in result["items"]],
        matched=result["matched"],
        returned=result["returned"],
    )


def _parse_date(iso_str: str | None) -> date | None:
    """Parse an ISO 8601 datetime string to a date, tolerant of formats."""
    if not iso_str:
        return None
    try:
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        return None


@router.post("/import", response_model=StacImportResponse)
async def stac_import(
    request: StacImportRequest,
    user: Identity = Depends(require_permission("create_layers")),
    db: AsyncSession = Depends(get_db),
) -> StacImportResponse:
    """Import selected STAC items as raster datasets.

    Each item is registered as a raster_dataset record referencing the
    remote COG asset URL. Titiler serves the tiles directly from the
    remote source — no file download required.
    """
    results: list[StacImportResult] = []
    created = 0
    skipped = 0
    errors = 0

    # Batch duplicate check — single query instead of N individual SELECTs
    hrefs = [i.data_asset_href for i in request.items]
    existing_hrefs: set[str] = set(
        (
            await db.execute(
                select(Dataset.source_url).where(
                    Dataset.source_url.in_(hrefs),
                    Dataset.source_format == "stac",
                )
            )
        )
        .scalars()
        .all()
    )

    # Pre-filter importable items and SSRF-validate, then fetch COG info
    # concurrently instead of N sequential HTTP calls.
    importable: list[StacImportItem] = []
    for item in request.items:
        if item.data_asset_href in existing_hrefs:
            results.append(
                StacImportResult(
                    item_id=item.id, status="skipped", error="Already imported"
                )
            )
            skipped += 1
            continue
        try:
            await validate_url_for_ssrf(item.data_asset_href)
        except SSRFError as exc:
            results.append(
                StacImportResult(item_id=item.id, status="error", error=str(exc))
            )
            errors += 1
            continue
        importable.append(item)

    # Parallel COG info fetch — up to 10 concurrent Titiler requests
    cog_info_map: dict[str, dict | None] = {}
    if importable:
        sem = asyncio.Semaphore(10)

        async def _fetch_bounded(url: str) -> tuple[str, dict | None]:
            async with sem:
                return url, await _fetch_cog_info(url)

        cog_results = await asyncio.gather(
            *(_fetch_bounded(item.data_asset_href) for item in importable)
        )
        cog_info_map = dict(cog_results)

    for item in importable:
        try:
            # Savepoint per item so a failure doesn't corrupt the session
            async with db.begin_nested():
                spatial_extent = None
                if item.bbox and len(item.bbox) >= 4:
                    w, s, e, n = item.bbox[:4]
                    wkt = f"POLYGON(({w} {s},{e} {s},{e} {n},{w} {n},{w} {s}))"
                    spatial_extent = func.ST_GeomFromText(wkt, 4326)

                record = Record(
                    title=item.title,
                    record_type="raster_dataset",
                    visibility=request.visibility,
                    record_status="published",
                    spatial_extent=spatial_extent,
                    temporal_start=_parse_date(item.datetime_start),
                    temporal_end=_parse_date(item.datetime_end),
                    source_organization="STAC Import",
                    created_by=user.id,
                    updated_by=user.id,
                )
                db.add(record)
                await db.flush()

                table_name = f"stac_{record.id.hex[:16]}"
                dataset = Dataset(
                    record_id=record.id,
                    table_name=table_name,
                    source_format="stac",
                    source_url=item.data_asset_href,
                    source_filename=item.id,
                    srid=item.epsg,
                )
                db.add(dataset)
                await db.flush()

                ci = cog_info_map.get(item.data_asset_href) or {}
                nodata_raw = ci.get("nodata")

                raster_asset = get_catalog_port().raster_asset_orm_class()(
                    dataset_id=dataset.id,
                    asset_uri=item.data_asset_href,
                    storage_backend="remote",
                    cog_status="verified",
                    epsg=item.epsg,
                    band_count=ci.get("band_count"),
                    dtype=ci.get("dtype"),
                    width=ci.get("width"),
                    height=ci.get("height"),
                    nodata=str(nodata_raw) if nodata_raw is not None else None,
                    band_info=ci.get("band_info"),
                )
                db.add(raster_asset)

                for kw in item.keywords:
                    db.add(
                        RecordKeyword(
                            record_id=record.id,
                            keyword=kw,
                            keyword_type="theme",
                        )
                    )

            results.append(
                StacImportResult(
                    item_id=item.id,
                    dataset_id=dataset.id,
                    status="created",
                )
            )
            created += 1

        except Exception as exc:  # broad: per-item STAC import is isolated; any failure is recorded per-item without aborting the batch
            logger.warning("STAC item import failed", item_id=item.id, error=str(exc))
            results.append(
                StacImportResult(item_id=item.id, status="error", error=str(exc))
            )
            errors += 1

    # Audit log
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="stac_import",
            resource_type="stac_api",
            details={
                "url": request.url,
                "requested": len(request.items),
                "created": created,
                "skipped": skipped,
                "errors": errors,
            },
        ),
    )
    await db.commit()

    return StacImportResponse(
        results=results,
        created=created,
        skipped=skipped,
        errors=errors,
    )
