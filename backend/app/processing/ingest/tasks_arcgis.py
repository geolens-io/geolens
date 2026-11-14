"""Guarded ArcGIS paged fetch and the staged object-ID coverage check."""

import hashlib
import json
import re
from typing import Any


async def run_paged_arcgis_service_fetch(
    *,
    service_type_raw: str,
    service_type: str,
    source_url: str,
    layer_name: str,
    layer_id: "int | str | None",
    token: "str | None",
    staging_table: str,
    db_conn_str: str,
    schema: str,
    feature_count: int,
    page_size: int,
    order_field: str,
    is_non_spatial: bool = False,
    on_spawn: Any = None,
    on_page: Any = None,
    planned_ids: tuple[int, ...] | None = None,
    return_z: bool = False,
) -> None:
    """Guarded ArcGIS paging shared by initial import and refresh/reupload.

    Both doors distrust driver-side paging: a page that makes no row-count
    progress aborts rather than looping or silently stopping short.

    ``on_spawn`` is forwarded to every page's subprocess spawn (the refresh
    door's origin-contact stamp is a monotonic OR, so repeated arming is
    harmless). ``on_page`` (async, ``(imported_rows, feature_count)``) lets
    the import path publish per-page progress; pass None to skip.
    """
    from app.platform.extensions import get_processing_port
    from app.processing.ingest import ogr

    port = get_processing_port()
    imported_rows, append = 0, False
    force_arcgis_geojson = bool(planned_ids and max(planned_ids) > (1 << 31) - 1)
    if planned_ids is not None:
        planned_chunk_size = min(page_size, _ARCGIS_OBJECT_ID_FETCH_CHUNK_SIZE)

        def _fits_gdal_get_url(object_ids: tuple[int, ...]) -> bool:
            # Use the same builder as the actual import so this includes the
            # ArcGIS options and a query-form credential without exposing the
            # resulting URL in an error or log.
            page_source, _ = port.build_gdal_source(
                service_type_raw,
                source_url,
                layer_name,
                layer_id,
                token=token,
                order_field=order_field,
                result_limit=None,
                result_offset=None,
                object_ids=object_ids,
                force_arcgis_geojson=force_arcgis_geojson,
                return_z=return_z,
            )
            return len(page_source.encode("utf-8")) <= _ARCGIS_GDAL_GET_URL_MAX_BYTES

        page_specs: list[tuple[int | None, tuple[int, ...] | None]] = []
        start = 0
        while start < len(planned_ids):
            remaining = min(planned_chunk_size, len(planned_ids) - start)
            candidate = planned_ids[start : start + remaining]
            if _fits_gdal_get_url(candidate):
                page_specs.append((None, candidate))
                start += remaining
                continue

            # A count-only chunk can exceed the URL limits of proxies when
            # object IDs are long signed 64-bit values. Find the largest
            # prefix that the actual GDAL GET request can transport.
            lower, upper = 1, remaining - 1
            largest_fitting = 0
            while lower <= upper:
                midpoint = (lower + upper) // 2
                if _fits_gdal_get_url(planned_ids[start : start + midpoint]):
                    largest_fitting = midpoint
                    lower = midpoint + 1
                else:
                    upper = midpoint - 1
            if largest_fitting == 0:
                raise ogr.IngestionError(
                    "ArcGIS object-ID request exceeds the safe URL transport budget."
                )
            page_specs.append((None, planned_ids[start : start + largest_fitting]))
            start += largest_fitting
    else:
        page_specs = [(offset, None) for offset in range(0, feature_count, page_size)]
    for offset, object_ids in page_specs:
        page_source, page_layer = port.build_gdal_source(
            service_type_raw,
            source_url,
            layer_name,
            layer_id,
            token=token,
            order_field=order_field,
            result_limit=None if object_ids is not None else page_size,
            result_offset=offset,
            object_ids=object_ids,
            force_arcgis_geojson=force_arcgis_geojson,
            return_z=return_z,
        )
        await ogr.run_ogr2ogr_service(
            page_source,
            page_layer,
            staging_table,
            db_conn_str,
            service_type,
            token=token,
            is_non_spatial=is_non_spatial,
            append=append,
            schema=schema,
            on_spawn=on_spawn,
            keep_z=return_z,
        )
        next_imported_rows = await ogr.staged_row_count(staging_table, schema)
        grew = next_imported_rows - imported_rows
        if grew <= 0:
            raise ogr.IngestionError(
                "ArcGIS service import made no row-count progress "
                f"at offset {offset if offset is not None else 'ID chunk'}; upstream pagination may be "
                "unsupported or returned an empty page."
            )
        expected = (
            len(object_ids)
            if object_ids is not None
            else min(page_size, feature_count - offset)
        )
        if grew != expected:
            # Positive growth alone isn't enough: a server returning fewer
            # rows than requested while offset advances by page_size would
            # silently skip records. A mid-fetch source mutation trips this
            # too; failing is the safe direction.
            raise ogr.IngestionError(
                f"ArcGIS page at offset {offset if offset is not None else 'ID chunk'} returned {grew} rows where "
                f"{expected} were expected; the server may cap responses "
                "below its advertised page size or the source changed "
                "mid-fetch. Refusing to continue with a potentially "
                "incomplete copy."
            )
        imported_rows = next_imported_rows
        if on_page is not None:
            await on_page(imported_rows, feature_count)
        append = True


_ARCGIS_SAFE_OID_FIELD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,62}\Z")
_ARCGIS_MAX_OID = (1 << 63) - 1
# ``build_gdal_source`` bounds the query-form objectIds request to this size.
# The normal service page limit can be larger, so planned-ID fetches must not
# reuse it unchecked.
_ARCGIS_OBJECT_ID_FETCH_CHUNK_SIZE = 1_000
# Keep GET requests below common proxy limits. The source builder includes the
# driver prefix, endpoint, ArcGIS query parameters, and any query-form token.
_ARCGIS_GDAL_GET_URL_MAX_BYTES = 8 * 1024


def _arcgis_staged_oid_digest(oid_field: str, ids: list[int]) -> str:
    payload = json.dumps(
        {"oid_field": oid_field, "ids": sorted(ids)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


async def verify_arcgis_staged_oid_coverage(
    session: Any,
    *,
    schema: str,
    table_name: str,
    oid_field: str,
    planned_ids: tuple[int, ...],
) -> dict[str, Any]:
    """Compare staged source OIDs with one bounded, preplanned ArcGIS set.

    The `gid` primary key is GeoLens-local (`-lco FID=gid`) and must never be
    treated as upstream identity. This returns compact evidence; raw source
    IDs remain only in worker memory.
    """
    from sqlalchemy import text

    from app.processing.ingest.metadata import _qtable, get_column_info

    if not _ARCGIS_SAFE_OID_FIELD.fullmatch(oid_field):
        return {
            "status": "unavailable",
            "reason": "unsupported_oid_field",
            "oid_field": oid_field,
        }
    columns = await get_column_info(session, table_name, schema=schema)
    matching_columns = [
        column["name"]
        for column in columns
        if isinstance(column.get("name"), str)
        and column["name"].casefold() == oid_field.casefold()
    ]
    if len(matching_columns) != 1:
        return {
            "status": "unavailable",
            "reason": "source_oid_not_preserved",
            "oid_field": oid_field,
        }

    # The identifier is constrained above; table/schema use the existing
    # catalog table validator. The limit detects an ignored objectIds filter
    # without materializing an unbounded source response in worker memory.
    safe_oid_field = matching_columns[0]
    query = (
        f'SELECT "{safe_oid_field}", COUNT(*) '
        f"FROM {_qtable(table_name, schema=schema)} "
        f'GROUP BY "{safe_oid_field}" '
        f"LIMIT {len(planned_ids) + 1}"
    )
    result = await session.execute(
        # codeql[py/sql-injection]
        text(query)
    )
    rows = result.all()
    if len(rows) > len(planned_ids):
        return {
            "status": "mismatched",
            "reason": "unexpected_source_oid_cardinality",
            "oid_field": oid_field,
            "planned_count": len(planned_ids),
            "staged_distinct_count": len(rows),
        }

    staged_ids: list[int] = []
    duplicate_count = 0
    invalid_count = 0
    for source_id, occurrences in rows:
        if (
            isinstance(source_id, bool)
            or not isinstance(source_id, int)
            or source_id < 0
            or source_id > _ARCGIS_MAX_OID
        ):
            invalid_count += int(occurrences)
            continue
        staged_ids.append(source_id)
        if occurrences > 1:
            duplicate_count += int(occurrences) - 1

    planned = set(planned_ids)
    staged = set(staged_ids)
    missing_count = len(planned - staged)
    unexpected_count = len(staged - planned)
    status = (
        "matched"
        if not invalid_count
        and not duplicate_count
        and not missing_count
        and not unexpected_count
        else "mismatched"
    )
    return {
        "status": status,
        "oid_field": oid_field,
        "planned_count": len(planned_ids),
        "staged_distinct_count": len(staged),
        "missing_count": missing_count,
        "unexpected_count": unexpected_count,
        "duplicate_count": duplicate_count,
        "invalid_count": invalid_count,
        "staged_id_set_digest": _arcgis_staged_oid_digest(oid_field, staged_ids),
    }
