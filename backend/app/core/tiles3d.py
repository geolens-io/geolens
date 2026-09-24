"""Where a 3D Tiles tileset is stored and where the catalog serves it.

The upload and its job sweep, delete, quota, the catalog record, the
distributions, the dataset response and the tileset route all read these
facts, so they are defined once in ``core``.
"""

from __future__ import annotations

import uuid

# The internal dataset_assets key of a tileset. Its href points at the live
# unpack attempt and its size_bytes, the unpacked total, is what the storage
# quota counts. It is never published: clients reach the tileset by its path.
TILESET_ASSET_KEY = "tileset"

# The entry point's media type; tile content keeps the type of its own format.
TILESET_MEDIA_TYPE = "application/json"

# The entry point every tileset archive carries, and the file the pointer names.
TILESET_ENTRY_POINT = "tileset.json"

# The upload `kind` that routes a zip to the tileset ingest, and the
# `file_type` its job is stamped with. A tileset zip looks like any other zip
# from outside, so the request naming it is the only discriminator.
TILESET_FILE_TYPE = "tiles3d"

# The job-row field an ingest attempt names its unpack prefix under before its
# first put, so the job sweep can reap what a killed attempt wrote.
UNPUBLISHED_TILESET_ATTEMPTS_FIELD = "unpublished_tileset_attempts"


def tileset_prefix(dataset_id: uuid.UUID | str) -> str:
    """The storage prefix that holds every unpack attempt of a dataset's tileset."""
    return f"tiles3d/{dataset_id}/"


def tileset_path(dataset_id: uuid.UUID | str) -> str:
    """The API path of a dataset's ``tileset.json``."""
    return f"/datasets/{dataset_id}/tiles3d/tileset.json"


def tileset_attempt_prefix(dataset_id: uuid.UUID, attempt_id: uuid.UUID) -> str:
    """The prefix one unpack attempt writes every object of the tileset under."""
    return f"{tileset_prefix(dataset_id)}{attempt_id}/"
