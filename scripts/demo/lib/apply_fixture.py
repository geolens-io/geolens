"""Apply a map fixture JSON to a live GeoLens instance.

Usage (from the orchestrator):
    from scripts.demo.lib.apply_fixture import apply_fixture

    map_id = await apply_fixture(client, base_url, headers, fixture_path, existing)

The function:
1. Reads the fixture JSON from disk.
2. Calls resolve_fixture to swap _stem+_ext → live dataset UUIDs.
3. POSTs /api/maps/ to create a new empty map.
4. PUTs /api/maps/{map_id} with the fully resolved body.
5. Returns the created map_id (str UUID).

On HTTP error, raises RuntimeError with the status code and first 500 chars
of the response body for debugging.

Auth: Uses the ``X-Api-Key`` header (case-sensitive) from the ``headers`` arg.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from scripts.demo.lib.fixture_schema import resolve_fixture


async def apply_fixture(
    client: httpx.AsyncClient,
    base_url: str,
    headers: dict[str, str],
    fixture_path: Path,
    existing: dict[str, str],
) -> str:
    """Create a map from a JSON fixture file and return the new map ID.

    Args:
        client: Shared httpx.AsyncClient (caller owns lifecycle).
        base_url: GeoLens API base URL (e.g. ``"http://api:8000"``).
        headers: Request headers including ``X-Api-Key``.
        fixture_path: Path to the fixture JSON file on disk.
        existing: ``{source_filename: dataset_id}`` from fetch_existing_datasets.

    Returns:
        The UUID of the newly created map (str).

    Raises:
        RuntimeError: On HTTP errors from the API.
        KeyError: If any fixture layer references a stem not in ``existing``.
    """
    fixture: dict[str, Any] = json.loads(Path(fixture_path).read_text())

    # Resolve _stem+_ext → live dataset UUIDs
    resolved = resolve_fixture(fixture, existing)

    # Step 3: POST /api/maps/ to create a new empty map
    create_body = {
        "name": fixture.get("name") or fixture.get("_meta", {}).get("name", "Untitled"),
        "description": fixture.get("description") or fixture.get("_meta", {}).get("description") or None,
    }
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

    # Step 4: PUT /api/maps/{map_id} with the full resolved body
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

    return map_id
