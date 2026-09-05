"""Which OGR drivers may open a staged upload.

fix(#1846, GHSA-hrf5-v3cq-frx5): GDAL picks a driver by asking every
registered driver whether it recognises the bytes, and several of them answer
yes to a document that is really a set of instructions. OGR_VRT follows
``<SrcDataSource>`` to an arbitrary local path or URL. The WFS driver
identifies on CONTENT alone -- a file whose bytes open with
``<OGRWFSDataSource>`` is opened by it whatever the file is called, at any
depth inside an archive -- and then fetches whatever ``<URL>`` names. Nothing
about the staged PATH bounds where either read lands.

So the upload path stops asking. The declared upload extension already says
what the file is supposed to be; this module turns that into the repeated
``-if <driver>`` arguments that tell ogrinfo/ogr2ogr which drivers may be
attempted at all. An extension nobody listed falls back to
``ARCHIVE_MEMBER_DRIVERS``, which is broad but still names only local-file
drivers -- the conservative direction for an operator who widens
``UPLOAD_ALLOWED_EXTENSIONS`` to a format this table has not met.

This is the primary layer. ``gdal_vector_safe_env`` in
``processing/raster/vrt.py`` is the independent second one, and it catches
what an allowlist cannot: a driver whose short name contains a space cannot be
named in ``GDAL_SKIP`` at all, and a driver added to a future base image is
excluded here by omission rather than by having been thought about.

Neither reaches the SQLite family. ``GPKG`` is the primary supported upload
format and it is a database the uploader writes in full, schema included, so a
document that reads from outside the file can arrive as a legitimate
GeoPackage. That is a third layer, and it is a content check rather than a
driver one: ``validate_content_directives`` in ``ingest/validation.py``,
which judges an archive member by its bytes rather than by its name.
Every extension here that maps to ``GPKG`` or ``SQLite`` must also appear in
that module's ``SQLITE_FAMILY_EXTENSIONS``, which
``tests/test_rule2_structural.py`` asserts.
"""

from pathlib import Path

# Every driver a legitimate upload can need, and no driver that reaches the
# network or follows a pointer out of the document. A ZIP is the widest case
# by construction: GDAL opens ``/vsizip/<archive>`` and the member could be any
# of these. Names are GDAL driver short names, exactly as ``ogrinfo --formats``
# prints them; an unrecognised name is a WARNING to GDAL rather than an error,
# so ``tests/test_gdal_driver_clamp.py`` pins each one against a real GDAL.
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
# One table, because every vector GDAL subprocess on the upload path asks the
# same question and a second copy is how the two answers drift apart.
#
# ``.kmz`` is a zipped KML that LIBKML opens directly rather than through
# ``/vsizip``, so it gets the KML pair rather than the archive union.
# ``.parquet`` is absent on purpose: it never reaches a GDAL subprocess (the
# Debian build has no Arrow driver, so ``ingest/parquet.py`` handles it
# in-process). ``.tif``/``.tiff`` are raster and go through the raster
# pipeline, which has its own clamp.
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

    Returned as a flat argv fragment so callers splat it into the command they
    are already building. ``-if`` is repeatable; measured accepted by both
    ogrinfo and ogr2ogr on the 3.10.3 the images ship and on 3.13.0.
    """
    args: list[str] = []
    for driver in allowed_input_drivers(file_path):
        args += ["-if", driver]
    return args
