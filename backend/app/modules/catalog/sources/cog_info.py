"""Structural metadata for a remote COG, read through Titiler.

Lives outside ``stac_router`` (importing an API-edge module registers routes
as a side effect) so the STAC refresh path can re-probe a moved asset href
rather than carry over stale band/dtype/nodata/statistics. Titiler reads the
asset through the API relay, never from its URL.
"""

from __future__ import annotations

import re
import uuid
from urllib.parse import urlsplit

import httpx
import structlog

from app.core.crs_uri import parse_crs_uri
from app.core.geo import crs_facts_of, pixel_size_from_affine
from app.core.url_redaction import redact_exception_text
from app.platform.http.remote_raster import RemoteRasterFormat, remote_raster_format
from app.platform.storage.raster_relay import relay_url
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


_UNIDENTIFIED_CRS_MESSAGE = (
    "GeoLens imports remote COGs whose CRS has an EPSG code or is OGC CRS84, "
    "and this item's asset has neither. Reproject the file to an EPSG CRS, "
    "for example with gdalwarp -t_srs EPSG:<code>, and import it again."
)
_NOT_GEOTIFF_MESSAGE = (
    "GeoLens reads remote rasters only as GeoTIFF or COG, and this item's "
    "asset is neither. Remote VRT files are not supported; import a COG of "
    "the data instead."
)


def import_refusal(probed: dict | None) -> str | None:
    """Why a probed asset can't be imported, or None when it can."""
    if probed is None:
        return None
    if probed.get("not_geotiff"):
        return _NOT_GEOTIFF_MESSAGE
    if probed.get("crs_unidentified"):
        return _UNIDENTIFIED_CRS_MESSAGE
    return None


def _nodata_of(info: dict) -> float | None:
    """The scalar nodata value from a raw ``/cog/info`` reply, if it has one.

    Titiler has no "nodata" key: "Nodata" carries the value in
    nodata_value, while "Mask"/"Alpha"/"None" mean the asset has no scalar
    nodata to store.
    """
    return info.get("nodata_value") if info.get("nodata_type") == "Nodata" else None


async def fetch_cog_info(
    url: str, *, dataset_id: uuid.UUID | None = None
) -> dict | None:
    """Fetch COG metadata + statistics from Titiler for a remote asset URL.

    Returns dict with band_count, dtype, width, height, crs_wkt, band_info
    (min/max per band), res_x/res_y/is_rotated, or None on failure.
    Georeferencing keys are absent, not None, when their endpoint could not
    be read — see ``_georeferencing``/``_geotransform``. Returns
    ``{"not_geotiff": True}`` when Titiler could not read the asset because it
    is not a GeoTIFF, which the relay refuses to serve.

    None collapses every other failure shape: a non-200 from Titiler isn't
    proof the origin was contacted, so ``last_checked_at`` is stamped only on
    success and every failure leaves it NULL for the probe to settle.

    The caller validates ``url`` with ``validate_url_for_ssrf`` first; the
    relay then checks and pins every connection Titiler's read makes.
    """
    if urlsplit(url).path.lower().endswith(".vrt"):
        return {"not_geotiff": True}
    source = relay_url(url, dataset_id)
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0)
        ) as client:
            info_resp = await client.get(
                build_titiler_cog_url("info", query={"url": source})
            )
            if info_resp.status_code != 200:
                if await remote_raster_format(url) is RemoteRasterFormat.OTHER:
                    return {"not_geotiff": True}
                return None
            info = info_resp.json()

            band_count = info.get("count", 1)
            dtype = info.get("dtype")
            nodata = _nodata_of(info)

            band_info = []
            try:
                stats_resp = await client.get(
                    build_titiler_cog_url("statistics", query={"url": source})
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
                            "url": source,
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
                "nodata": nodata,
                "band_info": band_info or None,
                **_georeferencing(info),
                **geotransform,
            }
    except Exception as exc:  # broad: httpx/JSON errors vary, degrade to None
        logger.debug(
            "Failed to fetch COG info from Titiler",
            dataset_id=str(dataset_id) if dataset_id else None,
            error=redact_exception_text(exc),
        )
        return None


async def fetch_cog_nodata(
    url: str, *, dataset_id: uuid.UUID | None = None
) -> float | None:
    """The scalar nodata Titiler's ``/cog/info`` reports, or None.

    One header read, none of ``fetch_cog_info``'s statistics or transform
    calls. None covers both a failed read and an asset with no scalar
    nodata (Mask/Alpha, or none at all) — either way the caller leaves its
    stored value as it was. The caller validates the URL first, as for
    ``fetch_cog_info``.
    """
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0)
        ) as client:
            info_resp = await client.get(
                build_titiler_cog_url("info", query={"url": relay_url(url, dataset_id)})
            )
            if info_resp.status_code != 200:
                return None
            return _nodata_of(info_resp.json())
    except Exception as exc:  # broad: httpx/JSON errors vary, degrade to None
        logger.debug(
            "Failed to fetch COG nodata from Titiler",
            dataset_id=str(dataset_id) if dataset_id else None,
            error=redact_exception_text(exc),
        )
        return None
