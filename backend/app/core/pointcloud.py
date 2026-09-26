"""Where a COPC point cloud is stored and how the catalog names it.

Delete, quota and the dataset response read these facts, so they are defined
once in ``core``.
"""

from __future__ import annotations

import uuid

# The internal dataset_assets key of a point cloud. Its href points at the
# live upload attempt's file and its size_bytes is what the storage quota
# counts. It is never published: clients reach the file by its route.
POINTCLOUD_ASSET_KEY = "pointcloud"

# The media type Planetary Computer's STAC gives COPC assets; the COPC
# specification names none.
POINTCLOUD_MEDIA_TYPE = "application/vnd.laszip+copc"


def pointcloud_prefix(dataset_id: uuid.UUID | str) -> str:
    """The storage prefix that holds every upload attempt of a point cloud."""
    return f"pointclouds/{dataset_id}/"
