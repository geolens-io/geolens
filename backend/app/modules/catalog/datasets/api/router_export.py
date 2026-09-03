"""Dataset export endpoints: DCAT JSON-LD catalog and COG download."""

import uuid

import jwt
import structlog
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.modules.audit.service import AuditEvent, audit_emit
from app.core.identity import Identity
from app.modules.auth.dependencies import (
    get_optional_user,
)
from app.modules.auth.models import User
from app.core.config import settings
from app.modules.catalog.authorization import (
    apply_visibility_filter,
    check_dataset_access,
    check_dataset_access_or_anonymous,
    get_user_roles,
    visible_lineage_summaries,
)
from app.standards.dcat.service import (
    catalog_to_dcat,
    dcat_fallback_fields,
    record_to_dcat,
)
from app.standards.dcat.validation import validate_dcat3
from app.standards.dcat_us.service import (
    catalog_to_dcat_us3,
    dcat_us3_fallback_fields,
    record_to_dcat_us3,
)
from app.standards.dcat_us.validation import validate_dcat_us3
from app.standards.geodcat_ap.service import (
    catalog_to_geodcat_ap,
    geodcat_ap_fallback_fields,
    record_to_geodcat_ap,
)
from app.standards.geodcat_ap.validation import validate_geodcat_ap
from app.modules.catalog.datasets.domain.models import (
    Dataset as DatasetModel,
    DatasetGrant,
    Record,
)
from app.modules.catalog.datasets.domain.service import get_dataset
from app.core.dependencies import get_db
from app.core.db.tenant_session import current_tenant_var
from app.core.tenancy import is_multi_tenant
from app.core.public_urls import get_public_urls
from app.platform.extensions import get_catalog_port, get_permission_extension
from app.platform.http.ranges import (
    RANGE_UNSATISFIABLE,
    if_match_passes,
    if_none_match_matches,
    not_modified_response,
    parse_byte_range,
    range_bound_to_this_version,
)
from app.platform.storage import get_storage
from app.platform.storage.titiler_url import resolve_storage_key
from app.standards.ogc.errors import (
    ERROR_RESPONSES_PUBLIC,
    FORBIDDEN_RESPONSE,
    PRECONDITION_FAILED_RESPONSE,
    SERVICE_UNAVAILABLE_RESPONSE,
)
from app.standards.ogc.utils import normalize_language_tag, parse_accept_languages

logger = structlog.get_logger()

router = APIRouter(
    prefix="/datasets", tags=["Datasets - Export"], responses=ERROR_RESPONSES_PUBLIC
)


# ---------------------------------------------------------------------------
# DCAT 3 JSON-LD export endpoints
# ---------------------------------------------------------------------------


def _dcat_relationship_options():
    return joinedload(DatasetModel.record).options(
        selectinload(Record.keywords),
        selectinload(Record.contacts),
        selectinload(Record.distributions),
        selectinload(Record.translations),
    )


def _language_headers(language: str | None) -> dict[str, str]:
    headers = {"Vary": "Accept-Language"}
    if language:
        headers["Content-Language"] = language
    return headers


def _dcat_content_language(document: object) -> str | None:
    """Return a header only when every tagged string uses one language."""
    languages: set[str] = set()

    def collect(value: object) -> None:
        if isinstance(value, dict):
            language = value.get("@language")
            if isinstance(language, str) and language:
                languages.add(language)
            for nested in value.values():
                collect(nested)
        elif isinstance(value, list):
            for nested in value:
                collect(nested)

    collect(document)
    return next(iter(languages)) if len(languages) == 1 else None


# fix(#430 BA-28): these anonymous feeds materialize every visible dataset (+ keywords/
# contacts/distributions) into one in-memory JSON-LD doc with no cache — a cheap
# repeatable memory/CPU amplifier on a large catalog. A single page is bounded at
# _DCAT_FEED_MAX_DATASETS; the catalog #catalog-enhancement fix adds limit/offset
# so a large-catalog operator (e.g. a federal data.json harvester) can crawl the
# whole feed instead of silently losing everything past the first 10k.
#
# Offset paging keeps the memory guard while unblocking >10k catalogs;
# a spec-correct single-document streaming data.json is the real fix if a
# harvester that can't page ever needs >10k in one request.
_DCAT_FEED_MAX_DATASETS = 10_000


def _catalog_completeness(
    datasets: list[DatasetModel],
    catalog: dict,
    dataset_key: str,
    fallback_fields: list[tuple[str, ...]],
) -> dict[str, int]:
    """Expose page-level serialization coverage without altering JSON-LD."""
    entries = catalog.get(dataset_key)
    serialized_count = len(entries) if isinstance(entries, list) else 0
    source_count = len(datasets)
    return {
        "source_dataset_count": source_count,
        "serialized_dataset_count": serialized_count,
        "excluded_dataset_count": max(source_count - serialized_count, 0),
        "metadata_fallback_dataset_count": sum(
            bool(fields) for fields in fallback_fields
        ),
        "metadata_fallback_field_count": sum(len(fields) for fields in fallback_fields),
    }


def _catalog_completeness_headers(stats: dict[str, int]) -> dict[str, str]:
    return {
        "X-GeoLens-Source-Dataset-Count": str(stats["source_dataset_count"]),
        "X-GeoLens-Serialized-Dataset-Count": str(stats["serialized_dataset_count"]),
        "X-GeoLens-Excluded-Dataset-Count": str(stats["excluded_dataset_count"]),
        "X-GeoLens-Metadata-Fallback-Dataset-Count": str(
            stats["metadata_fallback_dataset_count"]
        ),
    }


def _record_fallback_headers(fields: tuple[str, ...]) -> dict[str, str]:
    if not fields:
        return {}
    return {"X-GeoLens-Metadata-Fallback-Fields": ",".join(fields)}


def _record_language_headers(payload: dict) -> dict[str, str]:
    """Describe the language actually serialized by a DCAT profile."""
    language_value = payload.get("language")
    if not isinstance(language_value, str):
        title = payload.get("dcterms:title")
        language_value = title.get("@language") if isinstance(title, dict) else None
    language = normalize_language_tag(language_value, fallback="en") or "en"
    return {"Content-Language": language}


def _ensure_conformant_dcat_us3(payload: dict, schema_name: str) -> None:
    report = validate_dcat_us3(payload, schema_name)
    if report["valid"]:
        return
    logger.warning(
        "dcat_us_export_blocked",
        schema=schema_name,
        error_count=report["error_count"],
    )
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=(
            "DCAT-US export has unresolved mandatory metadata. Add a usable "
            "dataset contact or configure DCAT_CONTACT_EMAIL with a monitored "
            "organization role mailbox; inspect the matching validation endpoint."
        ),
    )


async def _get_visible_dcat_datasets(
    db: AsyncSession,
    user: Identity | None,
    *,
    limit: int = _DCAT_FEED_MAX_DATASETS,
    offset: int = 0,
) -> list[DatasetModel]:
    stmt = (
        select(DatasetModel)
        .join(Record, DatasetModel.record_id == Record.id)
        .options(_dcat_relationship_options())
        .order_by(Record.created_at.desc(), Record.id.desc())
        .offset(offset)
        .limit(limit)
    )

    if user is not None:
        user_roles = await get_user_roles(db, user)
    else:
        user_roles = set()

    stmt = apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)

    result = await db.execute(stmt)
    datasets = list(result.unique().scalars().all())
    if len(datasets) >= limit:
        logger.warning(
            "dcat_feed_truncated",
            limit=limit,
            offset=offset,
            authenticated=user is not None,
        )
    return datasets


# Shared query params for the paginated catalog feed handlers.
_FEED_LIMIT_Q = Query(
    _DCAT_FEED_MAX_DATASETS,
    ge=1,
    le=_DCAT_FEED_MAX_DATASETS,
    description="Max datasets in this page (default = max).",
)
_FEED_OFFSET_Q = Query(
    0, ge=0, description="Datasets to skip — page a catalog larger than one page."
)


async def _visible_lineage(
    db: AsyncSession,
    datasets: list[DatasetModel],
    user: Identity | None,
) -> dict[uuid.UUID, str | None]:
    """fix(#1103): access-checked ``dcterms:provenance`` for a page, in one query.

    These feeds serve anonymous requesters, and an analysis output's lineage
    sentence names the titles of the datasets it was derived from — including a
    private mask or join layer the requester is not allowed to know exists.
    The serializers no longer read the column, so a handler that forgets this
    emits no provenance rather than someone else's title.
    """
    user_roles = await get_user_roles(db, user) if user is not None else set()
    return await visible_lineage_summaries(
        db, [ds.record for ds in datasets], user, user_roles
    )


async def _visible_record_lineage(
    db: AsyncSession, dataset: DatasetModel, user: Identity | None
) -> str | None:
    """One dataset's access-checked provenance sentence. See _visible_lineage."""
    return (await _visible_lineage(db, [dataset], user))[dataset.record_id]


async def _get_dcat_dataset_for_export(
    db: AsyncSession,
    dataset_id: uuid.UUID,
    user: Identity | None,
) -> DatasetModel:
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )
    await check_dataset_access_or_anonymous(db, dataset, dataset_id, user)

    result = await db.execute(
        select(DatasetModel)
        .options(_dcat_relationship_options())
        .where(DatasetModel.id == dataset_id)
    )
    return result.unique().scalar_one()


# ROUTE-01 (Phase 1092): dual-shape decorator — both trailing-slash and
# no-trailing-slash variants register against the same handler. Slash form
# stays canonical (already in OpenAPI); no-slash is a hidden alias closing
# the 404 regression introduced by redirect_slashes=False (api/main.py).
@router.get("/dcat", response_class=JSONResponse, include_in_schema=False)
@router.get("/dcat/", response_class=JSONResponse)
async def get_dcat_catalog(
    request: Request,
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
    limit: int = _FEED_LIMIT_Q,
    offset: int = _FEED_OFFSET_Q,
) -> JSONResponse:
    """DCAT 3 JSON-LD catalog feed. Respects dataset visibility."""
    datasets = await _get_visible_dcat_datasets(db, user, limit=limit, offset=offset)

    app_base_url, base_url = await get_public_urls(db, request=request)
    preferred_languages = parse_accept_languages(request)
    catalog = catalog_to_dcat(
        datasets,
        base_url,
        app_base_url=app_base_url,
        preferred_languages=preferred_languages,
        lineage_by_record_id=await _visible_lineage(db, datasets, user),
    )
    completeness = _catalog_completeness(
        datasets,
        catalog,
        "dcat:dataset",
        [dcat_fallback_fields(dataset, preferred_languages) for dataset in datasets],
    )
    return JSONResponse(
        content=catalog,
        media_type="application/ld+json",
        headers={
            **_language_headers(_dcat_content_language(catalog)),
            **_catalog_completeness_headers(completeness),
        },
    )


@router.get(
    "/dcat/validation",
    response_class=JSONResponse,
    include_in_schema=False,
)
@router.get("/dcat/validation/", response_class=JSONResponse)
async def validate_dcat3_catalog(
    request: Request,
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Validate the visible W3C DCAT 3 catalog feed."""
    datasets = await _get_visible_dcat_datasets(db, user)

    app_base_url, base_url = await get_public_urls(db, request=request)
    catalog = catalog_to_dcat(
        datasets,
        base_url,
        app_base_url=app_base_url,
        lineage_by_record_id=await _visible_lineage(db, datasets, user),
    )
    report = validate_dcat3(catalog, "Catalog")
    report.update(
        _catalog_completeness(
            datasets,
            catalog,
            "dcat:dataset",
            [dcat_fallback_fields(dataset) for dataset in datasets],
        )
    )

    return JSONResponse(content=report)


@router.get("/dcat-us/3.0", response_class=JSONResponse, include_in_schema=False)
@router.get(
    "/dcat-us/3.0/",
    response_class=JSONResponse,
    responses={503: SERVICE_UNAVAILABLE_RESPONSE},
)
async def get_dcat_us3_catalog(
    request: Request,
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
    limit: int = _FEED_LIMIT_Q,
    offset: int = _FEED_OFFSET_Q,
) -> JSONResponse:
    """DCAT-US Schema v3.0 catalog feed. Respects dataset visibility."""
    datasets = await _get_visible_dcat_datasets(db, user, limit=limit, offset=offset)

    app_base_url, base_url = await get_public_urls(db, request=request)
    catalog = catalog_to_dcat_us3(
        datasets,
        base_url,
        app_base_url=app_base_url,
        catalog_contact_email=settings.dcat_contact_email,
        lineage_by_record_id=await _visible_lineage(db, datasets, user),
    )
    fallback_fields = [
        dcat_us3_fallback_fields(dataset, settings.dcat_contact_email)
        for dataset in datasets
    ]
    completeness = _catalog_completeness(datasets, catalog, "dataset", fallback_fields)
    _ensure_conformant_dcat_us3(catalog, "Catalog")

    return JSONResponse(
        content=catalog,
        media_type="application/ld+json",
        headers={
            "Content-Language": str(catalog.get("language") or "en"),
            **_catalog_completeness_headers(completeness),
        },
    )


@router.get(
    "/dcat-us/3.0/validation",
    response_class=JSONResponse,
    include_in_schema=False,
)
@router.get("/dcat-us/3.0/validation/", response_class=JSONResponse)
async def validate_dcat_us3_catalog(
    request: Request,
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Validate the visible DCAT-US Schema v3.0 catalog feed."""
    datasets = await _get_visible_dcat_datasets(db, user)

    app_base_url, base_url = await get_public_urls(db, request=request)
    catalog = catalog_to_dcat_us3(
        datasets,
        base_url,
        app_base_url=app_base_url,
        catalog_contact_email=settings.dcat_contact_email,
        lineage_by_record_id=await _visible_lineage(db, datasets, user),
    )
    report = validate_dcat_us3(catalog, "Catalog")
    fallback_fields = [
        dcat_us3_fallback_fields(dataset, settings.dcat_contact_email)
        for dataset in datasets
    ]
    report.update(_catalog_completeness(datasets, catalog, "dataset", fallback_fields))

    return JSONResponse(content=report)


@router.get("/geodcat-ap", response_class=JSONResponse, include_in_schema=False)
@router.get("/geodcat-ap/", response_class=JSONResponse)
async def get_geodcat_ap_catalog(
    request: Request,
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
    limit: int = _FEED_LIMIT_Q,
    offset: int = _FEED_OFFSET_Q,
) -> JSONResponse:
    """GeoDCAT-AP 2.0.0 catalog feed. Respects dataset visibility."""
    datasets = await _get_visible_dcat_datasets(db, user, limit=limit, offset=offset)

    app_base_url, base_url = await get_public_urls(db, request=request)
    catalog = catalog_to_geodcat_ap(
        datasets,
        base_url,
        app_base_url=app_base_url,
        lineage_by_record_id=await _visible_lineage(db, datasets, user),
    )
    completeness = _catalog_completeness(
        datasets,
        catalog,
        "dcat:dataset",
        [geodcat_ap_fallback_fields(dataset) for dataset in datasets],
    )

    return JSONResponse(
        content=catalog,
        media_type="application/ld+json",
        headers=_catalog_completeness_headers(completeness),
    )


@router.get(
    "/geodcat-ap/validation",
    response_class=JSONResponse,
    include_in_schema=False,
)
@router.get("/geodcat-ap/validation/", response_class=JSONResponse)
async def validate_geodcat_ap_catalog(
    request: Request,
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Validate the visible GeoDCAT-AP 2.0.0 catalog feed."""
    datasets = await _get_visible_dcat_datasets(db, user)

    app_base_url, base_url = await get_public_urls(db, request=request)
    catalog = catalog_to_geodcat_ap(
        datasets,
        base_url,
        app_base_url=app_base_url,
        lineage_by_record_id=await _visible_lineage(db, datasets, user),
    )
    report = validate_geodcat_ap(catalog, "Catalog")
    report.update(
        _catalog_completeness(
            datasets,
            catalog,
            "dcat:dataset",
            [geodcat_ap_fallback_fields(dataset) for dataset in datasets],
        )
    )

    return JSONResponse(content=report)


@router.get(
    "/{dataset_id}/dcat/validation",
    response_class=JSONResponse,
    include_in_schema=False,
)
@router.get("/{dataset_id}/dcat/validation/", response_class=JSONResponse)
async def validate_dcat3_record(
    request: Request,
    dataset_id: uuid.UUID,
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Validate a single dataset as W3C DCAT 3."""
    dataset = await _get_dcat_dataset_for_export(db, dataset_id, user)

    app_base_url, base_url = await get_public_urls(db, request=request)
    dcat = record_to_dcat(
        dataset,
        base_url,
        app_base_url=app_base_url,
        lineage_summary=await _visible_record_lineage(db, dataset, user),
    )
    report = validate_dcat3(dcat, "Dataset")
    fallback_fields = dcat_fallback_fields(dataset)
    report.update(
        {
            "uses_metadata_fallback": bool(fallback_fields),
            "metadata_fallback_fields": list(fallback_fields),
        }
    )

    return JSONResponse(content=report)


@router.get("/{dataset_id}/dcat/", response_class=JSONResponse)
async def get_dcat_record(
    request: Request,
    dataset_id: uuid.UUID,
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """DCAT 3 JSON-LD for a single dataset."""
    dataset = await _get_dcat_dataset_for_export(db, dataset_id, user)

    app_base_url, base_url = await get_public_urls(db, request=request)
    preferred_languages = parse_accept_languages(request)
    dcat = record_to_dcat(
        dataset,
        base_url,
        app_base_url=app_base_url,
        preferred_languages=preferred_languages,
        lineage_summary=await _visible_record_lineage(db, dataset, user),
    )
    fallback_fields = dcat_fallback_fields(dataset, preferred_languages)
    return JSONResponse(
        content=dcat,
        media_type="application/ld+json",
        headers={
            **_language_headers(_dcat_content_language(dcat)),
            **_record_fallback_headers(fallback_fields),
        },
    )


@router.get(
    "/{dataset_id}/dcat-us/3.0/validation",
    response_class=JSONResponse,
    include_in_schema=False,
)
@router.get("/{dataset_id}/dcat-us/3.0/validation/", response_class=JSONResponse)
async def validate_dcat_us3_record(
    request: Request,
    dataset_id: uuid.UUID,
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Validate a single dataset as DCAT-US Schema v3.0."""
    dataset = await _get_dcat_dataset_for_export(db, dataset_id, user)

    app_base_url, base_url = await get_public_urls(db, request=request)
    dcat = record_to_dcat_us3(
        dataset,
        base_url,
        app_base_url=app_base_url,
        catalog_contact_email=settings.dcat_contact_email,
        lineage_summary=await _visible_record_lineage(db, dataset, user),
    )
    report = validate_dcat_us3(dcat, "Dataset")
    fallback_fields = dcat_us3_fallback_fields(dataset, settings.dcat_contact_email)
    report.update(
        {
            "uses_metadata_fallback": bool(fallback_fields),
            "metadata_fallback_fields": list(fallback_fields),
        }
    )

    return JSONResponse(content=report)


@router.get(
    "/{dataset_id}/dcat-us/3.0", response_class=JSONResponse, include_in_schema=False
)
@router.get(
    "/{dataset_id}/dcat-us/3.0/",
    response_class=JSONResponse,
    responses={503: SERVICE_UNAVAILABLE_RESPONSE},
)
async def get_dcat_us3_record(
    request: Request,
    dataset_id: uuid.UUID,
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """DCAT-US Schema v3.0 JSON-LD for a single dataset."""
    dataset = await _get_dcat_dataset_for_export(db, dataset_id, user)

    app_base_url, base_url = await get_public_urls(db, request=request)
    dcat = record_to_dcat_us3(
        dataset,
        base_url,
        app_base_url=app_base_url,
        catalog_contact_email=settings.dcat_contact_email,
        lineage_summary=await _visible_record_lineage(db, dataset, user),
    )
    fallback_fields = dcat_us3_fallback_fields(dataset, settings.dcat_contact_email)
    _ensure_conformant_dcat_us3(dcat, "Dataset")

    return JSONResponse(
        content=dcat,
        media_type="application/ld+json",
        headers={
            **_record_language_headers(dcat),
            **_record_fallback_headers(fallback_fields),
        },
    )


@router.get(
    "/{dataset_id}/geodcat-ap/validation",
    response_class=JSONResponse,
    include_in_schema=False,
)
@router.get("/{dataset_id}/geodcat-ap/validation/", response_class=JSONResponse)
async def validate_geodcat_ap_record(
    request: Request,
    dataset_id: uuid.UUID,
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Validate a single dataset as GeoDCAT-AP 2.0.0."""
    dataset = await _get_dcat_dataset_for_export(db, dataset_id, user)

    app_base_url, base_url = await get_public_urls(db, request=request)
    geodcat = record_to_geodcat_ap(
        dataset,
        base_url,
        app_base_url=app_base_url,
        lineage_summary=await _visible_record_lineage(db, dataset, user),
    )
    report = validate_geodcat_ap(geodcat, "Dataset")
    fallback_fields = geodcat_ap_fallback_fields(dataset)
    report.update(
        {
            "uses_metadata_fallback": bool(fallback_fields),
            "metadata_fallback_fields": list(fallback_fields),
        }
    )

    return JSONResponse(content=report)


@router.get(
    "/{dataset_id}/geodcat-ap", response_class=JSONResponse, include_in_schema=False
)
@router.get("/{dataset_id}/geodcat-ap/", response_class=JSONResponse)
async def get_geodcat_ap_record(
    request: Request,
    dataset_id: uuid.UUID,
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """GeoDCAT-AP 2.0.0 JSON-LD for a single dataset."""
    dataset = await _get_dcat_dataset_for_export(db, dataset_id, user)

    app_base_url, base_url = await get_public_urls(db, request=request)
    geodcat = record_to_geodcat_ap(
        dataset,
        base_url,
        app_base_url=app_base_url,
        lineage_summary=await _visible_record_lineage(db, dataset, user),
    )
    fallback_fields = geodcat_ap_fallback_fields(dataset)

    return JSONResponse(
        content=geodcat,
        media_type="application/ld+json",
        headers={
            **_record_language_headers(geodcat),
            **_record_fallback_headers(fallback_fields),
        },
    )


# ---------------------------------------------------------------------------
# COG download
# ---------------------------------------------------------------------------

# fix(#1528): a range can be most of a multi-GB COG, so it is read in bounded
# pieces rather than buffered whole — the same reason the full-object path
# streams via get_stream() (ING-03). fix(#1540 review P1): the chunk size that
# used to live here belongs to the provider now, along with the loop that used
# it; see the note where `_iter_storage_range` was.

# fix(#1532): the byte-range parser moved to `app/platform/http/ranges.py`.
# The export download at `processing/export/router.py` had to serve ranges off a
# stored artifact too, and `processing/` may not import `modules/catalog/`, so
# the choice was one parser in a shared home or two that agree until one is
# fixed. Everything the seven review rounds settled — the case-insensitive unit,
# the saturating digit guard, ignore-versus-416 — travelled with it, comments
# included.


# fix(#1540 review P1): `_iter_storage_range` used to live here, looping
# `storage.get_range` at `_COG_RANGE_CHUNK_BYTES` a call. It kept resident
# memory to one chunk, which was the point, and paid for it in object-store
# requests: one per chunk, so `Range: bytes=0-` on a 5 GiB COG issued 5,120 of
# them serially while the rate limiter counted one API request. That is the
# same amplification the stale-resume fallback was fixed for a round earlier,
# on the path an ordinary tile read takes — and on an S3 or Azure deployment
# every managed raster takes it, because ingest writes `storage_backend="local"`
# whatever the object store is.
#
# The bound belongs in the provider, which is the only layer that can ask for a
# window once and hand back the response as it arrives. `get_range_stream` is
# that method; see its contract in `platform/storage/provider.py`. Deleting the
# loop rather than repairing it is deliberate: a helper that turns one range
# into N reads has no correct chunk size, only less-wrong ones.


async def _resolve_download_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: Identity | None = Depends(get_optional_user),
) -> Identity | None:
    """Resolve user for download endpoints.

    Accepts standard auth (header JWT, API key) plus a ``token`` query
    parameter — but the query-param token MUST be a download-scoped JWT
    (``typ='download'``, ``scope='dataset:{dataset_id}'``) with ≤2-minute
    TTL, not a session JWT.

    SEC-04 / M-66: a session JWT in a URL is leak-prone (browser history,
    server logs, referer headers). Restricting query-param auth to
    download-scoped tokens bounds damage if the URL is exposed. The
    Authorization header path keeps accepting full session JWTs unchanged.

    KNOWN-01 (Phase 1071): returns ``Identity | None`` rather than ``User``.
    The mint endpoint at ``POST /auth/download-token/{id}`` issues a no-sub
    download token for anonymous callers on public datasets. A VALID no-sub
    token is a valid auth signal — the typ/scope/exp checks already gate
    the request — so we return ``None`` instead of raising 401. The
    downstream consumer (``download_cog``) is responsible for enforcing
    public visibility when user is None.

    No auth signal at all (no header AND no ``?token=``) also returns
    ``None`` rather than raising 401: mirrors ``get_optional_user``, which is
    what ``/datasets/{id}/export`` (``processing/export/router.py``) depends
    on directly. Before this, a plain anonymous GET here — no Authorization
    header, no minted token — hit the unconditional 401 below regardless of
    the dataset's visibility, so a public+published raster's COG could not be
    opened directly in QGIS/GDAL the way its tiles and vector export already
    can; only a caller that first minted a download token could get through.
    ``download_cog`` runs the same ``check_dataset_access_or_anonymous`` +
    public-visibility gate the export route runs, so this closes that
    asymmetry without loosening anything: a private/restricted/unpublished
    dataset still denies (404, to hide existence) once ``download_cog``
    applies that gate.

    401 is reserved for an auth signal that is actually invalid: bad token
    bytes, wrong typ, wrong scope, expired token, or a sub-bearing token
    whose user no longer exists / is inactive.
    """
    if user is not None:
        return user

    # Fallback: download-scoped JWT in ?token= query param (browser <a href> downloads)
    #
    # fix(#1693 codex r1): check presence (`is not None`), not truthiness. A
    # URL with a bare `?token=` (empty value) is a PRESENT-but-malformed
    # credential — jwt.decode("") raises DecodeError ("Not enough segments"),
    # a PyJWTError caught below and turned into 401 — not an ABSENT one. The
    # `if qt:` this replaces treated "" the same as "no ?token= at all" and
    # fell all the way through to the anonymous return None below it, which
    # would hide a client's broken token propagation behind a silent
    # anonymous success on a public dataset instead of the 401 that every
    # other malformed-token case in this block raises.
    qt = request.query_params.get("token")
    if qt is not None:
        # WR-04 (Phase 1071 review): no audience claim is verified here because
        # the mint endpoint (auth/router.py) does not emit an `aud` claim in
        # download-token payloads. If a future change adds `aud` to minted tokens
        # for tenant isolation or scope restriction, this decode MUST also pass
        # `audience=<expected_aud>` — otherwise PyJWT's audience validation is
        # silently skipped and tokens with any or no audience are accepted.
        try:
            payload = jwt.decode(
                qt, settings.jwt_secret_key.get_secret_value(), algorithms=["HS256"]
            )
        except jwt.PyJWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired download token",
            )

        if is_multi_tenant():
            try:
                token_tenant_id = uuid.UUID(str(payload.get("tid")))
                active_tenant_id = uuid.UUID(current_tenant_var.get() or "")
            except (ValueError, TypeError, AttributeError):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired download token",
                )
            if token_tenant_id != active_tenant_id:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired download token",
                )

        # fix(#1778): remember the credential's own deadline. The last hop of
        # this route hands the caller a presigned bucket URL, and that URL has
        # to expire with the capability that authorized it rather than on a
        # flat hour of its own. Stashed rather than returned because the
        # dependency's contract is Identity | None and a no-sub token resolves
        # to None -- the anonymous public-dataset case still has a deadline.
        request.state.download_token_exp = payload.get("exp")

        # Per SEC-04: enforce typ='download' on the query-param lane.
        if payload.get("typ") != "download":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=(
                    "Query-param ?token= requires a download-scoped JWT "
                    "(typ='download'); use Authorization header for session tokens"
                ),
            )

        # Scope check: token MUST be bound to the dataset_id in the URL.
        expected_scope = f"dataset:{request.path_params.get('dataset_id', '')}"
        if payload.get("scope") != expected_scope:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Download token scope does not match this dataset",
            )

        user_id = payload.get("sub")
        if user_id:
            # Sub-bearing authenticated download token: look up the user.
            # CR-02 (Phase 1071 review): narrow the except to only guard the
            # uuid.UUID() conversion, not the db.execute() call. A ValueError
            # from SQLAlchemy (ORM-contract violation) should bubble up rather
            # than being silently swallowed by a broad except ValueError: pass.
            try:
                user_uuid = uuid.UUID(user_id)
            except ValueError:
                pass  # malformed sub claim — fall through to 401
            else:
                result = await db.execute(select(User).where(User.id == user_uuid))
                found = result.scalar_one_or_none()
                if found and found.is_active and found.status == "active":
                    return found
            # Sub-bearing token whose user disappeared or is inactive — 401.
            # This IS an invalid auth signal (a token was presented and its
            # sub claim does not resolve to a usable user), unlike the
            # no-token case below, so it stays a hard 401 rather than falling
            # through to anonymous.
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )
        else:
            # KNOWN-01: no-sub anonymous download token. Token is valid
            # (typ/scope/exp all passed); return None and let download_cog
            # enforce public-visibility as defense-in-depth.
            return None

    # No Authorization header, no API key, no ?token= at all: no auth signal
    # to reject. Return None so download_cog's own
    # check_dataset_access_or_anonymous + public-visibility gate decides
    # access, the same way the export route's get_optional_user dependency
    # lets export_dataset_endpoint decide.
    return None


# fix(#1528): HEAD alongside GET. FastAPI's APIRoute does not add it the way
# starlette's plain Route does, so this answered `405 allow: GET` — refusing
# every client that probes before downloading (GDAL/QGIS `/vsicurl/`, resumable
# downloaders, link checkers). Same gap fix(#1513) closed for the export route,
# and `_register_standards_head_routes` in app/api/main.py for the standards
# surface.
#
# The HEAD is stronger than the export route's, and the difference is the
# point. That route runs a live conversion, so its length is unknowable before
# generating the content and its HEAD omits Content-Length under RFC 9110
# section 9.3.2. This one serves STORED bytes: one storage.size() gives a real
# Content-Length, and the `Accept-Ranges: bytes` it advertises is backed by an
# actual 206 below rather than by starlette's FileResponse re-running a
# conversion per range (the instability fix(#1532) tracks). A COG endpoint that
# could not serve ranges would be a COG endpoint in name only.
#
# include_in_schema=False for the reason `_clone_api_route` gives: a derived
# route documents nothing the canonical one does not, and publishing it would
# churn both SDKs and the CLI.
@router.head("/{dataset_id}/download/cog", include_in_schema=False)
@router.get(
    "/{dataset_id}/download/cog",
    response_class=Response,
    # fix(#1778): the ranged-download branch raises 412
    # on a failed If-Match; the published contract omitted it.
    responses={403: FORBIDDEN_RESPONSE, 412: PRECONDITION_FAILED_RESPONSE},
)
async def download_cog(
    dataset_id: uuid.UUID,
    request: Request,
    user: Identity | None = Depends(_resolve_download_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Download the Cloud-Optimized GeoTIFF for a raster dataset.

    Local storage: streams the COG file with Content-Type image/tiff.
    S3 storage: returns a 302 redirect to a presigned GET URL (1-hour expiry).
    Accepts standard auth or ?token= JWT query parameter for browser downloads.

    KNOWN-01 (Phase 1071): ``user`` may be None when a no-sub anonymous
    download token (issued by POST /auth/download-token/{id} for a public
    dataset) is presented on ``?token=``. The function branches on
    user-None to enforce public visibility and emit the audit row with
    user_id=NULL.
    """
    # The docstring above is the published OpenAPI description for the GET
    # operation, so it describes the GET only — the HEAD route is
    # include_in_schema=False and, since fix(#1540) review P1, answers the s3
    # backend from object metadata rather than redirecting. Adding that to the
    # docstring moves openapi.json and churns both SDKs and the CLI for prose
    # about an operation the schema does not carry, so it lives on the branch
    # itself instead.
    #
    # Same reasoning for what follows: `user` may ALSO be None for a plain
    # anonymous request with no auth signal at all (no header, no ?token=),
    # not only for the KNOWN-01 no-sub token case the docstring above
    # describes — see `_resolve_download_user`. That case is new
    # (fix(#1693): a public+published raster's COG used to 401 an anonymous
    # caller unconditionally before reaching this function, which the
    # docstring never had to mention because it never happened).
    # It's a comment rather than a docstring addition for the same
    # openapi.json/SDK/CLI churn reason.
    from slugify import slugify

    from app.modules.auth.permissions import get_effective_permissions

    # 1. Fetch dataset FIRST so we can branch visibility/permission on user-None.
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    # 2. Visibility + permission check (branches on authenticated vs anonymous).
    # Mirrors export_dataset_endpoint's gate (processing/export/router.py)
    # exactly: anonymous covers both a plain unauthenticated GET (no header,
    # no ?token=) and a mint-issued no-sub token, since _resolve_download_user
    # returns None for both.
    if user is None:
        # Anonymous download: enforce public+published gate via the anon-aware
        # helper (raises 404 to hide existence on denial), then a
        # defense-in-depth guard requiring public visibility — a tampered or
        # replayed download token cannot grant access to a private dataset.
        await check_dataset_access_or_anonymous(db, dataset, dataset_id, user)
        if dataset.record.visibility != "public":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Anonymous download requires public dataset",
            )
    else:
        # Authenticated path: full RBAC visibility check + export capability.
        await check_dataset_access(db, dataset, dataset_id, user)
        user_roles = await get_user_roles(db, user)
        matrix = await get_effective_permissions(db)
        # Route through the permission extension point (same call
        # export_dataset_endpoint makes) rather than inlining the per-role
        # matrix check, so a deployment that registers a custom
        # PermissionExtension applies its policy here too.
        # DefaultPermissionExtension.check_permission reduces to the same
        # any(matrix...) check, so OSS behavior is unchanged.
        granted = await get_permission_extension().check_permission(
            db,
            user,
            "export",
            user_roles=user_roles,
            permission_matrix=matrix,
        )
        if not granted:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Missing permission: export",
            )

    # 3. Verify raster type
    if dataset.record.record_type != "raster_dataset":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Not a raster dataset",
        )

    # 4. Fetch RasterAsset
    raster_asset = await get_catalog_port().get_raster_asset(db, dataset.id)
    if raster_asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Raster asset not found",
        )

    # 5. Build filename
    filename = f"{slugify(dataset.record.title)}.cog.tif"

    # 5b. Conditional request. fix(#1540 review P2): the ETag this route
    # publishes is only half a cache contract — a client that stores it and
    # revalidates has to be told "unchanged", or it re-downloads a COG it
    # already has, which for a multi-GB raster is the entire cost the header
    # was supposed to save.
    #
    # Before the audit row, and above the storage branching, for the reason
    # HEAD skips the audit: neither a 412 nor a 304 transfers bytes, so
    # recording either as `dataset.download_cog` would misreport who downloaded
    # what. The sequence is the one RFC 9110 section 13.2.2 fixes: If-Match,
    # then If-None-Match, then Range and If-Range.
    storage = get_storage()
    etag = _cog_etag(raster_asset)
    total_bytes: int | None = None

    if _this_service_owns_the_bytes(raster_asset) and (
        request.headers.get("if-match") or request.headers.get("if-none-match")
    ):
        # fix(#1540 review P2): stat BEFORE answering either precondition. RFC
        # 9110 section 13.2.1 puts preconditions after the normal request
        # checks, and existence is one: a row whose object has been deleted
        # answers 404 unconditionally, so a 304 here told a cache its stale copy
        # was a current representation of something that no longer exists — and
        # the same URL disagreed with itself about whether it existed depending
        # on whether the client sent a validator. The size is carried down
        # rather than re-measured, so a conditional request that goes on to
        # transfer bytes still stats exactly once (fix(#1540 review P2), the
        # double-stat round).
        total_bytes = await _cog_object_size(
            storage,
            physical_asset_key=_managed_key(raster_asset),
            dataset_id=dataset_id,
        )
        if not if_match_passes(request.headers.get("if-match"), etag):
            # A resuming client may say "only if this is still the
            # representation I have" with If-Match instead of If-Range.
            # Ignoring it left the absent If-Range reading as permission, so a
            # replacement mid-download was answered with a 206 of the new COG
            # at the old offsets — the same splice, through the header the
            # client happened to choose. A failed If-Match is a 412, not a
            # degradation: unlike If-Range, the RFC gives it no "ignore and
            # serve the whole thing" fallback.
            raise HTTPException(
                status_code=status.HTTP_412_PRECONDITION_FAILED,
                detail="COG has changed since the version you hold",
                headers={"ETag": etag} if etag is not None else None,
            )
        # fix(#1554): evaluated whatever `etag` is. The old `etag is not None`
        # guard was the right test for a specific tag and the wrong one for
        # `*`, which asks whether a current representation exists rather than
        # which one it is — so a legacy row with no `sha256` answered a
        # wildcard revalidation with the whole COG. The stat above is what
        # makes that existence question answerable here.
        if if_none_match_matches(request.headers.get("if-none-match"), etag):
            return not_modified_response(etag)

    # 6. Audit log. user_id may be None for anonymous downloads (KNOWN-01).
    # The audit_logs.user_id column is nullable; AuditEvent.user_id is typed
    # uuid.UUID | None to match.
    #
    # fix(#1528): not for HEAD. Nothing is transferred, so a
    # `dataset.download_cog` row for a probe misreports who downloaded what,
    # and every /vsicurl/ open begins with one. Same call fix(#1513) made on
    # the export route.
    #
    # Range GETs ARE audited, each one. That is a deliberate volume cost — a
    # COG client reading tiles emits a row per read where it used to emit one
    # per download — taken because the alternative is an audit blind spot: a
    # caller could otherwise pull an entire COG in ranges and appear in the log
    # zero times. `details.range` is what separates a tile read from a full
    # download when reading the log back.
    if request.method != "HEAD":
        await audit_emit(
            db,
            AuditEvent(
                user_id=user.id if user is not None else None,
                action="dataset.download_cog",
                resource_type="dataset",
                resource_id=dataset_id,
                details={
                    "filename": filename,
                    "storage_backend": raster_asset.storage_backend,
                    "range": request.headers.get("range"),
                },
                ip_address=request.client.host if request.client else None,
            ),
        )
        await db.commit()

    # 7. Storage-backend branching. `storage` was resolved above, because the
    # precondition block may already have had to stat the object.
    if raster_asset.storage_backend == "remote":
        # STAC import: asset_uri is the original remote COG URL — redirect.
        # SEC-06 / M-68: DNS records can change between import time (when
        # validate_url_for_ssrf was last run) and now. Re-run the SSRF check
        # immediately before redirecting to defeat DNS-rebinding TOCTOU.
        # If the hostname now resolves to a private IP (cloud metadata,
        # internal network), refuse the redirect with 403.
        from app.platform.security import (
            SSRFError,
            validate_url_for_ssrf,
        )

        try:
            await validate_url_for_ssrf(raster_asset.asset_uri)
        except SSRFError as exc:
            logger.warning(
                "cog_remote_redirect_blocked_by_ssrf",
                dataset_id=str(dataset_id),
                asset_uri=raster_asset.asset_uri,
                reason=str(exc),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Remote COG URL failed SSRF re-validation",
            )

        return RedirectResponse(url=raster_asset.asset_uri, status_code=302)

    physical_asset_key = _managed_key(raster_asset)

    if raster_asset.storage_backend == "s3":
        return await _s3_cog_response(
            request,
            storage,
            physical_asset_key=physical_asset_key,
            filename=filename,
            dataset_id=dataset_id,
            etag=etag,
            total_bytes=total_bytes,
        )

    return await _local_cog_response(
        request,
        storage,
        physical_asset_key=physical_asset_key,
        filename=filename,
        dataset_id=dataset_id,
        etag=etag,
        total_bytes=total_bytes,
    )


def _managed_key(raster_asset) -> str:
    """The physical storage key for an asset whose bytes this service owns.

    One call site became three when the precondition block had to stat the
    object before answering (fix(#1540 review P2)), and the tenant namespace
    this crosses is exactly the seam ``resolve_storage_key`` exists to own.
    """
    return resolve_storage_key(
        raster_asset.asset_uri, tenant_id=current_tenant_var.get()
    )


# fix(#1778): the presigned redirect used a flat 3600 seconds. That exchanged a
# 120-second, dataset-scoped, revocable capability (IA-P0-01 / SEC-04, minted by
# POST /auth/download-token/{id}) for an hour-long bearer URL that authenticates
# nobody: the SigV4 signature is in the query string and is bound to neither the
# caller, the session, nor the dataset grant. Revoking the grant, flipping the
# record to private, disabling the account or discarding the token does not
# invalidate it, because the bucket has never heard of any of those. The access
# gate above this is the full RBAC path, so the branch is reached for PRIVATE
# and INTERNAL datasets too, and the URL lands in browser history and in every
# proxy or CDN access log on the way.
#
# The ceiling is on the same order as the mint TTL rather than 30x it.
#
# fix(#1778 codex r8): and there is NO floor. The first version floored the
# window at 60 seconds to absorb clock skew, which meant a token with one
# second left still bought a minute of access to a private COG -- the same
# defect this block was written to remove, one order of magnitude smaller.
#
# `require_signable_job_lifetime` in processing/ingest/presigned.py already
# settled this for the upload doors, and says why: "`ExpiresIn` is relative to
# SIGNING time, so flooring at 1 mints a URL that is USABLE for one more
# second -- past the deadline this whole change exists to enforce. There is no
# `ExpiresIn` value that means 'already dead': the only way to avoid handing
# out a live URL is to not sign one." A 60-second floor is that argument
# ignored 60 times over. The download door now refuses on the same principle.
#
# The minimum is SigV4's own: `X-Amz-Expires` accepts 1..604800, so one second
# is the shortest signature that exists. Below that there is nothing to mint
# and the answer is 401 -- the authorizing credential expired between the
# dependency that verified it and this redirect.
_COG_PRESIGN_CEILING_SECONDS = 300
# The SigV4 lower bound on X-Amz-Expires. Not a policy knob: there is no
# shorter signature to hand out.
_COG_PRESIGN_MINIMUM_SECONDS = 1


def _cog_presign_seconds(request: Request) -> int:
    """How long the redirected bucket URL may stay valid.

    Capped at the remaining lifetime of the caller's download token when there
    is one, the way `sign_url_with_deadline` expires an ingest presign with its
    job rather than an hour from now. A caller who reached this route on a
    session JWT, an API key, or anonymously against a public dataset has no
    such deadline and gets the ceiling.

    Raises 401 when the token has less than one second left. fix(#1778 codex
    r8): rounding up instead would mint a URL that outlives the credential
    authorizing it, which is what the constants above now refuse to do.
    """
    import time

    deadline = getattr(request.state, "download_token_exp", None)
    if deadline is None:
        return _COG_PRESIGN_CEILING_SECONDS
    try:
        remaining_exact = float(deadline) - time.time()
    except (TypeError, ValueError):
        return _COG_PRESIGN_CEILING_SECONDS

    # int() truncates toward zero, which is the direction that matters: 1.9
    # seconds of token left signs a 1-second URL, never a 2-second one. The
    # signature can only ever expire before the credential does.
    remaining = int(remaining_exact)
    if remaining < _COG_PRESIGN_MINIMUM_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Download token expired",
        )
    return min(_COG_PRESIGN_CEILING_SECONDS, remaining)


async def _s3_cog_response(
    request: Request,
    storage,
    *,
    physical_asset_key: str,
    filename: str,
    dataset_id: uuid.UUID,
    etag: str | None,
    total_bytes: int | None = None,
) -> Response:
    """The s3 backend: HEAD here, a stale resume here, everything else redirected.

    fix(#1540 review P1): HEAD is answered from object metadata instead of
    falling through to the presigned redirect. `generate_presigned_get_url`
    signs `get_object`, and the HTTP method is part of an S3/MinIO SigV4
    canonical request. A redirect-following client keeps HEAD across a 302 (RFC
    9110 section 15.4 only rewrites the method for 303), so the redirected HEAD
    arrives at the bucket signed for the wrong verb and is refused. MEASURED
    against MinIO RELEASE.2025-09-07: a presigned get_object URL answers GET 200
    and HEAD 403, and the mirror image — a head_object URL fetched with GET —
    returns `SignatureDoesNotMatch`, the same rejection with a readable payload.
    Every /vsicurl/ open begins with that probe.

    fix(#1540 review P2): a resumed range whose validator no longer matches is
    also answered here, and this is the one case where the bytes come through
    this process. The bucket cannot be asked to decide it. MEASURED against the
    same MinIO: a presigned GET carrying `Range` plus an `If-Range` that does
    not match the object answers **206 anyway** — for the bucket's own ETag, for
    a foreign one, and for `If-None-Match` as well. The precondition is simply
    not evaluated. So a 302 here would hand a client resuming the OLD COG a 206
    of the NEW one, which is the splice fix(#1540 review P2) exists to prevent,
    and no redirect can prevent it: the client re-sends its `Range` across the
    hop and nothing in a 302 can strip it.

    Everything else still redirects, which is what keeps the design honest —
    whole-object GETs and matching resumes never touch this process's
    bandwidth, and they are the requests that carry the multi-GB payloads. The
    proxied case needs a replacement to have landed mid-download, and its cost
    is the same object the client was already downloading, moved from the
    bucket's egress to ours.
    """
    if request.method == "HEAD":
        return _cog_head_response(
            await _cog_size_once(
                total_bytes,
                storage,
                physical_asset_key=physical_asset_key,
                dataset_id=dataset_id,
            ),
            filename,
            etag,
        )

    if request.headers.get("range") and not range_bound_to_this_version(
        request.headers.get("if-range"), etag
    ):
        # fix(#1540 review P1): ONE get_object, streamed — not
        # `_iter_storage_range` over the whole object, which issues a ranged
        # request per 1 MiB chunk. A caller can select this branch deliberately
        # by sending any stale validator, so at a chunk apiece a 5 GiB COG cost
        # 5,120 object-store requests that the per-request rate limiter counts
        # as one. `_iter_storage_range` is right where the client named a
        # window and wrong here, where the answer is the entire object.
        total_bytes = await _cog_size_once(
            total_bytes,
            storage,
            physical_asset_key=physical_asset_key,
            dataset_id=dataset_id,
        )
        return StreamingResponse(
            storage.get_stream(physical_asset_key),
            media_type="image/tiff",
            headers={
                **_cog_headers(filename, etag),
                "Content-Length": str(total_bytes),
            },
        )

    url = storage.generate_presigned_get_url(
        physical_asset_key, expiration=_cog_presign_seconds(request)
    )
    return RedirectResponse(url=url, status_code=302)


def _this_service_owns_the_bytes(raster_asset) -> bool:
    """Is this asset's content ours to make claims about?

    The ``remote`` backend is a redirect to a third-party origin whose bytes
    this service never reads. It publishes no validator (see ``_cog_etag``) and
    evaluates no precondition: a client's ``If-Match`` there was issued by that
    origin, travels to it across the redirect, and is answered by the only party
    that can answer it. Managed backends are the opposite case — this service is
    the origin server, so an unverifiable precondition is a 412 rather than a
    shrug.
    """
    return raster_asset.storage_backend != "remote"


# fix(#1532 review r9): `if_match_passes`, `_if_none_match_matches`,
# `_without_weak_prefix` and `_cog_not_modified` moved to
# `app/platform/http/ranges.py`, joining the parser and the If-Range comparison
# that went there earlier. The export download evaluates the same preconditions
# against the same kind of strong ETag and lives under `processing/`, which
# cannot import this module — so it was one implementation in a shared home or
# two that agree until one is fixed.
def _cog_etag(raster_asset) -> str | None:
    """The stored COG's own SHA-256, quoted as a STRONG entity-tag.

    fix(#1540 review P2): a range response has to say which version of the
    object it is a slice of, or a resumable client can splice two of them. The
    stable download URL names a dataset, not a build: a replacement swaps
    ``asset_uri`` and ``sha256`` on the same row
    (``tasks_raster_swap.py:_write_swapped_fields``), so consecutive range GETs
    to one URL can read different objects while every response is a 206. The
    client assembles a prefix of the old COG and a suffix of the new one, gets
    no error at any point, and treats the result as a raster.

    ``sha256`` is the digest of the COG bytes themselves (``sha256_file`` over
    the converted file in ``tasks_raster.py``), so it changes if and only if
    those bytes change. That is the definition of a strong validator, and it is
    why nothing weaker is offered: ``Last-Modified`` has one-second granularity,
    and a replacement that lands inside the same second as its predecessor is
    exactly the case this exists to catch.

    None on rows ingested before the column was populated. A response then
    carries no validator, and ``range_bound_to_this_version`` refuses to honour
    a conditional range rather than guessing — see its docstring.

    None for the ``remote`` backend too, and for a different reason: those bytes
    belong to a third-party origin this service redirects to and never reads.
    Publishing a digest recorded at import time would claim an object is
    unchanged on the strength of a measurement that may be months old, and the
    origin already answers with validators of its own.
    """
    if not _this_service_owns_the_bytes(raster_asset):
        return None
    sha = raster_asset.sha256
    return f'"{sha}"' if sha else None


# fix(#1532 review r1): `range_bound_to_this_version` moved to
# `app/platform/http/ranges.py` as `range_bound_to_this_version`, alongside the
# parser, for the same reason: the export download evaluates the identical
# If-Range precondition and cannot import this module.


async def _cog_object_size(
    storage, *, physical_asset_key: str, dataset_id: uuid.UUID
) -> int:
    """Stat the stored COG ONCE: 404 when it is gone, 503 when the backend is not.

    Stat'ing upfront is what lets a missing object surface as a 404 BEFORE an
    async iterator is handed to ``StreamingResponse``. Starlette consumes that
    iterator after returning the response, so a deferred raise inside the
    generator would produce a 500 (or a broken Transfer-Encoding chunk) rather
    than a clean 404. The size is that same call's answer, which is what makes
    both halves of fix(#1528) honest — a real Content-Length on HEAD and on the
    full GET, and the denominator of every Content-Range.

    fix(#1540 review P2): ONE ``size()``, not ``exists()`` then ``size()``. Every
    provider normalizes a missing object to ``FileNotFoundError`` (the
    ``StorageProvider`` protocol says so; S3 and Azure convert their native
    not-found under fix(#430 BA-24)), so the existence answer was already inside
    the size answer, and asking twice cost a second ``head_object`` per
    ``/vsicurl/`` probe — against a PR whose argument for answering HEAD here
    rather than signing a second URL was that it is ONE round trip. It also
    opened a window: a delete landing between the calls made ``exists()`` say yes
    and ``size()`` raise, which the handler below turned into a 503 for an object
    that was merely gone. ``test_head_cog_issues_exactly_one_s3_metadata_call``
    and ``test_a_delete_racing_the_stat_is_a_404_not_a_503`` fail if either half
    comes back.

    fix(#1540 review P1): shared with the ``s3`` branch rather than living
    inside the local one, so a HEAD gets the same 200/404/503 answer whichever
    backend holds the bytes.
    """
    try:
        return await storage.size(physical_asset_key)
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="COG file not found",
        )
    except Exception:  # broad: storage backend (S3/MinIO/local) can throw varied SDK/I/O errors; map to 503
        logger.exception("cog_storage_error", dataset_id=str(dataset_id))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="COG download temporarily unavailable",
        )


async def _cog_size_once(
    already_known: int | None,
    storage,
    *,
    physical_asset_key: str,
    dataset_id: uuid.UUID,
) -> int:
    """The object's size, stat'ing only if the caller has not already.

    fix(#1540 review P2): the precondition block has to stat before it can
    answer a 304 — a row whose bytes are gone must 404 whether or not the
    client sent a validator. Handing that measurement down is what keeps the
    single-stat property the double-stat round established: a conditional
    request that goes on to transfer bytes still touches object metadata once.
    """
    if already_known is not None:
        return already_known
    return await _cog_object_size(
        storage, physical_asset_key=physical_asset_key, dataset_id=dataset_id
    )


def _cog_headers(filename: str, etag: str | None) -> dict[str, str]:
    """Headers every stored-bytes response from this route carries.

    fix(#1528): ``accept-ranges`` goes on all of them, including the 416 — RFC
    9110 section 14.3 scopes it to the RESOURCE, not to the one response
    carrying it, and a client that just got a 416 is precisely the one that
    needs telling it may retry with a corrected range.

    fix(#1540 review P2): ``ETag`` likewise, on the 200, the 206 and the HEAD.
    Advertising ``Accept-Ranges`` without a validator invites exactly the
    resumable client that can splice two COGs, and the 206 in particular is
    useless for that client unless it can name the version its slice came from.

    Content-Disposition does NOT go on the 416, which is why the caller merges
    this dict rather than the 416 reusing it. That response's body is the JSON
    error, not the raster; naming it ``attachment; filename="....cog.tif"``
    would have a browser save an error document under the COG's filename.
    """
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": get_catalog_port().safe_content_disposition(filename),
    }
    if etag is not None:
        headers["ETag"] = etag
    return headers


def _cog_head_response(total_bytes: int, filename: str, etag: str | None) -> Response:
    """The HEAD answer: one stat, no read, a real length.

    A HEAD that streamed the object to learn its length would make every
    /vsicurl/ open cost a full download — the amplification the export route's
    HEAD avoids by not running its conversion.

    A Range on a HEAD is deliberately ignored. HEAD describes the selected
    representation, so answering 206 here would report a tile's length as the
    size of the COG.

    Passing content-length explicitly also suppresses starlette's own:
    ``init_headers`` populates it from the body, which for this empty one is
    ``content-length: 0`` — a confident wrong answer that reads as an empty COG,
    and strictly worse than the 405 this replaces. fix(#1513) had to strip that
    header for the same reason; here the real value displaces it.
    ``test_head_cog_carries_the_real_content_length`` fails if this is ever
    dropped back to the default.

    The ETag matters most on THIS response: a HEAD is how a resumable client
    learns both that ranges are available and which version it is about to
    start reading, and it is the only answer the ``s3`` backend gets from this
    process at all.
    """
    return Response(
        status_code=status.HTTP_200_OK,
        media_type="image/tiff",
        headers={**_cog_headers(filename, etag), "Content-Length": str(total_bytes)},
    )


async def _local_cog_response(
    request: Request,
    storage,
    *,
    physical_asset_key: str,
    filename: str,
    dataset_id: uuid.UUID,
    etag: str | None,
    total_bytes: int | None = None,
) -> Response:
    """Serve stored COG bytes: HEAD, a byte range, or the whole object.

    Split out of ``download_cog`` in fix(#1528) — folding three response
    shapes into a handler that already branches over three storage backends put
    it past ruff's complexity ceiling (C901, 17 > 15).

    Everything that decides the STATUS has already run in the caller: access
    control, the raster-type gate, and the RasterAsset lookup. This function
    only decides which representation to send, which is why it is safe for HEAD
    and GET to share it.
    """
    # Local storage: stream bytes from disk in 1 MiB chunks (ING-03 / P2-03).
    # The full file is NOT buffered into memory — a 5 GB COG no longer pins
    # 5 GB of resident memory before the first byte streams.
    total_bytes = await _cog_size_once(
        total_bytes,
        storage,
        physical_asset_key=physical_asset_key,
        dataset_id=dataset_id,
    )
    cog_headers = _cog_headers(filename, etag)

    if request.method == "HEAD":
        return _cog_head_response(total_bytes, filename, etag)

    byte_range = parse_byte_range(request.headers.get("range"), total_bytes)

    if byte_range is not None and not range_bound_to_this_version(
        request.headers.get("if-range"), etag
    ):
        # fix(#1540 review P2): the resumed range names a version this object is
        # no longer at — a replacement landed between the client's requests.
        # RFC 9110 section 13.1.5 says ignore the Range, so the client gets the
        # whole current COG and 200. Before the ETag it got a 206 of the NEW
        # bytes at the OLD offsets, appended those to the prefix it already had,
        # and wrote out a file that is half of each: no error anywhere, and a
        # raster it then treats as authoritative.
        #
        # Before the 416 check on purpose. "Ignore the Range" means ignore it,
        # including when the stale offsets no longer fit the new object; a 416
        # would be answering a question that is no longer being asked.
        byte_range = None

    if byte_range == RANGE_UNSATISFIABLE:
        raise HTTPException(
            status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            detail="Requested range not satisfiable",
            headers={
                "Accept-Ranges": "bytes",
                # The size is the whole point of the 416: it is how a client
                # that guessed at the length learns the real one and retries.
                "Content-Range": f"bytes */{total_bytes}",
                # And the version that size belongs to: a client that retries
                # against a length it learned here should be able to tell if the
                # object changed again in between.
                **({"ETag": etag} if etag is not None else {}),
            },
        )

    if byte_range is not None:
        # The reason the format exists: a client reads the COG header, then
        # fetches only the tiles it needs. Served through get_range() so the
        # bytes outside the window are never read — see
        # `test_range_request_does_not_read_the_whole_object`, which fails if
        # this is ever implemented by slicing a full-object stream.
        start, end = byte_range
        return StreamingResponse(
            storage.get_range_stream(physical_asset_key, start, end - start + 1),
            status_code=status.HTTP_206_PARTIAL_CONTENT,
            media_type="image/tiff",
            headers={
                **cog_headers,
                "Content-Range": f"bytes {start}-{end}/{total_bytes}",
                "Content-Length": str(end - start + 1),
            },
        )

    return StreamingResponse(
        storage.get_stream(physical_asset_key),
        media_type="image/tiff",
        headers={**cog_headers, "Content-Length": str(total_bytes)},
    )
