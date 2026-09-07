"""Structural metadata for a remote COG, read through Titiler.

feat(#1266): lifted out of ``stac_router`` (importing an API-edge module
registers routes as a side effect) so the STAC refresh path can re-probe a
moved asset href rather than carry over stale band/dtype/nodata/statistics.
"""

from __future__ import annotations

import httpx
import structlog

from app.core.geo import pixel_size_from_affine
from app.core.url_redaction import redact_exception_text
from app.platform.storage.titiler_url import build_titiler_cog_url

logger = structlog.get_logger(__name__)


def _georeferencing(info: dict) -> dict:
    """``crs_wkt``/``epsg`` from Titiler's raw ``/cog/info`` reply.

    fix(#1334): Titiler's ``crs`` is an OGC CRS URI, which GDAL's parser
    accepts directly, round-tripping through the same ``rasterio.crs.CRS``
    other ingest paths use. fix(#1376): WKT2_2019 explicitly, matching
    STAC's ``proj:wkt2`` (rasterio defaults to WKT1_GDAL) and migration 0041.

    fix(#1334): both keys are derived from the SAME parsed CRS
    object on purpose. Titiler's probe reads the CURRENT bytes and is
    ground truth; the STAC item's ``proj:code``/``proj:epsg`` is only the
    publisher's claim. Deriving both from one object keeps the exported
    ``proj:wkt2``/``proj:code`` from ever contradicting each other.

    fix(#1334/#1375 review): ``res_x``/``res_y`` are NOT derived here —
    this payload carries no affine transform, so bounds/pixel-count would
    silently inflate resolution for a rotated/sheared raster. They come
    from ``_geotransform`` instead.

    Failures degrade to None rather than raising — descriptive UI metadata,
    not something a failed probe should abort over.
    """
    crs_wkt = None
    epsg = None
    crs_value = info.get("crs")
    if isinstance(crs_value, str) and crs_value:
        try:
            from rasterio.crs import CRS

            parsed = CRS.from_user_input(crs_value)
            crs_wkt = parsed.to_wkt(version="WKT2_2019")
            epsg = parsed.to_epsg()
        except (
            Exception
        ):  # broad: an unfamiliar CRS string should not fail the whole probe
            crs_wkt = None
            epsg = None

    return {"crs_wkt": crs_wkt, "epsg": epsg}


def _geotransform(item: dict) -> dict:
    """``res_x``/``res_y``/``is_rotated`` from a Titiler-generated STAC item.

    fix(#1375): ``/cog/stac``'s ``proj:transform`` (rio-stac's 9-element
    affine) is the same six numbers ``raster/cog.py`` reads off
    ``rasterio``'s ``src.transform`` locally, fed to the same
    ``pixel_size_from_affine``. Elements 1/3 (``transform.b``/``.d``) set
    ``is_rotated``.

    fix(#1375): resolution is the pixel VECTORS' lengths, not
    elements 0/4 alone — those understate a rotated raster by 13% at 30°
    (see ``pixel_size_from_affine``); the local path had the same bug and
    was fixed alongside this one.

    ``/cog/validate`` was rejected as the endpoint: it reports the same
    ``(transform.a, transform.e)`` pair but no ``b``/``d``, so it can't
    answer the rotation question. Verified against the pinned titiler
    2.2.1/rio-tiler 9.4.2 image: ``/cog/info``'s ``bounds`` for a
    30°-rotated COG overstate its footprint by 37% (#1334 declined to
    publish that number).

    Returns an EMPTY dict, not Nones, when the transform is missing or
    malformed — absent keys leave the row untouched; a None would assert
    "measured, no value".
    """
    props = item.get("properties") or {}
    transform = props.get("proj:transform")
    # 9 elements in practice (bottom row included); only the first six carry
    # content, so >= 6 accepts either spelling.
    if not isinstance(transform, (list, tuple)) or len(transform) < 6:
        return {}
    try:
        scale_x, shear_x, _, shear_y, scale_y, _ = (float(v) for v in transform[:6])
    except (TypeError, ValueError):
        return {}
    res_x, res_y = pixel_size_from_affine(scale_x, shear_x, shear_y, scale_y)
    return {
        "res_x": res_x,
        "res_y": res_y,
        "is_rotated": shear_x != 0.0 or shear_y != 0.0,
    }


def reconcile_epsg(probe: dict, declared: int | None) -> int | None:
    """The EPSG to store: the probe's, when it established any CRS at all.

    fix(#1334): "no EPSG" and "no CRS at all" are different
    questions — falling back to ``declared`` on a bare ``epsg is None``
    also fires for an exotic CRS PROJ can't map to an authority code, and
    would pair the probed (real) WKT with a declared code that may name a
    different projection. ``declared`` is trustworthy only when the probe
    established NOTHING (no ``crs_wkt`` at all); anything else the probe
    established must be kept, not patched over.
    """
    if probe.get("crs_wkt") is not None:
        return probe.get("epsg")
    return declared


async def fetch_cog_info(url: str) -> dict | None:
    """Fetch COG metadata + statistics from Titiler for a remote asset URL.

    Returns dict with band_count, dtype, width, height, crs_wkt, band_info
    (min/max per band), res_x/res_y/is_rotated, or None on failure.
    Georeferencing keys are absent, not None, when their endpoint could not
    be read — see ``_georeferencing``/``_geotransform``.

    fix(#1271): None collapses every failure shape deliberately — a
    non-200 from Titiler isn't proof the origin was contacted (the
    CPL_VSIL_CURL_ALLOWED_EXTENSIONS allowlist rejects some assets before
    any upstream fetch), so ``last_checked_at`` is stamped only on success;
    every failure leaves it NULL for the probe to settle.

    SEC-OBSV-02: dual SSRF gate, both halves required for every caller.
    Gate 1 (caller-side): ``validate_url_for_ssrf`` before calling this.
    Gate 2 (Titiler-side): its own CPL_VSIL_CURL_ALLOWED_EXTENSIONS clamp
    rejects a non-raster extension that slipped past Gate 1. Removing
    either is an SSRF regression, not a refactor side-effect (#1927).
    """
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0)
        ) as client:
            info_resp = await client.get(
                build_titiler_cog_url("info", query={"url": url})
            )
            if info_resp.status_code != 200:
                return None
            info = info_resp.json()

            band_count = info.get("count", 1)
            dtype = info.get("dtype")

            band_info = []
            try:
                stats_resp = await client.get(
                    build_titiler_cog_url("statistics", query={"url": url})
                )
                if stats_resp.status_code == 200:
                    stats = stats_resp.json()
                    for key in sorted(k for k in stats if k.startswith("b")):
                        band_info.append(
                            {
                                "min": stats[key].get("min"),
                                "max": stats[key].get("max"),
                                "mean": stats[key].get("mean"),
                            }
                        )
            except Exception:  # broad: stats optional, Titiler payload shape varies
                pass

            # fix(#1375): with_raster/with_eo are OFF — their defaults make
            # this a PIXEL read (rio-stac downsamples to compute per-band
            # stats, which fetch_cog_info already gets from /cog/statistics).
            # Measured on the pinned 2.2.1 image, 2048x2048 3-band COG:
            # 7ms off vs 90ms on.
            geotransform: dict = {}
            try:
                stac_resp = await client.get(
                    build_titiler_cog_url(
                        "stac",
                        query={
                            "url": url,
                            "with_raster": "false",
                            "with_eo": "false",
                        },
                    )
                )
                if stac_resp.status_code == 200:
                    geotransform = _geotransform(stac_resp.json())
            except Exception:  # broad: unmeasured res is a blank display, not a fail
                pass

            return {
                "band_count": band_count,
                "dtype": dtype,
                "width": info.get("width"),
                "height": info.get("height"),
                "nodata": info.get("nodata"),
                "band_info": band_info or None,
                **_georeferencing(info),
                **geotransform,
            }
    except Exception as exc:  # broad: httpx/JSON errors vary, degrade to None
        logger.debug(
            "Failed to fetch COG info from Titiler",
            url=url,
            error=redact_exception_text(exc),
        )
        return None
