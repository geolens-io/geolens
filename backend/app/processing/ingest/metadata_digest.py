"""Deterministic content digests for staged vector tables."""

import hashlib

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.processing.ingest.metadata_sql import _qtable


async def compute_table_content_digest(
    session: AsyncSession,
    table_name: str,
    *,
    schema: str,
    has_geometry: bool,
) -> str:
    """Hash staged feature contents without depending on row order or generated IDs."""
    table = _qtable(table_name, schema=schema)

    await session.execute(
        text(
            """
            SELECT
                set_config('TimeZone', 'UTC', true),
                set_config('DateStyle', 'ISO, YMD', true),
                set_config('IntervalStyle', 'iso_8601', true),
                set_config('bytea_output', 'hex', true),
                set_config('extra_float_digits', '3', true)
            """
        )
    )

    # Keep the staged rows unchanged between the digest and publication.
    # codeql[py/sql-injection]
    await session.execute(text(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE"))

    geometry_values = (
        ", encode(ST_AsEWKB(geom, 'XDR'), 'hex'), "
        "encode(ST_AsEWKB(geom_4326, 'XDR'), 'hex')"
        if has_geometry
        else ""
    )
    payload = (
        "jsonb_build_array("
        "to_jsonb(staged) - 'gid' - 'geom' - 'geom_4326'"
        f"{geometry_values})"
    )

    # ``gid`` is assigned during ingest. Fixed-endian EWKB preserves the complete
    # geometry while allowing otherwise identical rows to arrive in any order.
    # codeql[py/sql-injection]
    statement = text(
        f"""
        SELECT sha256(convert_to(({payload})::text, 'UTF8')) AS row_digest
        FROM {table} AS staged
        ORDER BY row_digest
        """
    ).execution_options(yield_per=1000)

    digest = hashlib.sha256()
    digest.update(b"geolens-staged-content-v1\0")
    digest.update(b"spatial\0" if has_geometry else b"nonspatial\0")
    result = await session.stream(statement)
    try:
        async for row_digest in result.scalars():
            digest.update(bytes(row_digest))
    finally:
        await result.close()
    return digest.hexdigest()
