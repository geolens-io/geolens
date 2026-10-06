"""Derive the stored ``source_format`` from an uploaded file path.

One home for the mapping: the first-upload and reupload ingest paths used to
carry two drifting copies of ``"shapefile" if suffix == "zip" else suffix``.

Values produced here are constrained by ``chk_datasets_source_format``
(catalog.datasets); adding a new one needs an Alembic migration.
"""

import zipfile
from pathlib import Path, PurePosixPath

import structlog

logger = structlog.get_logger()

# GDAL tells the zipped formats apart itself, but `source_format` is derived
# from the filename, so the central directory is read for the data member.
# Earlier entries win when a bundle carries several and no layer is selected
# (a shapefile zip often ships a `.csv` or `.json` sidecar).
_FILEGDB_MARKER = ".gdb/"
_MEMBER_SUFFIX_FORMATS = (
    (".shp", "shapefile"),
    (".gpkg", "gpkg"),
    (".geojson", "geojson"),
    (".csv", "csv"),
    (".json", "geojson"),
)

# Cheap second bound for archives reaching this helper outside
# `validate_zip_safety`'s MAX_ARCHIVE_ENTRIES (10k) cap.
_MAX_MEMBERS_SCANNED = 10_000


def zip_data_format(file_path: str, layer_name: str | None = None) -> str:
    """Classify a zip by its data member, defaulting to ``shapefile``.

    A ``layer_name`` selects the member whose stem matches it, since that is
    the one GDAL imported (layer names are case-sensitive); the suffix priority only settles archives where
    no layer is chosen or none matches.

    Reads the central directory only; no member is decompressed. Any failure
    to read the archive returns ``shapefile`` (GDAL has already opened the
    file by the time this runs, so this is a naming question, not a gate).
    """
    found: set[str] = set()
    selected: str | None = None
    try:
        with zipfile.ZipFile(file_path) as archive:
            for index, name in enumerate(archive.namelist()):
                if index >= _MAX_MEMBERS_SCANNED:
                    break
                # Windows zips may use `\` separators.
                slashed = name.replace("\\", "/")
                normalized = slashed.lower()
                if _FILEGDB_MARKER in normalized or normalized.endswith(".gdb"):
                    return "fgdb"
                if normalized.startswith("__macosx/"):
                    continue
                for suffix, fmt in _MEMBER_SUFFIX_FORMATS:
                    if normalized.endswith(suffix):
                        found.add(suffix)
                        if layer_name and PurePosixPath(slashed).stem == layer_name:
                            selected = selected or fmt
    except (zipfile.BadZipFile, OSError, ValueError):
        logger.warning(
            "Could not inspect zip members for the source format",
            file_path=Path(file_path).name,
            exc_info=True,
        )
    if selected:
        return selected
    for suffix, fmt in _MEMBER_SUFFIX_FORMATS:
        if suffix in found:
            return fmt
    return "shapefile"


def derive_source_format(file_path: str, layer_name: str | None = None) -> str:
    """Map an uploaded file path to its stored ``source_format`` value.

    ``.kmz`` normalizes to ``kml``: a KMZ is a zipped KML, one format in two
    containers, and splitting them would double every format-keyed lookup
    (labels, distributions, origin classification) for no gained distinction.

    ``layer_name`` is the layer the import selected; it decides which member
    of a multi-format zip is the source.
    """
    suffix = Path(file_path).suffix.lower().lstrip(".")
    if suffix == "zip":
        return zip_data_format(file_path, layer_name)
    if suffix == "kmz":
        return "kml"
    return suffix
