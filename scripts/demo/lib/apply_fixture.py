"""Apply a map fixture JSON to a live GeoLens instance.

Usage (from the orchestrator):
    from scripts.demo.lib.apply_fixture import apply_fixture

    map_id = await apply_fixture(client, base_url, headers, fixture_path, existing)

The function:
1. Accepts a pre-parsed fixture dict (no disk I/O inside this function) — the
   orchestrator reads + parses each JSON once when building its theme index.
2. Checks ``GET /api/maps/?limit=100`` for an existing map with the same name
   and reuses it via PUT (idempotent re-runs avoid orphan duplicates).
3. If no existing map matches, POSTs ``/api/maps/`` to create a new empty map.
4. PUTs ``/api/maps/{map_id}`` with the fully resolved body.
5. Returns the map_id (str UUID).

On HTTP error, raises RuntimeError with the status code and first 500 chars
of the response body for debugging. PUT failures on freshly-created maps
trigger a best-effort DELETE cleanup so the catalog doesn't accumulate orphans.

Auth: Uses the ``X-Api-Key`` header (case-sensitive) from the ``headers`` arg.
"""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
import sys
from pathlib import Path
from typing import cast

import httpx

# Support both: imported as scripts.demo.lib.apply_fixture (from project root)
# and imported as lib.apply_fixture (from scripts/demo/ via orchestrator sys.path insert).
try:
    from scripts.demo.lib.fixture_schema import FixtureDict, resolve_fixture
except ModuleNotFoundError:
    # When called from the orchestrator context (sys.path includes scripts/demo/)
    sys.path.insert(0, str(Path(__file__).parent))
    from fixture_schema import FixtureDict, resolve_fixture  # type: ignore[no-redef]

logger = logging.getLogger("apply_fixture")


async def _find_existing_map_id(
    client: httpx.AsyncClient,
    base_url: str,
    headers: dict[str, str],
    name: str,
) -> str | None:
    """Return the map ID matching ``name`` from /api/maps/, or None."""
    try:
        resp = await client.get(
            f"{base_url}/api/maps/?limit=100",
            headers=headers,
        )
    except Exception as exc:
        logger.warning("GET /api/maps/ (idempotency check) failed: %s", exc)
        return None
    if resp.status_code >= 400:
        return None
    body = resp.json()
    items = body.get("maps") or body.get("items") or body.get("results") or []
    for item in items:
        if item.get("name") == name:
            return cast(str, item["id"])
    return None


def _fixture_thumbnail_data_uri(
    fixture_path: Path,
    fixture: FixtureDict,
) -> str | None:
    """Return the data URI for a fixture thumbnail, or None if absent."""
    thumbnail_ref = fixture.get("_thumbnail")
    if not thumbnail_ref:
        return None

    fixture_dir = fixture_path.parent.resolve()
    thumbnail_path = (fixture_dir / thumbnail_ref).resolve()
    try:
        thumbnail_path.relative_to(fixture_dir)
    except ValueError as exc:
        raise RuntimeError(
            f"{fixture_path.name} thumbnail must stay under {fixture_dir}: "
            f"{thumbnail_ref!r}"
        ) from exc

    if not thumbnail_path.is_file():
        raise RuntimeError(
            f"{fixture_path.name} references missing thumbnail: {thumbnail_ref}"
        )

    mime_type, _encoding = mimetypes.guess_type(thumbnail_path.name)
    if mime_type is None or not mime_type.startswith("image/"):
        raise RuntimeError(
            f"{fixture_path.name} thumbnail must be an image file: {thumbnail_ref}"
        )

    encoded = base64.b64encode(thumbnail_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


async def _upload_fixture_thumbnail(
    client: httpx.AsyncClient,
    base_url: str,
    headers: dict[str, str],
    map_id: str,
    fixture_path: Path,
    fixture: FixtureDict,
) -> None:
    """Upload the fixture's marketing thumbnail after map body persistence."""
    data_uri = _fixture_thumbnail_data_uri(fixture_path, fixture)
    if data_uri is None:
        return

    resp = await client.put(
        f"{base_url}/api/maps/{map_id}/thumbnail/",
        headers={**headers, "Content-Type": "application/json"},
        json={"data_uri": data_uri},
    )
    if resp.status_code >= 400:
        raise RuntimeError(
            f"PUT /api/maps/{map_id}/thumbnail/ failed with {resp.status_code}: "
            f"{resp.text[:500]}"
        )


async def apply_fixture(
    client: httpx.AsyncClient,
    base_url: str,
    headers: dict[str, str],
    fixture_path: Path,
    existing: dict[str, str],
    *,
    fixture: FixtureDict | None = None,
) -> str:
    """Create or update a map from a JSON fixture and return the map ID.

    Args:
        client: Shared httpx.AsyncClient (caller owns lifecycle).
        base_url: GeoLens API base URL (e.g. ``"http://api:8000"``).
        headers: Request headers including ``X-Api-Key``.
        fixture_path: Path to the fixture JSON file on disk (used for error
            messages and as a fallback read if ``fixture`` is not provided).
        existing: ``{source_filename: dataset_id}`` from fetch_existing_datasets.
        fixture: Optional pre-parsed fixture dict. If provided, the file at
            ``fixture_path`` is NOT re-read — the orchestrator indexes fixtures
            in a single pass and passes the parsed dict to avoid duplicate I/O.

    Returns:
        The UUID of the created-or-updated map (str).

    Raises:
        RuntimeError: On HTTP errors from the API.
        KeyError: If any fixture layer references a stem not in ``existing``.
    """
    if fixture is None:
        fixture = cast(FixtureDict, json.loads(Path(fixture_path).read_text()))

    # Resolve _stem+_ext → live dataset UUIDs
    resolved = resolve_fixture(fixture, existing)

    name = fixture.get("name") or fixture.get("_meta", {}).get("name", "Untitled")
    description = (
        fixture.get("description")
        or fixture.get("_meta", {}).get("description")
        or None
    )

    # Idempotency check — if a map with this name already exists, PUT to it
    # instead of POSTing a duplicate. Prevents orphan accumulation on re-runs.
    existing_map_id = await _find_existing_map_id(client, base_url, headers, name)
    if existing_map_id:
        put_resp = await client.put(
            f"{base_url}/api/maps/{existing_map_id}",
            headers={**headers, "Content-Type": "application/json"},
            json=resolved,
        )
        if put_resp.status_code >= 400:
            raise RuntimeError(
                f"PUT /api/maps/{existing_map_id} (idempotent update) failed with "
                f"{put_resp.status_code}: {put_resp.text[:500]}"
            )
        await _upload_fixture_thumbnail(
            client, base_url, headers, existing_map_id, fixture_path, fixture
        )
        return existing_map_id

    # Step 3: POST /api/maps/ to create a new empty map
    create_body = {"name": name, "description": description}
    create_resp = await client.post(
        f"{base_url}/api/maps/",
        headers={**headers, "Content-Type": "application/json"},
        json=create_body,
    )
    if create_resp.status_code >= 400:
        raise RuntimeError(
            f"POST /api/maps/ failed with {create_resp.status_code}: "
            f"{create_resp.text[:500]}"
        )

    map_id: str = create_resp.json()["id"]

    # Step 4: PUT /api/maps/{map_id} with the full resolved body.
    # If the PUT fails we must DELETE the orphan empty map so repeated runs
    # with transient failures don't accumulate junk in the catalog.
    try:
        put_resp = await client.put(
            f"{base_url}/api/maps/{map_id}",
            headers={**headers, "Content-Type": "application/json"},
            json=resolved,
        )
        if put_resp.status_code >= 400:
            raise RuntimeError(
                f"PUT /api/maps/{map_id} failed with {put_resp.status_code}: "
                f"{put_resp.text[:500]}"
            )
        await _upload_fixture_thumbnail(
            client, base_url, headers, map_id, fixture_path, fixture
        )
    except Exception:
        # Best-effort cleanup of the orphaned empty map. The DELETE endpoint
        # requires a confirm_title body matching the map's name. We surface
        # cleanup failures via logger.warning so the operator knows the catalog
        # may have a stale entry, without masking the original PUT error.
        try:
            delete_resp = await client.request(
                "DELETE",
                f"{base_url}/api/maps/{map_id}",
                headers={**headers, "Content-Type": "application/json"},
                json={"confirm_title": name},
            )
            if delete_resp.status_code >= 400:
                logger.warning(
                    "Orphan DELETE /api/maps/%s returned %d: %s",
                    map_id,
                    delete_resp.status_code,
                    delete_resp.text[:200],
                )
        except Exception as cleanup_exc:
            logger.warning("Orphan cleanup failed for map %s: %s", map_id, cleanup_exc)
        raise

    return map_id
