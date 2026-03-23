#!/usr/bin/env python3
"""Seed GeoLens with public data from an ArcGIS Online organization.

Discovers all public Feature/Map Services in an ArcGIS Online organization,
downloads each layer as GeoJSON, and ingests into GeoLens via the three-step
upload API (upload → preview → commit → poll).

Requires: pip install httpx

Usage:
    # Dry run — list discoverable layers
    python scripts/seed-ago-data.py --dry-run

    # Import all layers into GeoLens
    python scripts/seed-ago-data.py --api-key <key>

    # Import from a different org
    python scripts/seed-ago-data.py --org-url https://otherorg.maps.arcgis.com --api-key <key>
"""

import argparse
import asyncio
import io
import json
import logging
import os
import sys
import time
import zipfile
from pathlib import Path

try:
    import httpx
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

DEFAULT_ORG_URL = "https://njhighlands.maps.arcgis.com"
DEFAULT_BASE_URL = "http://localhost:8080"

# Item types that contain downloadable spatial data
DOWNLOADABLE_TYPES = {"Feature Service", "Map Service"}

# Max features per ArcGIS query (servers typically cap at 1000-2000)
MAX_RECORD_COUNT = 2000

# Pause between ArcGIS API pages to be respectful
REQUEST_DELAY = 0.3

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ArcGIS Online discovery
# ---------------------------------------------------------------------------


async def get_org_id(client: httpx.AsyncClient, org_url: str) -> tuple[str, str]:
    """Return (org_id, org_name) from the portal self endpoint."""
    resp = await client.get(
        f"{org_url}/sharing/rest/portals/self", params={"f": "json"}
    )
    resp.raise_for_status()
    data = resp.json()
    return data["id"], data.get("name", "Unknown")


async def search_public_items(
    client: httpx.AsyncClient, org_url: str, org_id: str
) -> list[dict]:
    """Paginate the ArcGIS search API for all public items in the org."""
    items: list[dict] = []
    start = 1

    while True:
        resp = await client.get(
            f"{org_url}/sharing/rest/search",
            params={
                "q": f"accountid:{org_id} access:public",
                "num": 100,
                "start": start,
                "sortField": "title",
                "sortOrder": "asc",
                "f": "json",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        items.extend(results)

        next_start = data.get("nextStart", -1)
        total = data.get("total", 0)
        logger.info("Fetched %d/%d items...", len(items), total)

        if next_start == -1 or next_start > total:
            break
        start = next_start

    return items


async def get_service_layers(
    client: httpx.AsyncClient, service_url: str
) -> list[dict]:
    """Get all layers (and tables) from a Feature/Map Service."""
    resp = await client.get(service_url.rstrip("/"), params={"f": "json"})
    resp.raise_for_status()
    data = resp.json()
    layers = data.get("layers") or []
    tables = data.get("tables") or []
    return layers + tables


async def download_layer_geojson(
    client: httpx.AsyncClient, layer_url: str, layer_name: str
) -> dict | None:
    """Download all features from a layer as GeoJSON, handling pagination."""
    # Get count
    resp = await client.get(
        layer_url + "/query",
        params={"where": "1=1", "returnCountOnly": "true", "f": "json"},
    )
    resp.raise_for_status()
    total_count = resp.json().get("count", 0)
    if total_count == 0:
        logger.warning("    Layer '%s' has 0 features, skipping", layer_name)
        return None

    # Get server max record count
    resp = await client.get(layer_url, params={"f": "json"})
    resp.raise_for_status()
    server_max = resp.json().get("maxRecordCount", 1000)
    page_size = min(server_max, MAX_RECORD_COUNT)

    logger.info(
        "    Downloading %d features (page size: %d)...", total_count, page_size
    )

    all_features: list[dict] = []
    offset = 0
    use_out_sr = True

    while offset < total_count:
        params: dict = {
            "where": "1=1",
            "outFields": "*",
            "resultOffset": offset,
            "resultRecordCount": page_size,
            "f": "geojson",
        }
        if use_out_sr:
            params["outSR"] = "4326"

        resp = await client.get(layer_url + "/query", params=params)
        resp.raise_for_status()

        try:
            data = resp.json()
        except json.JSONDecodeError:
            logger.error(
                "    Failed to parse response for '%s' at offset %d",
                layer_name,
                offset,
            )
            break

        if "error" in data:
            err_msg = data["error"].get("message", str(data["error"]))
            if offset == 0 and use_out_sr:
                # Retry without outSR — some services don't support reprojection
                logger.warning("    Retrying without outSR: %s", err_msg)
                use_out_sr = False
                continue
            logger.error("    API error for '%s': %s", layer_name, err_msg)
            break

        features = data.get("features", [])
        if not features:
            break

        all_features.extend(features)
        offset += len(features)
        logger.info("      %d/%d features...", len(all_features), total_count)
        await asyncio.sleep(REQUEST_DELAY)

    if not all_features:
        return None

    return {"type": "FeatureCollection", "features": all_features}


def geojson_to_zip(geojson: dict, name: str) -> bytes:
    """Package a GeoJSON dict into a ZIP file for upload to GeoLens."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{name}.geojson", json.dumps(geojson))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Metadata helpers
# ---------------------------------------------------------------------------


def sanitize_name(name: str) -> str:
    """Create a filesystem/table-safe name."""
    return (
        name.replace(" ", "_")
        .replace("/", "_")
        .replace("\\", "_")
        .replace(":", "_")
        .replace("(", "")
        .replace(")", "")
        .lower()
    )


def generate_display_name(layer_name: str, service_title: str) -> str:
    """Generate a human-readable display name."""
    name = layer_name.replace("_", " ").title()
    return name


def generate_tags(
    layer_name: str, service_title: str, org_name: str
) -> list[str]:
    """Generate tags for a dataset based on its layer name."""
    tags = [org_name.lower().replace(" ", "-"), "arcgis-online"]
    lower = layer_name.lower()

    tag_keywords = {
        "water": "hydrology",
        "stream": "hydrology",
        "watershed": "hydrology",
        "wetland": "hydrology",
        "riparian": "hydrology",
        "flood": "hydrology",
        "forest": "forestry",
        "wildlife": "ecology",
        "habitat": "ecology",
        "species": "ecology",
        "vernal": "ecology",
        "mussel": "ecology",
        "land_use": "land-use",
        "land_cover": "land-use",
        "impervious": "land-use",
        "zoning": "land-use",
        "agriculture": "agriculture",
        "farm": "agriculture",
        "soil": "agriculture",
        "boundary": "boundaries",
        "municipal": "boundaries",
        "county": "boundaries",
        "trail": "recreation",
        "park": "recreation",
        "road": "transport",
        "bus": "transport",
        "rail": "transport",
        "redevelopment": "planning",
        "center": "planning",
        "contour": "elevation",
        "elevation": "elevation",
        "geolog": "geology",
        "carbonate": "geology",
        "rock": "geology",
        "preserve": "conservation",
        "conservation": "conservation",
    }

    for keyword, tag in tag_keywords.items():
        if keyword in lower and tag not in tags:
            tags.append(tag)

    return tags


# ---------------------------------------------------------------------------
# Full discovery: org → items → layers
# ---------------------------------------------------------------------------


async def discover_layers(
    client: httpx.AsyncClient, org_url: str
) -> tuple[list[dict], str]:
    """Discover all downloadable layers in an ArcGIS Online organization.

    Returns (layers_manifest, org_name) where each entry in layers_manifest is:
        {"service_title": ..., "layer_name": ..., "layer_url": ..., "item_id": ...}
    """
    org_id, org_name = await get_org_id(client, org_url)
    print(f"Organization: {org_name} (ID: {org_id})")

    items = await search_public_items(client, org_url, org_id)

    spatial_items = [i for i in items if i.get("type") in DOWNLOADABLE_TYPES]
    other_items = [i for i in items if i.get("type") not in DOWNLOADABLE_TYPES]

    print(f"\nFound {len(items)} public items:")
    print(f"  {len(spatial_items)} downloadable (Feature/Map Services)")
    print(f"  {len(other_items)} non-spatial (skipped)")
    if other_items:
        type_counts: dict[str, int] = {}
        for i in other_items:
            t = i.get("type", "Unknown")
            type_counts[t] = type_counts.get(t, 0) + 1
        for t, c in sorted(type_counts.items()):
            print(f"    - {t}: {c}")

    manifest: list[dict] = []

    for item in spatial_items:
        title = item.get("title", "untitled")
        item_url = item.get("url", "")
        item_id = item.get("id", "")

        if not item_url:
            logger.warning("Skipping %s — no service URL", title)
            continue

        try:
            layers = await get_service_layers(client, item_url)
        except Exception as e:
            logger.warning("Skipping %s — failed to get layers: %s", title, e)
            continue

        if not layers:
            logger.warning("Skipping %s — no layers", title)
            continue

        for layer in layers:
            layer_id = layer.get("id", 0)
            layer_name = layer.get("name", title)
            layer_url = f"{item_url.rstrip('/')}/{layer_id}"

            manifest.append(
                {
                    "service_title": title,
                    "layer_name": layer_name,
                    "layer_url": layer_url,
                    "item_id": item_id,
                }
            )

    print(f"\n{len(manifest)} layers discovered across {len(spatial_items)} services")
    return manifest, org_name


# ---------------------------------------------------------------------------
# GeoLens API: idempotency check
# ---------------------------------------------------------------------------


async def clean_failed_datasets(
    client: httpx.AsyncClient, base_url: str, api_key: str
) -> int:
    """Delete datasets from previous failed imports that have no features."""
    headers = {"X-Api-Key": api_key}
    deleted = 0
    skip = 0
    limit = 200

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
            ds_id = ds.get("id")
            if ds_id:
                try:
                    del_resp = await client.delete(
                        f"{base_url}/api/datasets/{ds_id}",
                        headers=headers,
                    )
                    if del_resp.status_code in (200, 204):
                        deleted += 1
                except Exception:
                    pass

        total = data.get("total", 0)
        skip += limit
        if skip >= total or not datasets:
            break

    return deleted


async def fetch_existing_datasets(
    client: httpx.AsyncClient, base_url: str, api_key: str
) -> dict[str, str]:
    """Paginate GET /api/datasets/ and return mapping of source_filename -> dataset_id."""
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
# GeoLens API: job polling
# ---------------------------------------------------------------------------


async def poll_job(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    job_id: str,
    timeout: int = 300,
) -> dict:
    """Poll GET /api/jobs/{job_id} until complete or failed."""
    headers = {"X-Api-Key": api_key}
    start = time.monotonic()

    while True:
        resp = await client.get(
            f"{base_url}/api/jobs/{job_id}", headers=headers
        )
        resp.raise_for_status()
        result = resp.json()
        status = result.get("status")

        if status in ("complete", "failed"):
            return result

        if time.monotonic() - start >= timeout:
            raise TimeoutError(
                f"Job {job_id} did not complete within {timeout}s"
            )

        await asyncio.sleep(3)


# ---------------------------------------------------------------------------
# GeoLens API: three-step ingest
# ---------------------------------------------------------------------------


async def ingest_dataset(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    filename: str,
    data: bytes,
    name: str,
    tags: list[str],
) -> dict:
    """Ingest a dataset through the GeoLens three-step API.

    Steps: upload → preview → commit → poll for completion.
    Returns the final job status dict.
    """
    headers = {"X-Api-Key": api_key}

    # Step 1 — Upload
    upload_resp = await client.post(
        f"{base_url}/api/ingest/upload",
        headers=headers,
        files={"file": (filename, data, "application/zip")},
    )
    upload_resp.raise_for_status()
    job_id = upload_resp.json()["job_id"]

    # Step 2 — Preview
    preview_resp = await client.post(
        f"{base_url}/api/ingest/preview/{job_id}", headers=headers
    )
    preview_resp.raise_for_status()

    # Step 3 — Commit
    commit_body = {
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

    # Step 4 — Poll until done
    result = await poll_job(client, base_url, api_key, job_id)

    # Step 5 — Apply keywords via records API
    dataset_id = result.get("dataset_id")
    if dataset_id and tags:
        try:
            ds_resp = await client.get(
                f"{base_url}/api/datasets/{dataset_id}", headers=headers
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
                    if kw_resp.status_code not in (201, 409):
                        kw_resp.raise_for_status()
        except Exception as exc:
            logger.warning("Failed to set keywords for %s: %s", name, exc)

    return result


# ---------------------------------------------------------------------------
# Concurrent processing
# ---------------------------------------------------------------------------


async def process_one(
    entry: dict,
    index: int,
    total: int,
    sem: asyncio.Semaphore,
    arcgis_client: httpx.AsyncClient,
    geolens_client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    org_name: str,
    existing: dict[str, str],
    cache_dir: Path | None,
    results: list[dict],
) -> None:
    """Download one layer from ArcGIS and ingest into GeoLens."""
    layer_name = entry["layer_name"]
    layer_url = entry["layer_url"]
    service_title = entry["service_title"]
    safe_name = sanitize_name(layer_name)
    filename = f"{safe_name}.geojson.zip"
    tag = f"[{index}/{total}]"

    # Idempotency check
    if filename in existing:
        print(f"  {tag} Skipping {layer_name} (already imported)")
        results.append(
            {
                "name": layer_name,
                "status": "skipped",
                "dataset_id": existing[filename],
            }
        )
        return

    async with sem:
        try:
            # Check cache
            cached_geojson = None
            if cache_dir is not None:
                cache_path = cache_dir / f"{safe_name}.geojson"
                if cache_path.exists() and cache_path.stat().st_size > 0:
                    print(f"  {tag} Loading {layer_name} from cache...")
                    with open(cache_path) as f:
                        cached_geojson = json.load(f)

            if cached_geojson is None:
                print(f"  {tag} Downloading {layer_name}...")
                cached_geojson = await download_layer_geojson(
                    arcgis_client, layer_url, layer_name
                )
                if cached_geojson is None:
                    print(f"  {tag} Skipping {layer_name} (no features)")
                    results.append(
                        {"name": layer_name, "status": "skipped_empty"}
                    )
                    return

                # Write to cache
                if cache_dir is not None:
                    cache_path = cache_dir / f"{safe_name}.geojson"
                    with open(cache_path, "w") as f:
                        json.dump(cached_geojson, f)

            feature_count = len(cached_geojson.get("features", []))
            zip_data = geojson_to_zip(cached_geojson, safe_name)
            display_name = generate_display_name(layer_name, service_title)
            tags = generate_tags(layer_name, service_title, org_name)

            print(
                f"  {tag} Ingesting {layer_name} ({feature_count} features)..."
            )
            result = await ingest_dataset(
                geolens_client,
                base_url,
                api_key,
                filename,
                zip_data,
                display_name,
                tags,
            )

            if result.get("status") == "failed":
                raise RuntimeError(
                    result.get("error_message", "Unknown ingest error")
                )

            results.append(
                {
                    "name": layer_name,
                    "status": "succeeded",
                    "dataset_id": result.get("dataset_id"),
                }
            )
            print(f"  {tag} Done {layer_name}")

        except Exception as exc:
            results.append(
                {"name": layer_name, "status": "failed", "error": str(exc)}
            )
            print(f"  {tag} Failed {layer_name}: {exc}")


# ---------------------------------------------------------------------------
# Collection assignment
# ---------------------------------------------------------------------------


async def create_or_get_collection(
    client: httpx.AsyncClient,
    base_url: str,
    headers: dict,
    name: str,
    description: str,
) -> str | None:
    """Create a collection or return existing one's ID."""
    resp = await client.post(
        f"{base_url}/api/catalog/collections/",
        headers=headers,
        json={"name": name, "description": description},
    )
    if resp.status_code == 201:
        return resp.json()["id"]

    if resp.status_code == 409:
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


async def assign_collection(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    org_name: str,
    results: list[dict],
) -> None:
    """Create a collection for the org and assign all succeeded datasets."""
    headers = {"X-Api-Key": api_key}
    dataset_ids = [
        r["dataset_id"]
        for r in results
        if r["status"] in ("succeeded", "skipped") and r.get("dataset_id")
    ]

    if not dataset_ids:
        print("No datasets to assign to collection")
        return

    coll_name = org_name
    coll_desc = f"Public datasets from {org_name} ArcGIS Online organization"

    coll_id = await create_or_get_collection(
        client, base_url, headers, coll_name, coll_desc
    )
    if coll_id is None:
        print(f"Failed to create/find collection: {coll_name}")
        return

    try:
        resp = await client.post(
            f"{base_url}/api/catalog/collections/{coll_id}/datasets",
            headers=headers,
            json={"dataset_ids": dataset_ids},
        )
        resp.raise_for_status()
        added = resp.json().get("added", 0)
        print(
            f"  Collection '{coll_name}': "
            f"{added} dataset(s) added ({len(dataset_ids)} total)"
        )
    except Exception as exc:
        print(f"Collection assignment failed: {exc}")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def print_summary(
    total: int, succeeded: int, skipped: int, failed: int, failures: list[dict]
) -> None:
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
            print(f"  {f['name']}: {f['error']}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed GeoLens with public data from an ArcGIS Online organization",
    )
    parser.add_argument(
        "--org-url",
        default=os.environ.get("ARCGIS_ORG_URL", DEFAULT_ORG_URL),
        help=f"ArcGIS Online org URL (default: {DEFAULT_ORG_URL})",
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
        help="List discoverable layers without downloading or importing",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Directory to cache downloaded GeoJSON (resumes partial runs)",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete failed datasets from previous runs before importing",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="Max parallel download+ingest streams (default: 3)",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main(args: argparse.Namespace) -> None:
    base_url = args.base_url.rstrip("/")
    api_key = args.api_key

    # Use separate clients for ArcGIS (longer timeouts for large queries)
    # and GeoLens (follows seed-natural-earth patterns)
    async with (
        httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=30.0),
            follow_redirects=True,
        ) as arcgis_client,
        httpx.AsyncClient(
            timeout=httpx.Timeout(300.0, connect=30.0),
            follow_redirects=True,
        ) as geolens_client,
    ):
        # Discover layers from ArcGIS
        manifest, org_name = await discover_layers(arcgis_client, args.org_url)

        if not manifest:
            print("No layers found to import")
            return

        if args.dry_run:
            print(f"\nDry Run — {len(manifest)} layers:")
            print("=" * 60)
            for i, entry in enumerate(manifest, 1):
                print(
                    f"  {i:3d}. {entry['layer_name']}  "
                    f"({entry['service_title']})"
                )
                print(f"       {entry['layer_url']}")
            return

        # Validate GeoLens connectivity
        try:
            health_resp = await geolens_client.get(f"{base_url}/api/health")
            health_resp.raise_for_status()
        except (httpx.HTTPStatusError, httpx.TransportError) as exc:
            print(f"Cannot reach GeoLens at {base_url}: {exc}")
            sys.exit(1)

        # Cache setup
        cache_dir: Path | None = args.cache_dir
        if cache_dir is not None:
            cache_dir.mkdir(parents=True, exist_ok=True)
            print(f"Using download cache: {cache_dir}")

        # Clean previous failed imports if requested
        if args.clean:
            print("Cleaning previous datasets...")
            deleted = await clean_failed_datasets(
                geolens_client, base_url, api_key
            )
            if deleted:
                print(f"Deleted {deleted} dataset(s) from previous runs")

        # Idempotency check
        print("Checking existing datasets...")
        existing = await fetch_existing_datasets(
            geolens_client, base_url, api_key
        )
        if existing:
            print(f"Found {len(existing)} existing dataset(s) in catalog")

        # Bounded concurrency
        results: list[dict] = []
        sem = asyncio.Semaphore(args.concurrency)
        total = len(manifest)

        print(f"\nImporting {total} layers...")

        async with asyncio.TaskGroup() as tg:
            for i, entry in enumerate(manifest, 1):
                tg.create_task(
                    process_one(
                        entry=entry,
                        index=i,
                        total=total,
                        sem=sem,
                        arcgis_client=arcgis_client,
                        geolens_client=geolens_client,
                        base_url=base_url,
                        api_key=api_key,
                        org_name=org_name,
                        existing=existing,
                        cache_dir=cache_dir,
                        results=results,
                    )
                )

        # Summary
        succeeded = sum(1 for r in results if r["status"] == "succeeded")
        skipped = sum(
            1 for r in results if r["status"] in ("skipped", "skipped_empty")
        )
        failed = sum(1 for r in results if r["status"] == "failed")
        failures = [
            {"name": r["name"], "error": r.get("error", "")}
            for r in results
            if r["status"] == "failed"
        ]

        print_summary(total, succeeded, skipped, failed, failures)

        # Assign to collection
        print()
        print("--- Collection Assignment ---")
        await assign_collection(
            geolens_client, base_url, api_key, org_name, results
        )


if __name__ == "__main__":
    args = parse_args()

    if args.dry_run:
        asyncio.run(main(args))
    else:
        if not args.api_key:
            print(
                "Error: --api-key or GEOLENS_API_KEY env var required",
                file=sys.stderr,
            )
            sys.exit(1)
        asyncio.run(main(args))
