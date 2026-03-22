"""Export scenario task for GeoLens load testing.

Exercises the dataset export endpoint with GeoJSON format.
"""

import random

from common import AUTH_HEADERS, DatasetMixin


def export_dataset_geojson(client):
    """Export a random vector dataset as GeoJSON."""
    datasets = DatasetMixin.get_vector_datasets()
    if not datasets:
        return

    ds = random.choice(datasets)
    dataset_id = ds.get("id", "")

    with client.get(
        f"/api/datasets/{dataset_id}/export?format=geojson",
        headers=AUTH_HEADERS,
        name="/api/datasets/[id]/export",
        catch_response=True,
    ) as resp:
        if resp.status_code == 200:
            resp.success()
        elif resp.status_code == 400:
            # Non-spatial dataset or format mismatch -- not a test failure
            resp.success()
        else:
            resp.failure(f"Export returned {resp.status_code}")
