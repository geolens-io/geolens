"""GDAL driver-registration clamps for every vector subprocess, wherever it runs.

Lives in ``platform/`` because ``modules/catalog/sources/preview.py`` needs
them and ``modules/catalog/`` may not import ``app.processing.*``
(``test_layering.py``); moving them under a product domain puts them out of
reach of that caller. Imports nothing from ``app.modules.*`` or
``app.processing.*``.

The raster VSI clamps (``gdal_safe_env``, ``gdal_safe_open_env``) stay in
``processing/raster/vrt.py``, which bounds a different thing and builds a
``rasterio.Env``. That module re-exports both helpers here, so either import
path works (#1857 item 3).
"""

import os

# fix(#1846, GHSA-hrf5-v3cq-frx5): the raster clamps above say nothing about
# which DRIVER GDAL picks, and driver selection is the whole question for a
# vector source. Several OGR drivers treat the bytes they are handed as
# instructions rather than as data: OGR_VRT follows <SrcDataSource> to any
# local path or URL, and the WFS driver identifies on CONTENT alone -- a file
# whose bytes open with <OGRWFSDataSource> is opened by it whatever the file
# is named -- and then fetches whatever <URL> says. A staged upload is a local
# path, so nothing about the PATH bounds where the read lands.
#
# GDAL_SKIP is the registration-time answer: named drivers are never
# registered in the child, so identification cannot reach them. Two variants,
# because the two callers want different driver sets.
#
# Measured on GDAL 3.10.3 (the worker image) and 3.13.0:
#   - GDAL_SKIP tokenises on spaces AND commas, so a driver whose short name
#     contains a space cannot be named here at all (`GDAL_SKIP="ESRI Shapefile"`
#     answers "Unable to find driver ESRI to unload"). That is why `Interlis 1`
#     and `Interlis 2` are absent: the input-driver allowlist in
#     `processing/ingest/gdal_drivers.py` is what excludes them, and it is the
#     primary layer for local uploads for exactly this kind of reason.
#   - An unknown name in GDAL_SKIP warns and is otherwise ignored, so a typo
#     here silently weakens the clamp. `tests/test_gdal_driver_clamp.py` pins
#     every name against the driver list the image actually ships.
_NETWORK_AND_POINTER_DRIVERS: tuple[str, ...] = (
    # Follows a pointer out of the document it was handed.
    "OGR_VRT",
    "GMLAS",
    "NAS",
    # Reaches the network from a name or a document.
    "WFS",
    "OAPIF",
    "OGCAPI",
    "HTTP",
    "CSW",
    "EEDA",
    "PLSCENES",
    "NGW",
    "Elasticsearch",
    "Carto",
    "AmigoCloud",
    # Spawns a helper program of its own.
    "GPSBabel",
)

# The service importers exist to read a remote WFS or OGC API - Features
# endpoint, so those two drivers are the point of the call and stay. Every
# other entry is still refused: a service response has no business selecting
# the VRT driver or shelling out to GPSBabel.
_SERVICE_KEPT_DRIVERS = frozenset({"WFS", "OAPIF"})


def _gdal_skip_env(drivers: tuple[str, ...]) -> dict[str, str]:
    """os.environ overlaid with a GDAL_SKIP clamp for ``drivers``."""
    return {**os.environ, "GDAL_SKIP": " ".join(drivers)}


def gdal_vector_safe_env() -> dict[str, str]:
    """Subprocess env for a vector GDAL CLI reading a LOCAL staged file.

    Refuses every driver in ``_NETWORK_AND_POINTER_DRIVERS``. Pair it with
    ``local_input_driver_args`` from ``processing/ingest/gdal_drivers.py``:
    the allowlist decides what MAY open the file, this decides what may never,
    and the two are independent so a gap in either is not a way through.

    Deliberately does NOT carry the raster ``_VRT_SAFE_ENV`` clamps.
    ``CPL_VSIL_CURL_ALLOWED_EXTENSIONS`` gates the ``/vsicurl`` handler, which
    the OGR service drivers do not go through, and ``VRT_VIRTUAL_OVERVIEWS``
    is a raster-pyramid option. Carrying them here would read as protection on
    the paths that have none.
    """
    return _gdal_skip_env(_NETWORK_AND_POINTER_DRIVERS)


def gdal_service_safe_env() -> dict[str, str]:
    """Subprocess env for a vector GDAL CLI reading a REMOTE service.

    Same clamp minus the two drivers the service importers exist to use. The
    URL itself is gated by ``validate_url_for_ssrf`` at submission time; this
    only bounds which drivers the response can reach.
    """
    return _gdal_skip_env(
        tuple(d for d in _NETWORK_AND_POINTER_DRIVERS if d not in _SERVICE_KEPT_DRIVERS)
    )
