"""Where a 3D Tiles tileset is stored and where the catalog serves it.

Delete, quota, the catalog record, the distributions, the dataset response and
the tileset route all read these facts, so they are defined once in ``core``.
"""

from __future__ import annotations

import uuid

# The internal dataset_assets key of a tileset. Its href points at the live
# unpack attempt and its size_bytes, the unpacked total, is what the storage
# quota counts. It is never published: clients reach the tileset by its path.
TILESET_ASSET_KEY = "tileset"

# The entry point's media type; tile content keeps the type of its own format.
TILESET_MEDIA_TYPE = "application/json"


def tileset_prefix(dataset_id: uuid.UUID | str) -> str:
    """The storage prefix that holds every unpack attempt of a dataset's tileset."""
    return f"tiles3d/{dataset_id}/"


def tileset_path(dataset_id: uuid.UUID | str) -> str:
    """The API path of a dataset's ``tileset.json``."""
    return f"/datasets/{dataset_id}/tiles3d/tileset.json"
