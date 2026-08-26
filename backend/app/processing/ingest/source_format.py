"""Derive the stored ``source_format`` from an uploaded file path.

One home for the mapping, because two ingest paths make the same decision:
``ingest_file`` (tasks_vector.py) on first upload and ``ingest_reupload``
(tasks_reupload.py) on replace-in-place. They drifted as two copies of
``"shapefile" if suffix == "zip" else suffix``, which is the reason the
zip-container disambiguation below lives here rather than at either site.

Values produced here are constrained by ``chk_datasets_source_format``
(catalog.datasets); adding a new one needs an Alembic migration.
"""

import zipfile
from pathlib import Path

import structlog

logger = structlog.get_logger()

# A zip upload is a Shapefile bundle by default and a File Geodatabase when
# it carries a `.gdb` directory. GDAL tells the two apart on its own — the
# OpenFileGDB driver claims `/vsizip/<archive>.zip` directly — but the value
# stored in `datasets.source_format` is derived from the filename, and every
# zip a `.gdb` arrived in was recorded as `shapefile`.
_FILEGDB_MARKER = ".gdb/"

# Bound the member scan: `validate_zip_safety` already caps an upload at
# MAX_ARCHIVE_ENTRIES (10k) members, and a File Geodatabase announces itself
# in its first few entries. This is the cheap second bound for archives that
# reach this helper by some other door.
_MAX_MEMBERS_SCANNED = 10_000


def zip_contains_filegdb(file_path: str) -> bool:
    """True when a zip archive carries a ``.gdb`` directory.

    Reads the central directory only — no member is decompressed. Any failure
    to read the archive returns ``False`` so the caller keeps the historical
    ``shapefile`` answer: by the time this runs GDAL has already opened the
    file, so a parse failure here is a naming question, not an ingest gate.
    """
    try:
        with zipfile.ZipFile(file_path) as archive:
            for index, name in enumerate(archive.namelist()):
                if index >= _MAX_MEMBERS_SCANNED:
                    break
                # Normalize separators: a zip written on Windows may use `\`,
                # and a `.gdb` at the archive root has no trailing member of
                # its own unless the writer stored directory entries.
                normalized = name.replace("\\", "/").lower()
                if _FILEGDB_MARKER in normalized or normalized.endswith(".gdb"):
                    return True
    except (zipfile.BadZipFile, OSError, ValueError):
        logger.warning(
            "Could not inspect zip members for a File Geodatabase",
            file_path=Path(file_path).name,
            exc_info=True,
        )
    return False


def derive_source_format(file_path: str) -> str:
    """Map an uploaded file path to its stored ``source_format`` value.

    ``.kmz`` normalizes to ``kml``: a KMZ is a zipped KML, one format in two
    containers, and splitting them would double every format-keyed lookup
    (labels, distributions, origin classification) for no gained distinction.
    """
    suffix = Path(file_path).suffix.lower().lstrip(".")
    if suffix == "zip":
        return "fgdb" if zip_contains_filegdb(file_path) else "shapefile"
    if suffix == "kmz":
        return "kml"
    return suffix
