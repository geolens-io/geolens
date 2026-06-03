"""Tile fetch scenario tasks for GeoLens load testing.

Exercises vector tile and raster tile proxy endpoints with HMAC token signing.
"""

import logging
import random

from common import (
    AUTH_HEADERS,
    SAMPLE_LOCATIONS,
    DatasetMixin,
    TileTokenCache,
    lon_lat_to_tile,
    random_tile,
)

logger = logging.getLogger(__name__)

# Module-level token cache shared across all tasks
_token_cache = TileTokenCache()


def _pick_location_tile(zoom: int) -> tuple[int, int]:
    """Pick a tile at the given zoom from a random sample location."""
    lon, lat = random.choice(SAMPLE_LOCATIONS)
    return lon_lat_to_tile(lon, lat, zoom)


def fetch_vector_tile(client):
    """Fetch a vector tile at z8-z14 from a random dataset and location."""
    vector_datasets = DatasetMixin.get_vector_datasets()
    if not vector_datasets:
        return

    ds = random.choice(vector_datasets)
    dataset_id = ds.get("id", "")
    table_name = ds.get("table_name", "")
    if not table_name:
        return

    token = _token_cache.get_token(client, str(dataset_id))
    if not token:
        return

    zoom = random.randint(8, 14)
    x, y = _pick_location_tile(zoom)

    sig = token.get("sig", "")
    exp = token.get("exp", "")
    scope = token.get("scope", "")

    with client.get(
        f"/api/tiles/data.{table_name}/{zoom}/{x}/{y}.pbf?sig={sig}&exp={exp}&scope={scope}",
        headers=AUTH_HEADERS,
        name="/api/tiles/[table]/[z]/[x]/[y].pbf",
        catch_response=True,
    ) as resp:
        if resp.status_code in (200, 204):
            resp.success()
        else:
            resp.failure(f"Vector tile returned {resp.status_code}")


def fetch_tile_low_zoom(client):
    """Fetch a vector tile at z4-z7 for broad coverage."""
    vector_datasets = DatasetMixin.get_vector_datasets()
    if not vector_datasets:
        return

    ds = random.choice(vector_datasets)
    dataset_id = ds.get("id", "")
    table_name = ds.get("table_name", "")
    if not table_name:
        return

    token = _token_cache.get_token(client, str(dataset_id))
    if not token:
        return

    zoom = random.randint(4, 7)
    x, y = random_tile(zoom)

    sig = token.get("sig", "")
    exp = token.get("exp", "")
    scope = token.get("scope", "")

    with client.get(
        f"/api/tiles/data.{table_name}/{zoom}/{x}/{y}.pbf?sig={sig}&exp={exp}&scope={scope}",
        headers=AUTH_HEADERS,
        name="/api/tiles/[table]/[z]/[x]/[y].pbf",
        catch_response=True,
    ) as resp:
        if resp.status_code in (200, 204):
            resp.success()
        else:
            resp.failure(f"Low-zoom tile returned {resp.status_code}")


def fetch_raster_tile(client):
    """Fetch a raster tile via the proxy endpoint."""
    raster_datasets = DatasetMixin.get_raster_datasets()
    if not raster_datasets:
        return

    ds = random.choice(raster_datasets)
    dataset_id = ds.get("id", "")

    zoom = random.randint(6, 12)
    x, y = _pick_location_tile(zoom)

    with client.get(
        f"/api/tiles/raster-proxy/{dataset_id}/{zoom}/{x}/{y}.png",
        headers=AUTH_HEADERS,
        name="/api/tiles/raster-proxy/[id]/[z]/[x]/[y].png",
        catch_response=True,
    ) as resp:
        if resp.status_code in (200, 204):
            resp.success()
        else:
            resp.failure(f"Raster tile returned {resp.status_code}")
