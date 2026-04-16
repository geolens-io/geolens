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

    # Basic aggregate stats
    agg_sql = text(
        f"SELECT MIN({column_name}::numeric), MAX({column_name}::numeric), "
        f"COUNT({column_name}), AVG({column_name}::numeric) "
        f"FROM data.{table_name} "
        f"WHERE {column_name} IS NOT NULL"
    )
    agg_result = await session.execute(agg_sql)
    agg_row = agg_result.one()

    # Compute quantile fractions dynamically based on class_count
    fractions = [round(i / class_count, 4) for i in range(1, class_count)]
    fractions_str = ", ".join(str(f) for f in fractions)

    q_sql = text(
        f"SELECT percentile_cont(ARRAY[{fractions_str}]) "
        f"WITHIN GROUP (ORDER BY {column_name}::numeric) "
        f"FROM data.{table_name} "
        f"WHERE {column_name} IS NOT NULL"
    )
    q_result = await session.execute(q_sql)
    q_row = q_result.one()

    return {
        "min": float(agg_row[0]) if agg_row[0] is not None else None,
        "max": float(agg_row[1]) if agg_row[1] is not None else None,
        "count": int(agg_row[2]) if agg_row[2] is not None else 0,
        "mean": float(agg_row[3]) if agg_row[3] is not None else None,
        "quantiles": [float(v) for v in q_row[0]] if q_row[0] is not None else [],
    }
