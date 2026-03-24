#!/usr/bin/env python3
"""Seed GeoLens with public data from an ArcGIS Online organization.

Discovers all public Feature/Map Services in an ArcGIS Online organization
and ingests each layer into GeoLens via the service connector API. This
stores the source URL on each dataset, enabling future updates via the
reupload API or the --update flag.

Requires: pip install httpx

Usage:
    # Dry run — list discoverable layers
    python scripts/seed-ago-data.py --dry-run

    # Import all layers into GeoLens
    python scripts/seed-ago-data.py --api-key <key>

    # Import from a different org
    python scripts/seed-ago-data.py --org-url https://otherorg.maps.arcgis.com --api-key <key>

    # Update existing datasets from their source AGO services
    python scripts/seed-ago-data.py --api-key <key> --update

    # Control parallelism
    python scripts/seed-ago-data.py --api-key <key> --concurrency 5
"""

import argparse
import asyncio
import os
import random
import re
import sys
import time

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

SERVICE_TYPE = "ArcGIS FeatureServer"


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
        print(f"  Fetched {len(items)}/{total} items...")

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


# ---------------------------------------------------------------------------
# Full discovery: org → items → layers
# ---------------------------------------------------------------------------


async def discover_layers(
    client: httpx.AsyncClient, org_url: str
) -> tuple[list[dict], str]:
    """Discover all downloadable layers in an ArcGIS Online organization.

    Returns (layers_manifest, org_name) where each entry has:
        service_title, layer_name, layer_id, service_url, summary
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
        snippet = item.get("snippet") or ""
        access_info = item.get("accessInformation") or ""
        license_info = item.get("licenseInfo") or ""
        tags = item.get("tags") or []
        owner = item.get("owner") or ""

        if not item_url:
            print(f"Skipping {title} — no service URL")
            continue

        try:
            layers = await get_service_layers(client, item_url)
        except Exception as e:
            print(f"Skipping {title} — failed to get layers: {e}")
            continue

        if not layers:
            print(f"Skipping {title} — no layers")
            continue

        for layer in layers:
            layer_id = layer.get("id", 0)
            layer_name = layer.get("name", title)
            layer_description = layer.get("description") or snippet

            manifest.append(
                {
                    "service_title": title,
                    "layer_name": layer_name,
                    "layer_id": layer_id,
                    "service_url": item_url.rstrip("/"),
                    "summary": layer_description,
                    "source_org": access_info,
                    "license": license_info,
                    "tags": tags,
                    "owner": owner,
                }
            )

    print(f"\n{len(manifest)} layers discovered across {len(spatial_items)} services")
    return manifest, org_name


# ---------------------------------------------------------------------------
# GeoLens API helpers
# ---------------------------------------------------------------------------


async def fetch_existing_datasets(
    client: httpx.AsyncClient, base_url: str, api_key: str
) -> dict[str, dict]:
    """Paginate GET /api/datasets/ and return mapping of source_url -> dataset info."""
    existing: dict[str, dict] = {}
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
                source_url = ds.get("source_url")
                ds_id = ds.get("id")
                if source_url and ds_id:
                    existing[source_url] = {
                        "id": ds_id,
                        "source_filename": ds.get("source_filename"),
                    }
                # Also index by source_filename for backward compat
                fname = ds.get("source_filename")
                if fname and ds_id:
                    existing[f"file:{fname}"] = {
                        "id": ds_id,
                        "source_url": source_url,
                    }
            total = data.get("total", 0)
            skip += limit
            if skip >= total or not datasets:
                break
    except (httpx.HTTPStatusError, httpx.TransportError) as exc:
        print(f"Warning: Failed to fetch existing datasets: {exc}")
        return {}

    return existing


async def poll_job(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    job_id: str,
    timeout: int = 1200,
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
# GeoLens API: service ingest (new import)
# ---------------------------------------------------------------------------


async def ingest_via_service(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    service_url: str,
    layer_name: str,
    layer_id: int,
    display_name: str,
    summary: str = "",
    timeout: int = 1200,
) -> dict:
    """Ingest a layer via the GeoLens service connector API.

    Steps: service/preview → commit → poll for completion.
    Stores source_url on the dataset for future updates.
    """
    headers = {"X-Api-Key": api_key}

    # Step 1 — Service preview (creates IngestJob with source_url)
    preview_resp = await client.post(
        f"{base_url}/api/services/preview/",
        headers=headers,
        json={
            "url": service_url,
            "service_type": SERVICE_TYPE,
            "layer_name": layer_name,
            "layer_title": display_name,
            "layer_id": layer_id,
        },
    )
    preview_resp.raise_for_status()
    job_id = str(preview_resp.json()["job_id"])

    # Step 2 — Commit
    commit_body: dict = {
        "title": display_name,
        "visibility": "public",
    }
    if summary:
        commit_body["summary"] = summary
    commit_resp = await client.post(
        f"{base_url}/api/ingest/commit/{job_id}",
        headers=headers,
        json=commit_body,
    )
    commit_resp.raise_for_status()

    # Step 3 — Poll until done
    return await poll_job(client, base_url, api_key, job_id, timeout=timeout)


# ---------------------------------------------------------------------------
# GeoLens API: service reupload (update existing)
# ---------------------------------------------------------------------------


async def update_via_service(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    dataset_id: str,
    service_url: str,
    layer_name: str,
    layer_id: int,
    display_name: str,
    timeout: int = 1200,
) -> dict:
    """Update an existing dataset by re-importing from its source service.

    Steps: reupload/service/preview → reupload/{job_id}/commit → poll.
    """
    headers = {"X-Api-Key": api_key}

    # Step 1 — Reupload service preview
    preview_resp = await client.post(
        f"{base_url}/api/datasets/{dataset_id}/reupload/service/preview",
        headers=headers,
        json={
            "url": service_url,
            "service_type": SERVICE_TYPE,
            "layer_name": layer_name,
            "layer_title": display_name,
            "layer_id": layer_id,
        },
    )
    preview_resp.raise_for_status()
    job_id = str(preview_resp.json()["job_id"])

    # Step 2 — Commit reupload
    commit_resp = await client.post(
        f"{base_url}/api/datasets/{dataset_id}/reupload/{job_id}/commit",
        headers=headers,
        json={},
    )
    commit_resp.raise_for_status()

    # Step 3 — Poll until done
    return await poll_job(client, base_url, api_key, job_id, timeout=timeout)


# ---------------------------------------------------------------------------
# GeoLens API: post-import metadata enrichment
# ---------------------------------------------------------------------------


async def enrich_metadata(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    dataset_id: str,
    entry: dict,
) -> None:
    """Apply AGO metadata (source org, license, tags) to an imported dataset."""
    headers = {"X-Api-Key": api_key}

    # PATCH dataset with source_organization and license
    patch_body: dict = {}
    if entry.get("source_org"):
        patch_body["source_organization"] = entry["source_org"]
    if entry.get("license"):
        patch_body["license"] = re.sub(r"<[^>]+>", "", entry["license"]).strip()

    if patch_body:
        try:
            await client.patch(
                f"{base_url}/api/datasets/{dataset_id}",
                headers=headers,
                json=patch_body,
            )
        except Exception as exc:
            print(f"  Warning: metadata enrichment failed for {dataset_id}: {exc}")

    # Get the record_id for keyword assignment
    tags = entry.get("tags") or []
    if not tags:
        return

    try:
        ds_resp = await client.get(
            f"{base_url}/api/datasets/{dataset_id}", headers=headers
        )
        ds_resp.raise_for_status()
        record_id = ds_resp.json().get("record_id")
        if not record_id:
            return

        for tag in tags:
            await client.post(
                f"{base_url}/api/records/{record_id}/keywords/",
                headers=headers,
                json={"keyword": tag, "keyword_type": "theme"},
            )
    except Exception as exc:
        print(f"  Warning: keyword assignment failed for {dataset_id}: {exc}")


# ---------------------------------------------------------------------------
# Concurrent processing
# ---------------------------------------------------------------------------


MAX_RETRIES = 3
BACKOFF_BASE = 5  # seconds


async def process_one(
    entry: dict,
    index: int,
    total: int,
    sem: asyncio.Semaphore,
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    existing: dict[str, dict],
    update_mode: bool,
    results: list[dict],
    timeout: int = 1200,
) -> None:
    """Import or update one layer via the service connector."""
    layer_name = entry["layer_name"]
    layer_id = entry["layer_id"]
    service_url = entry["service_url"]
    summary = entry.get("summary", "")
    display_name = layer_name.replace("_", " ").title()
    tag = f"[{index}/{total}]"

    # Check if already exists
    existing_entry = existing.get(service_url + f"/{layer_id}")

    if existing_entry and not update_mode:
        print(f"  {tag} Skipping {layer_name} (already imported)")
        results.append(
            {
                "name": layer_name,
                "status": "skipped",
                "dataset_id": existing_entry["id"],
            }
        )
        return

    async with sem:
        try:
            last_exc = None
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    if existing_entry and update_mode:
                        # Update existing dataset
                        dataset_id = existing_entry["id"]
                        print(f"  {tag} Updating {layer_name}...")
                        result = await update_via_service(
                            client,
                            base_url,
                            api_key,
                            dataset_id,
                            service_url,
                            layer_name,
                            layer_id,
                            display_name,
                            timeout=timeout,
                        )
                    else:
                        # New import
                        print(f"  {tag} Importing {layer_name}...")
                        result = await ingest_via_service(
                            client,
                            base_url,
                            api_key,
                            service_url,
                            layer_name,
                            layer_id,
                            display_name,
                            summary=summary,
                            timeout=timeout,
                        )

                    if result.get("status") == "failed":
                        raise RuntimeError(
                            result.get("error_message", "Unknown ingest error")
                        )

                    dataset_id = result.get("dataset_id")
                    action = "updated" if (existing_entry and update_mode) else "succeeded"

                    # Enrich with AGO metadata (source org, license, tags)
                    if dataset_id and action == "succeeded":
                        await enrich_metadata(client, base_url, api_key, dataset_id, entry)

                    results.append(
                        {
                            "name": layer_name,
                            "status": action,
                            "dataset_id": dataset_id,
                        }
                    )
                    print(f"  {tag} Done {layer_name}")
                    break  # success, exit retry loop

                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code >= 500 and attempt < MAX_RETRIES:
                        delay = BACKOFF_BASE * (3 ** (attempt - 1))  # 5s, 15s, 45s
                        jitter = delay * (0.5 + random.random())  # 50-150% of delay
                        print(f"  {tag} Retry {attempt}/{MAX_RETRIES} for {layer_name} after {exc.response.status_code} (waiting {jitter:.0f}s)")
                        last_exc = exc
                        await asyncio.sleep(jitter)
                        continue
                    # Non-5xx or exhausted retries — fall through to outer handler
                    raise

                except Exception:
                    raise  # Don't retry non-HTTP errors

            else:
                # All retries exhausted
                results.append(
                    {"name": layer_name, "status": "failed", "error": f"Failed after {MAX_RETRIES} retries: {last_exc}"}
                )
                print(f"  {tag} Failed {layer_name} after {MAX_RETRIES} retries: {last_exc}")
                return

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

    print(f"Warning: Failed to create/find collection {name!r}: HTTP {resp.status_code}")
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
        if r["status"] in ("succeeded", "updated", "skipped") and r.get("dataset_id")
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
    total: int, results: list[dict], update_mode: bool
) -> None:
    succeeded = sum(1 for r in results if r["status"] == "succeeded")
    updated = sum(1 for r in results if r["status"] == "updated")
    skipped = sum(
        1 for r in results if r["status"] in ("skipped", "skipped_empty")
    )
    failed = sum(1 for r in results if r["status"] == "failed")
    failures = [
        {"name": r["name"], "error": r.get("error", "")}
        for r in results
        if r["status"] == "failed"
    ]

    print()
    label = "Update" if update_mode else "Import"
    print(f"=== {label} Summary ===")
    print(f"  Succeeded: {succeeded}")
    if updated:
        print(f"  Updated:   {updated}")
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
        "--update",
        action="store_true",
        help="Upsert mode: import new layers and refresh existing ones from source",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Max parallel download+ingest streams (default: 1)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=1200,
        help="Job poll timeout in seconds (default: 1200)",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main(args: argparse.Namespace) -> None:
    base_url = args.base_url.rstrip("/")
    api_key = args.api_key

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(660.0, connect=30.0),
        follow_redirects=True,
    ) as client:
        # Discover layers from ArcGIS
        manifest, org_name = await discover_layers(client, args.org_url)

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
                print(f"       {entry['service_url']}/{entry['layer_id']}")
            return

        # Validate GeoLens connectivity
        try:
            health_resp = await client.get(f"{base_url}/api/health")
            health_resp.raise_for_status()
        except (httpx.HTTPStatusError, httpx.TransportError) as exc:
            print(f"Cannot reach GeoLens at {base_url}: {exc}")
            sys.exit(1)

        # Idempotency check — index by source_url
        print("Checking existing datasets...")
        existing = await fetch_existing_datasets(client, base_url, api_key)
        if existing:
            # Count unique dataset IDs
            ds_ids = {v["id"] for v in existing.values() if "id" in v}
            print(f"Found {len(ds_ids)} existing dataset(s) in catalog")

        # Build lookup by service_url/layer_id
        existing_by_layer: dict[str, dict] = {}
        for key, val in existing.items():
            if not key.startswith("file:"):
                existing_by_layer[key] = val

        # Bounded concurrency
        results: list[dict] = []
        sem = asyncio.Semaphore(args.concurrency)
        total = len(manifest)

        action = "Updating" if args.update else "Importing"
        print(f"\n{action} {total} layers...")

        async with asyncio.TaskGroup() as tg:
            for i, entry in enumerate(manifest, 1):
                # Build the lookup key matching source_url stored by ingest_service
                lookup_key = f"{entry['service_url']}/{entry['layer_id']}"
                # Also check the base service URL (ingest_service stores it without layer suffix)
                lookup_existing = existing_by_layer.get(
                    lookup_key
                ) or existing_by_layer.get(entry["service_url"])

                tg.create_task(
                    process_one(
                        entry=entry,
                        index=i,
                        total=total,
                        sem=sem,
                        client=client,
                        base_url=base_url,
                        api_key=api_key,
                        existing={lookup_key: lookup_existing} if lookup_existing else {},
                        update_mode=args.update,
                        results=results,
                        timeout=args.timeout,
                    )
                )

        # Summary
        print_summary(total, results, args.update)

        # Assign to collection (skip for update-only runs)
        if not args.update:
            print()
            print("--- Collection Assignment ---")
            await assign_collection(client, base_url, api_key, org_name, results)


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
