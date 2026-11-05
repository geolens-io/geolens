"""SQL for the aggregate endpoint's feature list and date buckets.

The builders take column references already checked against the live table
and quoted; bucket names and directions come from validated literals.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Sequence

from app.modules.catalog.datasets.domain.service import nulls_last_keyset

_INT8_MIN, _INT8_MAX = -(2**63), 2**63 - 1
AFTER_GID_BIND = "agg_after_gid"
# The envelope to 6 decimals, as the feature GeoJSON routes write coordinates.
_BBOX = (
    "CASE WHEN NOT ST_IsEmpty(_t.geom_4326) THEN ARRAY["
    + ", ".join(
        f"round(ST_{edge}(_t.geom_4326)::numeric, 6)::float8"
        for edge in ("XMin", "YMin", "XMax", "YMax")
    )
    + "] END"
)

# Each date type as a timestamp of its UTC wall clock, for date_trunc.
_UTC_WALL_CLOCK = {
    "timestamp with time zone": "({} AT TIME ZONE 'UTC')",
    "timestamp without time zone": "{}",
    "date": "{}::timestamp",
}
DATE_TYPES = frozenset(_UTC_WALL_CLOCK)


def bucket_sql(column: str, data_type: str, bucket: str) -> tuple[str, str]:
    """What a date bucket groups on, and its returned key over the grouped ``_g._k``.

    A bucket is the UTC start of its day, Monday-first week, month or year.
    Its key is ISO 8601 UTC text, such as ``2026-03-01T00:00:00Z``, with
    ISO 8601's signed astronomical year before year 1.
    """
    start = f"date_trunc('{bucket}', {_UTC_WALL_CLOCK[data_type].format(column)})"
    k = "_g._k"
    text = '\'-MM-DD"T"HH24:MI:SS"Z"\''
    return start, (
        f"CASE WHEN NOT isfinite({k}) THEN {k}::text"
        f" WHEN {k} < '0001-01-01' THEN"
        f" CASE WHEN extract(year FROM {k}) < -1 THEN '-' ELSE '' END"
        f" || lpad((-1 - extract(year FROM {k})::int)::text, 4, '0')"
        f" || to_char({k}, {text})"
        f" ELSE to_char({k}, 'YYYY' || {text}) END"
    )


def encode_cursor(gid: int, sort_column: str | None, sort: str) -> str:
    raw = json.dumps([gid, sort_column, sort], separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str, sort_column: str | None, sort: str) -> int:
    """The gid of the row a cursor continues after.

    Raises ValueError for text that is not a cursor issued for this order.
    """
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        gid, column, direction = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise ValueError("not a cursor") from exc
    if type(gid) is not int or not _INT8_MIN <= gid <= _INT8_MAX:
        raise ValueError("not a cursor")
    if column != sort_column or direction != sort:
        raise ValueError("cursor is for another order")
    return gid


def rows_sql(
    source: str,
    predicates: Sequence[str],
    values: Sequence[str],
    *,
    sort: str | None,
    descending: bool,
    paged: bool,
    limit: int,
    with_bbox: bool,
) -> str:
    """One page of rows from ``source AS _t``, plus one to show whether more follow.

    Rows order by ``sort`` with NULLs last, then by gid; without ``sort``, by
    gid in the given direction. A ``paged`` query continues after the row
    whose gid binds as ``AFTER_GID_BIND``, reading that row's sort value
    inside the query; once the row is deleted or filtered out, the page is
    empty. With ``with_bbox``, each row ends with its envelope.
    """
    direction = "DESC" if descending else "ASC"
    after = f"CAST(:{AFTER_GID_BIND} AS bigint)"
    preds = list(predicates)
    head = join = ""
    if sort is None:
        order = f"_t.gid {direction}"
        if paged:
            preds.append(f"_t.gid {'<' if descending else '>'} {after}")
    else:
        order = f"{sort} {direction} NULLS LAST, _t.gid"
        if paged:
            head = (
                f"WITH _a AS (SELECT {sort} AS v FROM {source} AS _t"
                f" WHERE _t.gid = {after}) "
            )
            join = " CROSS JOIN _a"
            preds.append(
                nulls_last_keyset(sort, "_a.v", "_t.gid", after, descending=descending)
            )
    selects = ["_t.gid", *values]
    if with_bbox:
        selects.append(_BBOX)
    where = f" WHERE {' AND '.join(preds)}" if preds else ""
    return (
        f"{head}SELECT {', '.join(selects)} FROM {source} AS _t{join}{where}"
        f" ORDER BY {order} LIMIT {limit + 1}"
    )
