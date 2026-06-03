"""Catalog browsing scenario tasks for GeoLens load testing.

Exercises paginated dataset listing and geometry-type filtering.
"""

import random

from common import AUTH_HEADERS

GEOMETRY_TYPES = ["Point", "LineString", "Polygon", "MultiPolygon"]


def browse_catalog(client):
    """Browse the dataset catalog with random pagination offset."""
    skip = random.randint(0, 10) * 50  # offsets 0-500 in steps of 50
    with client.get(
        f"/api/datasets/?limit=50&skip={skip}",
        headers=AUTH_HEADERS,
        name="/api/datasets/?limit=50",
        catch_response=True,
    ) as resp:
        if resp.status_code == 200:
            resp.success()
        else:
            resp.failure(f"Catalog browse returned {resp.status_code}")


def browse_catalog_filtered(client):
    """Browse the dataset catalog filtered by geometry type."""
    geom_type = random.choice(GEOMETRY_TYPES)
    with client.get(
        f"/api/datasets/?limit=50&geometry_type={geom_type}",
        headers=AUTH_HEADERS,
        name="/api/datasets/?geometry_type=[type]",
        catch_response=True,
    ) as resp:
        if resp.status_code == 200:
            resp.success()
        else:
            resp.failure(f"Filtered browse returned {resp.status_code}")
