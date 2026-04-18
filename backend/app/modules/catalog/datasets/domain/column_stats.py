"""Column-level statistics and distinct value queries for dataset tables."""

import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]*$", re.IGNORECASE)


def _validate_identifier(name: str, label: str) -> None:
    """Validate a SQL identifier to prevent injection.

    Raises ValueError if the name contains invalid characters.
    """
    if not _IDENTIFIER_RE.match(name):
        raise ValueError(f"Invalid {label}: {name!r}")


def _qtable(table_name: str) -> str:
    """Return quoted 'data.table_name' identifier after validation."""
    _validate_identifier(table_name, "table name")
    return f'"data"."{table_name}"'


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

    sql = text(
        f"SELECT DISTINCT {column_name} AS val "
        f"FROM data.{table_name} "
        f"WHERE {column_name} IS NOT NULL "
        f"ORDER BY val LIMIT :limit"
    ).bindparams(limit=limit)

    result = await session.execute(sql)
    return [row[0] for row in result.all()]


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

    # Compute quantile fractions dynamically based on class_count
    fractions = [round(i / class_count, 4) for i in range(1, class_count)]
    fractions_str = ", ".join(str(f) for f in fractions)

    # Combined stats + quantiles in a single query (single table scan)
    col_q = _sql_quote_ident(column_name)
    tbl_q = _qtable(table_name)
    combined_sql = text(
        f"SELECT MIN({col_q}::numeric), MAX({col_q}::numeric), "
        f"COUNT({col_q}), AVG({col_q}::numeric), "
        f"percentile_cont(ARRAY[{fractions_str}]) "
        f"WITHIN GROUP (ORDER BY {col_q}::numeric) "
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
    }
