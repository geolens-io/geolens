"""Where a COPC point cloud is stored and how the catalog names it.

The upload doors, the job sweep, delete, quota and the dataset response read
these facts, so they are defined once in ``core``.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

# The internal dataset_assets key of a point cloud. Its href points at the
# live upload attempt's file and its size_bytes is what the storage quota
# counts. It is never published.
POINTCLOUD_ASSET_KEY = "pointcloud"

# The media type Planetary Computer's STAC gives COPC assets; the COPC
# specification names none.
POINTCLOUD_MEDIA_TYPE = "application/vnd.laszip+copc"

# The upload `kind` that routes a .laz to the point cloud ingest, and the
# `file_type` its job is stamped with.
POINTCLOUD_FILE_TYPE = "pointcloud"

# A COPC file is a LAZ file. No door takes a .laz without the point cloud kind,
# so GDAL never opens one.
POINTCLOUD_SUFFIX = ".laz"
LAZ_WITHOUT_KIND = (
    "A .laz file holds a point cloud. Upload it as a new dataset with "
    f"kind={POINTCLOUD_FILE_TYPE}."
)

# Every attempt's object has this name, and the route that serves it ends in it.
POINTCLOUD_FILENAME = "data.copc.laz"

_UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_ATTEMPT_KEY = re.compile(
    rf"pointclouds/{_UUID}/(?P<attempt>{_UUID})/{re.escape(POINTCLOUD_FILENAME)}"
)


def pointcloud_prefix(dataset_id: uuid.UUID | str) -> str:
    """The storage prefix that holds every upload attempt of a point cloud."""
    return f"pointclouds/{dataset_id}/"


def pointcloud_attempt_key(dataset_id: uuid.UUID, attempt_id: uuid.UUID) -> str:
    """The object one ingest attempt writes the point cloud to."""
    return f"{pointcloud_prefix(dataset_id)}{attempt_id}/{POINTCLOUD_FILENAME}"


def is_pointcloud_attempt_key(value: object) -> bool:
    """Whether ``value`` is exactly one attempt's object, the only shape reaped."""
    return isinstance(value, str) and _ATTEMPT_KEY.fullmatch(value) is not None


def is_laz(filename: str | None) -> bool:
    """Whether an upload's name marks it as a point cloud."""
    return Path(filename or "").suffix.lower() == POINTCLOUD_SUFFIX
