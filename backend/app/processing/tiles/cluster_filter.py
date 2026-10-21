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
    if not raw:
        return None
    _parse(raw)
    canonical = json.dumps(json.loads(raw), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


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
    if not raw:
        return None
    from app.platform.extensions import get_catalog_port
    from app.standards.ogc.filtering import (
        compile_feature_cql2_ast,
        feature_queryable_columns,
    )

    ast_root = _parse(raw)
    queryables = feature_queryable_columns(
        await get_catalog_port().get_column_info(session, table_name), None
    )
    if tile_columns is not None:
        queryables = {k: v for k, v in queryables.items() if k in set(tile_columns)}
    where_sql, binds = compile_feature_cql2_ast(ast_root, queryables)
    position = {
        bind.key: FIRST_FILTER_PARAM + index for index, bind in enumerate(binds)
    }
    sql = _BIND_REF.sub(lambda m: f"${position[f'cql2_{m.group(1)}']}", where_sql)
    if ":cql2_" in sql:
        raise ValueError("cluster filter has an unmapped bind parameter")
    return ClusterFilter(sql, [bind.value for bind in binds])
