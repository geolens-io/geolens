"""Column-level statistics and distinct value queries for dataset tables."""

import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]*$", re.IGNORECASE)

# Postgres data_type values (from information_schema.columns) on which the
# numeric MIN/MAX/AVG/percentile/stddev aggregation is valid. Anything else
# (text, varchar, uuid, bool, etc.) is treated categorically so a stats request
# on a text column returns a valid response instead of a 500.
_NUMERIC_TYPES = {
    "smallint",
    "integer",
    "bigint",
    "decimal",
    "numeric",
    "real",
    "double precision",
    "money",
}


def _validate_identifier(name: str, label: str) -> None:
    """Validate a SQL identifier to prevent injection.

    Raises ValueError if the name contains invalid characters.
    """
    if not _IDENTIFIER_RE.match(name):
        raise ValueError(f"Invalid {label}: {name!r}")


def _current_data_schema() -> str:
    """Resolve the active physical schema (``data`` in single-tenant mode)."""
    from app.core.db.tenant_schema import tenant_data_schema
    from app.core.db.tenant_session import current_tenant_var

    return tenant_data_schema(current_tenant_var.get())


def _qtable(table_name: str, *, schema: str | None = None) -> str:
    """Return a validated, quoted physical table identifier."""
    _validate_identifier(table_name, "table name")
    resolved_schema = schema or _current_data_schema()
    _validate_identifier(resolved_schema, "schema name")
    return f'"{resolved_schema}"."{table_name}"'


def _sql_quote_ident(name: str) -> str:
    """Return a safely double-quoted SQL identifier."""
    return '"' + name.replace('"', '""') + '"'


async def get_distinct_values(
    session: AsyncSession,
    table_name: str,
    column_name: str,
    limit: int = 100,
    *,
    allowed_tables: set[str] | None = None,
) -> list:
    """Return distinct non-null values for a column, preserving native types.

    Numeric and boolean values are returned in their native Python types so
    that MapLibre match expressions do strict-type comparisons correctly.
    Text values remain strings.
    """
    _validate_identifier(table_name, "table name")
    _validate_identifier(column_name, "column name")
    if allowed_tables is not None and table_name not in allowed_tables:
        raise PermissionError(f"Access denied to table: {table_name!r}")

    table_ref = _qtable(table_name)
    # fix(#458 E-33): quote the (already regex-validated) identifier so
    # reserved-word column names (desc, order, user) don't 500 the query;
    # get_column_stats/get_column_null_cardinality below already quote.
    col_q = _sql_quote_ident(column_name)

    sql = text(
        f"SELECT DISTINCT {col_q} AS val "
        f"FROM {table_ref} "
        f"WHERE {col_q} IS NOT NULL "
        f"ORDER BY val LIMIT :limit"
    ).bindparams(limit=limit)

    result = await session.execute(sql)
    return [row[0] for row in result.all()]


async def get_column_null_cardinality(
    session: AsyncSession,
    table_name: str,
    columns: list[str],
    *,
    allowed_tables: set[str] | None = None,
    max_columns: int = 20,
    sample_size: int = 10000,
) -> dict[str, dict]:
    """Return null-count and distinct-count estimates per column.

    Used to enrich AI metadata generation context so the LLM can comment
    accurately on completeness and value variety. Computed on-demand via
    one query that scans (or samples) the table once.

    For tables larger than ``sample_size`` rows, TABLESAMPLE BERNOULLI is
    used to bound query cost; the returned counts are approximate
    extrapolations from the sample. Small tables get exact counts.

    Returns:
        Dict mapping column_name to {"null_count": int, "distinct_count": int,
        "total_count": int, "approximate": bool}. Columns absent from the
        live table or exceeding max_columns are silently skipped.
    """
    _validate_identifier(table_name, "table name")
    if allowed_tables is not None and table_name not in allowed_tables:
        raise PermissionError(f"Access denied to table: {table_name!r}")

    schema = _current_data_schema()

    # Filter columns down to identifier-safe + live-in-table to avoid
    # producing query failures on bogus inputs.
    live_result = await session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :t"
        ).bindparams(schema=schema, t=table_name)
    )
    live_columns = {row[0] for row in live_result.all()}
    candidates: list[tuple[str, str]] = []
    for col in columns:
        if not col or col not in live_columns:
            continue
        try:
            _validate_identifier(col, "column name")
        except ValueError:
            continue
        candidates.append((col, _sql_quote_ident(col)))
        if len(candidates) >= max_columns:
            break

    if not candidates:
        return {}

    # Decide between full scan (small tables) and sampling (large tables).
    # pg_class.reltuples is autovacuum-maintained and "good enough" for
    # the size decision.
    size_q = await session.execute(
        text(
            "SELECT reltuples::bigint FROM pg_class "
            "WHERE relname = :t AND relnamespace = "
            "(SELECT oid FROM pg_namespace WHERE nspname = :schema)"
        ).bindparams(t=table_name, schema=schema)
    )
    est_rows = size_q.scalar_one_or_none() or 0
    approximate = est_rows > sample_size

    if approximate:
        # Sample ~sample_size rows via TABLESAMPLE BERNOULLI(pct).
        pct = max(0.1, min(100.0, 100.0 * sample_size / max(est_rows, 1)))
        from_clause = (
            f"{_qtable(table_name, schema=schema)} TABLESAMPLE BERNOULLI ({pct})"
        )
    else:
        from_clause = _qtable(table_name, schema=schema)

    # Build SELECT clause: total + per-column not-null + per-column distinct.
    parts = ["COUNT(*) AS _total"]
    for idx, (_, quoted) in enumerate(candidates):
        parts.append(f"COUNT({quoted}) AS _nn_{idx}")
        parts.append(f"COUNT(DISTINCT {quoted}) AS _dc_{idx}")

    query = f"SELECT {', '.join(parts)} FROM {from_clause}"
    row = (await session.execute(text(query))).one()
    sampled_total = int(row[0]) if row[0] is not None else 0
    out: dict[str, dict] = {}
    for idx, (col_name, _) in enumerate(candidates):
        nn = int(row[1 + idx * 2]) if row[1 + idx * 2] is not None else 0
        dc = int(row[2 + idx * 2]) if row[2 + idx * 2] is not None else 0
        if approximate and sampled_total > 0:
            # Extrapolate null count to the full table; cardinality is a
            # SAMPLE distinct count and stays as-is (it under-estimates
            # for high-cardinality columns, which the LLM should be told).
            ratio = est_rows / sampled_total
            null_count = int(round((sampled_total - nn) * ratio))
            total = est_rows
        else:
            null_count = sampled_total - nn
            total = sampled_total
        out[col_name] = {
            "null_count": null_count,
            "distinct_count": dc,
            "total_count": total,
            "approximate": approximate,
        }
    return out


async def get_column_stats(
    session: AsyncSession,
    table_name: str,
    column_name: str,
    *,
    class_count: int = 5,
    allowed_tables: set[str] | None = None,
) -> dict:
    """Return min, max, count, mean, and quantiles for a numeric column.

    Args:
        class_count: Number of classification classes. Quantile fractions are
            computed dynamically as [1/n, 2/n, ..., (n-1)/n] so that the
            returned ``quantiles`` list always has exactly ``class_count - 1``
            entries regardless of the requested class count.
    """
    _validate_identifier(table_name, "table name")
    _validate_identifier(column_name, "column name")
    if allowed_tables is not None and table_name not in allowed_tables:
        raise PermissionError(f"Access denied to table: {table_name!r}")

    schema = _current_data_schema()

    # Detect the column's data type so we never cast a text column ::numeric
    # (which raises a DataError -> 500). Reuses the information_schema lookup
    # pattern from get_column_null_cardinality.
    type_result = await session.execute(
        text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :t "
            "AND column_name = :c"
        ).bindparams(schema=schema, t=table_name, c=column_name)
    )
    data_type = type_result.scalar_one_or_none()
    if data_type is None:
        raise ValueError(f"Column not found: {column_name!r}")

    col_q = _sql_quote_ident(column_name)
    tbl_q = _qtable(table_name, schema=schema)

    if data_type not in _NUMERIC_TYPES:
        # Non-numeric column: numeric aggregates are undefined, so return a
        # categorical summary (row count + distinct count) instead of casting
        # to ::numeric. Numeric fields are null/empty.
        cat_sql = text(
            f"SELECT COUNT({col_q}), COUNT(DISTINCT {col_q}) "
            f"FROM {tbl_q} "
            f"WHERE {col_q} IS NOT NULL"
        )
        cat_row = (await session.execute(cat_sql)).one()
        return {
            "min": None,
            "max": None,
            "count": int(cat_row[0]) if cat_row[0] is not None else 0,
            "mean": None,
            "quantiles": [],
            "stddev": None,
            "data_type": "categorical",
            "distinct_count": int(cat_row[1]) if cat_row[1] is not None else 0,
        }

    # Compute quantile fractions dynamically based on class_count
    fractions = [round(i / class_count, 4) for i in range(1, class_count)]
    fractions_str = ", ".join(str(f) for f in fractions)

    # Combined stats + quantiles in a single query (single table scan)
    combined_sql = text(
        f"SELECT MIN({col_q}::numeric), MAX({col_q}::numeric), "
        f"COUNT({col_q}), AVG({col_q}::numeric), "
        f"percentile_cont(ARRAY[{fractions_str}]) "
        f"WITHIN GROUP (ORDER BY {col_q}::numeric), "
        f"stddev_samp({col_q}::numeric) "
        f"FROM {tbl_q} "
        f"WHERE {col_q} IS NOT NULL"
    )
    result = await session.execute(combined_sql)
    row = result.one()

    return {
        "min": float(row[0]) if row[0] is not None else None,
        "max": float(row[1]) if row[1] is not None else None,
        "count": int(row[2]) if row[2] is not None else 0,
        "mean": float(row[3]) if row[3] is not None else None,
        "quantiles": [float(v) for v in row[4]] if row[4] is not None else [],
        "stddev": float(row[5]) if row[5] is not None else None,
    }
