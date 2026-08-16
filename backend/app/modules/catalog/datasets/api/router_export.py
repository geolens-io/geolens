"""Dataset export endpoints: DCAT JSON-LD catalog and COG download."""

import re
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
from app.platform.extensions import get_catalog_port
from app.platform.storage import get_storage
from app.platform.storage.titiler_url import resolve_storage_key
from app.standards.ogc.errors import (
    ERROR_RESPONSES_PUBLIC,
    FORBIDDEN_RESPONSE,
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

# fix(#1528): chunk size for a streamed byte range. A range can be most of a
# multi-GB COG, so it is read in bounded pieces rather than buffered whole —
# the same reason the full-object path streams via get_stream() (ING-03).
_COG_RANGE_CHUNK_BYTES = 1024 * 1024  # 1 MiB

# One anchored pattern, deliberately strict about what it accepts:
#   bytes=FIRST-LAST | bytes=FIRST- | bytes=-SUFFIX
# `[0-9]` rather than `\d` because Python's `\d` is unicode-aware, and
# int("٣") succeeds while int("²") raises — a header parser should not have
# opinions about Arabic-Indic digits. Anything this does not match (a second
# range, an unknown unit, a reversed pair) is IGNORED per RFC 9110 section
# 14.2, which is the safe direction: the client gets the whole representation
# it can already handle, never a partial one mislabelled as something else.
_BYTE_RANGE_RE = re.compile(r"^bytes=(?:([0-9]+)-([0-9]*)|-([0-9]+))$")

# The Range named no byte of the representation (first-byte-pos at or past the
# end, or a zero-length suffix). RFC 9110 section 15.5.17 wants a 416 carrying
# the real size, NOT a 200 with the whole object: a client that asked for one
# tile and silently received the entire COG splices it at the wrong offset.
_RANGE_UNSATISFIABLE = "unsatisfiable"


def _parse_cog_range(raw: str | None, size: int) -> tuple[int, int] | str | None:
    """Resolve a Range header to an inclusive ``(start, end)`` byte pair.

    Returns ``None`` when there is no usable range and the caller should serve
    the complete representation, ``_RANGE_UNSATISFIABLE`` when it must answer
    416, and otherwise the resolved pair — already clamped to the object, so
    callers never have to re-check the bounds.

    Multi-range requests return ``None``. RFC 9110 section 14.2 lets a server
    answer a multi-range request with a single range or with the whole
    representation; ``multipart/byteranges`` is not implemented here, and
    answering the FIRST range while echoing only its Content-Range would be
    the corrupt-download failure — a client expecting two parts writes one of
    them over both offsets.
    """
    if not raw:
        return None
    match = _BYTE_RANGE_RE.match(raw.strip())
    if match is None:
        return None
    first, last, suffix = match.groups()

    if suffix is not None:
        # bytes=-N: the final N bytes. A zero-length suffix names nothing.
        if int(suffix) == 0 or size == 0:
            return _RANGE_UNSATISFIABLE
        return (max(0, size - int(suffix)), size - 1)

    start = int(first)
    if size == 0 or start >= size:
        return _RANGE_UNSATISFIABLE
    if last == "":
        # bytes=N-: from N to the end.
        return (start, size - 1)
    end = int(last)
    if end < start:
        return None  # reversed pair: invalid, so ignore rather than reject
    # A last-byte-pos past the end is CLAMPED, not rejected — clients that do
    # not know the size ask for more than exists on purpose.
    return (start, min(end, size - 1))


async def _iter_storage_range(storage, key: str, start: int, length: int):
    """Yield exactly ``length`` bytes from ``start``, in bounded chunks.

    ``storage.get_range`` returns bytes rather than a stream, so a single call
    for a whole range would materialize it in memory — fine for the 16 KB
    header read a COG client opens with, not for a caller that asks for a
    gigabyte. The loop keeps resident memory at one chunk regardless of the
    range's size.

    A short read ends the stream instead of looping forever: if the object
    shrank under us the response is truncated against its Content-Length, which
    every HTTP client reports as a failed transfer. That is the loud failure;
    padding to length would be the quiet corrupt one.
    """
    remaining = length
    offset = start
    while remaining > 0:
        chunk = await storage.get_range(
            key, offset, min(remaining, _COG_RANGE_CHUNK_BYTES)
        )
        if not chunk:
            return
        yield chunk
        offset += len(chunk)
        remaining -= len(chunk)


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

    401 is reserved for: no auth signal at all (no header AND no token),
    invalid token bytes, wrong typ, wrong scope, expired token, or a
    sub-bearing token whose user no longer exists / is inactive.
    """
    if user is not None:
        return user

    # Fallback: download-scoped JWT in ?token= query param (browser <a href> downloads)
    qt = request.query_params.get("token")
    if qt:
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
            # Sub-bearing token whose user disappeared or is inactive — 401
            # (fall through to the unconditional 401 below).
        else:
            # KNOWN-01: no-sub anonymous download token. Token is valid
            # (typ/scope/exp all passed); return None and let download_cog
            # enforce public-visibility as defense-in-depth.
            return None

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
    )


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
    responses={403: FORBIDDEN_RESPONSE},
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
    if user is None:
        # Anonymous download via mint-issued no-sub token. The mint endpoint at
        # POST /auth/download-token/{id} already enforced
        # check_dataset_access_or_anonymous(); the token's typ/scope/exp checks
        # in _resolve_download_user are the auth gate. Still require public
        # visibility here as defense-in-depth (a tampered/replayed token
        # cannot grant access to a private dataset).
        await check_dataset_access_or_anonymous(db, dataset, dataset_id, user)
        if dataset.record.visibility != "public":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Anonymous download requires public dataset",
            )
    else:
        # Authenticated path: full RBAC visibility check + export permission.
        await check_dataset_access(db, dataset, dataset_id, user)
        user_roles = await get_user_roles(db, user)
        matrix = await get_effective_permissions(db)
        if not any(matrix.get(role, {}).get("export", False) for role in user_roles):
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

    # 7. Storage-backend branching
    storage = get_storage()

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

    physical_asset_key = resolve_storage_key(
        raster_asset.asset_uri, tenant_id=current_tenant_var.get()
    )

    if raster_asset.storage_backend == "s3":
        url = storage.generate_presigned_get_url(physical_asset_key, expiration=3600)
        return RedirectResponse(url=url, status_code=302)

    return await _local_cog_response(
        request,
        storage,
        physical_asset_key=physical_asset_key,
        filename=filename,
        dataset_id=dataset_id,
    )


async def _local_cog_response(
    request: Request,
    storage,
    *,
    physical_asset_key: str,
    filename: str,
    dataset_id: uuid.UUID,
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
    #
    # Probe existence upfront so FileNotFoundError surfaces as 404 BEFORE the
    # async iterator is handed to StreamingResponse. Starlette consumes the
    # iterator after returning the response, so a deferred raise inside the
    # generator would produce a 500 (or a broken Transfer-Encoding chunk)
    # rather than a clean 404.
    #
    # fix(#1528): the size is read in the same guarded block. It is what makes
    # both halves of this fix honest — a real Content-Length on HEAD and on the
    # full GET, and the denominator of every Content-Range below — and a
    # backend that throws on size() must map to the same 503 as one that throws
    # on exists(), not to a raw 500.
    try:
        if not await storage.exists(physical_asset_key):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="COG file not found",
            )
        total_bytes = await storage.size(physical_asset_key)
    except HTTPException:
        raise
    except Exception:  # broad: storage backend (S3/MinIO/local) can throw varied SDK/I/O errors; map to 503
        logger.exception("cog_storage_error", dataset_id=str(dataset_id))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="COG download temporarily unavailable",
        )

    # fix(#1528): `accept-ranges` goes on every response from this branch,
    # including the 416 — RFC 9110 section 14.3 scopes it to the RESOURCE, not
    # to the one response carrying it, and a client that just got a 416 is
    # precisely the one that needs telling it may retry with a corrected range.
    #
    # Content-Disposition does NOT go on the 416, which is why these are two
    # dicts and not one. That response's body is the JSON error, not the
    # raster; naming it `attachment; filename="....cog.tif"` would have a
    # browser save an error document under the COG's filename.
    cog_headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": get_catalog_port().safe_content_disposition(filename),
    }

    if request.method == "HEAD":
        # Answered entirely from metadata: one stat, no read. A HEAD that
        # streamed the object to learn its length would make every /vsicurl/
        # open cost a full download — the amplification the export route's HEAD
        # avoids by not running its conversion.
        #
        # A Range on a HEAD is deliberately ignored. HEAD describes the
        # selected representation, so answering 206 here would report a tile's
        # length as the size of the COG.
        #
        # Passing content-length explicitly also suppresses starlette's own:
        # `init_headers` populates it from the body, which for this empty one
        # is `content-length: 0` — a confident wrong answer that reads as an
        # empty COG, and strictly worse than the 405 this replaces. fix(#1513)
        # had to strip that header for the same reason; here the real value
        # displaces it. `test_head_cog_carries_the_real_content_length` fails
        # if this is ever dropped back to the default.
        return Response(
            status_code=status.HTTP_200_OK,
            media_type="image/tiff",
            headers={**cog_headers, "Content-Length": str(total_bytes)},
        )

    byte_range = _parse_cog_range(request.headers.get("range"), total_bytes)

    if byte_range == _RANGE_UNSATISFIABLE:
        raise HTTPException(
            status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            detail="Requested range not satisfiable",
            headers={
                "Accept-Ranges": "bytes",
                # The size is the whole point of the 416: it is how a client
                # that guessed at the length learns the real one and retries.
                "Content-Range": f"bytes */{total_bytes}",
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
            _iter_storage_range(storage, physical_asset_key, start, end - start + 1),
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
