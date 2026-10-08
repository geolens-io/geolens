"""Layer filters for the materialize worker.

The router validated each filter at enqueue against the live columns, but a
re-upload during the queue wait can drop a column a filter reads. The worker
therefore compiles each filter again against the table it is about to read,
with the same CQL2 parser and whitelist the OGC items ``filter`` uses.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.analysis_sql import render_filtered_table_ref


async def narrow_to_layer_filter(
    session: AsyncSession,
    schema: str,
    layer: tuple[str, str],
    *,
    cql2: dict[str, Any] | None,
    label: str,
    binds: list[Any],
    has_geometry: bool = True,
) -> str:
    """``layer``'s table ref narrowed to the features ``cql2`` keeps.

    ``layer`` is ``(table_ref, table_name)``. The compiled filter's bind
    parameters are appended to ``binds``. Raises ValueError, naming the layer,
    when the filter no longer fits the table's columns.
    """
    table_ref, table_name = layer
    if cql2 is None:
        return table_ref
    from fastapi import HTTPException

    from app.processing.ingest.metadata import get_column_info
    from app.standards.ogc.filtering import (
        compile_feature_cql2_ast,
        feature_queryable_columns,
        parse_feature_cql2,
    )

    try:
        filter_expr = json.dumps(cql2, ensure_ascii=False, separators=(",", ":"))
        ast_root = parse_feature_cql2(filter_expr, "cql2-json")
        live_columns = await get_column_info(session, table_name, schema=schema)
        queryables = feature_queryable_columns(
            live_columns, "geometry" if has_geometry else None
        )
        where_sql, layer_binds = compile_feature_cql2_ast(
            ast_root, queryables, bind_prefix=f"{label}_filter"
        )
    except (HTTPException, RecursionError) as exc:
        detail = getattr(exc, "detail", "the filter nests too deeply")
        raise ValueError(
            f"The {label} layer's filter can't be applied: {detail}. The layer "
            "may have been re-uploaded since this analysis was queued."
        ) from exc
    binds.extend(layer_binds)
    return render_filtered_table_ref(table_ref, where_sql)


async def narrow_analysis_inputs(
    session: AsyncSession,
    schema: str,
    *,
    source: tuple[str, str, bool],
    mask: tuple[str | None, str | None],
    join: tuple[str | None, str | None],
    filters: tuple[dict[str, Any] | None, ...],
) -> tuple[str, str | None, str | None, list[Any]]:
    """Every input ref narrowed by its layer filter, plus the binds they name.

    ``source`` is ``(table_ref, table_name, has_geometry)``; ``mask`` and
    ``join`` are ``(table_ref, table_name)``, both None when the operation
    reads no such layer, and are known to have geometry. ``filters`` holds the
    source, mask and join filters in that order.
    """
    source_filter, mask_filter, join_filter = filters
    binds: list[Any] = []
    src_ref = await narrow_to_layer_filter(
        session,
        schema,
        source[:2],
        cql2=source_filter,
        label="source",
        binds=binds,
        has_geometry=source[2],
    )
    narrowed: list[str | None] = []
    for (table_ref, table_name), cql2, label in (
        (mask, mask_filter, "mask"),
        (join, join_filter, "join"),
    ):
        if table_ref is None or table_name is None:
            narrowed.append(table_ref)
            continue
        narrowed.append(
            await narrow_to_layer_filter(
                session,
                schema,
                (table_ref, table_name),
                cql2=cql2,
                label=label,
                binds=binds,
            )
        )
    return src_ref, narrowed[0], narrowed[1], binds
