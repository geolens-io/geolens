#!/usr/bin/env python3
"""Seed GeoLens with synthetic datasets for performance testing.

Queries existing Natural Earth datasets for source geometries, then generates
1000+ synthetic datasets with varied geometry types and row counts. Uses the
same 3-step ingest API as seed-natural-earth.py.

Requires: pip install httpx
"""

import argparse
import asyncio
import io
import json
import logging
import os
import random
import sys
import time

try:
    import httpx  # noqa: F401
except ImportError:
    print(
        "Missing required package. Install with:\n"
        "  pip install httpx",
        file=sys.stderr,
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL = "http://localhost:8080"
SEED_FILENAME_PREFIX = "perf_seed_"

# Row count distribution buckets
# (weight, min_rows, max_rows, label)
ROW_BUCKETS = [
    (0.40, 100, 1000, "small"),
    (0.40, 1000, 10_000, "medium"),
    (0.15, 10_000, 50_000, "large"),
    (0.05, 50_000, 200_000, "very-large"),
]

# Geometry types we track for balanced distribution
GEOMETRY_TYPES = ["Point", "LineString", "Polygon", "MultiPolygon"]

# Tags applied to all synthetic datasets
BASE_TAGS = ["perf-seed", "synthetic"]

# Category-specific tags for variety
CATEGORY_TAGS = [
    ["urban", "infrastructure"],
    ["environmental", "monitoring"],
    ["transport", "network"],
    ["boundaries", "administrative"],
    ["hydrology", "water"],
    ["land-use", "planning"],
    ["demographics", "census"],
    ["geology", "terrain"],
    ["climate", "weather"],
    ["ecology", "habitat"],
]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Idempotency: fetch existing datasets
# ---------------------------------------------------------------------------


async def fetch_existing_datasets(
    client: httpx.AsyncClient, base_url: str, api_key: str
) -> dict[str, str]:
    """Paginate GET /api/datasets/ and return source_filename -> dataset_id mapping.

    Only returns entries matching the perf_seed_* filename pattern.
    """
    existing: dict[str, str] = {}
    skip = 0
    limit = 200
    headers = {"X-Api-Key": api_key}

    try:
        while True:
            resp = await client.get(
                f"{base_url}/api/datasets/",
                params={"limit": limit, "skip": skip},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            datasets = data.get("datasets", [])
            for ds in datasets:
                fname = ds.get("source_filename")
                ds_id = ds.get("id")
                if fname and ds_id and fname.startswith(SEED_FILENAME_PREFIX):
                    existing[fname] = ds_id
            total = data.get("total", 0)
            skip += limit
            if skip >= total or not datasets:
                break
    except (httpx.HTTPStatusError, httpx.TransportError) as exc:
        logger.warning("Failed to fetch existing datasets: %s", exc)
        return {}

    return existing


# ---------------------------------------------------------------------------
# Fetch NE source datasets and their geometries
# ---------------------------------------------------------------------------


async def fetch_ne_sources(
    client: httpx.AsyncClient, base_url: str, api_key: str
) -> list[dict]:
    """Fetch all Natural Earth datasets and sample rows from each.

    Returns a list of dicts with keys: id, name, source_filename, geom_type, features.
    """
    headers = {"X-Api-Key": api_key}
    sources: list[dict] = []
    skip = 0
    limit = 200

    # First, collect all NE dataset IDs
    ne_datasets: list[dict] = []
    while True:
        resp = await client.get(
            f"{base_url}/api/datasets/",
            params={"limit": limit, "skip": skip},
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()
        datasets = data.get("datasets", [])
        for ds in datasets:
            fname = ds.get("source_filename") or ""
            if fname.startswith("ne_10m_") and fname.endswith(".zip"):
                ne_datasets.append(ds)
        total = data.get("total", 0)
        skip += limit
        if skip >= total or not datasets:
            break

    if not ne_datasets:
        return []

    print(f"Found {len(ne_datasets)} Natural Earth source datasets")

    # Fetch sample rows from each NE dataset
    for ds in ne_datasets:
        ds_id = ds["id"]
        try:
            rows_resp = await client.get(
                f"{base_url}/api/datasets/{ds_id}/features/",
                params={"limit": 500},
                headers=headers,
            )
            rows_resp.raise_for_status()
            rows_data = rows_resp.json()
            features = rows_data.get("features", [])
            if not features:
                continue

            # Detect geometry type from first feature
            first_geom = features[0].get("geometry", {})
            geom_type = first_geom.get("type", "Point")

            sources.append({
                "id": ds_id,
                "name": ds.get("title", ds.get("source_filename", "")),
                "source_filename": ds.get("source_filename", ""),
                "geom_type": geom_type,
                "features": features,
            })
        except Exception as exc:
            logger.warning("Failed to fetch rows for %s: %s", ds_id, exc)
            continue

    return sources


# ---------------------------------------------------------------------------
# Geometry manipulation utilities
# ---------------------------------------------------------------------------


def round_coords(coords, precision: int = 5):
    """Recursively round coordinate values to given decimal precision."""
    if isinstance(coords, (int, float)):
        return round(coords, precision)
    return [round_coords(c, precision) for c in coords]


def jitter_point(coords: list, magnitude: float = 0.01) -> list:
    """Add random jitter to a point coordinate pair."""
    return [
        coords[0] + random.uniform(-magnitude, magnitude),
        coords[1] + random.uniform(-magnitude, magnitude),
    ]


def jitter_geometry(geometry: dict, magnitude: float = 0.01) -> dict:
    """Apply coordinate jitter to a geometry, preserving type."""
    geom_type = geometry.get("type", "")
    coords = geometry.get("coordinates", [])

    if geom_type == "Point":
        return {"type": "Point", "coordinates": jitter_point(coords, magnitude)}
    elif geom_type == "LineString":
        return {
            "type": "LineString",
            "coordinates": [jitter_point(c, magnitude) for c in coords],
        }
    elif geom_type == "Polygon":
        return {
            "type": "Polygon",
            "coordinates": [
                [jitter_point(c, magnitude) for c in ring] for ring in coords
            ],
        }
    elif geom_type == "MultiPolygon":
        return {
            "type": "MultiPolygon",
            "coordinates": [
                [[jitter_point(c, magnitude) for c in ring] for ring in poly]
                for poly in coords
            ],
        }
    elif geom_type == "MultiLineString":
        return {
            "type": "MultiLineString",
            "coordinates": [
                [jitter_point(c, magnitude) for c in line] for line in coords
            ],
        }
    elif geom_type == "MultiPoint":
        return {
            "type": "MultiPoint",
            "coordinates": [jitter_point(c, magnitude) for c in coords],
        }
    # Fallback: return as-is
    return geometry


def simplify_geometry(geometry: dict, precision: int = 5) -> dict:
    """Round all coordinates to reduce file size."""
    return {
        "type": geometry.get("type", ""),
        "coordinates": round_coords(geometry.get("coordinates", []), precision),
    }


# ---------------------------------------------------------------------------
# Synthetic feature generation
# ---------------------------------------------------------------------------


def generate_features(
    source_features: list[dict],
    target_count: int,
    geom_type: str,
) -> list[dict]:
    """Generate target_count features by subsampling or oversampling source features.

    Subsamples when target < source, oversamples with jitter when target > source.
    Simplifies polygon/line coordinates to reduce file size.
    """
    n_source = len(source_features)
    features: list[dict] = []

    if target_count <= n_source:
        # Subsample
        sampled = random.sample(source_features, target_count)
        for i, feat in enumerate(sampled):
            geom = feat.get("geometry", {})
            geom = simplify_geometry(geom)
            features.append({
                "type": "Feature",
                "properties": {"id": i + 1, "source_idx": i},
                "geometry": geom,
            })
    else:
        # Use all source features, then oversample with jitter
        for i in range(target_count):
            src_idx = i % n_source
            src_feat = source_features[src_idx]
            geom = src_feat.get("geometry", {})

            if i >= n_source:
                # Apply jitter to create variation
                jitter_mag = 0.005 + (i / target_count) * 0.02
                geom = jitter_geometry(geom, jitter_mag)

            geom = simplify_geometry(geom)
            features.append({
                "type": "Feature",
                "properties": {"id": i + 1, "source_idx": src_idx},
                "geometry": geom,
            })

    return features


# ---------------------------------------------------------------------------
# Dataset plan generation
# ---------------------------------------------------------------------------


def pick_row_count() -> tuple[int, str]:
    """Pick a row count from the weighted distribution."""
    r = random.random()
    cumulative = 0.0
    for weight, min_rows, max_rows, label in ROW_BUCKETS:
        cumulative += weight
        if r <= cumulative:
            return random.randint(min_rows, max_rows), label
    # Fallback
    return 500, "small"


def generate_dataset_plan(
    index: int,
    ne_sources: list[dict],
    geom_type_counts: dict[str, int],
) -> dict:
    """Generate a plan for one synthetic dataset.

    Selects source, row count, and geometry type with balanced distribution.
    """
    # Bias source selection toward underrepresented geometry types
    target_geom = min(GEOMETRY_TYPES, key=lambda g: geom_type_counts.get(g, 0))

    # Find sources matching the target geometry type
    matching_sources = [s for s in ne_sources if s["geom_type"] == target_geom]
    if not matching_sources:
        # Fall back to any source
        matching_sources = ne_sources

    source = random.choice(matching_sources)
    geom_type = source["geom_type"]

    row_count, size_label = pick_row_count()

    # For very large counts (>50K), force Point geometry to keep GeoJSON manageable
    if row_count > 50_000 and geom_type != "Point":
        point_sources = [s for s in ne_sources if s["geom_type"] == "Point"]
        if point_sources:
            source = random.choice(point_sources)
            geom_type = "Point"

    # Update geometry type counts
    geom_type_counts[geom_type] = geom_type_counts.get(geom_type, 0) + 1

    # Generate metadata
    source_name = source["name"].replace(" (10m)", "")
    filename = f"{SEED_FILENAME_PREFIX}{index:04d}.geojson"
    title = f"{source_name} - Variant {index}"
    description = (
        f"Synthetic performance test dataset #{index}. "
        f"Generated from {source_name} with {row_count} {geom_type} features. "
        f"Size category: {size_label}."
    )

    # Pick category tags for variety
    category = CATEGORY_TAGS[index % len(CATEGORY_TAGS)]
    tags = BASE_TAGS + category + [size_label, geom_type.lower()]

    return {
        "index": index,
        "source": source,
        "geom_type": geom_type,
        "row_count": row_count,
        "size_label": size_label,
        "filename": filename,
        "title": title,
        "description": description,
        "tags": tags,
    }


# ---------------------------------------------------------------------------
# Job polling (same as NE seeder)
# ---------------------------------------------------------------------------


async def poll_job(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    job_id: str,
    timeout: int = 600,
) -> dict:
    """Poll GET /api/jobs/{job_id} until complete or failed."""
    headers = {"X-Api-Key": api_key}
    start = time.monotonic()

    while True:
        resp = await client.get(
            f"{base_url}/api/jobs/{job_id}",
            headers=headers,
        )
        resp.raise_for_status()
        result = resp.json()
        status = result.get("status")

        if status in ("complete", "failed"):
            return result

        elapsed = time.monotonic() - start
        if elapsed >= timeout:
            raise TimeoutError(
                f"Job {job_id} did not complete within {timeout}s"
            )

        await asyncio.sleep(3)


# ---------------------------------------------------------------------------
# HTTP retry helper
# ---------------------------------------------------------------------------


async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    max_attempts: int = 3,
    **kwargs,
) -> httpx.Response:
    """Execute an HTTP request with retry on transient errors (429, 500, 502, 503)."""
    for attempt in range(1, max_attempts + 1):
        try:
            resp = await client.request(method, url, **kwargs)
            if resp.status_code in (429, 500, 502, 503) and attempt < max_attempts:
                delay = 2 ** attempt
                logger.warning(
                    "Retry %d/%d for %s: HTTP %d",
                    attempt, max_attempts, url, resp.status_code,
                )
                await asyncio.sleep(delay)
                continue
            resp.raise_for_status()
            return resp
        except httpx.TransportError as exc:
            if attempt == max_attempts:
                raise
            delay = 2 ** attempt
            logger.warning("Retry %d/%d for %s: %s", attempt, max_attempts, url, exc)
            await asyncio.sleep(delay)
    raise RuntimeError(f"Failed after {max_attempts} attempts: {url}")


# ---------------------------------------------------------------------------
# Three-step ingest pipeline
# ---------------------------------------------------------------------------


async def ingest_dataset(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    plan: dict,
) -> dict:
    """Ingest a synthetic dataset through the GeoLens three-step API.

    Steps: generate GeoJSON -> upload -> preview -> commit -> poll -> keywords.
    Returns the final job status dict.
    """
    headers = {"X-Api-Key": api_key}

    # Generate features
    features = generate_features(
        plan["source"]["features"],
        plan["row_count"],
        plan["geom_type"],
    )

    # Build GeoJSON FeatureCollection
    geojson = {
        "type": "FeatureCollection",
        "features": features,
    }

    # Serialize to BytesIO
    buf = io.BytesIO()
    buf.write(json.dumps(geojson).encode("utf-8"))
    buf.seek(0)

    # Step 1 - Upload
    upload_resp = await request_with_retry(
        client, "POST",
        f"{base_url}/api/ingest/upload",
        headers=headers,
        files={"file": (plan["filename"], buf, "application/geo+json")},
    )
    job_id = upload_resp.json()["job_id"]

    # Step 2 - Preview
    await request_with_retry(
        client, "POST",
        f"{base_url}/api/ingest/preview/{job_id}",
        headers=headers,
    )

    # Step 3 - Commit
    commit_body = {
        "title": plan["title"],
        "description": plan["description"],
        "visibility": "public",
        "srid_override": 4326,
    }
    await request_with_retry(
        client, "POST",
        f"{base_url}/api/ingest/commit/{job_id}",
        headers=headers,
        json=commit_body,
    )

    # Step 4 - Poll until complete or failed
    result = await poll_job(client, base_url, api_key, job_id)

    # Step 5 - Apply keywords
    dataset_id = result.get("dataset_id")
    if dataset_id and plan["tags"]:
        try:
            ds_resp = await client.get(
                f"{base_url}/api/datasets/{dataset_id}",
                headers=headers,
            )
            ds_resp.raise_for_status()
            record_id = ds_resp.json().get("record_id")
            if record_id:
                for tag in plan["tags"]:
                    kw_resp = await client.post(
                        f"{base_url}/api/records/{record_id}/keywords/",
                        headers=headers,
                        json={"keyword": tag, "keyword_type": "theme"},
                    )
                    if kw_resp.status_code not in (201, 409):
                        kw_resp.raise_for_status()
        except Exception as exc:
            logger.warning("Failed to set keywords for %s: %s", plan["filename"], exc)

    return result


# ---------------------------------------------------------------------------
# Concurrent processing
# ---------------------------------------------------------------------------


async def process_one(
    plan: dict,
    total: int,
    sem: asyncio.Semaphore,
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    existing: dict[str, str],
    results: list[dict],
    start_time: float,
) -> None:
    """Process a single synthetic dataset: generate + ingest."""
    index = plan["index"]
    filename = plan["filename"]
    tag = f"[{index}/{total}]"

    # Idempotency check
    if filename in existing:
        print(f"  {tag} Skipping {filename} (already imported)")
        results.append({
            "filename": filename,
            "status": "skipped",
            "geom_type": plan["geom_type"],
        })
        return

    async with sem:
        try:
            result = await ingest_dataset(client, base_url, api_key, plan)

            if result.get("status") == "failed":
                raise RuntimeError(
                    result.get("error_message", "Unknown ingest error")
                )

            results.append({
                "filename": filename,
                "status": "succeeded",
                "geom_type": plan["geom_type"],
                "row_count": plan["row_count"],
                "dataset_id": result.get("dataset_id"),
            })

            # Progress logging every 25 datasets
            completed = sum(
                1 for r in results if r["status"] in ("succeeded", "skipped")
            )
            if completed % 25 == 0 or completed == total:
                elapsed = time.monotonic() - start_time
                rate = completed / elapsed if elapsed > 0 else 0
                remaining = (total - completed) / rate if rate > 0 else 0
                print(
                    f"  {tag} Ingested {filename} "
                    f"({plan['geom_type']}, {plan['row_count']} rows) "
                    f"[{completed}/{total} done, ~{remaining:.0f}s remaining]"
                )
            else:
                print(
                    f"  {tag} Ingested {filename} "
                    f"({plan['geom_type']}, {plan['row_count']} rows)"
                )

        except Exception as exc:
            results.append({
                "filename": filename,
                "status": "failed",
                "geom_type": plan["geom_type"],
                "error": str(exc),
            })
            print(f"  {tag} Failed {filename}: {exc}")


# ---------------------------------------------------------------------------
# Summary report
# ---------------------------------------------------------------------------


def print_summary(
    total: int,
    results: list[dict],
    elapsed: float,
) -> None:
    """Print summary after the seed run."""
    succeeded = sum(1 for r in results if r["status"] == "succeeded")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    failed = sum(1 for r in results if r["status"] == "failed")

    # Geometry type breakdown
    geom_counts: dict[str, int] = {}
    for r in results:
        if r["status"] in ("succeeded", "skipped"):
            gt = r.get("geom_type", "unknown")
            geom_counts[gt] = geom_counts.get(gt, 0) + 1

    print()
    print("=" * 60)
    print("  Seed Performance Data - Summary")
    print("=" * 60)
    print(f"  Total planned:  {total}")
    print(f"  Succeeded:      {succeeded}")
    print(f"  Skipped:        {skipped}")
    print(f"  Failed:         {failed}")
    print(f"  Elapsed:        {elapsed:.1f}s")
    print()
    print("  By geometry type:")
    for gt, count in sorted(geom_counts.items()):
        print(f"    {gt}: {count}")

    if failed > 0:
        print()
        print("  Failures:")
        for r in results:
            if r["status"] == "failed":
                print(f"    {r['filename']}: {r.get('error', 'unknown')}")
    print()


# ---------------------------------------------------------------------------
# Dry-run display
# ---------------------------------------------------------------------------


def run_dry_run(plans: list[dict]) -> None:
    """Print the generation plan without uploading."""
    print("Synthetic Dataset Seed Plan (Dry Run)")
    print("=" * 70)

    geom_counts: dict[str, int] = {}
    size_counts: dict[str, int] = {}
    total_rows = 0

    for plan in plans:
        geom_counts[plan["geom_type"]] = geom_counts.get(plan["geom_type"], 0) + 1
        size_counts[plan["size_label"]] = size_counts.get(plan["size_label"], 0) + 1
        total_rows += plan["row_count"]

    # Show first 20 and last 5
    for plan in plans[:20]:
        print(
            f"  {plan['index']:4d}. {plan['filename']}  "
            f"{plan['geom_type']:15s}  {plan['row_count']:>7d} rows  "
            f"({plan['size_label']})"
        )
    if len(plans) > 25:
        print(f"  ... ({len(plans) - 25} more) ...")
    for plan in plans[-5:]:
        print(
            f"  {plan['index']:4d}. {plan['filename']}  "
            f"{plan['geom_type']:15s}  {plan['row_count']:>7d} rows  "
            f"({plan['size_label']})"
        )

    print()
    print(f"Total datasets: {len(plans)}")
    print(f"Total rows: {total_rows:,}")
    print()
    print("Geometry type distribution:")
    for gt, count in sorted(geom_counts.items()):
        pct = count / len(plans) * 100
        print(f"  {gt}: {count} ({pct:.1f}%)")
    print()
    print("Size distribution:")
    for label, count in sorted(size_counts.items()):
        pct = count / len(plans) * 100
        print(f"  {label}: {count} ({pct:.1f}%)")


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Seed GeoLens with synthetic datasets for performance testing. "
        "Requires Natural Earth data to be seeded first (seed-natural-earth.py).",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("GEOLENS_API_KEY"),
        help="GeoLens API key (or set GEOLENS_API_KEY env var)",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("GEOLENS_BASE_URL", DEFAULT_BASE_URL),
        help=f"GeoLens base URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1000,
        help="Number of synthetic datasets to generate (default: 1000)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=5,
        help="Max concurrent ingest operations (default: 5)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print generation plan without uploading",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


async def main(args: argparse.Namespace) -> None:
    """Generate and ingest synthetic datasets into GeoLens."""
    base_url = args.base_url.rstrip("/")
    api_key = args.api_key
    count = args.count

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(600.0, connect=30.0),
        follow_redirects=True,
    ) as client:
        # Validate connectivity
        try:
            health_resp = await client.get(f"{base_url}/api/health")
            health_resp.raise_for_status()
        except (httpx.HTTPStatusError, httpx.TransportError) as exc:
            print(f"Cannot reach GeoLens at {base_url}: {exc}", file=sys.stderr)
            sys.exit(1)

        # Fetch NE source datasets
        print("Fetching Natural Earth source datasets...")
        ne_sources = await fetch_ne_sources(client, base_url, api_key)
        if not ne_sources:
            print(
                "Error: No Natural Earth datasets found. "
                "Run seed-natural-earth.py first.",
                file=sys.stderr,
            )
            sys.exit(1)

        print(f"Loaded {len(ne_sources)} NE sources with sample geometries")
        for src in ne_sources[:5]:
            print(f"  - {src['name']} ({src['geom_type']}, {len(src['features'])} sample rows)")
        if len(ne_sources) > 5:
            print(f"  ... and {len(ne_sources) - 5} more")

        # Generate dataset plans
        print(f"\nGenerating plan for {count} synthetic datasets...")
        geom_type_counts: dict[str, int] = {}
        plans: list[dict] = []
        for i in range(1, count + 1):
            plan = generate_dataset_plan(i, ne_sources, geom_type_counts)
            plans.append(plan)

        if args.dry_run:
            run_dry_run(plans)
            return

        # Check idempotency
        print("Checking existing datasets...")
        existing = await fetch_existing_datasets(client, base_url, api_key)
        if existing:
            print(f"Found {len(existing)} existing perf_seed datasets (will skip)")

        # Ingest with bounded concurrency
        results: list[dict] = []
        sem = asyncio.Semaphore(args.concurrency)
        run_start = time.monotonic()

        print(f"\nIngesting {count} datasets (concurrency={args.concurrency})...")

        async with asyncio.TaskGroup() as tg:
            for plan in plans:
                tg.create_task(
                    process_one(
                        plan=plan,
                        total=count,
                        sem=sem,
                        client=client,
                        base_url=base_url,
                        api_key=api_key,
                        existing=existing,
                        results=results,
                        start_time=run_start,
                    )
                )

        elapsed = time.monotonic() - run_start
        print_summary(count, results, elapsed)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    args = parse_args()

    if args.dry_run:
        # Dry run doesn't need API key or live connection for plan generation
        # but still needs NE sources for realistic plans -- unless we mock them
        # For dry run, generate plans with mock sources
        print("Synthetic Dataset Seed Plan (Dry Run)")
        print("=" * 70)
        print(f"Target count: {args.count}")
        print(f"Base URL: {args.base_url}")
        print()

        # Create mock sources for dry-run planning
        mock_sources = [
            {"id": "mock-1", "name": "Countries", "source_filename": "ne_10m_admin_0_countries.zip",
             "geom_type": "MultiPolygon", "features": [{"geometry": {"type": "MultiPolygon", "coordinates": [[[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]]}}]},
            {"id": "mock-2", "name": "Roads", "source_filename": "ne_10m_roads.zip",
             "geom_type": "LineString", "features": [{"geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}}]},
            {"id": "mock-3", "name": "Airports", "source_filename": "ne_10m_airports.zip",
             "geom_type": "Point", "features": [{"geometry": {"type": "Point", "coordinates": [0, 0]}}]},
            {"id": "mock-4", "name": "Lakes", "source_filename": "ne_10m_lakes.zip",
             "geom_type": "Polygon", "features": [{"geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}}]},
        ]

        geom_type_counts: dict[str, int] = {}
        plans: list[dict] = []
        for i in range(1, args.count + 1):
            plan = generate_dataset_plan(i, mock_sources, geom_type_counts)
            plans.append(plan)

        run_dry_run(plans)
    else:
        if not args.api_key:
            print(
                "Error: --api-key or GEOLENS_API_KEY env var required",
                file=sys.stderr,
            )
            sys.exit(1)
        asyncio.run(main(args))
