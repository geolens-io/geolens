#!/usr/bin/env python3
"""Ingest ADK High Peaks datasets + compose marketing map(s) via the GeoLens API.

Mirrors scripts/seed-natural-earth.py's auth bootstrap pattern: login -> mint
API key -> ingest with X-Api-Key header -> delete the key on exit.

Datasets ingested (6 total):
  raster:
    1. adk-high-peaks-dem-1m       (DEM 1m mosaic, ~1.4 GB)
    2. adk-high-peaks-ny-orthos    (TNM NAIP if available, otherwise NY State tiled orthos)
  vector:
    3. adk-blue-line               (APA Blue Line polygon)
    4. adk-hiking-trails           (NYSDEC Hiking Trails AOI subset)
    5. adk-land-classification     (APA Land Classification AOI subset)
    6. adk-nhd-flowlines           (USGS NHD stream/river flowlines)
    7. adk-nhd-waterbodies         (USGS NHD lakes/ponds/reservoirs)
    8. adk-46er-peaks              (Complete official ADK 46ers point dataset)

Saved maps composed:
  Map 1: "Adirondack High Peaks — Terrain & Trails"
  Map 2: "Adirondack High Peaks — 3D Relief"

DOGFOODING (load-bearing): every GeoLens HTTP call is wrapped in an
instrumented logger that records method/path/status/elapsed/payload-shape/
friction notes to .scratch/adk-data/api_issues_log.jsonl (one JSON line per
call). This is the raw input the API-ISSUES.md dogfooding report reads.

Idempotent: re-running this script does NOT duplicate datasets or maps. It
detects existing datasets by source_filename match and existing maps by name.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import httpx
except ImportError:
    print("Missing httpx. Install with: pip install httpx", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Use direct API port (8001) not the Vite proxy (8080).
# The Vite dev proxy drops large-body connections before forwarding to FastAPI,
# causing httpx.WriteTimeout / httpx.ReadError on multi-GB uploads (DEM: 1.3 GB).
# Port 8001 routes directly to FastAPI's ASGI server — no intermediary.
DEFAULT_BASE_URL = "http://localhost:8001"
# Browser-facing URL for map links (Vite dev proxy on 8080).
DEFAULT_BROWSER_URL = "http://localhost:8080"
BOOTSTRAP_KEY_NAME = "marketing-data-adk-high-peaks"

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRATCH_DIR = REPO_ROOT / ".scratch" / "adk-data"
API_ISSUES_LOG_PATH = SCRATCH_DIR / "api_issues_log.jsonl"

# (manifest_key, on-disk path, file_type=vector|raster, title, summary, tags)
DATASETS = [
    {
        "key": "adk-high-peaks-dem-1m",
        "path": SCRATCH_DIR / "cogs" / "adk_high_peaks_dem_1m.tif",
        "file_type": "raster",
        "title": "ADK High Peaks — 1m DEM (USGS 3DEP)",
        "summary": (
            "USGS 3DEP 1-meter LiDAR-derived DEM for the Adirondack High Peaks AOI. "
            "Sourced from the 2014 NY Clinton/Essex/Lake_Champlain QL2 LiDAR project, "
            "mosaicked + reprojected to EPSG:3857 and COG-converted."
        ),
        "tags": ["adirondacks", "high-peaks", "dem", "elevation", "lidar", "marketing", "terrain"],
        "srid_override": 3857,
        "strict_cog": False,
        "attribution": "USGS 3DEP / Clinton-Essex-Lake-Champlain QL2 LiDAR (2014)",
    },
    {
        "key": "adk-high-peaks-ny-orthos",
        "path": SCRATCH_DIR / "cogs" / "adk_high_peaks_ny_orthos_tiled_3857.tif",
        "file_type": "raster",
        "title": "ADK High Peaks — NY State Orthos (aerial)",
        "summary": (
            "Natural-color aerial imagery for the ADK High Peaks marketing maps. "
            "The pipeline queries TNM NAIP first and records the exact no-data "
            "evidence when unavailable, then falls back to tiled NY State ITS "
            "12-inch orthos exports rather than the original single soft render."
        ),
        "tags": ["adirondacks", "high-peaks", "aerial", "orthoimagery", "tnm-naip-checked", "marketing"],
        "srid_override": 3857,
        "strict_cog": False,
        "attribution": "TNM NAIP if available; otherwise NYS ITS Geospatial Services / wms/Latest/MapServer",
    },
    {
        "key": "adk-blue-line",
        "path": SCRATCH_DIR / "vectors" / "apa_blue_line_aoi.geojson",
        "file_type": "vector",
        "title": "APA Adirondack Park Boundary (Blue Line)",
        "summary": (
            "The Blue Line polygon defining the Adirondack Park boundary from APA's "
            "BluelinePolygon FeatureServer. Single feature; whole-park polygon "
            "(not AOI-clipped) for visual context."
        ),
        "tags": ["adirondacks", "boundaries", "park-boundary", "apa", "marketing"],
        "srid_override": 4326,
        "attribution": "NY State / Adirondack Park Agency",
    },
    {
        "key": "adk-hiking-trails",
        "path": SCRATCH_DIR / "vectors" / "nysdec_hiking_trails_aoi.geojson",
        "file_type": "vector",
        "title": "ADK High Peaks — NYSDEC Hiking Trails (AOI)",
        "summary": (
            "Hiking trails from NYSDEC's DEC_Trails FeatureService (layer 1, "
            "Hiking Trails), AOI-clipped to the Lake Placid / Mt. Marcy area. "
            "~241 line features."
        ),
        "tags": ["adirondacks", "high-peaks", "trails", "hiking", "recreation", "marketing"],
        "srid_override": 4326,
        "attribution": "NY State DEC",
    },
    {
        "key": "adk-land-classification",
        "path": SCRATCH_DIR / "vectors" / "apa_land_classification_aoi.geojson",
        "file_type": "vector",
        "title": "ADK High Peaks — APA Land Classification (AOI)",
        "summary": (
            "State-land classification polygons (Wilderness, Wild Forest, Primitive, "
            "Canoe, etc.) from APA's AdirondackParkLandClassification FeatureServer, "
            "AOI-clipped."
        ),
        "tags": ["adirondacks", "high-peaks", "land-use", "wilderness", "apa", "marketing"],
        "srid_override": 4326,
        "attribution": "NY State / Adirondack Park Agency",
    },
    {
        "key": "adk-nhd-flowlines",
        "path": SCRATCH_DIR / "vectors" / "nhd_flowlines_aoi.geojson",
        "file_type": "vector",
        "title": "ADK High Peaks — NHD Flowlines (AOI)",
        "summary": (
            "USGS National Hydrography Dataset large-scale flowlines for the "
            "High Peaks AOI, including streams, rivers, canals, ditches, and "
            "artificial paths."
        ),
        "tags": ["adirondacks", "high-peaks", "hydrography", "nhd", "streams", "marketing"],
        "srid_override": 4326,
        "attribution": "USGS TNM National Hydrography Dataset",
    },
    {
        "key": "adk-nhd-waterbodies",
        "path": SCRATCH_DIR / "vectors" / "nhd_waterbodies_aoi.geojson",
        "file_type": "vector",
        "title": "ADK High Peaks — NHD Waterbodies (AOI)",
        "summary": (
            "USGS National Hydrography Dataset large-scale waterbody polygons "
            "for the High Peaks AOI, including lakes, ponds, and reservoirs."
        ),
        "tags": ["adirondacks", "high-peaks", "hydrography", "nhd", "lakes", "marketing"],
        "srid_override": 4326,
        "attribution": "USGS TNM National Hydrography Dataset",
    },
    {
        "key": "adk-46er-peaks",
        "path": SCRATCH_DIR / "vectors" / "adk_46er_peaks.geojson",
        "file_type": "vector",
        "title": "ADK 46er High Peaks (complete official list)",
        "summary": (
            "Complete official list of the Adirondack 46ers, generated from APA's "
            "GNIS-derived Summits FeatureServer and enriched with official rank "
            "and elevation values."
        ),
        "tags": ["adirondacks", "high-peaks", "peaks", "46ers", "points-of-interest", "marketing"],
        "srid_override": 4326,
        "attribution": "APA Summits FeatureServer / USGS GNIS / ADK 46ers list",
    },
]


# ---------------------------------------------------------------------------
# Dogfooding instrumentation: API issues log
# ---------------------------------------------------------------------------


class APILogger:
    """Wraps httpx.AsyncClient calls + records every GeoLens HTTP exchange.

    Each line in api_issues_log.jsonl looks like:
        {"ts": "...", "method": "POST", "path": "/api/ingest/upload",
         "status": 200, "elapsed_ms": 234, "req_summary": "...",
         "resp_summary": "...", "friction": "..."}

    `friction` is a free-form note the script appends whenever a workaround
    was needed (e.g. "had to read source/router.py to learn that 422 means
    srid_override is invalid").
    """

    def __init__(self, log_path: Path, append: bool = False):
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if not append:
            # Truncate at start (default); pass append=True to preserve prior-run entries
            self.log_path.write_text("")
        self._calls = []

    def record(
        self,
        method: str,
        path: str,
        status: int | None,
        elapsed_ms: float,
        req_summary: str = "",
        resp_summary: str = "",
        friction: str = "",
        retry_count: int = 0,
        error: str | None = None,
    ):
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "method": method,
            "path": path,
            "status": status,
            "elapsed_ms": round(elapsed_ms, 1),
            "req_summary": req_summary[:300],
            "resp_summary": resp_summary[:500],
            "retry_count": retry_count,
            "friction": friction,
            "error": error,
        }
        self._calls.append(entry)
        with open(self.log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def summary(self) -> dict:
        """Return aggregate stats for the SUMMARY/API-ISSUES report."""
        if not self._calls:
            return {"total": 0}
        by_endpoint: dict = {}
        for c in self._calls:
            # Normalize {job_id} / {map_id} / {id} placeholders in path
            normalized = c["path"]
            import re
            normalized = re.sub(r"/[0-9a-f-]{36}", "/{id}", normalized)
            key = f"{c['method']} {normalized}"
            slot = by_endpoint.setdefault(key, {"count": 0, "times_ms": [], "errors": 0, "frictions": []})
            slot["count"] += 1
            slot["times_ms"].append(c["elapsed_ms"])
            if c.get("error") or (c.get("status") and c["status"] >= 400):
                slot["errors"] += 1
            if c.get("friction"):
                slot["frictions"].append(c["friction"])
        for key, slot in by_endpoint.items():
            times = sorted(slot["times_ms"])
            slot["p50_ms"] = times[len(times) // 2]
            slot["p95_ms"] = times[int(len(times) * 0.95)] if len(times) > 1 else times[0]
            del slot["times_ms"]
        return {"total": len(self._calls), "by_endpoint": by_endpoint}


# ---------------------------------------------------------------------------
# Auth bootstrap (mirrors seed-natural-earth.py)
# ---------------------------------------------------------------------------


async def bootstrap_api_key(
    client: httpx.AsyncClient, logger: APILogger, base_url: str, username: str, password: str
) -> tuple[str, str | None]:
    """Login + mint a temporary API key. Returns (plaintext_key, key_id)."""
    # 1. Login (form-encoded)
    t0 = time.monotonic()
    try:
        resp = await client.post(
            f"{base_url}/api/auth/login",
            data={"username": username, "password": password},
        )
        elapsed = (time.monotonic() - t0) * 1000
        body_short = resp.text[:300]
        friction = ""
        if "username" not in body_short and resp.status_code == 200:
            # access_token is the only useful field, no real friction
            friction = ""
        logger.record(
            "POST", "/api/auth/login", resp.status_code, elapsed,
            req_summary=f"username={username}",
            resp_summary=body_short,
            friction=friction or "form-encoded body required (not JSON) — undocumented in /docs",
        )
    except Exception as exc:
        elapsed = (time.monotonic() - t0) * 1000
        logger.record("POST", "/api/auth/login", None, elapsed, req_summary=f"username={username}",
                      friction="login transport error", error=str(exc))
        raise

    if resp.status_code != 200:
        raise RuntimeError(f"login failed: HTTP {resp.status_code}  body={body_short}")
    token = resp.json().get("access_token")
    if not token:
        raise RuntimeError(f"login response missing access_token: {body_short}")

    # 2. Mint API key
    t0 = time.monotonic()
    resp = await client.post(
        f"{base_url}/api/auth/api-keys/",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": BOOTSTRAP_KEY_NAME},
    )
    elapsed = (time.monotonic() - t0) * 1000
    logger.record(
        "POST", "/api/auth/api-keys/", resp.status_code, elapsed,
        req_summary=f"name={BOOTSTRAP_KEY_NAME!r}",
        resp_summary=resp.text[:500],
        friction="" if resp.status_code in (200, 201)
                 else "non-201 on create-key; check user has admin/upload permission",
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"create-key failed: HTTP {resp.status_code} body={resp.text[:300]}")
    body = resp.json()
    plaintext = body.get("key")
    key_id = body.get("id")
    if not plaintext:
        raise RuntimeError(f"create-key response missing 'key': {body}")
    return plaintext, key_id


async def cleanup_bootstrap_key(
    client: httpx.AsyncClient, logger: APILogger, base_url: str,
    username: str, password: str, key_id: str,
) -> None:
    """Best-effort: re-login + DELETE the API key."""
    t0 = time.monotonic()
    try:
        resp = await client.post(
            f"{base_url}/api/auth/login",
            data={"username": username, "password": password},
        )
        elapsed = (time.monotonic() - t0) * 1000
        logger.record("POST", "/api/auth/login", resp.status_code, elapsed,
                      req_summary="cleanup-relogin", resp_summary=resp.text[:200])
        resp.raise_for_status()
        token = resp.json().get("access_token")
        if not token:
            return

        t1 = time.monotonic()
        del_resp = await client.delete(
            f"{base_url}/api/auth/api-keys/{key_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        elapsed = (time.monotonic() - t1) * 1000
        logger.record(
            "DELETE", f"/api/auth/api-keys/{key_id}",
            del_resp.status_code, elapsed,
            req_summary=f"key_id={key_id}",
            resp_summary=del_resp.text[:200],
        )
    except Exception as exc:
        elapsed = (time.monotonic() - t0) * 1000
        logger.record("DELETE", f"/api/auth/api-keys/{key_id}",
                      None, elapsed, error=str(exc))


# ---------------------------------------------------------------------------
# Idempotency: load existing datasets + maps
# ---------------------------------------------------------------------------


async def fetch_existing_datasets(
    client: httpx.AsyncClient, logger: APILogger, base_url: str, api_key: str
) -> dict[str, dict]:
    """Return mapping of source_filename -> dataset summary dict.

    Paginates GET /api/datasets/ until exhausted.
    """
    existing: dict[str, dict] = {}
    skip = 0
    limit = 200
    headers = {"X-Api-Key": api_key}

    while True:
        t0 = time.monotonic()
        resp = await client.get(
            f"{base_url}/api/datasets/",
            params={"limit": limit, "skip": skip},
            headers=headers,
        )
        elapsed = (time.monotonic() - t0) * 1000
        logger.record(
            "GET", "/api/datasets/", resp.status_code, elapsed,
            req_summary=f"limit={limit}&skip={skip}",
            resp_summary=f"total field present, {len(resp.json().get('datasets', []) if resp.status_code == 200 else [])} datasets",
            friction="" if skip == 0 else "manual pagination — no cursor-style next link",
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("datasets", [])
        for ds in items:
            fname = ds.get("source_filename")
            if fname:
                existing[fname] = ds
        total = data.get("total", 0)
        skip += limit
        if skip >= total or not items:
            break
    return existing


async def fetch_existing_maps(
    client: httpx.AsyncClient, logger: APILogger, base_url: str, api_key: str
) -> dict[str, dict]:
    """Return mapping of map name -> map summary dict."""
    headers = {"X-Api-Key": api_key}
    t0 = time.monotonic()
    resp = await client.get(f"{base_url}/api/maps/", params={"limit": 200}, headers=headers)
    elapsed = (time.monotonic() - t0) * 1000
    logger.record(
        "GET", "/api/maps/", resp.status_code, elapsed,
        req_summary="limit=200",
        resp_summary=f"{len(resp.json().get('maps', []) if resp.status_code == 200 else [])} maps",
    )
    resp.raise_for_status()
    return {m["name"]: m for m in resp.json().get("maps", [])}


# ---------------------------------------------------------------------------
# Ingest pipeline (upload -> preview -> commit -> poll)
# ---------------------------------------------------------------------------


async def ingest_dataset(
    client: httpx.AsyncClient, logger: APILogger,
    base_url: str, api_key: str, ds: dict,
) -> dict:
    """Run the full upload/preview/commit/poll pipeline for one dataset."""
    headers = {"X-Api-Key": api_key}
    path = ds["path"]
    if not path.exists():
        return {"key": ds["key"], "status": "skipped", "reason": f"file missing: {path}"}

    fsize = path.stat().st_size
    size_mb = fsize / (1024 * 1024)

    # 1. Upload (multipart)
    print(f"\n[{ds['key']}] Uploading {path.name} ({size_mb:.1f} MB)...")
    t0 = time.monotonic()
    with open(path, "rb") as f:
        files = {"file": (path.name, f, "application/octet-stream")}
        resp = await client.post(
            f"{base_url}/api/ingest/upload",
            headers=headers,
            files=files,
            # write=None: no write timeout for large files (1+ GB DEM requires minutes to stream).
            # httpx.Timeout(total, connect=30) sets the same total for read+write, which fires
            # before the full body is sent. write=None disables the per-write-call deadline.
            timeout=httpx.Timeout(connect=30.0, write=None, read=600.0, pool=30.0),
        )
    elapsed = (time.monotonic() - t0) * 1000
    upload_friction = ""
    if resp.status_code == 413:
        upload_friction = "413 Payload Too Large — no documented max upload size in /docs"
    elif resp.status_code != 200:
        upload_friction = f"unexpected status {resp.status_code} on upload"
    logger.record(
        "POST", "/api/ingest/upload", resp.status_code, elapsed,
        req_summary=f"file={path.name} size_mb={size_mb:.1f} type={ds['file_type']}",
        resp_summary=resp.text[:500],
        friction=upload_friction,
    )
    # Accept 2xx range — the upload endpoint returned 200, 201, or 202 across
    # different sessions (API uses 202 Accepted when the upload queues an async job).
    # Script bug: originally checked `!= 200` only; broadened to accept any 2xx.
    if not (200 <= resp.status_code < 300):
        return {"key": ds["key"], "status": "failed", "stage": "upload",
                "error": f"HTTP {resp.status_code}: {resp.text[:300]}"}
    job_id = resp.json()["job_id"]
    print(f"  job_id={job_id}  elapsed={elapsed/1000:.1f}s")

    # 2. Preview
    t0 = time.monotonic()
    resp = await client.post(
        f"{base_url}/api/ingest/preview/{job_id}",
        headers=headers,
        timeout=300,
    )
    elapsed = (time.monotonic() - t0) * 1000
    preview_friction = ""
    if resp.status_code == 200:
        pv = resp.json()
        # Raster vs vector branching is structural — no `type` field in preview response
        is_raster = "band_count" in pv or "is_cog_compliant" in pv
        if is_raster != (ds["file_type"] == "raster"):
            preview_friction = "preview response shape doesn't match expected file_type — branching by field presence (no `type` discriminator) is undocumented"
        resp_summary = f"raster={is_raster} crs_epsg={pv.get('crs_epsg') or pv.get('crs')} geom_type={pv.get('geometry_type')}"
    else:
        resp_summary = resp.text[:300]
        preview_friction = f"unexpected status {resp.status_code}"
    logger.record(
        "POST", f"/api/ingest/preview/{job_id}",
        resp.status_code, elapsed,
        req_summary=f"job_id={job_id}",
        resp_summary=resp_summary,
        friction=preview_friction,
    )
    if resp.status_code != 200:
        return {"key": ds["key"], "status": "failed", "stage": "preview",
                "job_id": job_id, "error": f"HTTP {resp.status_code}: {resp.text[:300]}"}

    # 3. Commit
    commit_body: dict = {
        "title": ds["title"],
        "summary": ds["summary"],
        "visibility": "public",
        "srid_override": ds["srid_override"],
    }
    if ds["file_type"] == "raster":
        commit_body["strict_cog"] = ds.get("strict_cog", False)

    t0 = time.monotonic()
    resp = await client.post(
        f"{base_url}/api/ingest/commit/{job_id}",
        headers=headers,
        json=commit_body,
        timeout=300,
    )
    elapsed = (time.monotonic() - t0) * 1000
    commit_friction = ""
    if resp.status_code == 422:
        commit_friction = f"commit 422 — body validation failed (likely srid_override or strict_cog field mismatch). body={resp.text[:200]}"
    elif resp.status_code not in (200, 202):
        commit_friction = f"commit unexpected status {resp.status_code}"
    logger.record(
        "POST", f"/api/ingest/commit/{job_id}",
        resp.status_code, elapsed,
        req_summary=json.dumps({k: v for k, v in commit_body.items() if k != "summary"})[:200],
        resp_summary=resp.text[:300],
        friction=commit_friction,
    )
    if resp.status_code not in (200, 202):
        return {"key": ds["key"], "status": "failed", "stage": "commit",
                "job_id": str(job_id), "error": f"HTTP {resp.status_code}: {resp.text[:300]}"}

    # 4. Poll job until complete/failed
    print(f"  Polling job {job_id}...")
    poll_start = time.monotonic()
    poll_iters = 0
    timeout_s = 900 if ds["file_type"] == "raster" else 120
    while True:
        t0 = time.monotonic()
        resp = await client.get(f"{base_url}/api/jobs/{job_id}", headers=headers)
        elapsed = (time.monotonic() - t0) * 1000
        if resp.status_code != 200:
            logger.record(
                "GET", f"/api/jobs/{job_id}", resp.status_code, elapsed,
                resp_summary=resp.text[:200],
                friction=f"job-poll non-200 status",
            )
            await asyncio.sleep(5)
            continue
        body = resp.json()
        status = body.get("status")
        if poll_iters % 4 == 0:
            # log every 4th poll to avoid log spam
            logger.record(
                "GET", f"/api/jobs/{job_id}", resp.status_code, elapsed,
                resp_summary=f"status={status} step={body.get('current_step')} progress={body.get('progress')}",
            )

        if status in ("complete", "failed", "cancelled"):
            poll_total = time.monotonic() - poll_start
            print(f"  Job {status} after {poll_total:.1f}s (steps polled: {poll_iters + 1})")
            if status == "failed":
                return {"key": ds["key"], "status": "failed", "stage": "job",
                        "job_id": str(job_id),
                        "error": body.get("error_message") or "no error_message"}
            return {
                "key": ds["key"], "status": "succeeded",
                "job_id": str(job_id),
                "dataset_id": body.get("dataset_id"),
                "source_filename": path.name,
                "elapsed_s": round(poll_total, 1),
            }

        poll_iters += 1
        if time.monotonic() - poll_start > timeout_s:
            return {"key": ds["key"], "status": "failed", "stage": "job_timeout",
                    "job_id": str(job_id),
                    "error": f"poll timeout after {timeout_s}s (status was: {status})"}
        await asyncio.sleep(5)


async def apply_tags(
    client: httpx.AsyncClient, logger: APILogger,
    base_url: str, api_key: str, dataset_id: str, tags: list[str],
) -> None:
    """Apply tags via the records keywords API."""
    headers = {"X-Api-Key": api_key}

    # 1. Look up record_id for the dataset
    t0 = time.monotonic()
    ds_resp = await client.get(f"{base_url}/api/datasets/{dataset_id}", headers=headers)
    elapsed = (time.monotonic() - t0) * 1000
    if ds_resp.status_code != 200:
        logger.record("GET", f"/api/datasets/{dataset_id}", ds_resp.status_code, elapsed,
                      resp_summary=ds_resp.text[:200],
                      friction="cannot look up record_id for tagging")
        return
    record_id = ds_resp.json().get("record_id")
    logger.record("GET", f"/api/datasets/{dataset_id}", ds_resp.status_code, elapsed,
                  resp_summary=f"record_id={record_id}")
    if not record_id:
        return

    # 2. POST each tag
    for tag in tags:
        t0 = time.monotonic()
        kw_resp = await client.post(
            f"{base_url}/api/records/{record_id}/keywords/",
            headers=headers,
            json={"keyword": tag, "keyword_type": "theme"},
        )
        elapsed = (time.monotonic() - t0) * 1000
        friction = ""
        if kw_resp.status_code == 409:
            friction = "409 (duplicate keyword) — expected on rerun, OK"
        elif kw_resp.status_code not in (200, 201):
            friction = f"keyword create unexpected status {kw_resp.status_code}"
        logger.record(
            "POST", f"/api/records/{record_id}/keywords/", kw_resp.status_code, elapsed,
            req_summary=f"keyword={tag} type=theme",
            resp_summary=kw_resp.text[:200],
            friction=friction,
        )


# ---------------------------------------------------------------------------
# Map composition
# ---------------------------------------------------------------------------


async def compose_map(
    client: httpx.AsyncClient, logger: APILogger,
    base_url: str, api_key: str,
    name: str, description: str,
    layers_spec: list[dict],
    terrain_config: dict | None = None,
    browser_url: str | None = None,
    existing_map_id: str | None = None,
    view_state: dict | None = None,
) -> dict:
    """Create or update a map and replace its layer stack.

    browser_url: browser-facing origin for the map URL (defaults to base_url).
    Use when base_url is the direct API port (8001) and the app is served elsewhere.
    """
    headers = {"X-Api-Key": api_key}
    map_id = existing_map_id
    created_new = map_id is None
    layer_inputs = []
    for spec in layers_spec:
        layer: dict = {
            "dataset_id": spec["dataset_id"],
            "sort_order": spec["sort_order"],
            "visible": True,
            "opacity": spec.get("opacity", 1.0),
            "layer_type": spec["layer_type"],
        }
        if "paint" in spec:
            layer["paint"] = spec["paint"]
        if "style_config" in spec:
            layer["style_config"] = spec["style_config"]
        if "label_config" in spec:
            layer["label_config"] = spec["label_config"]
        if "popup_config" in spec:
            layer["popup_config"] = spec["popup_config"]
        if "display_name" in spec:
            layer["display_name"] = spec["display_name"]
        layer_inputs.append(layer)

    if created_new:
        create_body: dict = {"name": name, "description": description}
        if terrain_config is not None:
            create_body["terrain_config"] = terrain_config
        t0 = time.monotonic()
        resp = await client.post(f"{base_url}/api/maps/", headers=headers, json=create_body, timeout=60)
        elapsed = (time.monotonic() - t0) * 1000
        create_friction = ""
        if resp.status_code == 422:
            create_friction = f"map create 422 — body validation failed. body={resp.text[:300]}"
        elif resp.status_code not in (200, 201):
            create_friction = f"map create unexpected status {resp.status_code}"
        logger.record(
            "POST", "/api/maps/", resp.status_code, elapsed,
            req_summary=json.dumps({k: v for k, v in create_body.items() if k != "description"})[:300],
            resp_summary=resp.text[:400],
            friction=create_friction,
        )
        if resp.status_code not in (200, 201):
            return {"name": name, "error": f"HTTP {resp.status_code}: {resp.text[:300]}"}
        map_id = resp.json()["id"]
        print(f"  Map created: id={map_id}")
        patch_body = {"added": layer_inputs, "updated": [], "removed": []}
        t0 = time.monotonic()
        resp = await client.patch(
            f"{base_url}/api/maps/{map_id}/layers",
            headers=headers, json=patch_body, timeout=60,
        )
        method = "PATCH"
        path = f"/api/maps/{map_id}/layers"
        req_summary = f"added={len(layer_inputs)} updated=0 removed=0"
    else:
        update_body: dict = {"name": name, "description": description, "layers": layer_inputs}
        if terrain_config is not None:
            update_body["terrain_config"] = terrain_config
        if view_state:
            update_body.update(view_state)
        t0 = time.monotonic()
        resp = await client.put(
            f"{base_url}/api/maps/{map_id}",
            headers=headers,
            json=update_body,
            timeout=60,
        )
        method = "PUT"
        path = f"/api/maps/{map_id}"
        req_summary = f"replace_layers={len(layer_inputs)} terrain={terrain_config}"

    elapsed = (time.monotonic() - t0) * 1000
    layer_friction = ""
    if resp.status_code == 422:
        layer_friction = f"{method} map layers 422 — likely an invalid paint key, missing dataset, or bad popup_config. body={resp.text[:400]}"
    elif resp.status_code not in (200, 201):
        layer_friction = f"{method} map layers unexpected status {resp.status_code}"
    logger.record(
        method, path, resp.status_code, elapsed,
        req_summary=req_summary,
        resp_summary=resp.text[:500],
        friction=layer_friction,
    )
    if created_new and view_state and resp.status_code in (200, 201):
        update_body = dict(view_state)
        if terrain_config is not None:
            update_body["terrain_config"] = terrain_config
        t2 = time.monotonic()
        view_resp = await client.put(
            f"{base_url}/api/maps/{map_id}",
            headers=headers,
            json=update_body,
            timeout=60,
        )
        logger.record(
            "PUT", f"/api/maps/{map_id}", view_resp.status_code, (time.monotonic() - t2) * 1000,
            req_summary=f"view_state={view_state}",
            resp_summary=view_resp.text[:500],
            friction="" if view_resp.status_code in (200, 201) else "view-state update after map create failed",
        )

    _browser = (browser_url or base_url).rstrip("/")
    return {
        "name": name, "id": map_id,
        "url": f"{_browser}/maps/{map_id}",
        "layers_added": len(layer_inputs),
        "patch_status": resp.status_code,
        "patch_error": resp.text[:300] if resp.status_code not in (200, 201) else None,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def amain(args: argparse.Namespace) -> int:
    base_url = args.base_url.rstrip("/")
    browser_url = args.browser_url.rstrip("/") if args.browser_url else base_url
    # append=True preserves prior-run log entries (important for resume after crash/overload)
    logger = APILogger(API_ISSUES_LOG_PATH, append=args.append_log)

    async with httpx.AsyncClient(
        headers={"User-Agent": "geolens-marketing-data/1.0"},
        follow_redirects=True,
    ) as client:
        # Health check
        t0 = time.monotonic()
        try:
            hresp = await client.get(f"{base_url}/api/health", timeout=10)
            elapsed = (time.monotonic() - t0) * 1000
            logger.record("GET", "/api/health", hresp.status_code, elapsed,
                          resp_summary=hresp.text[:200])
            hresp.raise_for_status()
        except Exception as exc:
            logger.record("GET", "/api/health", None,
                          (time.monotonic() - t0) * 1000, error=str(exc))
            print(f"Cannot reach {base_url}: {exc}", file=sys.stderr)
            return 1

        # Bootstrap API key
        print(f"Bootstrapping API key (user: {args.username!r})...")
        api_key, key_id = await bootstrap_api_key(
            client, logger, base_url, args.username, args.password
        )

        # Save key path so the verify command in PLAN.md can find it
        try:
            key_path = SCRATCH_DIR / "api_key"
            key_path.write_text(api_key)
            os.chmod(key_path, 0o600)
        except Exception:
            pass

        try:
            # Idempotency: load existing datasets
            print("Loading existing datasets...")
            existing = await fetch_existing_datasets(client, logger, base_url, api_key)
            print(f"  Found {len(existing)} existing datasets")

            existing_maps = await fetch_existing_maps(client, logger, base_url, api_key)
            print(f"  Found {len(existing_maps)} existing maps")

            # Ingest each dataset
            results = []
            dataset_ids: dict[str, str] = {}  # manifest_key -> dataset_id

            for ds in DATASETS:
                fname = ds["path"].name
                if fname in existing:
                    print(f"\n[{ds['key']}] SKIP (already in catalog as {existing[fname]['id']})")
                    results.append({
                        "key": ds["key"], "status": "skipped",
                        "dataset_id": existing[fname]["id"],
                        "source_filename": fname,
                    })
                    dataset_ids[ds["key"]] = existing[fname]["id"]
                    continue

                res = await ingest_dataset(client, logger, base_url, api_key, ds)
                results.append(res)
                if res["status"] == "succeeded":
                    dataset_ids[ds["key"]] = res["dataset_id"]
                    # Apply tags
                    await apply_tags(client, logger, base_url, api_key,
                                     res["dataset_id"], ds["tags"])

            # Print ingest summary
            print("\n=== Ingest summary ===")
            for r in results:
                s = r["status"]
                ds_id = r.get("dataset_id", "")[:8] + "…" if r.get("dataset_id") else "-"
                err = r.get("error", "")[:80]
                print(f"  {s:<10}  {r['key']:<32}  ds_id={ds_id}  err={err}")

            # Compose maps
            print("\n=== Composing maps ===")
            map_results = []

            def primary_layers() -> list[dict]:
                layers_spec = []
                if "adk-high-peaks-ny-orthos" in dataset_ids:
                    layers_spec.append({
                        "dataset_id": dataset_ids["adk-high-peaks-ny-orthos"],
                        "sort_order": 0,
                        "opacity": 1.0,
                        "layer_type": "raster_geolens",
                        "style_config": {"builder": {"render_mode": "image"}},
                        "display_name": "TNM/NY Orthos aerial",
                    })
                if "adk-high-peaks-dem-1m" in dataset_ids:
                    layers_spec.append({
                        "dataset_id": dataset_ids["adk-high-peaks-dem-1m"],
                        "sort_order": 1,
                        "opacity": 0.45,
                        "layer_type": "raster_geolens",
                        "style_config": {"builder": {"render_mode": "hillshade"}},
                        "display_name": "DEM hillshade (1m)",
                    })
                if "adk-nhd-waterbodies" in dataset_ids:
                    layers_spec.append({
                        "dataset_id": dataset_ids["adk-nhd-waterbodies"],
                        "sort_order": 2,
                        "opacity": 0.55,
                        "layer_type": "vector_geolens",
                        "paint": {
                            "fill-color": "#4aa3c7",
                            "fill-opacity": 0.45,
                            "fill-outline-color": "#1f6f8b",
                        },
                        "display_name": "NHD lakes and ponds",
                    })
                if "adk-land-classification" in dataset_ids:
                    layers_spec.append({
                        "dataset_id": dataset_ids["adk-land-classification"],
                        "sort_order": 3,
                        "opacity": 0.28,
                        "layer_type": "vector_geolens",
                        "paint": {
                            "fill-color": "#7a8b4f",
                            "fill-opacity": 0.28,
                            "fill-outline-color": "#3d4d2a",
                        },
                        "display_name": "Land classification",
                    })
                if "adk-blue-line" in dataset_ids:
                    layers_spec.append({
                        "dataset_id": dataset_ids["adk-blue-line"],
                        "sort_order": 4,
                        "opacity": 0.8,
                        "layer_type": "vector_geolens",
                        "paint": {
                            "fill-color": "#1b6e3a",
                            "fill-opacity": 0.03,
                            "fill-outline-color": "#1b6e3a",
                        },
                        "display_name": "Blue Line (APA boundary)",
                    })
                if "adk-nhd-flowlines" in dataset_ids:
                    layers_spec.append({
                        "dataset_id": dataset_ids["adk-nhd-flowlines"],
                        "sort_order": 5,
                        "opacity": 0.85,
                        "layer_type": "vector_geolens",
                        "paint": {
                            "line-color": "#2b8fb8",
                            "line-width": 1.2,
                        },
                        "display_name": "NHD streams and rivers",
                    })
                if "adk-hiking-trails" in dataset_ids:
                    layers_spec.append({
                        "dataset_id": dataset_ids["adk-hiking-trails"],
                        "sort_order": 6,
                        "opacity": 0.9,
                        "layer_type": "vector_geolens",
                        "paint": {
                            "line-color": "#c44d00",
                            "line-width": 1.8,
                        },
                        "display_name": "Hiking trails",
                    })
                if "adk-46er-peaks" in dataset_ids:
                    layers_spec.append({
                        "dataset_id": dataset_ids["adk-46er-peaks"],
                        "sort_order": 7,
                        "opacity": 1.0,
                        "layer_type": "vector_geolens",
                        "paint": {
                            "circle-color": "#ffffff",
                            "circle-radius": 5,
                            "circle-stroke-color": "#111111",
                            "circle-stroke-width": 1.5,
                        },
                        "label_config": {
                            "text-field": ["get", "name"],
                            "text-size": 12,
                            "text-offset": [0, 1.2],
                            "text-halo-color": "#ffffff",
                            "text-halo-width": 1.5,
                        },
                        "display_name": "ADK 46er peaks",
                        "popup_config": {
                            "enabled": True,
                            "expression": None,
                            "visible_fields": ["name", "elev_ft", "rank", "source_name"],
                        },
                    })
                return layers_spec

            def relief_layers() -> list[dict]:
                layers = primary_layers()
                for layer in layers:
                    if layer.get("display_name") == "DEM hillshade (1m)":
                        layer["opacity"] = 0.32
                    elif layer.get("display_name") == "TNM/NY Orthos aerial":
                        layer["opacity"] = 0.92
                    elif layer.get("display_name") == "Land classification":
                        layer["opacity"] = 0.18
                return layers

            map1_name = "Adirondack High Peaks — Terrain & Trails"
            map1_existing = existing_maps.get(map1_name)
            map1_result = await compose_map(
                client, logger, base_url, api_key,
                name=map1_name,
                description=(
                    "Marketing demo composition: high-fidelity aerial + 1m DEM "
                    "hillshade + NHD hydrography + Blue Line + APA land classification "
                    "+ NYSDEC hiking trails + complete ADK 46er high-peak markers."
                ),
                layers_spec=primary_layers(),
                terrain_config={"enabled": False, "source_dataset_id": None, "exaggeration": 1.0},
                browser_url=browser_url,
                existing_map_id=map1_existing["id"] if map1_existing else None,
                view_state={"center_lng": -73.94, "center_lat": 44.19, "zoom": 12.5, "pitch": 35, "bearing": 0},
            )
            map_results.append(map1_result)
            print(f"  Map 1 saved: {map1_result.get('url')}")

            map2_name = "Adirondack High Peaks — 3D Relief"
            map2_existing = existing_maps.get(map2_name)
            map2_result = await compose_map(
                client, logger, base_url, api_key,
                name=map2_name,
                description=(
                    "Bonus 3D relief variant for screenshots: ADK terrain enabled "
                    "over high-fidelity aerial, DEM hillshade, hydrography, trails, "
                    "and complete 46er peak context."
                ),
                layers_spec=relief_layers(),
                terrain_config={
                    "enabled": True,
                    "source_dataset_id": dataset_ids.get("adk-high-peaks-dem-1m"),
                    "exaggeration": 1.7,
                },
                browser_url=browser_url,
                existing_map_id=map2_existing["id"] if map2_existing else None,
                view_state={"center_lng": -73.94, "center_lat": 44.16, "zoom": 13.2, "pitch": 62, "bearing": -24},
            )
            map_results.append(map2_result)
            print(f"  Map 2 saved: {map2_result.get('url')}")

            # Final summary
            print()
            print("=== Map results ===")
            for m in map_results:
                if "error" in m:
                    print(f"  FAIL  {m['name']!r}: {m['error']}")
                else:
                    tag = "SKIP" if m.get("skipped") else "DONE"
                    print(f"  {tag}  {m['name']!r}")
                    print(f"        {m.get('url')}")
                    if m.get("patch_error"):
                        print(f"        PATCH error: {m['patch_error']}")

            # Write a session JSON for the SUMMARY writer to consume
            session_json_path = SCRATCH_DIR / "compose_session.json"
            session_json_path.write_text(json.dumps({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "base_url": base_url,
                "ingest_results": results,
                "map_results": map_results,
                "api_logger_summary": logger.summary(),
            }, indent=2, default=str))
            print(f"\nSession JSON: {session_json_path}")
            print(f"API issues log: {API_ISSUES_LOG_PATH}")

        finally:
            # Cleanup bootstrap API key
            if key_id:
                print("\nCleaning up bootstrap API key...")
                await cleanup_bootstrap_key(
                    client, logger, base_url, args.username, args.password, key_id,
                )

    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Ingest ADK High Peaks datasets + compose marketing map(s)"
    )
    p.add_argument("--base-url", default=os.environ.get("GEOLENS_BASE_URL", DEFAULT_BASE_URL))
    p.add_argument(
        "--browser-url",
        default=os.environ.get("GEOLENS_BROWSER_URL", DEFAULT_BROWSER_URL),
        help="Browser-facing origin for map URLs (default: http://localhost:8080). "
             "Use when --base-url is the direct API port.",
    )
    p.add_argument("--username", default=os.environ.get("GEOLENS_ADMIN_USERNAME", "admin"))
    p.add_argument("--password", default=os.environ.get("GEOLENS_ADMIN_PASSWORD", "admin"))
    p.add_argument(
        "--append-log", action="store_true",
        help="Append to existing api_issues_log.jsonl instead of truncating (for resumes)",
    )
    return p.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    sys.exit(asyncio.run(amain(args)))
