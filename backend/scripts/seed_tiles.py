"""CLI script to pre-seed the Redis vector tile cache for all (or specific) datasets.

Generates MVT tiles from PostGIS for zoom levels 0-10 within each dataset's
spatial extent and stores them in Redis, eliminating cold-cache latency before
user traffic arrives.

Usage (inside Docker):
    docker compose exec api python -m scripts.seed_tiles

Usage (locally with env vars set):
    cd backend && python -m scripts.seed_tiles

Options:
    --dataset / -d    Seed only this dataset table_name
    --concurrency / -c  Concurrent workers (default: 10)
    --min-zoom        Minimum zoom level to seed (default: 0)
    --max-zoom        Maximum zoom level to seed (default: 10)
    --dry-run         Print tile counts per dataset, skip actual seeding
"""

import argparse
import asyncio
import gzip
import math
import sys
import time

import structlog

logger = structlog.stdlib.get_logger(__name__)

_LAT_MAX = 85.0511
_LAT_MIN = -85.0511


# ---------------------------------------------------------------------------
# Tile math (pure functions — testable without I/O)
# ---------------------------------------------------------------------------


def lng_to_tile_x(lng: float, z: int) -> int:
    """Convert a WGS84 longitude to a tile X index at zoom level z."""
    return int((lng + 180.0) / 360.0 * (1 << z))


def lat_to_tile_y(lat: float, z: int) -> int:
    """Convert a WGS84 latitude to a tile Y index at zoom level z.

    Uses the Slippy Map (Web Mercator) formula where Y=0 is the top (north).
    """
    lat_rad = math.radians(lat)
    n = 1 << z
    return int(
        (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi)
        / 2.0
        * n
    )


def bbox_to_tiles(
    west: float,
    south: float,
    east: float,
    north: float,
    z: int,
):
    """Yield (z, x, y) tuples for all tiles intersecting the bbox at zoom z.

    Latitude is clamped to the Web Mercator valid range [-85.0511, 85.0511]
    before computing tile indices.

    Args:
        west: Western boundary longitude
        south: Southern boundary latitude
        east: Eastern boundary longitude
        north: Northern boundary latitude
        z: Zoom level

    Yields:
        (z, x, y) tuples
    """
    # Clamp to Web Mercator valid range
    south = max(south, _LAT_MIN)
    north = min(north, _LAT_MAX)

    if south >= north:
        return

    n = 1 << z

    x_min = max(0, lng_to_tile_x(west, z))
    x_max = min(n - 1, lng_to_tile_x(east, z))

    # Note: latitude is inverted — north → lower Y, south → higher Y
    y_min = max(0, lat_to_tile_y(north, z))
    y_max = min(n - 1, lat_to_tile_y(south, z))

    if x_min > x_max or y_min > y_max:
        return

    for x in range(x_min, x_max + 1):
        for y in range(y_min, y_max + 1):
            yield (z, x, y)


# ---------------------------------------------------------------------------
# Dataset query
# ---------------------------------------------------------------------------

_DATASET_QUERY = """
    SELECT
        d.table_name,
        d.column_info,
        d.tile_cache_ttl,
        ST_XMin(r.spatial_extent) AS west,
        ST_YMin(r.spatial_extent) AS south,
        ST_XMax(r.spatial_extent) AS east,
        ST_YMax(r.spatial_extent) AS north
    FROM catalog.datasets d
    JOIN catalog.records r ON d.record_id = r.id
    WHERE r.record_type = 'vector_dataset'
      AND r.spatial_extent IS NOT NULL
"""

_DATASET_QUERY_FILTERED = _DATASET_QUERY + "\n      AND d.table_name = $1"


# ---------------------------------------------------------------------------
# Main seeding logic
# ---------------------------------------------------------------------------


async def _seed_dataset(
    pool,
    cache,
    table_name: str,
    columns,
    cache_ttl: int,
    all_tiles,
    concurrency: int,
    dry_run: bool,
) -> tuple[int, int]:
    """Seed all tiles for a single dataset.

    Returns:
        (seeded_count, error_count)
    """
    total = len(all_tiles)
    if dry_run:
        print(f"  [dry-run] {table_name}: {total} tiles (would seed)")
        return 0, 0

    print(f"  Seeding {table_name}: {total} tiles...")

    sem = asyncio.Semaphore(concurrency)
    start = time.monotonic()

    # Shared mutable state via list (avoids nonlocal for compatibility)
    counter = [0]
    errors = [0]

    async def seed_one(z: int, x: int, y: int) -> None:
        async with sem:
            try:
                from app.tiles.service import get_tile

                tile_data = await get_tile(pool, table_name, z, x, y, columns)
                if tile_data is None:
                    await cache.set(table_name, z, x, y, b"", ttl=cache_ttl)
                else:
                    compressed = gzip.compress(tile_data, compresslevel=6)
                    await cache.set(table_name, z, x, y, compressed, ttl=cache_ttl)
            except Exception as exc:
                logger.warning(
                    "seed_tile_failed",
                    table=table_name,
                    z=z,
                    x=x,
                    y=y,
                    error=str(exc),
                )
                errors[0] += 1
            finally:
                counter[0] += 1
                # Progress every 100 tiles or every 5 seconds
                if counter[0] % 100 == 0:
                    _print_progress(table_name, counter[0], total, start)

    tasks = [asyncio.create_task(seed_one(z, x, y)) for z, x, y in all_tiles]
    await asyncio.gather(*tasks)

    elapsed = time.monotonic() - start
    rate = counter[0] / elapsed if elapsed > 0 else 0
    print(
        f"  Done {table_name}: {counter[0]}/{total} tiles"
        f" ({errors[0]} errors) in {elapsed:.1f}s ({rate:.0f} tiles/sec)"
    )
    return counter[0] - errors[0], errors[0]


def _print_progress(table_name: str, done: int, total: int, start: float) -> None:
    elapsed = time.monotonic() - start
    pct = done / total * 100 if total > 0 else 0
    rate = done / elapsed if elapsed > 0 else 0
    print(
        f"  [{table_name}] {done}/{total} ({pct:.0f}%) - {rate:.0f} tiles/sec",
        flush=True,
    )


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pre-seed the Redis vector tile cache for all (or specific) datasets.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--dataset",
        "-d",
        metavar="TABLE_NAME",
        default=None,
        help="Seed only this dataset (by table_name). Default: all datasets.",
    )
    parser.add_argument(
        "--concurrency",
        "-c",
        type=int,
        default=10,
        metavar="N",
        help="Number of concurrent tile generation workers.",
    )
    parser.add_argument(
        "--min-zoom",
        type=int,
        default=0,
        metavar="Z",
        help="Minimum zoom level to seed.",
    )
    parser.add_argument(
        "--max-zoom",
        type=int,
        default=10,
        metavar="Z",
        help="Maximum zoom level to seed.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print tile counts per dataset without writing to Redis.",
    )
    args = parser.parse_args()

    from app.config import settings
    from app.tiles.pool import close_tile_pool, init_tile_pool
    from app.cache.tile_cache import TileCacheProvider

    if not settings.redis_url:
        print("ERROR: redis_url is not configured. Set REDIS_URL env var.", file=sys.stderr)
        sys.exit(1)

    print("Initializing tile pool...")
    pool = await init_tile_pool()

    cache = TileCacheProvider(url=settings.redis_url)
    print(f"Redis cache ready: {settings.redis_url}")

    # Query datasets
    if args.dataset:
        rows = await pool.fetch(_DATASET_QUERY_FILTERED, args.dataset)
    else:
        rows = await pool.fetch(_DATASET_QUERY)

    if not rows:
        if args.dataset:
            print(f"No vector dataset found with table_name='{args.dataset}'")
        else:
            print("No vector datasets found.")
        await close_tile_pool()
        return

    print(
        f"Found {len(rows)} dataset(s). Zoom range: z{args.min_zoom}–z{args.max_zoom}."
    )
    if args.dry_run:
        print("DRY RUN — no tiles will be written to Redis.\n")

    grand_total_tiles = 0
    grand_seeded = 0
    grand_errors = 0
    run_start = time.monotonic()

    for row in rows:
        table_name = row["table_name"]
        column_info = row["column_info"]
        # asyncpg returns JSONB as a Python object already
        if isinstance(column_info, str):
            import json
            columns = json.loads(column_info)
        else:
            columns = column_info or []

        cache_ttl = row["tile_cache_ttl"] or settings.tile_cache_ttl

        west = row["west"]
        south = row["south"]
        east = row["east"]
        north = row["north"]

        # Compute all tiles across all zoom levels
        all_tiles = []
        for z in range(args.min_zoom, args.max_zoom + 1):
            all_tiles.extend(bbox_to_tiles(west, south, east, north, z=z))

        grand_total_tiles += len(all_tiles)

        seeded, errors = await _seed_dataset(
            pool=pool,
            cache=cache,
            table_name=table_name,
            columns=columns,
            cache_ttl=cache_ttl,
            all_tiles=all_tiles,
            concurrency=args.concurrency,
            dry_run=args.dry_run,
        )
        grand_seeded += seeded
        grand_errors += errors

    elapsed = time.monotonic() - run_start
    rate = grand_seeded / elapsed if elapsed > 0 and grand_seeded > 0 else 0

    print("\n--- Summary ---")
    if args.dry_run:
        print(f"Total tiles (estimated): {grand_total_tiles}")
    else:
        print(
            f"Seeded: {grand_seeded}/{grand_total_tiles} tiles"
            f" | Errors: {grand_errors}"
            f" | Elapsed: {elapsed:.1f}s"
            f" | {rate:.0f} tiles/sec"
        )

    await close_tile_pool()


if __name__ == "__main__":
    asyncio.run(main())
