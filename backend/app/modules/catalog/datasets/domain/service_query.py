"""Dataset read queries for lookup, listing, details, and rows."""

from __future__ import annotations

import math
import struct
import uuid
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from app.modules.catalog.datasets.domain.schemas import DatasetResponse

from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.db.sqlstate import TABLE_ABSENT, sqlstate
from app.core.identity import Identity
from app.core.record_types import RASTER_FAMILY_RECORD_TYPES, capabilities
from app.core.pointcloud import POINTCLOUD_ASSET_KEY
from app.core.tiles3d import TILESET_ASSET_KEY
from app.modules.catalog.authorization import (
    apply_visibility_filter,
    can_view_dataset_provenance,
    visible_vrt_extents,
    visible_vrt_source_counts,
)
from app.modules.catalog.datasets.domain._sql_safety import (
    SAFE_TABLE_NAME_RE,
    _safe_column_ref,
)
from app.modules.catalog.datasets.domain.service_analysis import _json_safe
from app.modules.catalog.datasets.domain.models import (
    AttributeMetadata,
    Dataset,
    DatasetGrant,
    Record,
)
from app.platform.assets.keys import is_public_asset_key
from app.platform.extensions import get_catalog_port

logger = structlog.stdlib.get_logger(__name__)


__all__ = [
    "get_dataset",
    "get_tileset_href",
    "get_pointcloud_pointer",
    "list_datasets",
    "get_datasets_list",
    "get_dataset_detail",
    "get_dataset_rows",
    "InvalidSortColumn",
    "sortable_columns",
]


async def get_dataset(session: AsyncSession, dataset_id: uuid.UUID) -> Dataset | None:
    """Fetch a single dataset by ID with its record eager-loaded."""
    result = await session.execute(
        select(Dataset)
        .options(joinedload(Dataset.record))
        .where(Dataset.id == dataset_id)
    )
    return result.scalar_one_or_none()


def _carrier(rows: list[Any], key: str) -> Any | None:
    """The internal pointer row with *key* among a dataset's asset rows."""
    return next((row for row in rows if row.key == key), None)


async def get_tileset_href(session: AsyncSession, dataset_id: uuid.UUID) -> str | None:
    """The logical key of a tileset's live tileset.json, or None; never published."""
    rows = await get_catalog_port().get_dataset_assets(session, dataset_id)
    carrier = _carrier(rows, TILESET_ASSET_KEY)
    return None if carrier is None else carrier.href


async def get_pointcloud_pointer(session: AsyncSession, dataset_id: uuid.UUID) -> Any:
    """A point cloud's live pointer row, naming its file and size, or None; never published."""
    rows = await get_catalog_port().get_dataset_assets(session, dataset_id)
    return _carrier(rows, POINTCLOUD_ASSET_KEY)


async def list_datasets(
    session: AsyncSession,
    user: Identity,
    user_roles: set[str],
    *,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[Dataset], int]:
    """List datasets with visibility filtering.

    Returns a tuple of (datasets, total_count).
    """
    base_stmt = (
        select(Dataset)
        .join(Record, Dataset.record_id == Record.id)
        .options(joinedload(Dataset.record))
    )
    filtered_stmt = apply_visibility_filter(
        base_stmt, user, user_roles, Record, DatasetGrant
    )

    count_stmt = select(func.count()).select_from(filtered_stmt.subquery())
    total = await session.execute(count_stmt)
    total_count = total.scalar_one()

    # Record.created_at is a non-unique server-default; add a
    # unique tiebreaker so pagination over batch-seeded rows is stable.
    paginated_stmt = (
        filtered_stmt.offset(skip)
        .limit(limit)
        .order_by(Record.created_at.desc(), Record.id.desc())
    )
    result = await session.execute(paginated_stmt)
    datasets = list(result.scalars().unique().all())

    return datasets, total_count


async def get_datasets_list(
    db: AsyncSession,
    user: Identity,
    user_roles: set[str],
    *,
    skip: int = 0,
    limit: int = 50,
    base_url: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Fetch paginated dataset list with raster assets, VRT source counts, and actor info.

    Returns (dataset_response_list, total_count) ready for the API response.
    """
    from app.modules.catalog.datasets.domain.helpers import (
        _load_actor_identities,
        dataset_to_response,
    )

    is_admin = "admin" in user_roles
    datasets, total = await list_datasets(db, user, user_roles, skip=skip, limit=limit)

    actors_by_id = await _load_actor_identities(
        db,
        [
            actor_id
            for dataset in datasets
            for actor_id in (dataset.record.created_by, dataset.record.updated_by)
        ],
    )

    raster_ids = [
        d.id
        for d in datasets
        if getattr(d.record, "record_type", None) in RASTER_FAMILY_RECORD_TYPES
    ]
    raster_assets_by_dataset_id = await get_catalog_port().list_raster_assets(
        db, raster_ids
    )

    vrt_ids = [
        d.id
        for d in datasets
        if getattr(d.record, "record_type", None) == "vrt_dataset"
    ]
    source_counts = await visible_vrt_source_counts(db, vrt_ids, user, user_roles)
    vrt_extents = await visible_vrt_extents(db, vrt_ids, user, user_roles)

    # One visibility query for the page, not one per row.
    from app.modules.catalog.authorization import visible_lineage_summaries

    lineage = await visible_lineage_summaries(
        db, [d.record for d in datasets], user, user_roles
    )

    response_list = [
        dataset_to_response(
            d,
            actors_by_id=actors_by_id,
            raster_asset=raster_assets_by_dataset_id.get(d.id),
            is_admin=is_admin,
            source_count=source_counts.get(d.id),
            vrt_extents=vrt_extents,
            base_url=base_url,
            lineage_summary=lineage[d.record_id],
            # Per-row — the page can mix the caller's own
            # datasets with peers' public ones, so one page-level flag would
            # either over- or under-redact.
            can_view_provenance=can_view_dataset_provenance(d.record, user, user_roles),
        )
        for d in datasets
    ]

    return response_list, total


async def get_dataset_detail(
    db: AsyncSession,
    dataset_id: uuid.UUID,
    user: Identity | None,
    *,
    base_url: str | None = None,
    collections_data: list[dict] | None = None,
    dataset: "Dataset | None" = None,
    user_roles: set[str] | None = None,
) -> "DatasetResponse | None":
    """Fetch full dataset detail including raster assets, STAC assets, and collections.

    Returns a DatasetResponse or None if not found.
    The caller is responsible for visibility checks and audit logging.
    """
    from app.modules.catalog.datasets.domain.helpers import (
        _load_actor_identities,
        dataset_geom_is_generic,
        dataset_to_response,
    )
    from app.modules.catalog.datasets.domain.schemas import StacAsset
    from app.modules.catalog.datasets.domain.service_previous_version import (
        previous_version_summaries,
    )

    if dataset is None:
        dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        return None

    actors_by_id = await _load_actor_identities(
        db,
        [dataset.record.created_by, dataset.record.updated_by],
    )

    # Raster, VRT member count and DatasetAsset lookups run sequentially on the
    # caller's own session through CatalogPort, so catalog doesn't import
    # processing-owned raster ORM classes. AsyncSession isn't safe for
    # concurrent use, and a session per branch would nest a pool checkout on the
    # caller's held connection, exhausting the 10+3 pool at ~13 concurrent
    # detail requests. Three fast point lookups cost little sequentially.
    record_type = getattr(dataset.record, "record_type", None)
    needs_raster = record_type in RASTER_FAMILY_RECORD_TYPES
    needs_vrt_count = record_type == "vrt_dataset"

    raster_asset = None
    if needs_raster:
        raster_asset = await get_catalog_port().get_raster_asset(db, dataset.id)

    if user_roles is None:
        from app.modules.catalog.authorization import get_user_roles

        user_roles = await get_user_roles(db, user) if user is not None else set()
    is_admin = "admin" in user_roles

    source_count = None
    vrt_extents = {}
    if needs_vrt_count:
        source_count = (
            await visible_vrt_source_counts(db, [dataset.id], user, user_roles)
        )[dataset.id]
        vrt_extents = await visible_vrt_extents(db, [dataset.id], user, user_roles)

    dataset_asset_rows = await get_catalog_port().get_dataset_assets(db, dataset.id)
    tileset_asset = _carrier(dataset_asset_rows, TILESET_ASSET_KEY)
    pointcloud_asset = _carrier(dataset_asset_rows, POINTCLOUD_ASSET_KEY)
    stac_assets_dict = {}
    for da in dataset_asset_rows:
        # Apply the asset allowlist before exposing href, filename, or size.
        if not is_public_asset_key(da.key):
            continue
        stac_assets_dict[da.key] = StacAsset(
            href=da.href,
            type=da.media_type,
            title=da.title,
            description=da.description,
            roles=da.roles,
            size_bytes=da.size_bytes,
        )

    from app.modules.catalog.authorization import (
        visible_derived_from,
        visible_lineage_summary,
    )

    # Owner-or-admin only, like the sharing groups below.
    can_view_provenance = can_view_dataset_provenance(dataset.record, user, user_roles)
    response = dataset_to_response(
        dataset,
        collections=collections_data,
        actors_by_id=actors_by_id,
        raster_asset=raster_asset,
        tileset_asset=tileset_asset,
        pointcloud_asset=pointcloud_asset,
        is_admin=is_admin,
        source_count=source_count,
        vrt_extents=vrt_extents,
        base_url=base_url,
        stac_assets=stac_assets_dict or None,
        # Detail only, and only when the requester can reach the
        # source dataset.
        derived_from=await visible_derived_from(
            db, dataset.record.derived_from, user, user_roles
        ),
        # The prose names the same datasets the reference points at.
        lineage_summary=await visible_lineage_summary(
            db, dataset.record, user, user_roles
        ),
        # Every other accessible-dataset reader (named or anonymous) gets
        # origin_uri/origin_ref nulled.
        can_view_provenance=can_view_provenance,
    )
    if response is not None and can_view_provenance:
        from app.modules.catalog.datasets.domain.service_sharing import (
            dataset_groups,
        )

        response.groups = await dataset_groups(db, dataset.id)
    # Genericity probe (helpers.py) keeps all draw modes.
    if response is not None and dataset.source_format == "created":
        response.has_generic_geometry = await dataset_geom_is_generic(
            db, dataset.table_name
        )
    if response is not None and capabilities(record_type).feature_table:
        response.previous_versions = await previous_version_summaries(db, dataset)
        response.previous_version = next(iter(response.previous_versions), None)
    return response


# Geometry column names excluded from SELECT in get_dataset_rows.
_GEOM_COLUMN_NAMES = frozenset({"geom", "geom_4326", "wkb_geometry"})


# information_schema data_type values with a btree ordering whose values
# asyncpg reads back and binds again as the next page's anchor. Anything else
# can't be sorted on: no ordering (json, xml, geometric types), an anchor that
# doesn't bind back (jsonb, money, macaddr), or a hidden element type (ARRAY).
_SORTABLE_TYPES = frozenset(
    {
        "smallint",
        "integer",
        "bigint",
        "numeric",
        "real",
        "double precision",
        "character varying",
        "character",
        "text",
        "date",
        "timestamp without time zone",
        "timestamp with time zone",
        "time without time zone",
        "time with time zone",
        "interval",
        "boolean",
        "uuid",
        "inet",
        "cidr",
        "bytea",
    }
)


class InvalidSortColumn(ValueError):
    """The requested sort column is not a sortable column of the dataset."""


def _projected_columns(column_info: list[dict]) -> list[dict]:
    """Return the column_info entries to project, with `gid` always present."""
    projected = [
        c
        for c in column_info
        if SAFE_TABLE_NAME_RE.match(c["name"])
        and c.get("type") != "USER-DEFINED"
        and c["name"] not in _GEOM_COLUMN_NAMES
    ]
    if not any(c["name"] == "gid" for c in projected):
        projected.insert(0, {"name": "gid", "type": "integer"})
    return projected


def _build_select_cols(column_info: list[dict]) -> list[str]:
    """Return the quoted non-geometry columns to project, `gid` always present."""
    return [_safe_column_ref(c["name"]) for c in _projected_columns(column_info)]


def sortable_columns(column_info: list[dict]) -> list[str]:
    """Names the rows endpoint accepts as ``sort``: projected, orderable columns."""
    return [
        c["name"]
        for c in _projected_columns(column_info)
        if c.get("type") in _SORTABLE_TYPES
    ]


# The cursor row's sort value, read inside the page query. Quoted uppercase
# names can't collide with a projected column, which is always lowercase.
_ANCHOR_CTE = '"Anchor"'
_ANCHOR = '"Anchor"."V"'


def _sorted_keyset(col: str, *, descending: bool) -> str:
    """Predicate for rows after the cursor row in (col, gid), NULLs last.

    The cursor row's value stays in PostgreSQL and is compared in the
    column's own type; a Python round trip changes some values (a year of
    interval, second-resolution offsets, the largest dates).
    """
    op = "<" if descending else ">"
    return (
        f"gid > 0 AND ({_ANCHOR} IS NULL AND {col} IS NULL AND gid > :after_gid"
        f" OR {_ANCHOR} IS NOT NULL AND ({col} IS NULL OR {col} {op} {_ANCHOR}"
        f" OR ({col} = {_ANCHOR} AND gid > :after_gid)))"
    )


# A number's text form needn't be its label key (1e16 reads back as "1e+16",
# numeric 1.50 as "1.50"), so codes on these types compare as numbers.
_NUMBER_TYPES = {"double precision", "real", "numeric"}


def _is_number_text(code: str, col_type: str) -> bool:
    """Whether PostgreSQL reads *code* as a finite *col_type* value, so the
    cast can't fail the request."""
    try:
        exact = Decimal(code)
    except InvalidOperation:
        return False
    if "_" in code or not exact.is_finite():
        return False
    if col_type == "numeric":
        return -16383 < exact.adjusted() < 131072
    # float4in and float8in refuse overflow and a nonzero value that rounds to 0.
    number = float(exact)
    if col_type == "real" and math.isfinite(number):
        try:
            number = struct.unpack("f", struct.pack("f", number))[0]
        except OverflowError:
            return False
    return math.isfinite(number) and (number != 0 or exact == 0)


async def _label_matched_codes(
    db: AsyncSession, dataset_id: uuid.UUID, filters: dict[str, str]
) -> dict[str, list[str]]:
    """Per filtered column, the stored codes whose value label contains the term."""
    result = await db.execute(
        select(AttributeMetadata.field_name, AttributeMetadata.value_labels).where(
            AttributeMetadata.dataset_id == dataset_id,
            AttributeMetadata.is_current.is_(True),
            AttributeMetadata.field_name.in_(list(filters)),
            AttributeMetadata.value_labels.is_not(None),
        )
    )
    return {
        name: [
            code
            for code, label in labels.items()
            if isinstance(label, str) and filters[name].casefold() in label.casefold()
        ]
        for name, labels in result.all()
    }


def _build_where_filters(
    filters: dict[str, str] | None,
    column_types: dict[str, str],
    *,
    after_gid: int,
    limit: int,
    keyset: str,
    label_codes: dict[str, list[str]],
) -> tuple[str, dict[str, object]]:
    """Compose the WHERE clause + bind params for keyset pagination + ILIKE filters.

    ``keyset`` is the predicate selecting rows after ``after_gid``.
    ``label_codes`` adds, per column, rows whose stored code is in the list.
    """
    where_clauses: list[str] = [f"({keyset})"]
    bind_params: dict[str, object] = {"limit": limit, "after_gid": after_gid}
    for col_name, search_term in (filters or {}).items():
        if not SAFE_TABLE_NAME_RE.match(col_name):
            continue
        if col_name not in column_types:
            continue
        param_key = f"f_{col_name}"
        # Quoted, for the same reason as _build_select_cols.
        as_text = f"CAST({_safe_column_ref(col_name)} AS text)"
        clause = f"{as_text} ILIKE :{param_key}"
        bind_params[param_key] = f"%{search_term}%"
        if codes := label_codes.get(col_name):
            lhs, codes_ref = as_text, f"CAST(:fc_{col_name} AS text[])"
            if (col_type := column_types[col_name]) in _NUMBER_TYPES:
                codes = [code for code in codes if _is_number_text(code, col_type)]
                lhs = _safe_column_ref(col_name)
                codes_ref = f"CAST({codes_ref} AS {col_type}[])"
            clause += f" OR {lhs} = ANY({codes_ref})"
            bind_params[f"fc_{col_name}"] = codes
        where_clauses.append(f"({clause})")
    return " WHERE " + " AND ".join(where_clauses), bind_params


async def _select_rows(
    db: AsyncSession,
    table_ref: str,
    select_sql: str,
    cols: list[dict],
    *,
    filters: dict[str, str] | None,
    after_gid: int,
    limit: int,
    sort_col: str | None,
    descending: bool,
    label_codes: dict[str, list[str]],
) -> list[dict]:
    """Run the page query; a sorted page continues after the cursor row."""
    # Sorted reads keep the unsorted domain, gid > 0: a row at gid 0 or below
    # could never be a cursor, since `after` starts at 0 and can't go negative.
    keyset = "gid > :after_gid"
    order_sql = "gid"
    with_sql = join_sql = ""
    if sort_col is not None:
        direction = "DESC" if descending else "ASC"
        order_sql = f"{sort_col} {direction} NULLS LAST, gid"
        if after_gid:
            # A cursor row deleted since the last page leaves the CTE empty, so
            # the join returns an empty page.
            with_sql = (
                f'WITH {_ANCHOR_CTE} AS (SELECT {sort_col} AS "V"'
                f" FROM {table_ref} WHERE gid = :after_gid) "
            )
            join_sql = f" CROSS JOIN {_ANCHOR_CTE}"
            keyset = _sorted_keyset(sort_col, descending=descending)
    where_sql, bind_params = _build_where_filters(
        filters,
        column_types={c["name"]: c.get("type", "") for c in cols},
        after_gid=after_gid,
        limit=limit,
        keyset=keyset,
        label_codes=label_codes,
    )
    result = await db.execute(
        text(
            # codeql[py/sql-injection]
            f"{with_sql}SELECT {select_sql} FROM {table_ref}{join_sql}{where_sql} ORDER BY {order_sql} LIMIT :limit"
        ).bindparams(**bind_params)
    )
    return [
        {key: _json_safe(value) for key, value in row._mapping.items()}
        for row in result.all()
    ]


async def get_dataset_rows(
    db: AsyncSession,
    table_name: str,
    *,
    limit: int = 50,
    after_gid: int = 0,
    column_info: list[dict] | None = None,
    filters: dict[str, str] | None = None,
    sort: str | None = None,
    descending: bool = False,
    dataset_id: uuid.UUID | None = None,
) -> tuple[list[dict], int, list[dict], int | None]:
    """Fetch keyset-paginated rows from a dataset's data table.

    Returns (rows, approximate_total, column_info, next_cursor). Uses keyset
    pagination (WHERE gid > :after_gid) for constant-time page access at any
    depth. Geometry columns are excluded from SELECT to avoid transferring
    large binary data. Count uses pg_class.reltuples for O(1) estimation.

    ``filters`` is a dict of {column_name: search_term} for ILIKE filtering.
    Column names are validated against column_info to prevent injection.
    With ``dataset_id``, a filter also matches rows whose code's value label
    contains the term.

    ``sort`` orders by that column, then gid; ``after_gid`` is still the last
    row's gid, and a page after a since-deleted cursor row is empty. Raises
    InvalidSortColumn for a column not in ``sortable_columns(column_info)``.
    """
    if not SAFE_TABLE_NAME_RE.match(table_name):
        raise ValueError(f"Invalid table name: {table_name}")

    from app.core.db.tenant_schema import schema_exists, tenant_data_schema
    from app.core.db.tenant_session import current_tenant_var
    from app.modules.catalog.datasets.domain._sql_safety import _safe_table_ref

    _schema = tenant_data_schema(current_tenant_var.get())
    _table_ref = _safe_table_ref(table_name, schema=_schema)

    cols = column_info or []
    select_sql = ", ".join(_build_select_cols(cols))
    sort_col = None
    if sort is not None:
        # The identifier comes from column_info, not the request, so the SQL
        # never interpolates caller input.
        name = next((c for c in sortable_columns(cols) if c == sort), None)
        if name is None:
            raise InvalidSortColumn(sort)
        sort_col = _safe_column_ref(name)

    label_codes = (
        await _label_matched_codes(db, dataset_id, filters)
        if dataset_id is not None and filters
        else {}
    )
    try:
        rows = await _select_rows(
            db,
            _table_ref,
            select_sql,
            cols,
            filters=filters,
            after_gid=after_gid,
            limit=limit,
            sort_col=sort_col,
            descending=descending,
            label_codes=label_codes,
        )

        count_result = await db.execute(
            text(
                "SELECT reltuples::bigint FROM pg_class"
                " WHERE relname = :tbl"
                " AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = :schema)"
            ).bindparams(tbl=table_name, schema=_schema)
        )
        rel = count_result.scalar_one_or_none()
        approx_total = max(0, rel) if rel is not None else 0

        next_cursor = rows[-1]["gid"] if rows and len(rows) == limit else None
    except DBAPIError as exc:
        # Only an absent backing table degrades to an empty page. Operational
        # failures must reach the 503 handler.
        if sqlstate(exc) not in TABLE_ABSENT:
            raise
        await db.rollback()  # transaction aborted; read-only, so safe
        # A missing schema reports 42P01 too, so the code alone
        # can't tell an absent table from a never-provisioned
        # tenant schema. Only the second is drift and must not read as empty.
        if not await schema_exists(db, _schema):
            logger.error("Data schema %s does not exist", _schema)
            raise
        logger.warning("Data table %s is absent", table_name, exc_info=True)
        return [], 0, column_info or [], None

    return rows, approx_total, column_info or [], next_cursor
