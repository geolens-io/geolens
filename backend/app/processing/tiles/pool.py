"""Dedicated asyncpg connection pool for tile queries.

Separate from the SQLAlchemy engine pool to prevent tile traffic
from starving API CRUD operations.
"""

import asyncpg
import structlog

from app.core.config import settings

logger = structlog.stdlib.get_logger(__name__)

_tile_pool: asyncpg.Pool | None = None


def _parse_dsn() -> str:
    """Convert SQLAlchemy-style URL to asyncpg-compatible DSN."""
    url = settings.database_url
    # Strip SQLAlchemy driver prefix
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    return url


def _get_ssl_arg():
    """Extract SSL setting compatible with asyncpg from database_connect_args."""
    ssl_val = settings.database_connect_args.get("ssl")
    # asyncpg doesn't accept the string "prefer" -- pass None to let it negotiate
    if ssl_val == "prefer":
        return None
    return ssl_val


async def _setup_tile_connection(conn: asyncpg.Connection) -> None:
    """Drop tile connections to the read-only ``geolens_reader`` role.

    ``scripts/init-db.sh`` creates ``geolens_reader`` (NOLOGIN) with
    ``SELECT`` on every table in the ``data`` schema (and via
    ``ALTER DEFAULT PRIVILEGES`` on every future ingest table). The
    application user retains broader privileges by default; running the
    tile path as ``geolens_reader`` ensures any SQL-injection in the tile
    composition layer is scoped to read-only against the ``data`` schema
    rather than able to mutate or drop tables.

    ``RESET ROLE`` is implicit when the connection is returned to the
    pool because asyncpg short-circuits session state per checkout.
    Failures here log + skip the privilege drop so the tile path keeps
    working on deployments where the role doesn't exist (e.g. legacy
    upgrades that predate the role's creation in v6.0).
    """
    try:
        await conn.execute("SET ROLE geolens_reader")
    except asyncpg.PostgresError as exc:
        logger.warning(
            "Tile pool could not SET ROLE geolens_reader; running as app user",
            error=str(exc),
        )


async def init_tile_pool() -> asyncpg.Pool:
    """Create the dedicated tile connection pool."""
    global _tile_pool

    dsn = _parse_dsn()
    ssl = _get_ssl_arg()

    kwargs: dict = {
        "dsn": dsn,
        "min_size": settings.tile_pool_min_size,
        "max_size": settings.tile_pool_max_size,
        "command_timeout": 10,
        # H-10: drop privileges to geolens_reader on every fresh connection
        # so tile-path SQL runs read-only against the data schema.
        "setup": _setup_tile_connection,
    }

    if ssl is not None:
        kwargs["ssl"] = ssl

    # External pooler: disable prepared statement cache
    if settings.db_use_external_pooler:
        kwargs["statement_cache_size"] = 0

    _tile_pool = await asyncpg.create_pool(**kwargs)
    logger.info(
        "Tile connection pool initialized",
        min_size=settings.tile_pool_min_size,
        max_size=settings.tile_pool_max_size,
    )
    return _tile_pool


async def close_tile_pool() -> None:
    """Close the tile connection pool."""
    global _tile_pool
    if _tile_pool:
        await _tile_pool.close()
        _tile_pool = None
        logger.info("Tile connection pool closed")


def get_tile_pool() -> asyncpg.Pool:
    """Return the tile connection pool. Raises RuntimeError if not initialized."""
    if _tile_pool is None:
        raise RuntimeError("Tile pool not initialized. Call init_tile_pool() first.")
    return _tile_pool
