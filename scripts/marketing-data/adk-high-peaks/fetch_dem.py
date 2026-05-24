#!/usr/bin/env python3
"""Download USGS 3DEP 1m DEM tiles for the Adirondack High Peaks AOI.

AOI bbox (WGS84): -74.05 44.08 -73.85 44.32  (12 mi E-W x 16 mi N-S; Lake Placid +
Mt. Marcy + Algonquin + Heart Lake + Avalanche Lake).

Usage:
    python fetch_dem.py                            # DEM 1m via TNM API
    python fetch_dem.py --output-dir /custom/dir
    python fetch_dem.py --dataset naip             # NOTE: TNM no longer serves NAIP for NY (returns 0).
                                                   # Use fetch_aerial.py instead (NY State orthos service).

Idempotent: skips tiles already present with size > 0.
Retries: 3 attempts per tile, 2^attempt s backoff.

Requires: python3, httpx (in repo venv).
"""

import argparse
import asyncio
import json
import logging
import sys
import time
import urllib.parse
from pathlib import Path

try:
    import httpx
except ImportError:
    print("Missing httpx. Install with: pip install httpx", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AOI_BBOX = "-74.05,44.08,-73.85,44.32"  # TNM API format: minx,miny,maxx,maxy
TNM_API = "https://tnmaccess.nationalmap.gov/api/v1/products"

# DEM project preference: Clinton_Essex_Lake_Champlain is denser native LiDAR (QL2)
# than NY_NH_Gaps. We dedupe by tile grid (~10km x 10km) and prefer Clinton tiles.
DEM_PROJECT_PREFERENCE = [
    "2014_New_York_Clinton_Essex_Lake_Champlain_QL2_LiDAR",
    "NY_NH_Gaps_D24",
]

DATASETS = {
    "dem": {
        "tnm_dataset": "Digital Elevation Model (DEM) 1 meter",
        "output_subdir": "dem",
        "filename_prefix": "USGS_1M_",
    },
    "naip": {
        "tnm_dataset": "USDA National Agriculture Imagery Program (NAIP)",
        "output_subdir": "aerial",
        "filename_prefix": "",  # NAIP filenames vary, use server-provided names
    },
}

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TNM API: list products
# ---------------------------------------------------------------------------


async def list_tnm_products(client: httpx.AsyncClient, dataset_name: str, bbox: str) -> list[dict]:
    """Call TNM Access API and return the list of products matching dataset+bbox."""
    params = {
        "datasets": dataset_name,
        "bbox": bbox,
        "prodFormats": "GeoTIFF",
        "max": 50,
        "outputFormat": "JSON",
    }
    # TNM expects spaces literally in `datasets` (no URL-encode of spaces -> '+').
    # httpx will quote them as %20 which TNM accepts.
    print(f"Querying TNM API for {dataset_name!r} in bbox {bbox}...")
    resp = await client.get(TNM_API, params=params, timeout=60)
    resp.raise_for_status()
    body = resp.json()
    items = body.get("items", [])
    if not items:
        print(f"  No tiles returned. Full response: {json.dumps(body, indent=2)[:500]}")
    return items


def select_dem_tiles(items: list[dict]) -> list[dict]:
    """Dedupe DEM tiles by tile grid, preferring Clinton_Essex_Lake_Champlain.

    Each USGS DEM tile is named like USGS_1M_18_xN_yN.tif. The (xN, yN) pair
    identifies the 10km x 10km grid cell. Multiple projects may cover the
    same cell — pick the project highest in DEM_PROJECT_PREFERENCE.
    """
    # First pass: bucket by tile grid key (filename without project metadata)
    by_grid: dict[str, list[dict]] = {}
    for item in items:
        title = item.get("title", "")
        # USGS 1M tile titles like "USGS one meter x59y492 NY..."
        # Use the source title which is consistent; fall back to downloadURL filename.
        download_url = item.get("downloadURL", "")
        if not download_url:
            continue
        filename = download_url.rsplit("/", 1)[-1]
        # Extract grid key — look for x{N}y{N} pattern in filename
        import re
        m = re.search(r"x\d+y\d+", filename)
        grid_key = m.group(0) if m else filename
        by_grid.setdefault(grid_key, []).append(item)

    # Second pass: for each grid cell, pick the highest-preference project
    selected: list[dict] = []
    for grid_key, candidates in sorted(by_grid.items()):
        def project_rank(it: dict) -> int:
            url = it.get("downloadURL", "")
            for i, proj in enumerate(DEM_PROJECT_PREFERENCE):
                if proj in url:
                    return i
            return len(DEM_PROJECT_PREFERENCE)
        candidates.sort(key=project_rank)
        selected.append(candidates[0])
    return selected


# ---------------------------------------------------------------------------
# Download with retry
# ---------------------------------------------------------------------------


async def download_tile(
    client: httpx.AsyncClient,
    url: str,
    dest: Path,
    expected_size_mb: float | None = None,
) -> bool:
    """Stream a tile to disk with retry. Returns True if downloaded fresh, False if skipped (already exists)."""
    if dest.exists() and dest.stat().st_size > 0:
        size_mb = dest.stat().st_size / (1024 * 1024)
        print(f"  SKIP (already exists, {size_mb:.1f} MB): {dest.name}")
        return False

    tmp = dest.with_suffix(dest.suffix + ".tmp")
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            t0 = time.monotonic()
            async with client.stream("GET", url, timeout=httpx.Timeout(600.0, connect=30.0)) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", 0))
                downloaded = 0
                with open(tmp, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=1 << 20):
                        f.write(chunk)
                        downloaded += len(chunk)
            tmp.rename(dest)
            elapsed = time.monotonic() - t0
            size_mb = dest.stat().st_size / (1024 * 1024)
            rate_mbs = size_mb / elapsed if elapsed > 0 else 0
            print(f"  DONE ({size_mb:.1f} MB in {elapsed:.1f}s, {rate_mbs:.1f} MB/s): {dest.name}")
            return True
        except (httpx.HTTPStatusError, httpx.TransportError, httpx.TimeoutException) as exc:
            if attempt < max_attempts:
                delay = 2 ** attempt
                print(f"  RETRY {attempt}/{max_attempts} after {delay}s: {exc}", file=sys.stderr)
                await asyncio.sleep(delay)
            else:
                print(f"  FAILED after {max_attempts} attempts: {exc}", file=sys.stderr)
                if tmp.exists():
                    tmp.unlink()
                raise
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main(args: argparse.Namespace) -> int:
    if args.dataset not in DATASETS:
        print(f"Unknown dataset: {args.dataset}. Options: {list(DATASETS)}", file=sys.stderr)
        return 1

    ds_cfg = DATASETS[args.dataset]
    output_dir = Path(args.output_dir) / ds_cfg["output_subdir"]
    output_dir.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(
        headers={"User-Agent": "geolens-marketing-data/1.0"},
        follow_redirects=True,
    ) as client:
        items = await list_tnm_products(client, ds_cfg["tnm_dataset"], AOI_BBOX)
        if not items:
            print("No tiles returned from TNM API. Aborting.", file=sys.stderr)
            return 1

        # For DEM, dedupe by grid cell and prefer Clinton_Essex
        if args.dataset == "dem":
            items = select_dem_tiles(items)

        # Print summary table
        print()
        print(f"=== TNM products: {args.dataset.upper()} (AOI bbox {AOI_BBOX}) ===")
        print(f"{'#':>3}  {'size_MB':>10}  {'project':<60}  filename")
        total_bytes = 0
        for i, item in enumerate(items, 1):
            url = item.get("downloadURL", "")
            filename = url.rsplit("/", 1)[-1] if url else "(no url)"
            size_bytes = item.get("sizeInBytes") or 0
            size_mb = size_bytes / (1024 * 1024)
            total_bytes += size_bytes
            # Extract project name from URL path
            project = "?"
            if "/Projects/" in url:
                project = url.split("/Projects/")[1].split("/")[0]
            elif "naip" in url.lower():
                # NAIP URLs may not have /Projects/ — extract county-quad indicator instead
                parts = url.split("/")
                for p in parts:
                    if "ny" in p.lower() and "naip" in p.lower():
                        project = p
                        break
            print(f"{i:>3}  {size_mb:>10.1f}  {project:<60}  {filename}")

        total_gb = total_bytes / (1024 * 1024 * 1024)
        print()
        print(f"Total: {len(items)} tiles, {total_gb:.2f} GB combined")

        if total_gb > 5.0 and not args.yes:
            try:
                resp = input(f"Total download is {total_gb:.2f} GB. Proceed? [y/N]: ")
            except EOFError:
                resp = "n"
            if resp.strip().lower() not in ("y", "yes"):
                print("Aborted by user.")
                return 2

        # Download
        print()
        print(f"=== Downloading {len(items)} tiles to {output_dir} ===")
        downloaded = 0
        skipped = 0
        for i, item in enumerate(items, 1):
            url = item.get("downloadURL", "")
            if not url:
                continue
            filename = url.rsplit("/", 1)[-1]
            dest = output_dir / filename
            print(f"[{i}/{len(items)}] {filename}")
            try:
                fresh = await download_tile(client, url, dest)
                if fresh:
                    downloaded += 1
                else:
                    skipped += 1
            except Exception as exc:
                print(f"  ERROR: {exc}", file=sys.stderr)

        # Final tally
        total_size_bytes = sum(p.stat().st_size for p in output_dir.glob("*.tif"))
        total_size_gb = total_size_bytes / (1024 * 1024 * 1024)
        print()
        print(f"=== Done ({args.dataset.upper()}) ===")
        print(f"Downloaded fresh: {downloaded}")
        print(f"Skipped (cached): {skipped}")
        print(f"Output dir: {output_dir}")
        print(f"Total on-disk: {total_size_gb:.2f} GB")
        return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Download USGS 3DEP DEM or NAIP tiles for the ADK High Peaks AOI")
    p.add_argument("--dataset", choices=["dem", "naip"], default="dem",
                   help="Dataset to download (default: dem)")
    p.add_argument("--output-dir", default=".scratch/adk-data",
                   help="Output root dir (default: .scratch/adk-data)")
    p.add_argument("--yes", "-y", action="store_true",
                   help="Skip confirmation when total > 5 GB")
    return p.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.exit(asyncio.run(main(args)))
