"""Shared utilities for GeoLens Locust load tests.

Provides authentication, dataset discovery, tile coordinate helpers,
search term pools, and tile token caching.
"""

import logging
import math
import os
import random
import time

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = os.environ.get("GEOLENS_BASE_URL", "http://localhost:8080")

API_KEY = os.environ.get("GEOLENS_API_KEY")
if not API_KEY:
    raise EnvironmentError(
        "GEOLENS_API_KEY environment variable is required. "
        "Set it to a valid API key before running load tests."
    )

AUTH_HEADERS = {"X-Api-Key": API_KEY}

# ---------------------------------------------------------------------------
# Search term pool
# ---------------------------------------------------------------------------

SEARCH_TERMS = [
    "water", "roads", "boundary", "rivers", "countries",
    "population", "urban", "forest", "coast", "airport",
    "rail", "lakes", "elevation", "land", "ocean",
    "islands", "ports", "parks", "glaciers", "reefs",
]

# ---------------------------------------------------------------------------
# Sample locations for spatially distributed tile requests
# ---------------------------------------------------------------------------

SAMPLE_LOCATIONS = [
    (-74.006, 40.7128),    # New York City
    (-0.1276, 51.5074),    # London
    (139.6917, 35.6895),   # Tokyo
    (151.2093, -33.8688),  # Sydney
    (-46.6333, -23.5505),  # Sao Paulo
    (3.3792, 6.5244),      # Lagos
    (72.8777, 19.0760),    # Mumbai
    (116.4074, 39.9042),   # Beijing
    (18.4241, -33.9249),   # Cape Town
    (-99.1332, 19.4326),   # Mexico City
]

# ---------------------------------------------------------------------------
# Tile coordinate helpers
# ---------------------------------------------------------------------------


def lon_lat_to_tile(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    """Convert longitude/latitude to slippy map tile coordinates."""
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
    # Clamp to valid range
    x = max(0, min(n - 1, x))
    y = max(0, min(n - 1, y))
    return x, y


def random_tile(zoom: int) -> tuple[int, int]:
    """Generate a random valid tile coordinate at the given zoom level."""
    n = 2 ** zoom
    return random.randint(0, n - 1), random.randint(0, n - 1)


# ---------------------------------------------------------------------------
# Dataset discovery mixin
# ---------------------------------------------------------------------------


class DatasetMixin:
    """Mixin providing dataset discovery and caching for Locust users."""

    _all_datasets: list[dict] | None = None
    _vector_datasets: list[dict] | None = None
    _raster_datasets: list[dict] | None = None

    @classmethod
    def discover_datasets(cls, client) -> list[dict]:
        """Paginate /api/datasets/ and cache the full list of datasets."""
        if cls._all_datasets is not None:
            return cls._all_datasets

        datasets = []
        skip = 0
        limit = 50
        while True:
            resp = client.get(
                f"/api/datasets/?limit={limit}&skip={skip}",
                headers=AUTH_HEADERS,
                name="/api/datasets/ [discovery]",
            )
            if resp.status_code != 200:
                logger.warning("Dataset discovery failed: %s", resp.status_code)
                break
            data = resp.json()
            items = data if isinstance(data, list) else data.get("datasets", data.get("items", data.get("results", [])))
            if not items:
                break
            datasets.extend(items)
            skip += limit
            if len(items) < limit:
                break

        cls._all_datasets = datasets
        cls._vector_datasets = [d for d in datasets if d.get("table_name")]
        cls._raster_datasets = [d for d in datasets if d.get("record_type") == "raster"]

        logger.info(
            "Discovered %d datasets (%d vector, %d raster)",
            len(datasets),
            len(cls._vector_datasets),
            len(cls._raster_datasets),
        )
        return datasets

    @classmethod
    def get_vector_datasets(cls) -> list[dict]:
        """Return cached vector datasets (those with a table_name)."""
        return cls._vector_datasets or []

    @classmethod
    def get_raster_datasets(cls) -> list[dict]:
        """Return cached raster datasets (record_type == 'raster')."""
        return cls._raster_datasets or []


# ---------------------------------------------------------------------------
# Tile token cache
# ---------------------------------------------------------------------------


class TileTokenCache:
    """Thread-safe (gevent-compatible) cache for HMAC tile tokens.

    Tokens are valid for 15 minutes; we cache with a 10-minute TTL
    to avoid using expired tokens.
    """

    TTL_SECONDS = 600  # 10 minutes

    def __init__(self):
        self._cache: dict[str, tuple[dict, float]] = {}

    def get_token(self, client, dataset_id: str, headers: dict | None = None) -> dict | None:
        """Fetch (or return cached) tile signing token for a dataset."""
        now = time.monotonic()
        cached = self._cache.get(dataset_id)
        if cached and (now - cached[1]) < self.TTL_SECONDS:
            return cached[0]

        resp = client.get(
            f"/api/tiles/token/{dataset_id}/",
            headers=headers or AUTH_HEADERS,
            name="/api/tiles/token/[id]",
        )
        if resp.status_code != 200:
            logger.warning("Tile token fetch failed for %s: %s", dataset_id, resp.status_code)
            return None

        token_data = resp.json()
        self._cache[dataset_id] = (token_data, now)
        return token_data
