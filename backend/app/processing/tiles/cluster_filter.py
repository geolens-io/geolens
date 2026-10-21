"""A layer filter for the server-side cluster tile query.

The filter uses the CQL2 parser and column whitelist the OGC items ``filter``
uses, so it reads only live attribute columns and carries every value as a bind.
"""

import hashlib
import json
import re
from typing import Any, NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

# $1-$6 belong to the cluster query itself.
FIRST_FILTER_PARAM = 7
_BIND_REF = re.compile(r"(?<!:):cql2_(\d+)\b")


class ClusterFilter(NamedTuple):
    """The WHERE fragment (values as ``$7`` and up) and their values."""

    sql: str
    params: list[Any]


def refuse_type_fault(exc: Exception) -> None:
    """Raise HTTP 400 when the database refused the filter's types or values."""
    from fastapi import HTTPException, status

    from app.core.db.sqlstate import TYPE_FAULT_SQLSTATES

    code = getattr(exc, "sqlstate", None) or ""
    if code.startswith("22") or code in TYPE_FAULT_SQLSTATES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The filter is not evaluable against this dataset's columns",
        ) from exc


def _parse(raw: str) -> Any:
    from app.standards.ogc.filtering import parse_feature_cql2

    return parse_feature_cql2(raw, "cql2-json")


def validated_digest(raw: str | None) -> str | None:
    """A cache-key digest of ``raw`` that ignores key order and spacing.

    None when there is no filter. HTTP 400 when ``raw`` does not parse.
    """
    if raw is None:
        return None
    _parse(raw)
    canonical = json.dumps(json.loads(raw), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_OFFSET = re.compile(r"(Z|[+-]\d\d(:?\d\d)?)$")
_COMPARISONS = {"=", "<>", "<", ">", "<=", ">="}


def _typed_literal(value: Any, pg_type: str) -> Any:
    if not isinstance(value, str):
        return value
    if pg_type == "date":
        return {"date": value} if _DATE.fullmatch(value) else value
    stamp = value.strip().replace(" ", "T", 1)
    if "T" not in stamp:
        stamp += "T00:00:00"
    if pg_type == "timestamp with time zone" and not _OFFSET.search(stamp):
        stamp += "Z"
    return {"timestamp": stamp}


def _type_temporal_literals(node: Any, types: dict[str, str]) -> Any:
    """Wrap plain string literals compared with date/timestamp columns, as CQL2 requires.

    A client that does not know the column types sends dates as plain strings.
    """
    if isinstance(node, list):
        return [_type_temporal_literals(child, types) for child in node]
    if not isinstance(node, dict):
        return node
    out = {k: _type_temporal_literals(v, types) for k, v in node.items()}
    args = out.get("args")
    if (
        out.get("op") in _COMPARISONS
        and isinstance(args, list)
        and len(args) == 2
        and not (isinstance(args[0], dict) and "property" in args[0])
        and isinstance(args[1], dict)
        and "property" in args[1]
    ):
        out["args"] = _type_temporal_literals({**out, "args": args[::-1]}, types)[
            "args"
        ][::-1]
        return out
    if not isinstance(args, list) or not args or not isinstance(args[0], dict):
        return out
    pg_type = types.get(args[0].get("property"), "")
    if not (pg_type == "date" or pg_type.startswith("timestamp")):
        return out
    if out.get("op") in _COMPARISONS | {"between"}:
        out["args"] = [args[0]] + [_typed_literal(a, pg_type) for a in args[1:]]

    elif out.get("op") == "in" and len(args) == 2 and isinstance(args[1], list):
        out["args"] = [args[0], [_typed_literal(a, pg_type) for a in args[1]]]
    return out


async def compile_filter(
    session: AsyncSession,
    table_name: str,
    raw: str | None,
    tile_columns: list[str] | None,
) -> ClusterFilter | None:
    """Compile ``raw`` against the table's live columns; HTTP 400 when it can't apply.

    Geometry predicates are not queryable here: the cluster tile query filters
    attributes only. A dataset that limits its tile attributes to ``tile_columns``
    exposes only those columns to filters too (``[]`` exposes none).
    """
    if raw is None:
        return None
    from app.platform.extensions import get_catalog_port
    from app.standards.ogc.filtering import (
        compile_feature_cql2_ast,
        feature_queryable_columns,
    )

    queryables = feature_queryable_columns(
        await get_catalog_port().get_column_info(session, table_name), None
    )
    if tile_columns is not None:
        queryables = {k: v for k, v in queryables.items() if k in set(tile_columns)}
    typed = _type_temporal_literals(json.loads(raw), queryables)
    where_sql, binds = compile_feature_cql2_ast(_parse(json.dumps(typed)), queryables)
    position = {
        bind.key: FIRST_FILTER_PARAM + index for index, bind in enumerate(binds)
    }
    sql = _BIND_REF.sub(lambda m: f"${position[f'cql2_{m.group(1)}']}", where_sql)
    if ":cql2_" in sql:
        raise ValueError("cluster filter has an unmapped bind parameter")
    return ClusterFilter(sql, [bind.value for bind in binds])
