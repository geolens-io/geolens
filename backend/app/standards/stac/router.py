"""STAC API router: landing page, conformance, collections, items, search.

Visibility is enforced on all item-returning endpoints (Phase 1061 SEC-S01).
Anonymous users see only public+published raster records; authenticated users
see public + their owned private + any restricted records granted to their roles.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from starlette.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.catalog.collections.models import Collection, CollectionDataset
from app.core.config import settings
from app.core.identity import Identity
from app.core.record_types import RASTER_FAMILY_RECORD_TYPES
import app.core.db as _db_module
from app.modules.auth.dependencies import (
    get_optional_user,
    get_optional_user_no_security_schema,
)
from app.modules.catalog.authorization import (
    apply_visibility_filter,
    get_user_roles,
    visible_lineage_summaries,
    visible_lineage_summary,
)
from app.modules.catalog.datasets.domain.models import (
    Dataset,
    DatasetGrant,
    Record,
    RecordKeyword,
)
from app.modules.catalog.features.service import parse_bbox
from app.core.dependencies import get_db
from app.core.public_urls import get_public_api_url, get_public_app_url
from app.platform.extensions import get_catalog_port
from app.standards.ogc.errors import ERROR_RESPONSES_PUBLIC, NOT_FOUND_RESPONSE
from app.standards.ogc.utils import (
    content_language_for_record_languages,
    link_header_value,
    parse_accept_languages,
)
from app.core.geo import make_bbox_filter, rollup_bbox, rollup_bbox_columns
from app.modules.catalog.search.service import build_assets, dataset_to_ogc_record
from app.standards.stac.schemas import (
    StacCatalog,
    StacCollection,
    StacCollectionListResponse,
    StacConformance,
    StacItemCollection,
    StacItemCollectionResponse,
    StacItemResponse,
    StacLink,
)
from app.standards.stac.serializer import (
    STAC_CONFORMANCE,
    ogc_collection_to_stac_collection,
    ogc_record_to_stac_item,
)
from app.platform.storage import get_storage

stac_router = APIRouter(prefix="/stac", tags=["STAC"])


class GeoJSONResponse(JSONResponse):
    """JSON response class whose documented media type is GeoJSON."""

    media_type = "application/geo+json"


# Record types eligible for STAC
_STAC_RECORD_TYPES = RASTER_FAMILY_RECORD_TYPES

# Page-size ceiling shared by every item-returning STAC handler (H-24 lowered it
# from 1000 to bound deep-paging cost). An over-maximum limit is CLAMPED, never
# rejected: the STAC Item Search spec requires it and stac-api-validator
# enforces it. One constant so a future ceiling change cannot miss a handler.
_STAC_MAX_LIMIT = 200

# STAC Items must be collection-scoped to remain browsable by machine clients.
# This virtual collection does not create or mutate a catalog Collection; it is
# a deterministic protocol view over published raster/VRT datasets with no
# CollectionDataset membership.
STAC_UNASSIGNED_COLLECTION_ID = "geolens-unassigned"
_STAC_UNASSIGNED_COLLECTION_NAME = "Unassigned GeoLens Items"
_STAC_UNASSIGNED_COLLECTION_DESCRIPTION = (
    "Published raster datasets that have not been assigned to a GeoLens collection."
)


def _stac_content_language_headers(
    items: Sequence[dict | StacItemResponse],
) -> dict[str, str]:
    languages: list[str | None] = []
    for item in items:
        payload = item.model_dump(mode="json") if isinstance(item, BaseModel) else item
        value = payload.get("properties", {}).get("language")
        languages.append(value.get("code") if isinstance(value, dict) else None)
    language = content_language_for_record_languages(languages, fallback=None)
    headers = {"Vary": "Accept-Language"}
    if language:
        headers["Content-Language"] = language
    return headers


def _published_raster_filters():
    # Phase 1061 SEC-S01: aggregate queries scoped by CollectionDataset; item
    # bodies remain visibility-gated below via _base_published_raster_query.
    return (
        Record.record_type.in_(_STAC_RECORD_TYPES),
        Record.record_status == "published",
    )


def _unassigned_dataset_filter():
    """Match datasets without changing their core Collection relationships."""
    return Dataset.id.not_in(select(CollectionDataset.dataset_id))


def _parse_collection_uuid(collection_id: str) -> uuid.UUID | None:
    """Parse a stored Collection ID, returning None for non-UUID identifiers."""
    try:
        return uuid.UUID(collection_id)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _resolve_urls(db: AsyncSession, request: Request) -> tuple[str, str]:
    """Return (stac_api_url, public_api_url) with a single settings lookup."""
    public_api_url = await get_public_api_url(db, request=request)
    stac_api_url = f"{public_api_url.rstrip('/')}/stac"
    return stac_api_url, public_api_url


def _item_collection_response(result: StacItemCollection) -> Response:
    """Serialize one STAC FeatureCollection with matching HTTP navigation."""
    headers = _stac_content_language_headers(result.features)
    if link_value := link_header_value(result.links):
        headers["Link"] = link_value
    # exclude_none: optional StacLink fields (method, title) must be omitted,
    # not null — the STAC link schema requires `method` to match ^[A-Z]+$.
    payload = result.model_dump(mode="json", exclude_none=True)
    # Validation must not add optional fields that the item serializer omitted.
    payload["features"] = [
        feature.model_dump(mode="json", exclude_unset=True)
        for feature in result.features
    ]
    return JSONResponse(
        content=payload,
        media_type="application/geo+json",
        headers=headers,
    )


def _stac_page_url(
    base_href: str, offset: int, limit: int, extra: dict | None = None
) -> str:
    """Build a STAC pagination URL preserving active query params."""
    params: dict[str, str] = {"offset": str(offset), "limit": str(limit)}
    if extra:
        params.update(extra)
    return f"{base_href}?{urlencode(params)}"


def _parse_extent_row(
    ext_row: tuple | None,
) -> tuple[list[float] | None, list[str | None] | None, str | None]:
    """Parse a spatial/temporal extent + license DB row into STAC-ready values.

    fix(#886): the leading six columns come from ``rollup_bbox_columns``, and
    the STAC Collection ``extent.spatial.bbox`` takes the spec form -- STAC
    inherits RFC 7946 §5.2, so a rollup that crosses the antimeridian must be
    served as ``west > east`` rather than the global bbox a naive fold produced.
    """
    temporal_extent = None
    spatial_extent = rollup_bbox(ext_row[:6]) if ext_row else None
    if ext_row and (ext_row[6] is not None or ext_row[7] is not None):
        t_start = ext_row[6].isoformat() + "T00:00:00Z" if ext_row[6] else None
        t_end = ext_row[7].isoformat() + "T00:00:00Z" if ext_row[7] else None
        temporal_extent = [t_start, t_end]
    license = _collapse_licenses(ext_row[8]) if ext_row else None
    return spatial_extent, temporal_extent, license


def _collapse_licenses(values: list[str | None] | None) -> str | None:
    """Collapse member-record licenses into one STAC Collection license."""
    licenses = {v for v in (values or []) if v}
    if not licenses:
        return None
    return licenses.pop() if len(licenses) == 1 else "various"


async def _fetch_dataset_asset_rows(
    db: AsyncSession,
    dataset_ids: list[uuid.UUID],
) -> dict[str, list[dict]]:
    """Bulk-fetch DatasetAsset rows grouped by dataset ID."""
    if not dataset_ids:
        return {}
    by_dataset: dict[str, list[dict]] = {}
    for da in await get_catalog_port().list_dataset_assets(db, dataset_ids):
        ds_key = str(da.dataset_id)
        by_dataset.setdefault(ds_key, []).append(
            {
                "key": da.key,
                "href": da.href,
                "media_type": da.media_type,
                "roles": da.roles,
                "title": da.title,
                "description": da.description,
            }
        )
    return by_dataset


async def _fetch_raster_meta(
    db: AsyncSession,
    dataset_ids: list[uuid.UUID],
) -> dict[str, dict]:
    """Bulk-fetch raster metadata for a set of dataset IDs.

    Reads the shared raster query through CatalogPort (KISS-6). STAC items
    don't need vrt_type/resolution_strategy at this layer, which is what the
    port's ``_without_vrt`` reader means.
    """
    return await get_catalog_port().fetch_raster_meta_bulk_without_vrt(db, dataset_ids)


# fix(#1108 review): sentinel distinguishing "the page loop did not precompute
# lineage" from a precomputed None (a record with no lineage at all).
_LINEAGE_UNRESOLVED: Any = object()


async def _dataset_to_stac_item(
    db: AsyncSession,
    dataset: Dataset,
    public_api_url: str,
    stac_api_url: str,
    *,
    stac_asset_rows: list[dict] | None = None,
    raster_meta: dict | None = None,
    collection_id: str | None = None,
    spatial_extent_geojson: str | None = None,
    public_app_url: str | None = None,
    preferred_languages: Sequence[str] | None = None,
    user: Identity | None = None,
    user_roles: set[str] | None = None,
    lineage_summary: Any = _LINEAGE_UNRESOLVED,
) -> dict:
    """Convert a Dataset ORM object to a STAC Item dict with presigned URLs.

    ``spatial_extent_geojson`` (PERF-5) lets bulk callers (e.g. STAC items
    page) skip per-dataset Python-side WKB deserialization in
    ``dataset_to_ogc_record`` by precomputing ST_AsGeoJSON in one query.

    ``public_app_url`` (fix(#315) follow-up): the raster/VRT ``raster_tiles``
    asset is served at the public APP origin (/raster-tiles/...), not the /api
    origin, so it is threaded to both ``dataset_to_ogc_record`` and the
    presigned-URL ``build_assets`` re-build below.
    """
    record = dataset.record

    # Build OGC record (base representation)
    ogc_record = dataset_to_ogc_record(
        dataset,
        public_api_url,
        stac_asset_rows=stac_asset_rows,
        raster_meta=raster_meta,
        spatial_extent_geojson=spatial_extent_geojson,
        public_app_url=public_app_url,
        preferred_languages=preferred_languages,
        # fix(#1103): the prose names the same datasets the derived_from link
        # below points at, and is gated the same way — per requester, on each
        # referenced dataset rather than on the output they can already see.
        # fix(#1108 review): page loops precompute the whole page through
        # visible_lineage_summaries (one query per page, mirroring PERF-5's
        # spatial_extent_geojson); only single-item callers resolve here.
        lineage_summary=(
            await visible_lineage_summary(db, record, user, user_roles or set())
            if lineage_summary is _LINEAGE_UNRESOLVED
            else lineage_summary
        ),
    )

    # Re-build assets with storage_provider for presigned URLs
    try:
        storage = get_storage()
    except RuntimeError:
        storage = None

    ogc_record["assets"] = build_assets(
        dataset,
        public_api_url,
        stac_asset_rows=stac_asset_rows,
        record_status=record.record_status or "draft",
        storage_backend=settings.storage_provider,
        storage_provider=storage,
        public_app_url=public_app_url,
    )

    # Look up collection membership if not provided
    if collection_id is None:
        cd_result = await db.execute(
            select(CollectionDataset.collection_id)
            .where(CollectionDataset.dataset_id == dataset.id)
            .order_by(
                CollectionDataset.sort_order.asc(),
                CollectionDataset.added_at.asc(),
                CollectionDataset.collection_id.asc(),
            )
            .limit(1)
        )
        cd_row = cd_result.scalar_one_or_none()
        if cd_row is not None:
            collection_id = str(cd_row)
        else:
            collection_id = STAC_UNASSIGNED_COLLECTION_ID

    return ogc_record_to_stac_item(
        ogc_record,
        collection_id=collection_id,
        stac_api_url=stac_api_url,
        derived_from_id=await _visible_derived_from_id(db, record, user, user_roles),
    )


async def _visible_derived_from_id(
    db: AsyncSession,
    record: Record,
    user: Identity | None,
    user_roles: set[str] | None,
) -> str | None:
    """Source item id for a ``rel="derived_from"`` link, when it is fetchable.

    feat(#765): gated on the same query the item endpoints serve from, so the
    link never points at an item this requester would get a 404 for, and a
    private source is omitted entirely rather than disclosed as a dangling id.
    """
    reference = getattr(record, "derived_from", None) or {}
    raw_id = reference.get("dataset_id")
    if not raw_id:
        return None
    try:
        source_id = uuid.UUID(str(raw_id))
    except (TypeError, ValueError):
        return None
    stmt = (
        _base_published_raster_query(user, user_roles or set())
        .where(Dataset.id == source_id)
        .limit(1)
    )
    found = (await db.execute(stmt)).scalars().first()
    return str(source_id) if found is not None else None


# RFC 3339 date-time as required by the STAC API spec: full date + time with a
# Z or numeric UTC offset. The shared parse_ogc_datetime is deliberately more
# lenient (day-granular, bare dates), so STAC validates syntax first.
_RFC3339_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$"
)


def _validate_stac_datetime(datetime_str: str) -> str:
    """Enforce STAC's strict RFC 3339 datetime syntax, returning a normalized
    value (empty open-interval ends become ``..``) for the shared parser."""

    def _parse_side(part: str) -> datetime | None:
        if part in ("", ".."):
            return None
        if not _RFC3339_DATETIME_RE.match(part):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid RFC 3339 datetime: {part!r}",
            )
        try:
            # RFC 3339 allows lowercase t/z; fromisoformat does not.
            return datetime.fromisoformat(part.upper())
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid RFC 3339 datetime: {e}",
            )

    if "/" in datetime_str:
        parts = datetime_str.split("/")
        if len(parts) != 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid datetime interval: expected exactly one '/'",
            )
        start, end = (_parse_side(p) for p in parts)
        if start is None and end is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid datetime interval: both ends are open",
            )
        if start is not None and end is not None and start > end:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid datetime interval: start is after end",
            )
        return f"{parts[0] or '..'}/{parts[1] or '..'}"

    _parse_side(datetime_str)
    if datetime_str == "..":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid datetime: '..' is only valid inside an interval",
        )
    return datetime_str


def _base_published_raster_query(
    user: Identity | None,
    user_roles: set[str],
):
    """Base select for published raster/VRT datasets with visibility enforced.

    Phase 1061 SEC-S01: matches the OGC Features peer router. Anonymous users
    see only public+published records; authenticated users see public + their
    owned private + any restricted records granted to their roles.
    """
    stmt = (
        select(Dataset)
        .join(Record, Dataset.record_id == Record.id)
        .options(
            selectinload(Dataset.record).selectinload(Record.keywords),
            selectinload(Dataset.record).selectinload(Record.contacts),
            selectinload(Dataset.record).selectinload(Record.distributions),
            selectinload(Dataset.record).selectinload(Record.translations),
        )
        .where(
            Record.record_type.in_(_STAC_RECORD_TYPES),
            Record.record_status == "published",
        )
    )
    return apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)


async def _resolve_roles(db: AsyncSession, user: Identity | None) -> set[str]:
    """Resolve user_roles, returning an empty set for anonymous callers."""
    if user is None:
        return set()
    return await get_user_roles(db, user)


async def _has_visible_items(
    db: AsyncSession,
    user: Identity | None,
    user_roles: set[str],
    scope_filter,
) -> bool:
    """Return whether the caller can see at least one STAC Item in scope."""
    stmt = (
        _base_published_raster_query(user, user_roles)
        .where(scope_filter)
        .with_only_columns(Dataset.id)
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none() is not None


async def _has_unassigned_items(
    db: AsyncSession,
    user: Identity | None,
    user_roles: set[str],
) -> bool:
    """Return whether the caller can see at least one unassigned STAC Item."""
    return await _has_visible_items(db, user, user_roles, _unassigned_dataset_filter())


def _collection_membership_filter(collection_uuid: uuid.UUID):
    """Match datasets belonging to a stored Collection."""
    return Dataset.id.in_(
        select(CollectionDataset.dataset_id).where(
            CollectionDataset.collection_id == collection_uuid
        )
    )


async def _collection_scope_filter(
    db: AsyncSession,
    collection_id: str,
    user: Identity | None,
    user_roles: set[str],
):
    """Resolve a real or virtual STAC collection to its item filter."""
    if collection_id == STAC_UNASSIGNED_COLLECTION_ID:
        if not await _has_unassigned_items(db, user, user_roles):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collection not found",
            )
        return _unassigned_dataset_filter()

    collection_uuid = _parse_collection_uuid(collection_id)
    if collection_uuid is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Collection not found",
        )
    coll_result = await db.execute(
        select(Collection.id).where(Collection.id == collection_uuid)
    )
    if coll_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Collection not found",
        )
    membership = _collection_membership_filter(collection_uuid)
    # Collections with no visible STAC Items are hidden from the STAC surface
    # (they would otherwise advertise a fabricated global extent), matching the
    # gating the virtual unassigned collection already gets above.
    if not await _has_visible_items(db, user, user_roles, membership):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Collection not found",
        )
    return membership


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


# response_model_exclude_none (here and on the collection routes): optional
# StacLink fields must be omitted rather than serialized as null — the STAC
# link schema types `method` as a ^[A-Z]+$ string.
@stac_router.get("/", response_model=StacCatalog, response_model_exclude_none=True)
async def landing_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: Identity | None = Depends(get_optional_user_no_security_schema),
) -> StacCatalog:
    """STAC Catalog landing page."""
    stac_api_url, _ = await _resolve_urls(db, request)

    links = [
        StacLink(rel="self", href=f"{stac_api_url}/", type="application/json"),
        StacLink(rel="root", href=f"{stac_api_url}/", type="application/json"),
        StacLink(
            rel="data", href=f"{stac_api_url}/collections", type="application/json"
        ),
        StacLink(
            rel="conformance",
            href=f"{stac_api_url}/conformance",
            type="application/json",
        ),
        StacLink(
            rel="search",
            href=f"{stac_api_url}/search",
            type="application/geo+json",
            method="GET",
        ),
        StacLink(
            rel="service-desc",
            href=f"{stac_api_url}/api",
            type="application/vnd.oai.openapi+json;version=3.1",
        ),
    ]

    # Add rel=child for each collection with at least one visible STAC Item —
    # empty collections are hidden from the STAC surface (see
    # _collection_scope_filter).
    user_roles = await _resolve_roles(db, user)
    child_stmt = (
        select(CollectionDataset.collection_id)
        .distinct()
        .select_from(Record)
        .join(Dataset, Dataset.record_id == Record.id)
        .join(CollectionDataset, CollectionDataset.dataset_id == Dataset.id)
        .where(*_published_raster_filters())
        .order_by(CollectionDataset.collection_id)
    )
    child_stmt = apply_visibility_filter(
        child_stmt, user, user_roles, Record, DatasetGrant
    )
    for coll_id in (await db.execute(child_stmt)).scalars().all():
        links.append(
            StacLink(
                rel="child",
                href=f"{stac_api_url}/collections/{coll_id}",
                type="application/json",
            )
        )
    if await _has_unassigned_items(db, user, user_roles):
        links.append(
            StacLink(
                rel="child",
                href=(f"{stac_api_url}/collections/{STAC_UNASSIGNED_COLLECTION_ID}"),
                type="application/json",
            )
        )

    return StacCatalog(
        id="geolens-stac",
        title="GeoLens STAC API",
        description="Published raster datasets from GeoLens catalog",
        conformsTo=STAC_CONFORMANCE,
        links=links,
    )


@stac_router.get("/api", include_in_schema=False)
async def service_desc(request: Request) -> Response:
    """The OpenAPI document, served with the media type the landing page's
    service-desc link advertises (the shared /openapi.json route always
    answers ``application/json``, which fails the STAC round-trip check)."""
    return JSONResponse(
        request.app.openapi(),
        media_type="application/vnd.oai.openapi+json;version=3.1",
    )


@stac_router.get("/conformance", response_model=StacConformance)
async def conformance() -> StacConformance:
    """STAC API conformance classes."""
    return StacConformance(conformsTo=STAC_CONFORMANCE)


@stac_router.get(
    "/collections",
    response_model=StacCollectionListResponse,
    response_model_exclude_none=True,
)
async def get_collections(
    request: Request,
    db: AsyncSession = Depends(get_db),
    # fix(#430 codex): no-schema variant keeps this public endpoint anonymous in
    # the OpenAPI surface — the plain optional dep stamped bearer security here,
    # narrowing the generated SDK clients to AuthenticatedClient.
    user: Identity | None = Depends(get_optional_user_no_security_schema),
) -> StacCollectionListResponse:
    """List all STAC Collections."""
    stac_api_url, _ = await _resolve_urls(db, request)
    # fix(#430 BA-05): aggregate extent/keyword/EPSG summaries must exclude
    # private-but-published rasters, matching the item-body visibility gate.
    user_roles = await _resolve_roles(db, user)

    # Fetch all collections
    coll_result = await db.execute(select(Collection))
    collections = coll_result.scalars().all()

    # fix(#1778): these four aggregates used to asyncio.gather with each
    # branch opening its own async_session() -- a nested pool checkout on
    # top of the connection this request already holds via `db` (get_db
    # never commits on the read path, so that connection stays checked out
    # for the whole request). 5 checkouts per anonymous, uncached request
    # exhausts the default 13-connection pool at 3 concurrent requests. Run
    # them sequentially on the caller's own session instead, the same trade
    # made in service_query.py's dataset-detail fetch (fix #1436 codex
    # review): these are grouped-aggregate queries over the same joined
    # set, so the wall-clock cost of sequencing them is negligible next to
    # that risk, and unlike dataset-detail this endpoint is anonymous.

    async def _fetch_extents() -> dict[str, tuple]:
        extent_stmt = (
            select(
                CollectionDataset.collection_id,
                *rollup_bbox_columns(Record.spatial_extent),
                func.min(Record.temporal_start),
                func.max(Record.temporal_end),
                func.array_agg(func.distinct(Record.license)),
            )
            .select_from(Record)
            .join(Dataset, Dataset.record_id == Record.id)
            .outerjoin(CollectionDataset, CollectionDataset.dataset_id == Dataset.id)
            .where(*_published_raster_filters())
            .group_by(CollectionDataset.collection_id)
        )
        extent_stmt = apply_visibility_filter(
            extent_stmt, user, user_roles, Record, DatasetGrant
        )
        rows = await db.execute(extent_stmt)
        return {
            (str(r[0]) if r[0] is not None else STAC_UNASSIGNED_COLLECTION_ID): r[1:]
            for r in rows.all()
        }

    async def _fetch_keywords() -> dict[str, list[str]]:
        kw_stmt = (
            select(
                CollectionDataset.collection_id,
                func.array_agg(func.distinct(RecordKeyword.keyword)),
            )
            .select_from(RecordKeyword)
            .join(Record, RecordKeyword.record_id == Record.id)
            .join(Dataset, Dataset.record_id == Record.id)
            .outerjoin(CollectionDataset, CollectionDataset.dataset_id == Dataset.id)
            .where(*_published_raster_filters())
            .group_by(CollectionDataset.collection_id)
        )
        kw_stmt = apply_visibility_filter(
            kw_stmt, user, user_roles, Record, DatasetGrant
        )
        rows = await db.execute(kw_stmt)
        result: dict[str, list[str]] = {}
        for row in rows.all():
            kws = row[1]
            if kws:
                key = (
                    str(row[0]) if row[0] is not None else STAC_UNASSIGNED_COLLECTION_ID
                )
                result[key] = sorted([k for k in kws if k])
        return result

    async def _fetch_projection_codes() -> dict[str, list[str]]:
        RasterAsset = get_catalog_port().raster_asset_orm_class()
        epsg_stmt = (
            select(
                CollectionDataset.collection_id,
                func.array_agg(func.distinct(RasterAsset.epsg)),
            )
            .select_from(RasterAsset)
            .join(Dataset, Dataset.id == RasterAsset.dataset_id)
            .join(Record, Record.id == Dataset.record_id)
            .outerjoin(CollectionDataset, CollectionDataset.dataset_id == Dataset.id)
            .where(*_published_raster_filters(), RasterAsset.epsg.isnot(None))
            .group_by(CollectionDataset.collection_id)
        )
        epsg_stmt = apply_visibility_filter(
            epsg_stmt, user, user_roles, Record, DatasetGrant
        )
        rows = await db.execute(epsg_stmt)
        result: dict[str, list[int]] = {}
        for row in rows.all():
            codes = row[1]
            if codes:
                key = (
                    str(row[0]) if row[0] is not None else STAC_UNASSIGNED_COLLECTION_ID
                )
                result[key] = [f"EPSG:{code}" for code in sorted(c for c in codes if c)]
        return result

    async def _fetch_has_unassigned() -> bool:
        return await _has_unassigned_items(db, user, user_roles)

    extent_map = await _fetch_extents()
    keywords_map = await _fetch_keywords()
    projection_map = await _fetch_projection_codes()
    has_unassigned = await _fetch_has_unassigned()

    stac_collections = []
    for coll in collections:
        coll_key = str(coll.id)
        if coll_key not in extent_map:
            # No visible STAC Items — hidden from the STAC surface rather than
            # advertised with a fabricated global extent.
            continue
        spatial_extent, temporal_extent, license = _parse_extent_row(
            extent_map[coll_key]
        )

        summaries = {}
        if coll_key in projection_map:
            summaries["proj:code"] = projection_map[coll_key]

        stac_coll = ogc_collection_to_stac_collection(
            coll_key,
            coll.name,
            coll.description,
            spatial_extent=spatial_extent,
            temporal_extent=temporal_extent,
            stac_api_url=stac_api_url,
            keywords=keywords_map.get(coll_key),
            summaries=summaries or None,
            license=license,
        )
        stac_collections.append(stac_coll)

    if has_unassigned:
        fallback_key = STAC_UNASSIGNED_COLLECTION_ID
        spatial_extent, temporal_extent, license = _parse_extent_row(
            extent_map.get(fallback_key)
        )
        fallback_summaries = None
        if fallback_key in projection_map:
            fallback_summaries = {"proj:code": projection_map[fallback_key]}
        stac_collections.append(
            ogc_collection_to_stac_collection(
                fallback_key,
                _STAC_UNASSIGNED_COLLECTION_NAME,
                _STAC_UNASSIGNED_COLLECTION_DESCRIPTION,
                spatial_extent=spatial_extent,
                temporal_extent=temporal_extent,
                stac_api_url=stac_api_url,
                keywords=keywords_map.get(fallback_key),
                summaries=fallback_summaries,
                license=license,
            )
        )

    return StacCollectionListResponse(
        collections=stac_collections,
        links=[
            StacLink(
                rel="self", href=f"{stac_api_url}/collections", type="application/json"
            ),
            StacLink(rel="root", href=f"{stac_api_url}/", type="application/json"),
        ],
    )


@stac_router.get(
    "/collections/{collection_id}",
    response_model=StacCollection,
    response_model_exclude_none=True,
    responses={404: NOT_FOUND_RESPONSE},
)
async def get_collection(
    collection_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    # fix(#430 codex): no-schema variant — see get_collections above.
    user: Identity | None = Depends(get_optional_user_no_security_schema),
) -> StacCollection:
    """Get a single STAC Collection."""
    stac_api_url, _ = await _resolve_urls(db, request)
    # fix(#430 BA-05): scope aggregate summaries to visible rasters.
    user_roles = await _resolve_roles(db, user)

    is_unassigned = collection_id == STAC_UNASSIGNED_COLLECTION_ID
    collection_uuid = _parse_collection_uuid(collection_id)
    if is_unassigned:
        if not await _has_unassigned_items(db, user, user_roles):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collection not found",
            )
        collection_name = _STAC_UNASSIGNED_COLLECTION_NAME
        collection_description = _STAC_UNASSIGNED_COLLECTION_DESCRIPTION
    else:
        if collection_uuid is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collection not found",
            )
        coll_result = await db.execute(
            select(Collection).where(Collection.id == collection_uuid)
        )
        coll = coll_result.scalar_one_or_none()
        if coll is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collection not found",
            )
        collection_name = coll.name
        collection_description = coll.description
        # Hidden from the STAC surface when it has no visible Items — see
        # _collection_scope_filter.
        if not await _has_visible_items(
            db, user, user_roles, _collection_membership_filter(collection_uuid)
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collection not found",
            )

    # Three independent metadata queries -- run concurrently with separate sessions.

    async def _fetch_extent() -> tuple | None:
        extent_stmt = (
            select(
                *rollup_bbox_columns(Record.spatial_extent),
                func.min(Record.temporal_start),
                func.max(Record.temporal_end),
                func.array_agg(func.distinct(Record.license)),
            )
            .select_from(Record)
            .join(Dataset, Dataset.record_id == Record.id)
            .where(*_published_raster_filters())
        )
        if is_unassigned:
            extent_stmt = extent_stmt.where(_unassigned_dataset_filter())
        else:
            extent_stmt = extent_stmt.join(
                CollectionDataset, CollectionDataset.dataset_id == Dataset.id
            ).where(CollectionDataset.collection_id == collection_uuid)
        extent_stmt = apply_visibility_filter(
            extent_stmt, user, user_roles, Record, DatasetGrant
        )
        async with _db_module.async_session() as s:
            return (await s.execute(extent_stmt)).one_or_none()

    async def _fetch_kw() -> list[str] | None:
        kw_stmt = (
            select(func.distinct(RecordKeyword.keyword))
            .select_from(RecordKeyword)
            .join(Record, RecordKeyword.record_id == Record.id)
            .join(Dataset, Dataset.record_id == Record.id)
            .where(*_published_raster_filters())
        )
        if is_unassigned:
            kw_stmt = kw_stmt.where(_unassigned_dataset_filter())
        else:
            kw_stmt = kw_stmt.join(
                CollectionDataset, CollectionDataset.dataset_id == Dataset.id
            ).where(CollectionDataset.collection_id == collection_uuid)
        kw_stmt = apply_visibility_filter(
            kw_stmt, user, user_roles, Record, DatasetGrant
        )
        async with _db_module.async_session() as s:
            rows = await s.execute(kw_stmt)
            result = sorted([r[0] for r in rows.all() if r[0]])
            return result or None

    async def _fetch_projection() -> dict | None:
        RasterAsset = get_catalog_port().raster_asset_orm_class()
        projection_stmt = (
            select(func.distinct(RasterAsset.epsg))
            .join(Dataset, Dataset.id == RasterAsset.dataset_id)
            .join(Record, Record.id == Dataset.record_id)
            .where(
                *_published_raster_filters(),
                RasterAsset.epsg.isnot(None),
            )
        )
        if is_unassigned:
            projection_stmt = projection_stmt.where(_unassigned_dataset_filter())
        else:
            projection_stmt = projection_stmt.join(
                CollectionDataset, CollectionDataset.dataset_id == Dataset.id
            ).where(CollectionDataset.collection_id == collection_uuid)
        projection_stmt = apply_visibility_filter(
            projection_stmt, user, user_roles, Record, DatasetGrant
        )
        async with _db_module.async_session() as s:
            rows = await s.execute(projection_stmt)
            codes = sorted([r[0] for r in rows.all() if r[0]])
            return {"proj:code": [f"EPSG:{code}" for code in codes]} if codes else None

    ext_row, coll_keywords, summaries = await asyncio.gather(
        _fetch_extent(), _fetch_kw(), _fetch_projection()
    )
    spatial_extent, temporal_extent, license = _parse_extent_row(ext_row)

    return ogc_collection_to_stac_collection(
        collection_id,
        collection_name,
        collection_description,
        spatial_extent=spatial_extent,
        temporal_extent=temporal_extent,
        stac_api_url=stac_api_url,
        keywords=coll_keywords,
        summaries=summaries,
        license=license,
    )


@stac_router.get(
    "/collections/{collection_id}/items",
    response_model=StacItemCollectionResponse,
    response_class=GeoJSONResponse,
    responses=ERROR_RESPONSES_PUBLIC,
)
async def get_collection_items(
    collection_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: Identity | None = Depends(get_optional_user),
    bbox: str | None = Query(None, description="Bounding box: west,south,east,north"),
    datetime_param: str | None = Query(
        None, alias="datetime", description="OGC datetime interval"
    ),
    limit: int = Query(
        10,
        ge=1,
        description=(
            f"Maximum number of items returned. Values above {_STAC_MAX_LIMIT} "
            f"are clamped to {_STAC_MAX_LIMIT}, per the STAC Item Search spec's "
            "clamp-don't-reject recommendation."
        ),
    ),
    offset: int = Query(
        0,
        ge=0,
        description=(
            "Legacy offset-based pagination. Phase 269 H-24 lowered the "
            f"max limit to {_STAC_MAX_LIMIT} and recommends keyset cursors via "
            "the rel=next link for deep paging."
        ),
    ),
) -> JSONResponse:
    """List STAC Items within a collection."""
    # Clamp before the page links are built so rel=next/prev advertise the
    # limit actually served.
    limit = min(limit, _STAC_MAX_LIMIT)
    stac_api_url, public_api_url = await _resolve_urls(db, request)
    # fix(#315 follow-up): raster_tiles assets are served at the public APP origin.
    public_app_url = await get_public_app_url(db, request=request)
    user_roles = await _resolve_roles(db, user)

    collection_scope = await _collection_scope_filter(
        db, collection_id, user, user_roles
    )

    # Base query filtered to this collection
    stmt = _base_published_raster_query(user, user_roles).where(collection_scope)

    # Filter by bbox (antimeridian-aware)
    if bbox:
        try:
            bbox_vals = parse_bbox(bbox)
        except (ValueError, TypeError) as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid bbox: {e}",
            )
        stmt = stmt.where(make_bbox_filter(Record.spatial_extent, bbox_vals))

    # Filter by datetime
    if datetime_param:
        stmt = _apply_datetime_filter(stmt, datetime_param)

    # Count total
    count_stmt = select(func.count()).select_from(
        stmt.with_only_columns(Dataset.id).subquery()
    )
    total = (await db.execute(count_stmt)).scalar() or 0

    # Paginate
    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    datasets = result.unique().scalars().all()

    # Bulk-fetch assets, raster metadata, and spatial-extent GeoJSON concurrently.
    # Bulk ST_AsGeoJSON in PostGIS is faster than per-dataset Python-side
    # to_shape() WKB deserialization in dataset_to_ogc_record (PERF-5).
    ds_ids = [d.id for d in datasets]

    async def _assets():
        async with _db_module.async_session() as s:
            return await _fetch_dataset_asset_rows(s, ds_ids)

    async def _raster():
        async with _db_module.async_session() as s:
            return await _fetch_raster_meta(s, ds_ids)

    async def _extents() -> dict[str, str | None]:
        if not ds_ids:
            return {}
        async with _db_module.async_session() as s:
            stmt = (
                select(
                    Dataset.id,
                    func.ST_AsGeoJSON(Record.spatial_extent, 6).label("geojson"),
                )
                .join(Record, Dataset.record_id == Record.id)
                .where(Dataset.id.in_(ds_ids))
            )
            return {str(row.id): row.geojson for row in (await s.execute(stmt)).all()}

    asset_rows_map, raster_meta_map, extent_geojson_map = await asyncio.gather(
        _assets(), _raster(), _extents()
    )

    # fix(#1108 review): lineage visibility for the whole page in one query
    # instead of one visible_lineage_summary round trip per item.
    lineage_map = await visible_lineage_summaries(
        db, [d.record for d in datasets], user, user_roles or set()
    )

    features = []
    coll_id_str = str(collection_id)
    for dataset in datasets:
        item = await _dataset_to_stac_item(
            db,
            dataset,
            public_api_url,
            stac_api_url,
            stac_asset_rows=asset_rows_map.get(str(dataset.id)),
            raster_meta=raster_meta_map.get(str(dataset.id)),
            collection_id=coll_id_str,
            spatial_extent_geojson=extent_geojson_map.get(str(dataset.id)),
            public_app_url=public_app_url,
            preferred_languages=parse_accept_languages(request),
            user=user,
            user_roles=user_roles,
            lineage_summary=lineage_map[dataset.record.id],
        )
        features.append(item)

    base_href = f"{stac_api_url}/collections/{collection_id}/items"
    active_params: dict[str, str] = {}
    if bbox:
        active_params["bbox"] = bbox
    if datetime_param:
        active_params["datetime"] = datetime_param

    links = [
        StacLink(
            rel="self",
            href=_stac_page_url(base_href, offset, limit, active_params),
            type="application/geo+json",
        ),
        StacLink(rel="root", href=f"{stac_api_url}/", type="application/json"),
        StacLink(
            rel="collection",
            href=f"{stac_api_url}/collections/{collection_id}",
            type="application/json",
        ),
    ]
    if offset + limit < total:
        links.append(
            StacLink(
                rel="next",
                href=_stac_page_url(base_href, offset + limit, limit, active_params),
                type="application/geo+json",
            )
        )
    if offset > 0:
        links.append(
            StacLink(
                rel="prev",
                href=_stac_page_url(
                    base_href, max(0, offset - limit), limit, active_params
                ),
                type="application/geo+json",
            )
        )

    result = StacItemCollection(
        features=features,
        links=links,
        numberMatched=total,
        numberReturned=len(features),
        context={"limit": limit, "returned": len(features), "matched": total},
    )
    return _item_collection_response(result)


async def _build_item_response(
    db: AsyncSession,
    dataset: Dataset,
    public_api_url: str,
    stac_api_url: str,
    *,
    collection_id: str | None = None,
    public_app_url: str | None = None,
    preferred_languages: Sequence[str] | None = None,
    user: Identity | None = None,
    user_roles: set[str] | None = None,
) -> JSONResponse:
    """Fetch assets/raster metadata, convert to STAC Item, return as geo+json."""

    async def _assets():
        async with _db_module.async_session() as s:
            return await _fetch_dataset_asset_rows(s, [dataset.id])

    async def _raster():
        async with _db_module.async_session() as s:
            return await _fetch_raster_meta(s, [dataset.id])

    asset_rows, raster_meta = await asyncio.gather(_assets(), _raster())

    # Intentional validation boundary: serializer output must satisfy the
    # published STAC response contract before it reaches the wire.
    item = StacItemResponse.model_validate(
        await _dataset_to_stac_item(
            db,
            dataset,
            public_api_url,
            stac_api_url,
            stac_asset_rows=asset_rows.get(str(dataset.id)),
            raster_meta=raster_meta.get(str(dataset.id)),
            collection_id=collection_id,
            public_app_url=public_app_url,
            preferred_languages=preferred_languages,
            user=user,
            user_roles=user_roles,
        )
    )
    return JSONResponse(
        content=item.model_dump(mode="json", exclude_unset=True),
        media_type="application/geo+json",
        headers=_stac_content_language_headers([item]),
    )


@stac_router.get(
    "/collections/{collection_id}/items/{item_id}",
    response_model=StacItemResponse,
    response_class=GeoJSONResponse,
    responses={404: NOT_FOUND_RESPONSE},
)
async def get_collection_item(
    collection_id: str,
    item_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: Identity | None = Depends(get_optional_user),
) -> JSONResponse:
    """Get a single STAC Item within a collection."""
    stac_api_url, public_api_url = await _resolve_urls(db, request)
    # fix(#315 follow-up): raster_tiles assets are served at the public APP origin.
    public_app_url = await get_public_app_url(db, request=request)
    user_roles = await _resolve_roles(db, user)

    collection_scope = await _collection_scope_filter(
        db, collection_id, user, user_roles
    )

    # Fetch published raster/VRT dataset within this collection
    stmt = _base_published_raster_query(user, user_roles).where(
        Dataset.id == item_id,
        collection_scope,
    )
    result = await db.execute(stmt)
    dataset = result.unique().scalar_one_or_none()
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Item not found in collection"
        )

    return await _build_item_response(
        db,
        dataset,
        public_api_url,
        stac_api_url,
        collection_id=collection_id,
        public_app_url=public_app_url,
        preferred_languages=parse_accept_languages(request),
        user=user,
        user_roles=user_roles,
    )


@stac_router.get(
    "/items/{item_id}",
    response_model=StacItemResponse,
    response_class=GeoJSONResponse,
    responses={404: NOT_FOUND_RESPONSE},
)
async def get_item(
    item_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: Identity | None = Depends(get_optional_user),
) -> JSONResponse:
    """Get a single STAC Item by dataset ID."""
    stac_api_url, public_api_url = await _resolve_urls(db, request)
    # fix(#315 follow-up): raster_tiles assets are served at the public APP origin.
    public_app_url = await get_public_app_url(db, request=request)
    user_roles = await _resolve_roles(db, user)

    stmt = _base_published_raster_query(user, user_roles).where(Dataset.id == item_id)
    result = await db.execute(stmt)
    dataset = result.unique().scalar_one_or_none()
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Item not found"
        )

    return await _build_item_response(
        db,
        dataset,
        public_api_url,
        stac_api_url,
        public_app_url=public_app_url,
        preferred_languages=parse_accept_languages(request),
        user=user,
        user_roles=user_roles,
    )


def _build_search_filters(
    *,
    bbox: str | list[float] | None = None,
    intersects: str | dict | None = None,
    datetime_str: str | None = None,
    ids: str | list[str] | None = None,
    collections: str | list[str] | None = None,
) -> tuple[list, bool]:
    """Build SQLAlchemy filter clauses for STAC search.

    Returns:
        A tuple of (filter_clauses, ids_empty). ids_empty is True when an ids
        parameter was provided but all values were invalid UUIDs, signaling
        that the caller should return an empty result immediately.
    """
    filters = []

    # Filter by ids — accept comma-separated string or list
    if ids:
        id_strings = ids.split(",") if isinstance(ids, str) else ids
        parsed_ids = []
        for id_str in id_strings:
            try:
                parsed_ids.append(uuid.UUID(id_str.strip()))
            except ValueError:
                continue
        if parsed_ids:
            filters.append(Dataset.id.in_(parsed_ids))
        else:
            return [], True

    # Filter by collections — accept comma-separated string or list
    if collections:
        coll_strings = (
            collections.split(",") if isinstance(collections, str) else collections
        )
        parsed_coll_ids = []
        include_unassigned = False
        for cid_str in coll_strings:
            cid_str = cid_str.strip()
            if cid_str == STAC_UNASSIGNED_COLLECTION_ID:
                include_unassigned = True
                continue
            try:
                parsed_coll_ids.append(uuid.UUID(cid_str))
            except ValueError:
                continue
        collection_filters = []
        if parsed_coll_ids:
            collection_filters.append(
                Dataset.id.in_(
                    select(CollectionDataset.dataset_id).where(
                        CollectionDataset.collection_id.in_(parsed_coll_ids)
                    )
                )
            )
        if include_unassigned:
            collection_filters.append(_unassigned_dataset_filter())
        if collection_filters:
            filters.append(or_(*collection_filters))
        else:
            # An unknown collection must produce no results, never silently
            # broaden a scoped search to the entire catalog.
            filters.append(Dataset.id.in_([]))

    # bbox and intersects are mutually exclusive per the STAC Item Search spec.
    if intersects and bbox:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only one of bbox and intersects may be specified",
        )

    # Filter by intersects (GeoJSON geometry) — accept string or dict
    if intersects:
        if isinstance(intersects, dict):
            intersects_str = json.dumps(intersects)
        else:
            intersects_str = intersects
            try:
                json.loads(intersects_str)  # validate JSON before sending to DB
            except (ValueError, TypeError) as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid intersects geometry: {e}",
                )
        _geom = func.ST_SetSRID(func.ST_GeomFromGeoJSON(intersects_str), 4326)
        filters.append(Record.spatial_extent.op("&&")(func.ST_Envelope(_geom)))
        filters.append(func.ST_Intersects(Record.spatial_extent, _geom))
    elif bbox:
        # Filter by bbox (only if intersects not provided). parse_bbox takes the
        # GET string and the POST list, so both spellings validate identically.
        try:
            bbox_vals = parse_bbox(bbox)
        except (ValueError, TypeError) as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid bbox: {e}",
            )
        filters.append(make_bbox_filter(Record.spatial_extent, bbox_vals))

    return filters, False


def _build_search_links(
    stac_api_url: str,
    *,
    matched: int,
    returned: int,
    offset: int,
    limit: int,
    bbox: str | list[float] | None = None,
    datetime_str: str | None = None,
    collections: str | list[str] | None = None,
    ids: str | list[str] | None = None,
    intersects: str | dict | None = None,
) -> list[StacLink]:
    """Build pagination and navigation links for STAC search results."""
    search_href = f"{stac_api_url}/search"
    active_params: dict[str, str] = {}
    if bbox:
        active_params["bbox"] = (
            bbox if isinstance(bbox, str) else ",".join(str(v) for v in bbox)
        )
    if datetime_str:
        active_params["datetime"] = datetime_str
    if collections:
        active_params["collections"] = (
            collections if isinstance(collections, str) else ",".join(collections)
        )
    if ids:
        active_params["ids"] = ids if isinstance(ids, str) else ",".join(ids)
    if intersects:
        active_params["intersects"] = (
            intersects if isinstance(intersects, str) else json.dumps(intersects)
        )

    links = [
        StacLink(
            rel="self",
            href=_stac_page_url(search_href, offset, limit, active_params),
            type="application/geo+json",
        ),
        StacLink(rel="root", href=f"{stac_api_url}/", type="application/json"),
    ]
    if offset + limit < matched:
        links.append(
            StacLink(
                rel="next",
                href=_stac_page_url(search_href, offset + limit, limit, active_params),
                type="application/geo+json",
            )
        )
    if offset > 0:
        links.append(
            StacLink(
                rel="prev",
                href=_stac_page_url(
                    search_href, max(0, offset - limit), limit, active_params
                ),
                type="application/geo+json",
            )
        )

    return links


async def _execute_search(
    db: AsyncSession,
    stac_api_url: str,
    public_api_url: str,
    user: Identity | None,
    user_roles: set[str],
    *,
    bbox: str | list[float] | None = None,
    datetime_str: str | None = None,
    collections: str | list[str] | None = None,
    ids: str | list[str] | None = None,
    intersects: str | dict | None = None,
    limit: int = 10,
    offset: int = 0,
    public_app_url: str | None = None,
    preferred_languages: Sequence[str] | None = None,
) -> JSONResponse:
    """Shared STAC Item Search logic for GET and POST endpoints.

    Parameters accept both string (from GET query params) and native types
    (from POST JSON body) to avoid unnecessary serialization round-trips.
    """
    # Build filters from search parameters
    filters, ids_empty = _build_search_filters(
        bbox=bbox,
        intersects=intersects,
        datetime_str=datetime_str,
        ids=ids,
        collections=collections,
    )

    # Early return when ids param was given but all values were invalid
    if ids_empty:
        result = StacItemCollection(
            features=[],
            links=[
                StacLink(
                    rel="self",
                    href=f"{stac_api_url}/search",
                    type="application/geo+json",
                ),
                StacLink(rel="root", href=f"{stac_api_url}/", type="application/json"),
            ],
            numberMatched=0,
            numberReturned=0,
            context={"limit": limit, "returned": 0, "matched": 0},
        )
        return _item_collection_response(result)

    stmt = _base_published_raster_query(user, user_roles)
    for f in filters:
        stmt = stmt.where(f)

    # Filter by datetime
    if datetime_str:
        stmt = _apply_datetime_filter(stmt, datetime_str)

    # Count total matches
    count_stmt = select(func.count()).select_from(
        stmt.with_only_columns(Dataset.id).subquery()
    )
    total = (await db.execute(count_stmt)).scalar() or 0

    # Apply pagination
    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    datasets = result.unique().scalars().all()

    # Fetch asset rows, raster metadata, and collection membership concurrently
    ds_ids = [d.id for d in datasets]

    async def _assets():
        async with _db_module.async_session() as s:
            return await _fetch_dataset_asset_rows(s, ds_ids)

    async def _raster():
        async with _db_module.async_session() as s:
            return await _fetch_raster_meta(s, ds_ids)

    async def _coll_membership() -> dict[str, str]:
        if not ds_ids:
            return {}
        cd_stmt = select(
            CollectionDataset.dataset_id, CollectionDataset.collection_id
        ).where(CollectionDataset.dataset_id.in_(ds_ids))

        # For collection-scoped Item Search, choose a canonical membership from
        # the requested collections so every returned Item names a collection
        # that satisfied the filter. Unscoped search uses the same deterministic
        # ordering as single-item retrieval.
        if collections:
            requested_values = (
                collections.split(",") if isinstance(collections, str) else collections
            )
            requested_ids: list[uuid.UUID] = []
            for value in requested_values:
                try:
                    requested_ids.append(uuid.UUID(value.strip()))
                except ValueError:
                    continue
            if requested_ids:
                cd_stmt = cd_stmt.where(
                    CollectionDataset.collection_id.in_(requested_ids)
                )

        cd_stmt = cd_stmt.order_by(
            CollectionDataset.dataset_id.asc(),
            CollectionDataset.sort_order.asc(),
            CollectionDataset.added_at.asc(),
            CollectionDataset.collection_id.asc(),
        )
        async with _db_module.async_session() as s:
            cd_result = await s.execute(cd_stmt)
            memberships: dict[str, str] = {}
            for row in cd_result.all():
                memberships.setdefault(str(row.dataset_id), str(row.collection_id))
            return memberships

    asset_rows_map, raster_meta_map, collection_id_map = await asyncio.gather(
        _assets(), _raster(), _coll_membership()
    )

    # fix(#1108 review): lineage visibility for the whole page in one query
    # instead of one visible_lineage_summary round trip per item.
    lineage_map = await visible_lineage_summaries(
        db, [d.record for d in datasets], user, user_roles or set()
    )

    # Convert to STAC Items
    features = []
    for dataset in datasets:
        item = await _dataset_to_stac_item(
            db,
            dataset,
            public_api_url,
            stac_api_url,
            stac_asset_rows=asset_rows_map.get(str(dataset.id)),
            raster_meta=raster_meta_map.get(str(dataset.id)),
            collection_id=(
                collection_id_map.get(str(dataset.id)) or STAC_UNASSIGNED_COLLECTION_ID
            ),
            public_app_url=public_app_url,
            preferred_languages=preferred_languages,
            user=user,
            user_roles=user_roles,
            lineage_summary=lineage_map[dataset.record.id],
        )
        features.append(item)

    # Build links
    links = _build_search_links(
        stac_api_url,
        matched=total,
        returned=len(features),
        offset=offset,
        limit=limit,
        bbox=bbox,
        datetime_str=datetime_str,
        collections=collections,
        ids=ids,
        intersects=intersects,
    )

    result = StacItemCollection(
        features=features,
        links=links,
        numberMatched=total,
        numberReturned=len(features),
        context={"limit": limit, "returned": len(features), "matched": total},
    )
    return _item_collection_response(result)


@stac_router.get(
    "/search",
    response_model=StacItemCollectionResponse,
    response_class=GeoJSONResponse,
    responses=ERROR_RESPONSES_PUBLIC,
)
async def search_get(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: Identity | None = Depends(get_optional_user),
    bbox: str | None = Query(None, description="Bounding box: west,south,east,north"),
    datetime_param: str | None = Query(
        None, alias="datetime", description="OGC datetime interval"
    ),
    collections: str | None = Query(None, description="Comma-separated collection IDs"),
    ids: str | None = Query(None, description="Comma-separated item IDs"),
    intersects: str | None = Query(
        None,
        max_length=10000,
        description=(
            "GeoJSON geometry for spatial intersection. SEC-FU-05 (sec-audit-20260519.md): "
            "max_length=10000 caps a multi-megabyte GeoJSON DoS-amplifier — fits ~150-vertex "
            "polygons at 2-decimal-place lat/lon coordinates."
        ),
    ),
    limit: int = Query(
        10,
        ge=1,
        description=(
            f"Maximum number of items returned. Values above {_STAC_MAX_LIMIT} "
            f"are clamped to {_STAC_MAX_LIMIT}, per the STAC Item Search spec's "
            "clamp-don't-reject recommendation."
        ),
    ),
    offset: int = Query(
        0,
        ge=0,
        description=(
            "Legacy offset-based pagination. Phase 269 H-24 lowered the "
            f"max limit to {_STAC_MAX_LIMIT} from 1000 to bound deep-paging cost."
        ),
    ),
) -> JSONResponse:
    """STAC Item Search (GET)."""
    stac_api_url, public_api_url = await _resolve_urls(db, request)
    # fix(#315 follow-up): raster_tiles assets are served at the public APP origin.
    public_app_url = await get_public_app_url(db, request=request)
    user_roles = await _resolve_roles(db, user)
    return await _execute_search(
        db,
        stac_api_url,
        public_api_url,
        user,
        user_roles,
        bbox=bbox,
        datetime_str=datetime_param,
        collections=collections,
        ids=ids,
        intersects=intersects,
        # STAC Item Search: limits above the server maximum are clamped, not
        # rejected (stac-api-validator enforces this).
        limit=min(limit, _STAC_MAX_LIMIT),
        offset=offset,
        public_app_url=public_app_url,
        preferred_languages=parse_accept_languages(request),
    )


class StacSearchBody(BaseModel):
    """JSON body for POST /search."""

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "bbox": [-77.2, 38.7, -76.8, 39.1],
                    "collections": ["geolens-unassigned"],
                    "limit": 25,
                }
            ]
        }
    }

    bbox: list[float] | None = None
    datetime: str | None = None
    collections: list[str] | None = None
    ids: list[str] | None = None
    intersects: dict | None = None
    limit: int = Field(
        default=10,
        ge=1,
        # WR-01 (Phase 1071 review) aligned GET/POST ceilings at le=200; the
        # STAC hardening pass replaces the hard bound with clamping on all three
        # item-returning handlers — the Item Search spec (and stac-api-validator)
        # requires over-limit values to be clamped to the server maximum, not
        # rejected.
        description=(
            f"Maximum number of items returned. Values above {_STAC_MAX_LIMIT} "
            f"are clamped to {_STAC_MAX_LIMIT}."
        ),
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Number of items to skip for pagination.",
    )

    @field_validator("intersects")
    @classmethod
    def _cap_intersects_size(cls, v: dict | None) -> dict | None:
        # SEC-023 (sibling of SEC-FU-05): the GET `intersects` query param is
        # capped at max_length=10000, but the POST body `intersects` dict
        # bypassed any bound and reached the same anonymous ST_GeomFromGeoJSON
        # predicate — a multi-megabyte GeoJSON could pin CPU/memory + a DB
        # connection. Cap the serialized size to match the GET handler.
        max_serialized = 10000
        if v is not None and len(json.dumps(v)) > max_serialized:
            raise ValueError(
                f"intersects GeoJSON too large (max {max_serialized} "
                "serialized characters)"
            )
        return v


@stac_router.post(
    "/search",
    response_model=StacItemCollectionResponse,
    response_class=GeoJSONResponse,
    responses=ERROR_RESPONSES_PUBLIC,
)
async def search_post(
    body: StacSearchBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: Identity | None = Depends(get_optional_user),
) -> JSONResponse:
    """STAC Item Search (POST with JSON body)."""
    stac_api_url, public_api_url = await _resolve_urls(db, request)
    # fix(#315 follow-up): raster_tiles assets are served at the public APP origin.
    public_app_url = await get_public_app_url(db, request=request)
    user_roles = await _resolve_roles(db, user)

    return await _execute_search(
        db,
        stac_api_url,
        public_api_url,
        user,
        user_roles,
        bbox=body.bbox,
        datetime_str=body.datetime,
        collections=body.collections,
        ids=body.ids,
        intersects=body.intersects,
        # Over-limit values clamp to the operational ceiling (H-24), required by
        # the Item Search spec instead of a le=200 rejection.
        limit=max(1, min(body.limit, _STAC_MAX_LIMIT)),
        offset=max(0, body.offset),
        public_app_url=public_app_url,
        preferred_languages=parse_accept_languages(request),
    )


# ---------------------------------------------------------------------------
# Datetime filter helper
# ---------------------------------------------------------------------------


def _apply_datetime_filter(stmt, datetime_str: str):
    """Apply OGC datetime interval filter to a query.

    Delegates parsing to the canonical ``parse_ogc_datetime`` helper in
    search/service.py so STAC and OGC Records share one implementation.
    Malformed inputs raise HTTP 400 (was silently ignored before — that
    masked client mistakes).
    """
    from app.modules.catalog.search.service import parse_ogc_datetime

    datetime_str = _validate_stac_datetime(datetime_str.strip())
    start, end = parse_ogc_datetime(datetime_str)

    # fix(#430 BA-13): admit null-temporal records — dataset_to_ogc_record advertises
    # datetime=created_at for them, so filter them by that SAME fallback instant.
    # fix(#430 codex): unconditional NULL inclusion returned every null-temporal
    # record for any datetime filter (e.g. datetime=1900-01-01 matched a record
    # created in 2026); compare created_at against the requested bounds instead.
    # parse_ogc_datetime truncates to whole DAYS, so created_at comparisons are
    # day-granular: a bound day includes any created_at within that day
    # (fix #430 codex round 2 — `created_at == start` only matched exact midnight).
    null_temporal = Record.temporal_start.is_(None) & Record.temporal_end.is_(None)
    if "/" in datetime_str:
        if start is not None:
            stmt = stmt.where(
                (Record.temporal_end >= start)
                | (Record.temporal_start >= start)
                | (null_temporal & (Record.created_at >= start))
            )
        if end is not None:
            stmt = stmt.where(
                (Record.temporal_start <= end)
                # temporal_start NULL with temporal_end set = open start (-inf);
                # always within any end bound. Null-null uses created_at,
                # day-inclusive on the end bound.
                | (Record.temporal_start.is_(None) & Record.temporal_end.isnot(None))
                | (null_temporal & (Record.created_at < end + timedelta(days=1)))
            )
    else:
        # Single instant (day-granular) — match records whose temporal range
        # contains it. Null-temporal records advertise datetime=created_at, so
        # they match when created_at falls anywhere on the requested day.
        if start is not None:
            range_contains = (
                (Record.temporal_start <= start) | (Record.temporal_start.is_(None))
            ) & ((Record.temporal_end >= start) | (Record.temporal_end.is_(None)))
            stmt = stmt.where(
                (range_contains & ~null_temporal)
                | (
                    null_temporal
                    & (Record.created_at >= start)
                    & (Record.created_at < start + timedelta(days=1))
                )
            )
    return stmt
