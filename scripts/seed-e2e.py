#!/usr/bin/env python3
"""Seed GeoLens with the 2 datasets needed by Playwright e2e tests.

Downloads ne_10m_admin_0_countries and ne_10m_reefs from the NACIS CDN,
ingests them via the upload API, and creates a "World Countries" collection.

Requires: pip install httpx
"""

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

try:
    import httpx
except ImportError:
    print("Missing required package. Install with:\n  pip install httpx", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CDN_BASE = "https://naciscdn.org/naturalearth/10m"
DEFAULT_BASE_URL = "http://localhost:8080"

DATASETS = [
    {"stem": "ne_10m_admin_0_countries", "theme": "cultural", "name": "Admin 0 Countries (10m)"},
    {"stem": "ne_10m_reefs", "theme": "physical", "name": "Reefs (10m)"},
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def download_or_cache(stem: str, theme: str, cache_dir: Path) -> bytes:
    """Download dataset ZIP or load from cache."""
    cached = cache_dir / f"{stem}.zip"
    if cached.exists() and cached.stat().st_size > 0:
        print(f"  Using cached {stem}")
        return cached.read_bytes()

    url = f"{CDN_BASE}/{theme}/{stem}.zip"
    print(f"  Downloading {stem}...")
    resp = httpx.get(url, follow_redirects=True, timeout=120.0)
    resp.raise_for_status()
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(resp.content)
    return resp.content


async def poll_job(
    client: httpx.AsyncClient, base_url: str, headers: dict, job_id: str,
    timeout: int = 120,
) -> dict:
    """Poll GET /api/jobs/{job_id} until complete or failed."""
    start = time.monotonic()
    while True:
        resp = await client.get(f"{base_url}/api/jobs/{job_id}", headers=headers)
        resp.raise_for_status()
        result = resp.json()
        status = result.get("status")
        if status in ("complete", "failed"):
            return result
        if time.monotonic() - start >= timeout:
            raise TimeoutError(f"Job {job_id} did not complete within {timeout}s")
        await asyncio.sleep(3)


async def ingest_dataset(
    client: httpx.AsyncClient, base_url: str, headers: dict,
    stem: str, data: bytes, name: str,
) -> str:
    """Upload, preview, commit, poll. Returns dataset_id."""
    # Step 1 - Upload
    resp = await client.post(
        f"{base_url}/api/ingest/upload/",
        headers=headers,
        files={"file": (f"{stem}.zip", data, "application/zip")},
    )
    resp.raise_for_status()
    job_id = resp.json()["job_id"]

    # Step 2 - Preview
    resp = await client.post(f"{base_url}/api/ingest/preview/{job_id}", headers=headers)
    resp.raise_for_status()

    # Step 3 - Commit
    resp = await client.post(
        f"{base_url}/api/ingest/commit/{job_id}",
        headers=headers,
        json={"title": name, "visibility": "public", "srid_override": 4326},
    )
    resp.raise_for_status()

    # Step 4 - Poll
    result = await poll_job(client, base_url, headers, job_id)
    if result.get("status") == "failed":
        raise RuntimeError(f"Ingest failed for {stem}: {result.get('error_message', 'unknown')}")

    dataset_id = result["dataset_id"]
    print(f"  Ingested {stem} -> {dataset_id}")
    return dataset_id


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main(args: argparse.Namespace) -> None:
    """Seed the 2 e2e datasets and create a collection."""
    base_url = args.base_url.rstrip("/")
    headers = {"X-Api-Key": args.api_key}
    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.monotonic()
    dataset_ids: dict[str, str] = {}

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(300.0, connect=30.0), follow_redirects=True,
    ) as client:
        # Download and ingest each dataset
        for ds in DATASETS:
            data = download_or_cache(ds["stem"], ds["theme"], cache_dir)
            ds_id = await ingest_dataset(client, base_url, headers, ds["stem"], data, ds["name"])
            dataset_ids[ds["stem"]] = ds_id

        # Create "World Countries" collection
        countries_id = dataset_ids.get("ne_10m_admin_0_countries")
        if countries_id:
            resp = await client.post(
                f"{base_url}/api/catalog/collections/",
                headers=headers,
                json={"name": "World Countries"},
            )
            if resp.status_code in (201, 409):
                coll_id = resp.json().get("id")
                if coll_id:
                    await client.post(
                        f"{base_url}/api/catalog/collections/{coll_id}/datasets",
                        headers=headers,
                        json={"dataset_ids": [countries_id]},
                    )
                    print(f"  Collection 'World Countries' -> {coll_id}")
            else:
                resp.raise_for_status()

    elapsed = time.monotonic() - t0
    print(f"\nDone: {len(dataset_ids)} datasets seeded, 1 collection created ({elapsed:.1f}s)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed GeoLens with the 2 datasets needed by Playwright e2e tests",
    )
    parser.add_argument(
        "--api-key",
        required=True,
        help="GeoLens API key",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("GEOLENS_BASE_URL", DEFAULT_BASE_URL),
        help=f"GeoLens base URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--cache-dir",
        default="./cache",
        help="Directory to cache downloaded ZIPs (default: ./cache)",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(main(args))
