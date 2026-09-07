"""GDAL driver-registration and schema clamps for every vector subprocess.

In ``platform/`` because ``modules/catalog/sources/preview.py`` calls these
and ``modules/catalog/`` may not import ``app.processing.*``
(``test_layering.py``). The raster VSI clamps stay in
``processing/raster/vrt.py``, which re-exports both of these; the Rule 2 gate
credits either import path (#1857 item 3).
"""

import os

# fix(#1846, GHSA-hrf5-v3cq-frx5): several OGR drivers treat their input
# bytes as instructions, not data — OGR_VRT follows <SrcDataSource> to any
# local path or URL, and WFS identifies on content alone regardless of file
# name, then fetches whatever <URL> says. A staged upload is a local path,
# so the path alone doesn't bound where the read lands. GDAL_SKIP unloads
# named drivers at registration so identification can never reach them.
#
# Measured on GDAL 3.10.3/3.13.0: GDAL_SKIP tokenises on spaces AND commas,
# so a driver whose short name contains a space (`Interlis 1`, `Interlis 2`)
# can't be named here at all — they're excluded instead by the input-driver
# allowlist in `processing/ingest/gdal_drivers.py`. An unknown name in
# GDAL_SKIP warns and is otherwise ignored, so a typo silently weakens the
# clamp; `tests/test_gdal_driver_clamp.py` pins every name against the
# image's real driver list.
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

# WFS/OAPIF are the point of the service importers, so they stay; every
# other driver is still refused — a service response has no business
# selecting VRT or shelling out to GPSBabel.
_SERVICE_KEPT_DRIVERS = frozenset({"WFS", "OAPIF"})


# fix(#1828): at YES the GML driver fetches every `xs:import` location of a
# schema, and the schema a GetFeature response points at, credential header
# attached. Both are NO by value here so an operator's env cannot flip them.
_SCHEMA_FETCH_CLAMP: dict[str, str] = {
    "GML_USE_SCHEMA_IMPORT": "NO",
    "GML_DOWNLOAD_SCHEMA": "NO",
}


def _gdal_skip_env(drivers: tuple[str, ...]) -> dict[str, str]:
    """os.environ overlaid with a GDAL_SKIP clamp for ``drivers`` and the
    schema-fetch clamps, all by value."""
    return {**os.environ, "GDAL_SKIP": " ".join(drivers), **_SCHEMA_FETCH_CLAMP}


def gdal_vector_safe_env() -> dict[str, str]:
    """Subprocess env for a vector GDAL CLI reading a LOCAL staged file.

    Refuses every driver in ``_NETWORK_AND_POINTER_DRIVERS``. Pair with
    ``local_input_driver_args`` from ``processing/ingest/gdal_drivers.py``:
    that allowlist decides what MAY open the file, this decides what never
    can, and the two are independent so a gap in either isn't a way through.

    Deliberately omits the raster ``_VRT_SAFE_ENV`` clamps: they gate the
    ``/vsicurl`` handler, which the OGR service drivers do not go through, so
    carrying them here would read as protection on paths that have none.
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
