#!/usr/bin/env python3
"""Thematic demo seeder for GeoLens.

This is the FROZEN orchestrator. It owns:
  - All 3 ingest helpers (vector_ne_cdn, vector_local_with_summary, raster_local)
  - The collection creation flow
  - The fixture apply loop
  - The main() entry point

Plans 218-02, 218-03, 218-04 must NOT modify this file. They only modify their
assigned theme module (scripts/demo/themes/themeN.py) and their fixture JSON files.
"""

import argparse
import asyncio
import importlib.util
import json
import logging
import sys
from pathlib import Path

import httpx

# Import seed-natural-earth.py primitives via importlib (file has hyphen)
_ne_path = Path(__file__).parent.parent / "seed-natural-earth.py"
_ne_spec = importlib.util.spec_from_file_location("seed_natural_earth", _ne_path)
seed_natural_earth = importlib.util.module_from_spec(_ne_spec)
_ne_spec.loader.exec_module(seed_natural_earth)

fetch_existing_datasets = seed_natural_earth.fetch_existing_datasets
download_or_load_cache = seed_natural_earth.download_or_load_cache
ingest_dataset = seed_natural_earth.ingest_dataset
poll_job = seed_natural_earth.poll_job
create_or_get_collection = seed_natural_earth.create_or_get_collection
generate_name = seed_natural_earth.generate_name
clean_partial_downloads = seed_natural_earth.clean_partial_downloads

# Import per-theme dataset modules
sys.path.insert(0, str(Path(__file__).parent))
from themes import theme1, theme2, theme3
from lib.apply_fixture import apply_fixture

THEMES = [theme1, theme2, theme3]
NE_CDN_BASE = "https://naciscdn.org/naturalearth/10m"

logger = logging.getLogger("seed-thematic-demo")


# ------------------------------------------------------------------
# FROZEN INGEST HELPERS — Plans 02/03/04 must not modify these
# ------------------------------------------------------------------

async def ingest_vector_ne_cdn(client, base_url, api_key, entry, existing):
    """Ingest a Natural Earth vector layer from the NACIS CDN."""
    stem = entry["stem"]
    filename = f"{stem}.zip"
    if filename in existing:
        return {"stem": stem, "status": "skipped", "dataset_id": existing[filename]}
    url = f"{NE_CDN_BASE}/{entry['ne_theme']}/{filename}"
    # Cache dir comes from main() — passed via httpx context closure or arg
    # For simplicity, download_or_load_cache will be called with the cache_dir from main()
    raise NotImplementedError("Use ingest_vector_ne_cdn_with_cache")


async def ingest_vector_ne_cdn_with_cache(client, base_url, api_key, entry, existing, cache_dir):
    """Ingest a Natural Earth vector layer from the NACIS CDN using local cache."""
    stem = entry["stem"]
    filename = f"{stem}.zip"
    if filename in existing:
        return {"stem": stem, "status": "skipped", "dataset_id": existing[filename]}
    url = f"{NE_CDN_BASE}/{entry['ne_theme']}/{filename}"
    data = await download_or_load_cache(client, url, stem, cache_dir)
    name = generate_name(stem)
    tags = ["demo", "natural-earth", "10m", entry.get("license", "")]
    result = await ingest_dataset(client, base_url, api_key, stem, data, name, tags)
    if result.get("status") == "failed":
        return {"stem": stem, "status": "failed", "error": result.get("error_message")}
    return {"stem": stem, "status": "succeeded", "dataset_id": result.get("dataset_id")}


async def ingest_vector_local_with_summary(client, base_url, api_key, entry, existing):
    """Ingest a local vector file (typically a pre-joined GeoJSON or a CSV with lat/lon)."""
    stem = entry["stem"]
    path = Path(entry["local_path"])
    if not path.exists():
        return {"stem": stem, "status": "failed", "error": f"local file missing: {path} — Plan 05 Dockerfile must create it"}
    filename = path.name
    if filename in existing:
        return {"stem": stem, "status": "skipped", "dataset_id": existing[filename]}
    data = path.read_bytes()
    name = generate_name(stem)
    tags = ["demo", entry.get("license", "")]
    # Custom 3-step pipeline so we can pass `summary` in the commit body (or PATCH it after)
    headers = {"X-Api-Key": api_key}
    # Determine the upload filename — use the original extension for magic-byte detection
    ext = path.suffix  # .geojson or .csv
    upload = await client.post(
        f"{base_url}/api/ingest/upload",
        headers=headers,
        files={"file": (filename, data, "application/octet-stream")},
    )
    upload.raise_for_status()
    job_id = upload.json()["job_id"]
    prev = await client.post(f"{base_url}/api/ingest/preview/{job_id}", headers=headers)
    prev.raise_for_status()
    commit_body = {
        "title": name,
        "visibility": "public",
        "srid_override": 4326,
    }
    # Try with summary in commit body; if schema rejects, fall back to PATCH after
    commit = await client.post(
        f"{base_url}/api/ingest/commit/{job_id}",
        headers={**headers, "Content-Type": "application/json"},
        json=commit_body,
    )
    if commit.status_code >= 400:
        return {"stem": stem, "status": "failed", "error": f"commit {commit.status_code}: {commit.text[:300]}"}
    result = await poll_job(client, base_url, api_key, job_id, timeout=300)
    if result.get("status") != "complete":
        return {"stem": stem, "status": "failed", "error": result.get("error_message")}
    dataset_id = result.get("dataset_id")
    # PATCH the dataset description with the summary (carries snapshot_date, license, STAC fields)
    if dataset_id and entry.get("summary"):
        patch_resp = await client.patch(
            f"{base_url}/api/datasets/{dataset_id}",
            headers={**headers, "Content-Type": "application/json"},
            json={"description": entry["summary"]},
        )
        if patch_resp.status_code >= 400:
            logger.warning("Failed to PATCH description for %s: %s", stem, patch_resp.text[:200])
    return {"stem": stem, "status": "succeeded", "dataset_id": dataset_id}


async def ingest_raster_local(client, base_url, api_key, entry, existing):
    """Ingest a local raster (COG) with extended timeout for raster processing."""
    stem = entry["stem"]
    path = Path(entry["local_path"])
    if not path.exists():
        return {"stem": stem, "status": "failed", "error": f"local file missing: {path}"}
    filename = path.name
    if filename in existing:
        return {"stem": stem, "status": "skipped", "dataset_id": existing[filename]}
    data = path.read_bytes()
    name = generate_name(stem)
    headers = {"X-Api-Key": api_key}
    upload = await client.post(
        f"{base_url}/api/ingest/upload",
        headers=headers,
        files={"file": (filename, data, "image/tiff")},
    )
    upload.raise_for_status()
    job_id = upload.json()["job_id"]
    prev = await client.post(f"{base_url}/api/ingest/preview/{job_id}", headers=headers)
    prev.raise_for_status()
    commit_body = {
        "title": name,
        "visibility": "public",
        "compression": "DEFLATE",
        "resampling": "bilinear",
    }
    # Some commit endpoints accept summary directly; if not, PATCH after
    commit = await client.post(
        f"{base_url}/api/ingest/commit/{job_id}",
        headers={**headers, "Content-Type": "application/json"},
        json=commit_body,
    )
    if commit.status_code >= 400:
        return {"stem": stem, "status": "failed", "error": f"commit {commit.status_code}: {commit.text[:300]}"}
    # Raster ingest is slow — extend timeout to 600s per 218-RESEARCH.md G6
    result = await poll_job(client, base_url, api_key, job_id, timeout=600)
    if result.get("status") != "complete":
        return {"stem": stem, "status": "failed", "error": result.get("error_message")}
    dataset_id = result.get("dataset_id")
    if dataset_id and entry.get("summary"):
        patch_resp = await client.patch(
            f"{base_url}/api/datasets/{dataset_id}",
            headers={**headers, "Content-Type": "application/json"},
            json={"description": entry["summary"]},
        )
        if patch_resp.status_code >= 400:
            logger.warning("Failed to PATCH description for %s: %s", stem, patch_resp.text[:200])
    return {"stem": stem, "status": "succeeded", "dataset_id": dataset_id}


async def create_vrt_mosaic(client, base_url, api_key, source_dataset_ids, name, summary):
    """Create a VRT mosaic from existing raster dataset IDs."""
    headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}
    resp = await client.post(
        f"{base_url}/api/ingest/vrt/create",
        headers=headers,
        json={"source_dataset_ids": source_dataset_ids, "vrt_type": "mosaic"},
    )
    resp.raise_for_status()
    job_id = resp.json()["job_id"]
    return await poll_job(client, base_url, api_key, job_id, timeout=600)


async def ingest_theme(client, base_url, api_key, theme_module, existing, cache_dir):
    """Ingest all DATASETS for one theme module. Dispatches by entry type/source."""
    results = []
    for entry in theme_module.DATASETS:
        t = entry["type"]
        s = entry["source"]
        if t == "vector" and s == "ne_cdn":
            r = await ingest_vector_ne_cdn_with_cache(client, base_url, api_key, entry, existing, cache_dir)
        elif t == "vector" and s == "local":
            r = await ingest_vector_local_with_summary(client, base_url, api_key, entry, existing)
        elif t == "raster" and s == "local":
            r = await ingest_raster_local(client, base_url, api_key, entry, existing)
        else:
            r = {"stem": entry["stem"], "status": "failed", "error": f"unknown type/source: {t}/{s}"}
        results.append(r)
        print(f"  {entry['stem']}: {r['status']}{' (' + r.get('error', '') + ')' if r.get('error') else ''}")
    return results


async def assign_collection(client, base_url, api_key, theme_module, results):
    """Create the theme's collection and bulk-assign all succeeded/skipped dataset IDs."""
    headers = {"X-Api-Key": api_key}
    coll_id = await create_or_get_collection(
        client, base_url, headers, theme_module.THEME_NAME, theme_module.THEME_DESCRIPTION
    )
    if not coll_id:
        print(f"  Failed to create collection {theme_module.THEME_NAME}")
        return
    ids = [r["dataset_id"] for r in results if r.get("dataset_id") and r["status"] in ("succeeded", "skipped")]
    if ids:
        resp = await client.post(
            f"{base_url}/api/catalog/collections/{coll_id}/datasets",
            headers={**headers, "Content-Type": "application/json"},
            json={"dataset_ids": ids},
        )
        print(f"  Collection {theme_module.THEME_NAME}: {len(ids)} datasets assigned (status {resp.status_code})")


async def apply_theme_fixtures(client, base_url, api_key, theme_module, existing):
    """Apply all fixture files in scripts/demo/fixtures/maps/ matching this theme."""
    fixtures_dir = Path(__file__).parent / "fixtures" / "maps"
    headers = {"X-Api-Key": api_key}
    applied = []
    for fp in sorted(fixtures_dir.glob("*.json")):
        try:
            fixture = json.loads(fp.read_text())
            if fixture.get("_meta", {}).get("theme") != theme_module.THEME_NAME:
                continue
            map_id = await apply_fixture(client, base_url, headers, fp, existing)
            applied.append({"fixture": fp.name, "map_id": map_id})
            print(f"  Applied fixture {fp.name} → map {map_id}")
        except Exception as exc:
            print(f"  FAILED fixture {fp.name}: {exc}")
    return applied


async def main_async(args):
    """Main async entry point. Runs ingest, collection assignment, and fixture apply for all themes."""
    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    clean_partial_downloads(cache_dir)

    async with httpx.AsyncClient(timeout=120.0) as client:
        existing = await fetch_existing_datasets(client, args.base_url, args.api_key)
        print(f"=== GeoLens Thematic Demo Seeder ===")
        print(f"Existing datasets: {len(existing)}")

        themes_to_run = THEMES if args.theme_only is None else [THEMES[args.theme_only]]
        for tm in themes_to_run:
            print(f"\n--- {tm.THEME_NAME} ---")
            if not tm.DATASETS:
                print(f"  (no datasets registered for {tm.THEME_NAME} yet)")
                continue
            results = await ingest_theme(client, args.base_url, args.api_key, tm, existing, cache_dir)
            # Refresh existing to include newly ingested
            existing = await fetch_existing_datasets(client, args.base_url, args.api_key)
            # VRT mosaic only applies to Theme 1
            if tm.THEME_IDX == 0:
                raster_ids = [r["dataset_id"] for r in results
                               if r.get("dataset_id") and any(d["stem"] == r["stem"] and d["type"] == "raster" for d in tm.DATASETS)]
                if len(raster_ids) >= 2:
                    try:
                        vrt_result = await create_vrt_mosaic(client, args.base_url, args.api_key, raster_ids[:2],
                            name="Planet Earth Composite VRT",
                            summary="Mosaic of Theme 1 raster sources for Map 1.1.")
                        print(f"  VRT mosaic created: {vrt_result.get('dataset_id')}")
                        if vrt_result.get("dataset_id"):
                            results.append({"stem": "planet-earth-vrt", "status": "succeeded", "dataset_id": vrt_result["dataset_id"]})
                            existing = await fetch_existing_datasets(client, args.base_url, args.api_key)
                    except Exception as exc:
                        print(f"  VRT creation failed: {exc}")
            await assign_collection(client, args.base_url, args.api_key, tm, results)
            await apply_theme_fixtures(client, args.base_url, args.api_key, tm, existing)

        print("\n=== Demo seed complete ===")


def main():
    parser = argparse.ArgumentParser(description="GeoLens thematic demo seeder")
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--base-url", default="http://api:8000")
    parser.add_argument("--cache-dir", default="/data/demo/cache")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--theme-only", type=int, choices=[0, 1, 2], default=None)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    logging.basicConfig(level=args.log_level.upper())

    if args.dry_run:
        print("=== GeoLens Thematic Demo Seeder (DRY RUN) ===")
        print(f"Themes: {len(THEMES)}")
        for i, tm in enumerate(THEMES, 1):
            print(f"  {i}. {tm.THEME_NAME} ({len(tm.DATASETS)} datasets)")
        fixtures_dir = Path(__file__).parent / "fixtures" / "maps"
        fixture_count = len(list(fixtures_dir.glob("*.json"))) if fixtures_dir.exists() else 0
        print(f"Fixture maps: {fixture_count}  ({fixtures_dir})")
        print("OK")
        sys.exit(0)

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
