"""Which OGR drivers may open a staged upload.

fix(#1846, GHSA-hrf5-v3cq-frx5): GDAL picks a driver by asking every
registered one whether it recognises the bytes, and several answer yes to a
document that is really a set of instructions — OGR_VRT follows
``<SrcDataSource>`` to an arbitrary path or URL, and WFS identifies on
CONTENT alone (``<OGRWFSDataSource>`` bytes, any filename, any archive
depth) then fetches whatever ``<URL>`` names.

So the upload path stops asking: the declared extension becomes repeated
``-if <driver>`` arguments restricting which drivers may even be attempted.
An unlisted extension falls back to ``ARCHIVE_MEMBER_DRIVERS`` (local-file
drivers only — the conservative direction).

Primary layer. ``gdal_vector_safe_env`` (``processing/raster/vrt.py``) is
the independent second layer, catching what an allowlist can't: a driver
short name containing a space can't be named in ``GDAL_SKIP`` at all, and a
driver added to a future base image is excluded here only by omission.
Neither reaches SQLite/GPKG — GPKG is a legitimate upload format and a
database written in full by the uploader — so the third layer there is a
content check, ``validate_content_directives`` in ``ingest/validation.py``.
Every extension mapped to ``GPKG``/``SQLite`` here must also appear in that
module's ``SQLITE_FAMILY_EXTENSIONS`` (``tests/test_rule2_structural.py``
asserts it).
"""

from pathlib import Path

# Every driver a legitimate upload can need, none that reaches the network
# or follows a pointer out of the document. A ZIP is the widest case: GDAL
# opens ``/vsizip/<archive>`` and the member could be any of these. Names
# are GDAL driver short names as ``ogrinfo --formats`` prints them; an
# unrecognised name is a WARNING to GDAL, not an error, so
# ``tests/test_gdal_driver_clamp.py`` pins each one against a real GDAL.
ARCHIVE_MEMBER_DRIVERS: tuple[str, ...] = (
    "ESRI Shapefile",
    "OpenFileGDB",
    "GPKG",
    "SQLite",
    "GeoJSON",
    "GeoJSONSeq",
    "ESRIJSON",
    "TopoJSON",
    "JSONFG",
    "CSV",
    "KML",
    "LIBKML",
    "FlatGeobuf",
    "GML",
    "XLSX",
    "XLS",
    "ODS",
    "MapInfo File",
    "DXF",
    "DGN",
    "GPX",
    "OGR_GMT",
    "MVT",
    "PMTiles",
    "GTFS",
)

# Declared upload extension -> the drivers that may be attempted for it.
# One table, shared by every vector GDAL subprocess on the upload path, so a
# second copy can't drift from this one.
#
# ``.kmz`` is a zipped KML LIBKML opens directly (not via ``/vsizip``), so it
# gets the KML pair, not the archive union. ``.parquet`` is absent on
# purpose: it never reaches a GDAL subprocess (no Arrow driver on this
# build; ``ingest/parquet.py`` handles it in-process). ``.tif``/``.tiff`` go
# through the raster pipeline's own clamp.
_DRIVERS_BY_EXTENSION: dict[str, tuple[str, ...]] = {
    ".zip": ARCHIVE_MEMBER_DRIVERS,
    ".shz": ("ESRI Shapefile",),
    ".shp": ("ESRI Shapefile",),
    ".gdb": ("OpenFileGDB",),
    ".gpkg": ("GPKG",),
    ".sqlite": ("SQLite",),
    ".sqlite3": ("SQLite",),
    ".db": ("SQLite",),
    ".geojson": ("GeoJSON",),
    ".json": ("GeoJSON", "GeoJSONSeq", "ESRIJSON", "TopoJSON", "JSONFG"),
    ".topojson": ("TopoJSON",),
    ".geojsonl": ("GeoJSONSeq",),
    ".geojsons": ("GeoJSONSeq",),
    ".csv": ("CSV",),
    ".tsv": ("CSV",),
    ".psv": ("CSV",),
    ".kml": ("LIBKML", "KML"),
    ".kmz": ("LIBKML", "KML"),
    ".fgb": ("FlatGeobuf",),
    ".gml": ("GML",),
    ".xlsx": ("XLSX",),
    ".xlsm": ("XLSX",),
    ".xls": ("XLS",),
    ".ods": ("ODS",),
    ".tab": ("MapInfo File",),
    ".mif": ("MapInfo File",),
    ".dxf": ("DXF",),
    ".dgn": ("DGN",),
    ".gpx": ("GPX",),
    ".gmt": ("OGR_GMT",),
    ".mvt": ("MVT",),
    ".pmtiles": ("PMTiles",),
}


def allowed_input_drivers(file_path: str) -> tuple[str, ...]:
    """The drivers that may be attempted for a staged upload path."""
    suffix = Path(file_path).suffix.lower()
    return _DRIVERS_BY_EXTENSION.get(suffix, ARCHIVE_MEMBER_DRIVERS)


def local_input_driver_args(file_path: str) -> list[str]:
    """``-if`` arguments restricting ogrinfo/ogr2ogr to the allowed drivers.

    Flat argv fragment for callers to splat into the command being built.
    ``-if`` is repeatable; verified accepted by both tools on GDAL 3.10.3
    and 3.13.0.
    """
    args: list[str] = []
    for driver in allowed_input_drivers(file_path):
        args += ["-if", driver]
    return args
