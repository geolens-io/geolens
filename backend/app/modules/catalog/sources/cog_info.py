"""Structural metadata for a remote COG, read through Titiler.

feat(#1266): lifted out of ``stac_router`` (importing an API-edge module
registers routes as a side effect) so the STAC refresh path can re-probe a
moved asset href rather than carry over stale band/dtype/nodata/statistics.
"""

from __future__ import annotations

import re

import httpx
import structlog

from app.core.crs_uri import parse_crs_uri
from app.core.geo import crs_facts_of, pixel_size_from_affine
from app.core.url_redaction import redact_exception_text
from app.platform.storage.titiler_url import build_titiler_cog_url

logger = structlog.get_logger(__name__)

_BARE_EPSG = re.compile(r"^EPSG:(\d{1,9})$")

# OGC:CRS84 is WGS 84 with longitude first, which EPSG:4326 is not, so it has
# no EPSG code. Its WKT is built from our copy of the URI Titiler reports for
# it, never from Titiler's text. rio-tiler writes version 0 for an authority
# with no version, so that is the form Titiler reports. The others are every
# form parse_crs_uri would otherwise turn into 4326.
_CRS84_URI = "http://www.opengis.net/def/crs/OGC/0/CRS84"
_CRS84_REFERENCES = frozenset(
    {
        _CRS84_URI,
        "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
        "http://www.opengis.net/def/crs/OGC/1.3/CRS84/",
        "https://www.opengis.net/def/crs/OGC/1.3/CRS84",
        "https://www.opengis.net/def/crs/OGC/1.3/CRS84/",
        "urn:ogc:def:crs:OGC:1.3:CRS84",
    }
)


def _authority_epsg(value: str) -> int | None:
    """The code of an ``EPSG:<n>`` or OGC URI/URN CRS reference, else None."""
    if match := _BARE_EPSG.match(value):
        return int(match.group(1))
    return parse_crs_uri(value)


def _georeferencing(info: dict) -> dict:
    """``crs_wkt``/``epsg`` and the CRS facts from Titiler's raw ``/cog/info`` reply.

    Titiler reports an OGC CRS URI when PROJ matches the file's CRS to an
    authority code, and the file's own WKT otherwise. Only an EPSG or CRS84
    reference is read, and its WKT2_2019 text (STAC's ``proj:wkt2``) and facts
    come from the registry, so the API never parses CRS text a remote file
    supplied. Any other CRS sets ``crs_unidentified``: the asset has one,
    GeoLens can't say which, and callers refuse it rather than take the
    item's declared code.

    Titiler reads the asset's current bytes, so its CRS outranks the item's
    declared ``proj:code``; both keys come from the one reference, so the
    stored ``crs_wkt`` and ``epsg`` cannot disagree.
    ``res_x``/``res_y`` come from ``_geotransform``, since this reply carries
    no affine transform.
    """
    crs_value = info.get("crs")
    if not isinstance(crs_value, str) or not crs_value:
        return {"crs_wkt": None, "epsg": None}
    try:
        from rasterio.crs import CRS

        if crs_value in _CRS84_REFERENCES:
            crs, epsg = CRS.from_user_input(_CRS84_URI), None
        elif (epsg := _authority_epsg(crs_value)) is not None:
            crs = CRS.from_epsg(epsg)
        else:
            crs = None
        if crs is not None:
            crs_wkt = crs.to_wkt(version="WKT2_2019")
            return {"crs_wkt": crs_wkt, "epsg": epsg, **crs_facts_of(crs, crs_wkt)}
    except Exception:  # broad: a reference PROJ doesn't know is unidentified
        pass
    return {"crs_wkt": None, "epsg": None, "crs_unidentified": True}


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
    """The EPSG to store: the probe's, when it reported any CRS at all.

    "No EPSG" and "no CRS" are different answers. A CRS84 asset has no EPSG
    code, and one Titiler reported but GeoLens couldn't identify may be any
    projection, so neither may borrow ``declared``. That is trustworthy only
    when the probe reported no CRS.
    """
    if probe.get("crs_wkt") is not None or probe.get("crs_unidentified"):
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

    SEC-OBSV-02 (#1927): dual SSRF gate, both halves required. Gate 1
    (caller-side) is ``validate_url_for_ssrf`` before calling this; Gate 2
    (Titiler-side) is its own CPL_VSIL_CURL_ALLOWED_EXTENSIONS clamp.
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
                    band_keys = sorted(
                        (k for k in stats if k[:1] == "b" and k[1:].isdigit()),
                        key=lambda k: int(k[1:]),
                    )
                    for key in band_keys:
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
