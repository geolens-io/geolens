#!/usr/bin/env python3
"""Seed GeoLens with Natural Earth 1:10m vector datasets.

Downloads all Natural Earth 1:10m cultural and physical vector datasets
from the NACIS CDN and ingests them into GeoLens via the upload API,
auto-generating display names and tags for each dataset.

Requires: pip install httpx
"""

import argparse
import asyncio
import io
import logging
import os
import sys
import time
import zipfile
from pathlib import Path

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

NE_VERSION = "5.1.2"  # Natural Earth version (documentation only)
CDN_BASE = "https://naciscdn.org/naturalearth/10m"
DEFAULT_BASE_URL = "http://localhost:8080"

# ---------------------------------------------------------------------------
# Dataset manifest -- all Natural Earth 1:10m vector datasets
# URL pattern: {CDN_BASE}/{theme}/{stem}.zip
# ---------------------------------------------------------------------------

DATASETS: list[dict] = [
    # -----------------------------------------------------------------------
    # Cultural datasets (~78)
    # -----------------------------------------------------------------------
    # Admin 0 (countries / sovereignty)
    {"stem": "ne_10m_admin_0_countries", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_countries_lakes", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_boundary_lines_land", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_boundary_lines_disputed_areas", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_boundary_lines_map_units", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_boundary_lines_maritime_indicator", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_label_points", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_map_subunits", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_map_units", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_pacific_groupings", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_scale_rank", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_seams", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_sovereignty", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_disputed_areas", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_disputed_areas_scale_rank_minor_islands", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_boundary_lines_maritime_indicator_chn", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_antarctic_claims", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_antarctic_claim_limit_lines", "theme": "cultural"},
    # Admin 1 (states / provinces)
    {"stem": "ne_10m_admin_1_states_provinces", "theme": "cultural"},
    {"stem": "ne_10m_admin_1_states_provinces_lakes", "theme": "cultural"},
    {"stem": "ne_10m_admin_1_states_provinces_lines", "theme": "cultural"},
    {"stem": "ne_10m_admin_1_label_points", "theme": "cultural"},
    {"stem": "ne_10m_admin_1_seams", "theme": "cultural"},
    # Admin 2 (counties)
    {"stem": "ne_10m_admin_2_counties", "theme": "cultural"},
    {"stem": "ne_10m_admin_2_counties_lakes", "theme": "cultural"},
    {"stem": "ne_10m_admin_2_label_points", "theme": "cultural"},
    # Populated places
    {"stem": "ne_10m_populated_places", "theme": "cultural"},
    {"stem": "ne_10m_populated_places_simple", "theme": "cultural"},
    # Roads
    {"stem": "ne_10m_roads", "theme": "cultural"},
    {"stem": "ne_10m_roads_north_america", "theme": "cultural"},
    # Railroads
    {"stem": "ne_10m_railroads", "theme": "cultural"},
    {"stem": "ne_10m_railroads_north_america", "theme": "cultural"},
    # Airports
    {"stem": "ne_10m_airports", "theme": "cultural"},
    # Ports
    {"stem": "ne_10m_ports", "theme": "cultural"},
    # Urban areas
    {"stem": "ne_10m_urban_areas", "theme": "cultural"},
    {"stem": "ne_10m_urban_areas_landscan", "theme": "cultural"},
    # Time zones
    {"stem": "ne_10m_time_zones", "theme": "cultural"},
    # Cultural building blocks / additional
    {"stem": "ne_10m_admin_0_countries_arg", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_countries_bdg", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_countries_bra", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_countries_deu", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_countries_egy", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_countries_esp", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_countries_fra", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_countries_gbr", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_countries_grc", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_countries_idn", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_countries_ind", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_countries_iso", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_countries_isr", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_countries_ita", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_countries_jpn", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_countries_kor", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_countries_mar", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_countries_nep", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_countries_nld", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_countries_pak", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_countries_pol", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_countries_prt", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_countries_pse", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_countries_rus", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_countries_sau", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_countries_swe", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_countries_tlc", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_countries_tur", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_countries_twn", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_countries_ukr", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_countries_usa", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_countries_vnm", "theme": "cultural"},
    {"stem": "ne_10m_admin_0_countries_chn", "theme": "cultural"},
    {"stem": "ne_10m_admin_1_label_points_details", "theme": "cultural"},
    # -----------------------------------------------------------------------
    # Physical datasets (~52)
    # -----------------------------------------------------------------------
    # Coastline / land / ocean
    {"stem": "ne_10m_coastline", "theme": "physical"},
    {"stem": "ne_10m_land", "theme": "physical"},
    {"stem": "ne_10m_land_ocean_label_points", "theme": "physical"},
    {"stem": "ne_10m_land_ocean_seams", "theme": "physical"},
    {"stem": "ne_10m_land_scale_rank", "theme": "physical"},
    {"stem": "ne_10m_ocean", "theme": "physical"},
    {"stem": "ne_10m_ocean_scale_rank", "theme": "physical"},
    # Minor islands
    {"stem": "ne_10m_minor_islands", "theme": "physical"},
    {"stem": "ne_10m_minor_islands_coastline", "theme": "physical"},
    {"stem": "ne_10m_minor_islands_label_points", "theme": "physical"},
    # Rivers
    {"stem": "ne_10m_rivers_lake_centerlines", "theme": "physical"},
    {"stem": "ne_10m_rivers_lake_centerlines_scale_rank", "theme": "physical"},
    {"stem": "ne_10m_rivers_australia", "theme": "physical"},
    {"stem": "ne_10m_rivers_europe", "theme": "physical"},
    {"stem": "ne_10m_rivers_north_america", "theme": "physical"},
    # Lakes
    {"stem": "ne_10m_lakes", "theme": "physical"},
    {"stem": "ne_10m_lakes_australia", "theme": "physical"},
    {"stem": "ne_10m_lakes_europe", "theme": "physical"},
    {"stem": "ne_10m_lakes_historic", "theme": "physical"},
    {"stem": "ne_10m_lakes_north_america", "theme": "physical"},
    {"stem": "ne_10m_lakes_pluvial", "theme": "physical"},
    # Glaciated areas
    {"stem": "ne_10m_glaciated_areas", "theme": "physical"},
    # Antarctic ice
    {"stem": "ne_10m_antarctic_ice_shelves_lines", "theme": "physical"},
    {"stem": "ne_10m_antarctic_ice_shelves_polys", "theme": "physical"},
    # Geographic lines and regions
    {"stem": "ne_10m_geographic_lines", "theme": "physical"},
    {"stem": "ne_10m_geography_marine_polys", "theme": "physical"},
    {"stem": "ne_10m_geography_regions_elevation_points", "theme": "physical"},
    {"stem": "ne_10m_geography_regions_points", "theme": "physical"},
    {"stem": "ne_10m_geography_regions_polys", "theme": "physical"},
    # Graticules
    {"stem": "ne_10m_graticules_1", "theme": "physical"},
    {"stem": "ne_10m_graticules_5", "theme": "physical"},
    {"stem": "ne_10m_graticules_10", "theme": "physical"},
    {"stem": "ne_10m_graticules_15", "theme": "physical"},
    {"stem": "ne_10m_graticules_20", "theme": "physical"},
    {"stem": "ne_10m_graticules_30", "theme": "physical"},
    # Playas and reefs
    {"stem": "ne_10m_playas", "theme": "physical"},
    {"stem": "ne_10m_reefs", "theme": "physical"},
    # Bounding box and additional physical
    {"stem": "ne_10m_wgs84_bounding_box", "theme": "physical"},
]

# ---------------------------------------------------------------------------
# Tag lookup by layer group
# ---------------------------------------------------------------------------

LAYER_GROUP_TAGS: dict[str, list[str]] = {
    "admin_0": ["boundaries", "countries"],
    "admin_1": ["boundaries", "provinces"],
    "admin_2": ["boundaries", "counties"],
    "populated_places": ["cities", "population"],
    "roads": ["transport", "roads"],
    "railroads": ["transport", "rail"],
    "airports": ["transport", "airports"],
    "ports": ["transport", "ports"],
    "urban_areas": ["urban"],
    "time_zones": ["reference", "time-zones"],
    "rivers": ["hydrology", "rivers"],
    "lakes": ["hydrology", "lakes"],
    "coastline": ["physical", "coastline"],
    "land": ["physical", "land"],
    "ocean": ["physical", "ocean"],
    "minor_islands": ["physical", "islands"],
    "glaciated": ["physical", "glaciers"],
    "antarctic_ice": ["physical", "ice"],
    "graticules": ["reference", "grid"],
    "reefs": ["physical", "reefs"],
    "playas": ["physical", "playas"],
    "geographic_lines": ["reference", "lines"],
    "geography_marine": ["physical", "marine"],
    "geography_regions": ["physical", "regions"],
}

# ---------------------------------------------------------------------------
# Metadata generators
# ---------------------------------------------------------------------------


def generate_name(stem: str) -> str:
    """Generate a human-readable display name from a dataset stem.

    Example: ne_10m_admin_0_countries -> "Admin 0 Countries (10m)"
    """
    stripped = stem.removeprefix("ne_10m_")
    return stripped.replace("_", " ").title() + " (10m)"


def generate_tags(stem: str, theme: str) -> list[str]:
    """Generate tags for a dataset based on its stem and theme.

    Base tags: ["natural-earth", "10m", <theme>]
    Plus group-specific tags from LAYER_GROUP_TAGS.
    """
    tags = ["natural-earth", "10m", theme]
    stripped = stem.removeprefix("ne_10m_")
    for key, group_tags in LAYER_GROUP_TAGS.items():
        # Match key in stem, also handle singular forms (e.g. "lake" matches "lakes" group)
        if key in stripped or (key.endswith("s") and key[:-1] in stripped):
            tags.extend(group_tags)
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for tag in tags:
        if tag not in seen:
            seen.add(tag)
            unique.append(tag)
    return unique


# ---------------------------------------------------------------------------
# Idempotency check
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)


async def fetch_existing_datasets(
    client: httpx.AsyncClient, base_url: str, api_key: str
) -> dict[str, str]:
    """Paginate GET /api/datasets/ and return a mapping of source_filename -> dataset_id.

    Used for idempotency: datasets already in the catalog are skipped.
    The dataset_id values allow skipped datasets to be assigned to collections.
    On HTTP error, returns an empty dict (fail-open -- duplicates will fail
    gracefully at upload time).
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
                if fname and ds_id:
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
# Download with retry
# ---------------------------------------------------------------------------


async def download_dataset(
    client: httpx.AsyncClient,
    url: str,
) -> bytes:
    """Download a ZIP file from the given URL with retry on transient errors.

    Retries up to 3 times with exponential backoff (2s, 4s) on:
    httpx.TransportError, HTTP 429/500/502/503.
    Raises immediately on non-retryable errors (400/401/403/404 etc.).
    """
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content
        except httpx.TransportError as exc:
            if attempt == max_attempts:
                raise
            delay = 2 ** attempt
            logger.warning("Retry %d/%d for %s: %s", attempt, max_attempts, url, exc)
            await asyncio.sleep(delay)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (429, 500, 502, 503) and attempt < max_attempts:
                delay = 2 ** attempt
                logger.warning("Retry %d/%d for %s: HTTP %d", attempt, max_attempts, url, exc.response.status_code)
                await asyncio.sleep(delay)
            else:
                raise
    # Unreachable, but keeps type checkers happy
    raise RuntimeError(f"Failed to download {url} after {max_attempts} attempts")


# ---------------------------------------------------------------------------
# Download caching
# ---------------------------------------------------------------------------


def write_cache_atomic(cache_dir: Path, stem: str, data: bytes) -> None:
    """Write downloaded data to cache atomically via tmp + rename."""
    final = cache_dir / f"{stem}.zip"
    tmp = cache_dir / f"{stem}.zip.tmp"
    tmp.write_bytes(data)
    os.rename(tmp, final)


def clean_partial_downloads(cache_dir: Path) -> None:
    """Remove any .tmp files left from interrupted downloads."""
    for tmp in cache_dir.glob("*.zip.tmp"):
        tmp.unlink()


async def download_or_load_cache(
    client: httpx.AsyncClient,
    url: str,
    stem: str,
    cache_dir: Path | None,
) -> bytes:
    """Load from cache if available, otherwise download from CDN and cache."""
    if cache_dir is not None:
        cached = cache_dir / f"{stem}.zip"
        if cached.exists() and cached.stat().st_size > 0:
            return cached.read_bytes()

    # Cache miss -- download from CDN
    data = await download_dataset(client, url)

    # Write to cache if cache_dir is set
    if cache_dir is not None:
        write_cache_atomic(cache_dir, stem, data)

    return data


# ---------------------------------------------------------------------------
# Encoding detection
# ---------------------------------------------------------------------------

# Stems known to have non-ASCII attribute values (city names, country names)
# that may be misdetected by GDAL if the .cpg file is absent.
# Intentionally conservative -- add stems here if encoding failures are observed.
ENCODING_OVERRIDE_STEMS: set[str] = {
    "ne_10m_populated_places",
    "ne_10m_populated_places_simple",
    "ne_10m_admin_0_countries",
    "ne_10m_admin_1_states_provinces",
}


def detect_missing_cpg(data: bytes, stem: str) -> bool:
    """Check if a ZIP archive is missing a .cpg codepage file.

    Returns True if NO .cpg file is found (encoding detection may fail).
    """
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for name in zf.namelist():
                if name.lower().endswith(".cpg"):
                    return False
    except zipfile.BadZipFile:
        logger.warning("%s: invalid ZIP file, cannot check for .cpg", stem)
        return False
    return True


# ---------------------------------------------------------------------------
# Job polling
# ---------------------------------------------------------------------------


async def poll_job(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    job_id: str,
    timeout: int = 300,
) -> dict:
    """Poll GET /api/jobs/{job_id} until complete or failed.

    Polls every 3 seconds. Raises TimeoutError if the job does not finish
    within ``timeout`` seconds (default 300 = 5 minutes).
    """
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
# Three-step ingest pipeline
# ---------------------------------------------------------------------------


async def ingest_dataset(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    stem: str,
    data: bytes,
    name: str,
    tags: list[str],
    encoding: str | None = None,
) -> dict:
    """Ingest a dataset through the GeoLens three-step API.

    Steps: upload -> preview -> commit -> poll for completion.
    Returns the final job status dict.
    """
    headers = {"X-Api-Key": api_key}

    # Step 1 - Upload
    upload_resp = await client.post(
        f"{base_url}/api/ingest/upload",
        headers=headers,
        files={"file": (f"{stem}.zip", data, "application/zip")},
    )
    upload_resp.raise_for_status()
    job_id = upload_resp.json()["job_id"]

    # Step 2 - Preview (advances job state; response data discarded)
    preview_resp = await client.post(
        f"{base_url}/api/ingest/preview/{job_id}",
        headers=headers,
    )
    preview_resp.raise_for_status()

    # Step 3 - Commit
    commit_body: dict = {
        "title": name,
        "visibility": "public",
        "srid_override": 4326,
    }

    commit_resp = await client.post(
        f"{base_url}/api/ingest/commit/{job_id}",
        headers=headers,
        json=commit_body,
    )
    commit_resp.raise_for_status()

    # Step 4 - Poll until complete or failed
    result = await poll_job(client, base_url, api_key, job_id)

    # Step 5 - Apply keywords via records API (post-ingestion)
    dataset_id = result.get("dataset_id")
    if dataset_id and tags:
        try:
            # Fetch dataset to get record_id
            ds_resp = await client.get(
                f"{base_url}/api/datasets/{dataset_id}",
                headers=headers,
            )
            ds_resp.raise_for_status()
            record_id = ds_resp.json().get("record_id")
            if record_id:
                for tag in tags:
                    kw_resp = await client.post(
                        f"{base_url}/api/records/{record_id}/keywords/",
                        headers=headers,
                        json={"keyword": tag, "keyword_type": "theme"},
                    )
                    # 409 = duplicate keyword, that's fine
                    if kw_resp.status_code not in (201, 409):
                        kw_resp.raise_for_status()
        except Exception as exc:
            logger.warning("Failed to set keywords for %s: %s", stem, exc)

    return result


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Seed GeoLens with Natural Earth 1:10m vector datasets",
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
        "--dry-run",
        action="store_true",
        help="List datasets that would be imported without making API calls",
    )
    parser.add_argument(
        "--theme",
        choices=["cultural", "physical", "all"],
        default="all",
        help="Filter datasets by theme (default: all)",
    )
    parser.add_argument(
        "--dataset",
        help="Import only this dataset stem (e.g., ne_10m_airports) for debugging",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Directory to cache downloaded ZIPs (resumes partial runs without re-downloading)",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Dry-run display
# ---------------------------------------------------------------------------


def run_dry_run(datasets: list[dict]) -> None:
    """Print a list of datasets that would be imported."""
    print("Natural Earth 1:10m Datasets (Dry Run)")
    print("=" * 60)
    for i, ds in enumerate(datasets, 1):
        name = generate_name(ds["stem"])
        print(f"  {i:3d}. {ds['stem']}  {name}  [{ds['theme']}]")
    print(f"\nTotal datasets: {len(datasets)}")


# ---------------------------------------------------------------------------
# Summary report
# ---------------------------------------------------------------------------


def print_summary(
    total: int,
    succeeded: int,
    skipped: int,
    failed: int,
    failures: list[dict],
) -> None:
    """Print a plain-text summary after the import run."""
    print()
    print("=== Import Summary ===")
    print(f"  Succeeded: {succeeded}")
    print(f"  Skipped:   {skipped}")
    print(f"  Failed:    {failed}")
    print(f"  Total:     {total}")

    if failures:
        print()
        print("Failures:")
        for f in failures:
            print(f"  {f['stem']}: {f['error']}")


# ---------------------------------------------------------------------------
# Post-import collection assignment
# ---------------------------------------------------------------------------


async def create_or_get_collection(
    client: httpx.AsyncClient,
    base_url: str,
    headers: dict,
    name: str,
    description: str,
) -> str | None:
    """Create a collection or return existing one's ID if name already exists.

    Returns the collection UUID on success, or None on unexpected errors.
    """
    resp = await client.post(
        f"{base_url}/api/catalog/collections/",
        headers=headers,
        json={"name": name, "description": description},
    )
    if resp.status_code == 201:
        return resp.json()["id"]

    if resp.status_code == 409:
        # Already exists -- find by name in collection list
        list_resp = await client.get(
            f"{base_url}/api/catalog/collections/",
            headers=headers,
            params={"limit": 200},
        )
        list_resp.raise_for_status()
        for coll in list_resp.json().get("collections", []):
            if coll["name"] == name:
                return coll["id"]

    logger.warning(
        "Failed to create/find collection %r: HTTP %d", name, resp.status_code
    )
    return None


async def create_collections(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    results: list[dict],
) -> None:
    """Create Natural Earth collections and assign datasets post-import.

    Groups succeeded and skipped datasets by theme, creates two collections
    ("Natural Earth Cultural (10m)" and "Natural Earth Physical (10m)"),
    and bulk-assigns dataset UUIDs to each. Idempotent: handles duplicate
    collection names (409) and duplicate dataset membership gracefully.

    Errors are caught and logged without crashing the script.
    """
    try:
        headers = {"X-Api-Key": api_key}

        # Group dataset IDs by theme (include succeeded and skipped with valid IDs)
        cultural_ids: list[str] = []
        physical_ids: list[str] = []
        for r in results:
            if r["status"] not in ("succeeded", "skipped"):
                continue
            ds_id = r.get("dataset_id")
            if ds_id is None:
                continue
            if r.get("theme") == "cultural":
                cultural_ids.append(ds_id)
            elif r.get("theme") == "physical":
                physical_ids.append(ds_id)

        if not cultural_ids and not physical_ids:
            print("No datasets to assign to collections")
            return

        collections_spec = [
            (
                "Natural Earth Cultural (10m)",
                "Natural Earth 1:10m cultural vector datasets",
                cultural_ids,
            ),
            (
                "Natural Earth Physical (10m)",
                "Natural Earth 1:10m physical vector datasets",
                physical_ids,
            ),
        ]

        for coll_name, coll_desc, dataset_ids in collections_spec:
            if not dataset_ids:
                continue

            coll_id = await create_or_get_collection(
                client, base_url, headers, coll_name, coll_desc
            )
            if coll_id is None:
                print(f"Failed to create/find collection: {coll_name}")
                continue

            resp = await client.post(
                f"{base_url}/api/catalog/collections/{coll_id}/datasets/",
                headers=headers,
                json={"dataset_ids": dataset_ids},
            )
            resp.raise_for_status()
            added = resp.json().get("added", 0)
            print(
                f"  Collection {coll_name}: "
                f"{added} dataset(s) added ({len(dataset_ids)} total)"
            )

    except Exception as exc:
        print(f"Collection assignment failed: {exc}")
        logger.warning("Collection assignment error: %s", exc)


# ---------------------------------------------------------------------------
# Concurrent processing coroutine
# ---------------------------------------------------------------------------


async def process_one(
    entry: dict,
    index: int,
    total: int,
    sem: asyncio.Semaphore,
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    existing: dict[str, str],
    cache_dir: Path | None,
    results: list[dict],
) -> None:
    """Process a single dataset: download (or load cache) + ingest.

    Runs inside a semaphore to limit concurrent API streams.
    Catches all exceptions per-dataset to avoid cancelling sibling tasks.
    """
    stem = entry["stem"]
    theme = entry["theme"]
    filename = f"{stem}.zip"
    tag = f"[{index}/{total}]"

    # Idempotency check (no semaphore needed -- read-only check)
    if filename in existing:
        print(f"  {tag} Skipping {stem} (already imported)")
        results.append({
            "stem": stem,
            "status": "skipped",
            "theme": theme,
            "dataset_id": existing[filename],
        })
        return

    async with sem:
        try:
            url = f"{CDN_BASE}/{theme}/{filename}"
            print(f"  {tag} Downloading {stem}...")
            data = await download_or_load_cache(client, url, stem, cache_dir)

            name = generate_name(stem)
            tags = generate_tags(stem, theme)

            # Encoding detection (ING-04)
            encoding: str | None = None
            missing_cpg = detect_missing_cpg(data, stem)
            if missing_cpg and stem in ENCODING_OVERRIDE_STEMS:
                encoding = "UTF-8"
                print(f"  {tag} Warning: {stem} missing .cpg file, using UTF-8 encoding override")
            elif missing_cpg:
                print(f"  {tag} Note: {stem} missing .cpg file (encoding auto-detect)")

            # Ingest through three-step API
            print(f"  {tag} Ingesting {stem}...")
            result = await ingest_dataset(
                client, base_url, api_key, stem, data, name, tags,
                encoding=encoding,
            )

            if result.get("status") == "failed":
                raise RuntimeError(
                    result.get("error_message", "Unknown ingest error")
                )

            results.append({
                "stem": stem,
                "status": "succeeded",
                "theme": theme,
                "dataset_id": result.get("dataset_id"),
            })
            print(f"  {tag} Done {stem}")

        except Exception as exc:
            results.append({
                "stem": stem,
                "status": "failed",
                "theme": theme,
                "error": str(exc),
            })
            print(f"  {tag} Failed {stem}: {exc}")


# ---------------------------------------------------------------------------
# Main import pipeline
# ---------------------------------------------------------------------------


async def main(args: argparse.Namespace, datasets: list[dict]) -> None:
    """Download and ingest Natural Earth datasets into GeoLens."""
    base_url = args.base_url.rstrip("/")
    api_key = args.api_key

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(300.0, connect=30.0),
        follow_redirects=True,
    ) as client:
        # Validate connectivity
        try:
            health_resp = await client.get(f"{base_url}/api/health")
            health_resp.raise_for_status()
        except (httpx.HTTPStatusError, httpx.TransportError) as exc:
            print(f"Cannot reach GeoLens at {base_url}: {exc}")
            sys.exit(1)

        # Cache directory setup
        cache_dir: Path | None = args.cache_dir
        if cache_dir is not None:
            cache_dir.mkdir(parents=True, exist_ok=True)
            clean_partial_downloads(cache_dir)
            print(f"Using download cache: {cache_dir}")

        # Build idempotency map (source_filename -> dataset_id)
        print("Checking existing datasets...")
        existing = await fetch_existing_datasets(client, base_url, api_key)
        if existing:
            print(f"Found {len(existing)} existing dataset(s) in catalog")

        # Shared results list (safe: asyncio is single-threaded)
        results: list[dict] = []

        # Bounded concurrency: up to 3 parallel download+ingest streams
        sem = asyncio.Semaphore(3)
        total = len(datasets)

        print(f"\nImporting {total} datasets...")

        async with asyncio.TaskGroup() as tg:
            for i, entry in enumerate(datasets, 1):
                tg.create_task(
                    process_one(
                        entry=entry,
                        index=i,
                        total=total,
                        sem=sem,
                        client=client,
                        base_url=base_url,
                        api_key=api_key,
                        existing=existing,
                        cache_dir=cache_dir,
                        results=results,
                    )
                )

        # Aggregate results
        succeeded = sum(1 for r in results if r["status"] == "succeeded")
        skipped = sum(1 for r in results if r["status"] == "skipped")
        failed = sum(1 for r in results if r["status"] == "failed")
        failures = [
            {"stem": r["stem"], "error": r.get("error", "")}
            for r in results
            if r["status"] == "failed"
        ]

        print_summary(total, succeeded, skipped, failed, failures)

        # Assign datasets to collections by theme
        print()
        print("--- Collection Assignment ---")
        await create_collections(client, base_url, api_key, results)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    args = parse_args()

    # Filter by theme
    datasets = [
        d for d in DATASETS if args.theme == "all" or d["theme"] == args.theme
    ]

    # Filter by dataset stem
    if args.dataset:
        datasets = [d for d in datasets if d["stem"] == args.dataset]
        if not datasets:
            print(f"Error: dataset '{args.dataset}' not found in manifest", file=sys.stderr)
            sys.exit(1)

    if args.dry_run:
        run_dry_run(datasets)
    else:
        if not args.api_key:
            print(
                "Error: --api-key or GEOLENS_API_KEY env var required",
                file=sys.stderr,
            )
            sys.exit(1)
        asyncio.run(main(args, datasets))
