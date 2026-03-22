"""Dataset detail scenario tasks for GeoLens load testing.

Exercises dataset detail and feature row endpoints.
"""

import random

from common import AUTH_HEADERS, DatasetMixin


def view_dataset_detail(client):
    """Fetch detail for a random dataset."""
    datasets = DatasetMixin._all_datasets
    if not datasets:
        return

    ds = random.choice(datasets)
    dataset_id = ds.get("id", "")

    with client.get(
        f"/api/datasets/{dataset_id}",
        headers=AUTH_HEADERS,
        name="/api/datasets/[id]",
        catch_response=True,
    ) as resp:
        if resp.status_code == 200:
            resp.success()
        else:
            resp.failure(f"Dataset detail returned {resp.status_code}")


def fetch_dataset_rows(client):
    """Fetch feature rows for a random dataset."""
    datasets = DatasetMixin._all_datasets
    if not datasets:
        return

    ds = random.choice(datasets)
    dataset_id = ds.get("id", "")

    with client.get(
        f"/api/datasets/{dataset_id}/rows?limit=100",
        headers=AUTH_HEADERS,
        name="/api/datasets/[id]/rows",
        catch_response=True,
    ) as resp:
        if resp.status_code == 200:
            resp.success()
        else:
            resp.failure(f"Dataset rows returned {resp.status_code}")
