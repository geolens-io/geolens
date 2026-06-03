"""GeoLens Locust load testing suite.

Exercises the four critical API paths: search, catalog browse,
tile fetch, and dataset detail under configurable concurrency.

Usage:
    cd tests/load
    GEOLENS_API_KEY=<key> locust --headless -u 10 -r 2 --run-time 60s -f locustfile.py

Environment variables:
    GEOLENS_API_KEY  - Required. API key for authentication.
    GEOLENS_BASE_URL - Optional. Default: http://localhost:8080
"""

import sys
import os

# Ensure the tests/load directory is on the path so task modules
# can import common.py without package installation.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from locust import HttpUser, between, task

from common import BASE_URL, DatasetMixin, TileTokenCache
from tasks.search import search_fts, search_hybrid
from tasks.browse import browse_catalog, browse_catalog_filtered
from tasks.tiles import fetch_vector_tile, fetch_tile_low_zoom, fetch_raster_tile
from tasks.detail import view_dataset_detail, fetch_dataset_rows
from tasks.export import export_dataset_geojson


class GeoLensUser(HttpUser):
    """Simulates a GeoLens user exercising all critical API paths.

    Traffic distribution (approximate):
        - Search tasks:  ~29% (FTS + hybrid, weight 4)
        - Browse tasks:  ~21% (catalog + filtered, weight 3)
        - Tile tasks:    ~36% (vector high-zoom, vector low-zoom, raster, weight 5)
        - Detail tasks:  ~7% (dataset detail + feature rows, weight 2)
        - Export tasks:  ~7% (GeoJSON export, weight 1)
    """

    host = BASE_URL
    wait_time = between(1, 3)

    def on_start(self):
        """Authenticate and discover available datasets."""
        DatasetMixin.discover_datasets(self.client)
        self._token_cache = TileTokenCache()

    # ----- Search tasks (weight 3 total) -----

    @task(3)
    def do_search_fts(self):
        search_fts(self.client)

    @task(1)
    def do_search_hybrid(self):
        search_hybrid(self.client)

    # ----- Browse tasks (weight 2 total) -----

    @task(2)
    def do_browse_catalog(self):
        browse_catalog(self.client)

    @task(1)
    def do_browse_filtered(self):
        browse_catalog_filtered(self.client)

    # ----- Tile tasks (weight 4 total) -----

    @task(3)
    def do_fetch_vector_tile(self):
        fetch_vector_tile(self.client)

    @task(1)
    def do_fetch_tile_low_zoom(self):
        fetch_tile_low_zoom(self.client)

    @task(1)
    def do_fetch_raster_tile(self):
        fetch_raster_tile(self.client)

    # ----- Detail tasks (weight 1 total) -----

    @task(1)
    def do_view_dataset_detail(self):
        view_dataset_detail(self.client)

    @task(1)
    def do_fetch_dataset_rows(self):
        fetch_dataset_rows(self.client)

    # ----- Export tasks (weight 1 total) -----

    @task(1)
    def do_export_dataset(self):
        export_dataset_geojson(self.client)
