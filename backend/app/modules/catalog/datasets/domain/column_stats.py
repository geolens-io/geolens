"""Column-level statistics and distinct value queries for dataset tables."""

import math
import re
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.timestamptz_text import utc_timestamptz_text

_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]*$", re.IGNORECASE)

# information_schema.columns data_type values eligible for numeric
# aggregation; anything else is treated categorically so a stats request on
# a text column returns a valid response instead of a 500.
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

# Types whose driver value already serializes as a JSON string, boolean or
# number; every other type is returned as text.
_NATIVE_VALUE_TYPES = {
    "smallint",
    "integer",
    "bigint",
    "real",
    "double precision",
    "boolean",
    "text",
    "character varying",
    "character",
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
    """Return a safely double-quoted SQL identifier for use inside text().

    Colons are backslash-escaped because SQLAlchemy ``text()``
    parses ``:name`` as a bind parameter even inside double-quoted
    identifiers. Only valid inside ``text()``.
    """
    return '"' + name.replace('"', '""').replace(":", "\\:") + '"'


def _json_number(value):
    """Decimal as a float, or as text when a float can't carry it (NaN, 1e309)."""
    if isinstance(value, Decimal):
        number = float(value)
        return number if math.isfinite(number) else str(value)
    return value


def value_expr(col_q: str, data_type: str) -> str:
    """Render a column so its driver value serializes as JSON.

    ``data_type`` is the column's ``information_schema`` type; a type outside
    the native and numeric sets is returned as text, and a ``timestamptz`` in
    the UTC form vector tiles carry.
    """
    data_type = data_type.lower()
    if data_type == "timestamp with time zone":
        return utc_timestamptz_text(col_q)
    if (
        data_type
        and data_type not in _NATIVE_VALUE_TYPES
        and data_type not in _NUMERIC_TYPES - {"money"}
    ):
        return f"{col_q}::text"
    return col_q


def group_key_sql(col_q: str, data_type: str) -> tuple[str, str]:
    """What a column groups on, and its returned key over the grouped ``_g._k``.

    A timestamptz groups on its value and is written afterwards in UTC text
    with the full year, since the tile text folds every year past 9999 into
    ``infinity``. Other types group on their JSON-ready form.
    """
    if data_type != "timestamp with time zone":
        return value_expr(col_q, data_type), "_g._k"
    utc = "(_g._k AT TIME ZONE 'UTC')"
    far_future = (
        f"to_char({utc}, 'YYYY-MM-DD\"T\"HH24:MI:SS')"
        f" || rtrim(rtrim(to_char({utc}, '.US'), '0'), '.') || '+00:00'"
    )
    return col_q, (
        f"CASE WHEN isfinite(_g._k) AND {utc} >= '10000-01-01' THEN {far_future}"
        f" ELSE {utc_timestamptz_text('_g._k')} END"
    )


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
    Text values remain strings. ``numeric`` values are floats unless a float
    can't carry them. Every other type is returned as text; a ``timestamptz``
    uses the UTC form vector tiles carry.
    """
    _validate_identifier(table_name, "table name")
    _validate_identifier(column_name, "column name")
    if allowed_tables is not None and table_name not in allowed_tables:
        raise PermissionError(f"Access denied to table: {table_name!r}")

    table_ref = _qtable(table_name)
    # Quote so a reserved-word column name (desc, order,
    # user) doesn't 500 the query.
    col_q = _sql_quote_ident(column_name)

    type_result = await session.execute(
        text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :t "
            "AND column_name = :c"
        ).bindparams(schema=_current_data_schema(), t=table_name, c=column_name)
    )
    group, key = group_key_sql(col_q, type_result.scalar_one_or_none() or "")

    sql = text(
        # codeql[py/sql-injection]
        f"SELECT {key} AS val FROM ("
        f"SELECT DISTINCT {group} AS _k "
        f"FROM {table_ref} "
        f"WHERE {col_q} IS NOT NULL "
        f"ORDER BY _k LIMIT :limit"
        f") AS _g ORDER BY _g._k"
    ).bindparams(limit=limit)

    result = await session.execute(sql)
    return [_json_number(row[0]) for row in result.all()]


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

    Computed in one query that scans (or, for tables over ``sample_size``
    rows, TABLESAMPLE BERNOULLI-samples) the table once; sampled tables get
    approximate/extrapolated counts.

    Returns:
        Dict mapping column_name to {"null_count": int, "distinct_count": int,
        "total_count": int, "approximate": bool}. Columns absent from the
        live table or exceeding max_columns are silently skipped.
    """
    _validate_identifier(table_name, "table name")
    if allowed_tables is not None and table_name not in allowed_tables:
        raise PermissionError(f"Access denied to table: {table_name!r}")

    schema = _current_data_schema()

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

    # pg_class.reltuples (autovacuum-maintained) decides scan vs sample.
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
        pct = max(0.1, min(100.0, 100.0 * sample_size / max(est_rows, 1)))
        from_clause = (
            f"{_qtable(table_name, schema=schema)} TABLESAMPLE BERNOULLI ({pct})"
        )
    else:
        from_clause = _qtable(table_name, schema=schema)

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
            # distinct_count stays a sample count -- under-estimates
            # high-cardinality columns; null_count is extrapolated.
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
        class_count: quantile fractions are [1/n, ..., (n-1)/n], so
            ``quantiles`` always has exactly class_count - 1 entries.
    """
    _validate_identifier(table_name, "table name")
    _validate_identifier(column_name, "column name")
    if allowed_tables is not None and table_name not in allowed_tables:
        raise PermissionError(f"Access denied to table: {table_name!r}")

    schema = _current_data_schema()

    # Never cast a text column ::numeric -- that raises DataError -> 500.
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
        # Non-numeric: return a categorical summary instead of casting.
        cat_sql = text(
            # codeql[py/sql-injection] column passed _validate_identifier and is quoted by _sql_quote_ident; table via _qtable
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

    fractions = [round(i / class_count, 4) for i in range(1, class_count)]
    fractions_str = ", ".join(str(f) for f in fractions)

    combined_sql = text(
        # codeql[py/sql-injection] column passed _validate_identifier and is quoted by _sql_quote_ident; table via _qtable; fractions are computed from an int
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
