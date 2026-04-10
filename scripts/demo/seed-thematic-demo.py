#!/usr/bin/env python3
"""Thematic demo seeder for GeoLens.

This is the FROZEN orchestrator. It owns:
  - All 3 ingest helpers (vector_ne_cdn_with_cache, vector_local_with_summary, raster_local)
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
from types import ModuleType
from typing import TYPE_CHECKING, Any, Literal, TypedDict, cast

import httpx

if TYPE_CHECKING:
    from lib.fixture_schema import FixtureDict


class IngestResult(TypedDict, total=False):
    """Outcome of a single dataset ingest attempt.

    One of these is emitted per entry in a theme's DATASETS list. The shape
    is deliberately permissive (total=False) because a successful ingest
    carries ``dataset_id`` while a failure carries ``error``.
    """

    stem: str
    status: Literal["succeeded", "failed", "skipped"]
    dataset_id: str | None
    error: str | None

# Import seed-natural-earth.py primitives via importlib (file has hyphen).
# The assertions narrow away the `ModuleSpec | None` / `Loader | None` return
# types for mypy — at runtime the sibling file always exists, so the spec and
# loader are guaranteed to be non-None in this orchestrator context.
_ne_path = Path(__file__).parent.parent / "seed-natural-earth.py"
_ne_spec = importlib.util.spec_from_file_location("seed_natural_earth", _ne_path)
assert _ne_spec is not None, f"seed-natural-earth.py missing at {_ne_path}"
assert _ne_spec.loader is not None, "seed-natural-earth.py has no loader"
seed_natural_earth = importlib.util.module_from_spec(_ne_spec)
_ne_spec.loader.exec_module(seed_natural_earth)

fetch_existing_datasets = seed_natural_earth.fetch_existing_datasets
download_or_load_cache = seed_natural_earth.download_or_load_cache
ingest_dataset = seed_natural_earth.ingest_dataset
poll_job = seed_natural_earth.poll_job
create_or_get_collection = seed_natural_earth.create_or_get_collection
generate_name = seed_natural_earth.generate_name
clean_partial_downloads = seed_natural_earth.clean_partial_downloads

# Import per-theme dataset modules.
# These imports intentionally sit after `sys.path.insert(...)` so the script
# works in both orchestrator (scripts/demo/ on sys.path) and package
# (scripts.demo.*) contexts. Do NOT move to the top of the file.
sys.path.insert(0, str(Path(__file__).parent))
from themes import ThemeDataset, theme1, theme2, theme3  # noqa: E402
from lib.apply_fixture import apply_fixture  # noqa: E402

THEMES = [theme1, theme2, theme3]
NE_CDN_BASE = "https://naciscdn.org/naturalearth/10m"

logger = logging.getLogger("seed-thematic-demo")


# ------------------------------------------------------------------
# FROZEN INGEST HELPERS — Plans 02/03/04 must not modify these
# ------------------------------------------------------------------

async def ingest_vector_ne_cdn_with_cache(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    entry: ThemeDataset,
    existing: dict[str, str],
    cache_dir: Path,
) -> IngestResult:
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


async def _upload_commit_patch_flow(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    *,
    stem: str,
    path: Path,
    content_type: str,
    commit_body: dict[str, Any],
    poll_timeout: int,
    summary: str | None,
    upload_timeout: float = 300.0,
) -> IngestResult:
    """Shared upload → preview → commit → poll → PATCH-description pipeline.

    Extracted from ingest_vector_local_with_summary + ingest_raster_local so
    the two helpers only need to supply their per-type details (content_type,
    commit_body fields, poll_timeout). Everything else lives here: streaming
    upload, timeout handling, commit error translation, description PATCH.

    Args:
        stem: Theme dataset stem used in error messages.
        path: Local file path to stream. Caller already verified existence.
        content_type: Multipart part content type (``application/octet-stream``
            for vectors, ``image/tiff`` for rasters).
        commit_body: Request body for ``POST /api/ingest/commit/{job_id}``.
        poll_timeout: Seconds for ``poll_job`` before emitting a failed result.
        summary: Optional dataset description to PATCH after commit succeeds.
        upload_timeout: Per-request timeout for the multipart upload (defaults
            to 300s so a ~100 MB raster has headroom beyond the AsyncClient's
            global 120s default).

    Returns:
        IngestResult with status + dataset_id (on success) or status + error
        (on any failure mode). Never raises.
    """
    filename = path.name
    headers = {"X-Api-Key": api_key}

    # Stream the file into the multipart body rather than buffering via
    # read_bytes(). At current sizes the savings are small, but it removes
    # the OOM risk if future datasets grow past the seeder heap. Per-request
    # timeout override ensures a large raster upload isn't capped by the
    # client-wide 120s default.
    with path.open("rb") as fh:
        upload = await client.post(
            f"{base_url}/api/ingest/upload",
            headers=headers,
            files={"file": (filename, fh, content_type)},
            timeout=upload_timeout,
        )
    upload.raise_for_status()
    job_id = upload.json()["job_id"]

    prev = await client.post(
        f"{base_url}/api/ingest/preview/{job_id}", headers=headers
    )
    prev.raise_for_status()

    commit = await client.post(
        f"{base_url}/api/ingest/commit/{job_id}",
        headers={**headers, "Content-Type": "application/json"},
        json=commit_body,
    )
    if commit.status_code >= 400:
        return {
            "stem": stem,
            "status": "failed",
            "error": f"commit {commit.status_code}: {commit.text[:300]}",
        }

    try:
        result = await poll_job(client, base_url, api_key, job_id, timeout=poll_timeout)
    except TimeoutError:
        return {
            "stem": stem,
            "status": "failed",
            "error": (
                f"poll_job timed out after {poll_timeout}s — API may be slow "
                "or job stuck; re-run the seeder"
            ),
        }

    if result.get("status") != "complete":
        return {"stem": stem, "status": "failed", "error": result.get("error_message")}

    dataset_id = result.get("dataset_id")
    # PATCH the dataset description with the summary
    # (carries snapshot_date, license, STAC fields).
    if dataset_id and summary:
        patch_resp = await client.patch(
            f"{base_url}/api/datasets/{dataset_id}",
            headers={**headers, "Content-Type": "application/json"},
            json={"description": summary},
        )
        if patch_resp.status_code >= 400:
            logger.warning(
                "Failed to PATCH description for %s: %s", stem, patch_resp.text[:200]
            )
    return {"stem": stem, "status": "succeeded", "dataset_id": dataset_id}


async def ingest_vector_local_with_summary(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    entry: ThemeDataset,
    existing: dict[str, str],
) -> IngestResult:
    """Ingest a local vector file (typically a pre-joined GeoJSON or a CSV with lat/lon)."""
    stem = entry["stem"]
    path = Path(entry["local_path"])
    if not path.exists():
        return {
            "stem": stem,
            "status": "failed",
            "error": f"local file missing: {path} — Plan 05 Dockerfile must create it",
        }
    if path.name in existing:
        return {"stem": stem, "status": "skipped", "dataset_id": existing[path.name]}

    return await _upload_commit_patch_flow(
        client,
        base_url,
        api_key,
        stem=stem,
        path=path,
        content_type="application/octet-stream",
        commit_body={
            "title": generate_name(stem),
            "visibility": "public",
            "srid_override": 4326,
        },
        poll_timeout=300,
        summary=entry.get("summary"),
    )


async def ingest_raster_local(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    entry: ThemeDataset,
    existing: dict[str, str],
) -> IngestResult:
    """Ingest a local raster (COG) with extended timeout for raster processing."""
    stem = entry["stem"]
    path = Path(entry["local_path"])
    if not path.exists():
        return {"stem": stem, "status": "failed", "error": f"local file missing: {path}"}
    if path.name in existing:
        return {"stem": stem, "status": "skipped", "dataset_id": existing[path.name]}

    return await _upload_commit_patch_flow(
        client,
        base_url,
        api_key,
        stem=stem,
        path=path,
        content_type="image/tiff",
        commit_body={
            "title": generate_name(stem),
            "visibility": "public",
            "compression": "DEFLATE",
            "resampling": "bilinear",
        },
        # Raster ingest is slow — extend timeout to 600s per 218-RESEARCH.md G6.
        poll_timeout=600,
        summary=entry.get("summary"),
    )


async def ingest_theme(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    theme_module: ModuleType,
    existing: dict[str, str],
    cache_dir: Path,
) -> list[IngestResult]:
    """Ingest all DATASETS for one theme module. Dispatches by entry type/source."""
    results: list[IngestResult] = []
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
        err = r.get("error")
        suffix = f" ({err})" if err else ""
        print(f"  {entry['stem']}: {r['status']}{suffix}")
    return results


async def assign_collection(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    theme_module: ModuleType,
    results: list[IngestResult],
) -> None:
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
            f"{base_url}/api/catalog/collections/{coll_id}/datasets/",
            headers={**headers, "Content-Type": "application/json"},
            json={"dataset_ids": ids},
        )
        resp.raise_for_status()
        print(f"  Collection {theme_module.THEME_NAME}: {len(ids)} datasets assigned (status {resp.status_code})")


async def apply_theme_fixtures(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    theme_module: ModuleType,
    existing: dict[str, str],
    fixtures_by_theme: dict[str, list[tuple[Path, dict[str, Any]]]],
) -> tuple[list[dict[str, Any]], int]:
    """Apply all fixture files matching this theme.

    Returns:
        (applied, failure_count) — ``applied`` lists successfully applied
        fixtures; ``failure_count`` is incremented once per fixture that
        raised. Callers use the count to drive an overall exit code.
    """
    headers = {"X-Api-Key": api_key}
    applied: list[dict[str, Any]] = []
    failure_count = 0
    for fp, parsed in fixtures_by_theme.get(theme_module.THEME_NAME, []):
        try:
            map_id = await apply_fixture(
                client,
                base_url,
                headers,
                fp,
                existing,
                fixture=cast("FixtureDict", parsed),
            )
            applied.append({"fixture": fp.name, "map_id": map_id})
            print(f"  Applied fixture {fp.name} → map {map_id}")
        except Exception as exc:
            failure_count += 1
            # Correlate the failure to the theme so an operator scanning logs
            # can pair it with the "Failed stems" summary printed earlier. We
            # route through logger.exception (not print) so sensitive values
            # in the exception message land in structured logs rather than on
            # stdout, and the traceback is available for debugging.
            logger.exception(
                "FAILED fixture [%s → %s]: %s",
                theme_module.THEME_NAME,
                fp.name,
                exc,
            )
    return applied, failure_count


def _index_fixtures_by_theme(
    fixtures_dir: Path,
) -> dict[str, list[tuple[Path, dict[str, Any]]]]:
    """Walk fixture JSONs once and bucket them by their ``_meta.theme`` name.

    The orchestrator previously globbed + parsed every fixture per theme iter
    (8 fixtures × 3 themes = 24 parses when only 8 are needed). This helper
    does a single pass up front so each fixture JSON is parsed exactly once,
    and the parsed dict is carried through to apply_fixture so apply_fixture
    doesn't re-read from disk.

    Returns a mapping from theme name → list of ``(path, parsed_dict)`` tuples.
    """
    index: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
    for fp in sorted(fixtures_dir.glob("*.json")):
        try:
            parsed = json.loads(fp.read_text())
        except Exception as exc:
            logger.warning("Skipping unreadable fixture %s: %s", fp.name, exc)
            continue
        theme_name = parsed.get("_meta", {}).get("theme", "")
        if theme_name:
            index.setdefault(theme_name, []).append((fp, parsed))
    return index


async def main_async(args: argparse.Namespace) -> int:
    """Main async entry point. Returns an exit code — 0 on success, 1 if any
    fixture failed to apply. Handles ingest, collection assignment, and
    fixture apply for all themes.
    """
    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    clean_partial_downloads(cache_dir)

    fixtures_dir = Path(__file__).parent / "fixtures" / "maps"
    fixtures_by_theme = _index_fixtures_by_theme(fixtures_dir)

    total_fixture_failures = 0

    async with httpx.AsyncClient(timeout=120.0) as client:
        existing = await fetch_existing_datasets(client, args.base_url, args.api_key)
        print("=== GeoLens Thematic Demo Seeder ===")
        print(f"Existing datasets: {len(existing)}")

        themes_to_run = THEMES if args.theme_only is None else [THEMES[args.theme_only]]
        for tm in themes_to_run:
            print(f"\n--- {tm.THEME_NAME} ---")
            if not tm.DATASETS:
                print(f"  (no datasets registered for {tm.THEME_NAME} yet)")
                continue
            results = await ingest_theme(client, args.base_url, args.api_key, tm, existing, cache_dir)
            # Summarize ingest outcomes so the operator can correlate any later
            # resolve_fixture KeyError back to a specific upstream ingest failure.
            failed_stems = [r["stem"] for r in results if r.get("status") == "failed"]
            succeeded_stems = [r["stem"] for r in results if r.get("status") in ("succeeded", "skipped")]
            print(f"  Summary: {len(succeeded_stems)} ok, {len(failed_stems)} failed")
            if failed_stems:
                print(f"  Failed stems: {', '.join(failed_stems)}")
                # Still attempt apply_theme_fixtures — resolve_fixture now emits
                # a theme-aware KeyError that correlates back to these failures.
            # Only refetch if new datasets were successfully ingested (skipped
            # entries don't change the existing catalog state).
            if any(r.get("status") == "succeeded" for r in results):
                existing = await fetch_existing_datasets(client, args.base_url, args.api_key)
            # (Previously: Theme 1 attempted to create a VRT mosaic of the
            #  two signature rasters here. Removed 2026-04-09 because GEBCO
            #  is int16 and NE shaded relief is uint8, so the VRT backend
            #  rejected the dtype mismatch on every run. Map 1.1 ships as
            #  independent stacked raster layers — no fixture references a
            #  'planet-earth-vrt' stem, so nothing depends on this helper.
            #  If/when Phase 999.1 3D terrain work needs a mosaic, reinstate
            #  after picking rasters with compatible dtypes.)
            await assign_collection(client, args.base_url, args.api_key, tm, results)
            _applied, theme_failures = await apply_theme_fixtures(
                client, args.base_url, args.api_key, tm, existing, fixtures_by_theme
            )
            total_fixture_failures += theme_failures

        print("\n=== Demo seed complete ===")
        if total_fixture_failures > 0:
            print(f"WARNING: {total_fixture_failures} fixture(s) failed to apply")
            return 1
        return 0


def main() -> None:
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

    # Propagate main_async's exit code so Docker reports the seeder's
    # outcome accurately (non-zero if any fixture failed to apply).
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
