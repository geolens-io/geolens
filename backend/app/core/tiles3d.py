"""Where a 3D Tiles tileset is stored and where the catalog serves it.

The upload and its job sweep, delete, quota, the catalog record, the
distributions, the dataset response and the tileset route all read these
facts, so they are defined once in ``core``.
"""

from __future__ import annotations

import re
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

# The archives a tileset upload takes. A .3tz holds nothing but a tileset, so
# no door takes one without the tileset kind; a .zip without it is other data.
TILESET_ARCHIVE_SUFFIX = ".3tz"
TILESET_UPLOAD_SUFFIXES = frozenset({".zip", TILESET_ARCHIVE_SUFFIX})

# The job-row field an ingest attempt names its unpack prefix under before its
# first put, so the job sweep can reap what a killed attempt wrote.
UNPUBLISHED_TILESET_ATTEMPTS_FIELD = "unpublished_tileset_attempts"

_UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_ATTEMPT_PREFIX = re.compile(f"tiles3d/{_UUID}/{_UUID}/")


def tileset_prefix(dataset_id: uuid.UUID | str) -> str:
    """The storage prefix that holds every unpack attempt of a dataset's tileset."""
    return f"tiles3d/{dataset_id}/"


def tileset_path(dataset_id: uuid.UUID | str) -> str:
    """The API path of a dataset's ``tileset.json``."""
    return f"/datasets/{dataset_id}/tiles3d/tileset.json"


def tileset_attempt_prefix(dataset_id: uuid.UUID, attempt_id: uuid.UUID) -> str:
    """The prefix one unpack attempt writes every object of the tileset under."""
    return f"{tileset_prefix(dataset_id)}{attempt_id}/"


def tileset_attempt_dataset(prefix: str) -> uuid.UUID:
    """The dataset whose tileset an attempt prefix holds."""
    return uuid.UUID(prefix.split("/")[1])


def is_tileset_attempt_prefix(value: object) -> bool:
    """Whether ``value`` is exactly one attempt's prefix, the only shape reaped."""
    return isinstance(value, str) and _ATTEMPT_PREFIX.fullmatch(value) is not None
