"""Structural metadata for a remote COG, read through Titiler.

feat(#1266): lifted out of ``stac_router`` so a second caller can reach it.
The STAC refresh strategy adopts an asset href the publisher has MOVED, and a
moved object is not the same object: a re-tiled scene can change its band
count, its dtype, its nodata, and the statistics every rescale is computed
from. Carrying the old object's description onto the new one renders the new
raster through the old one's parameters — a single-band COG requested as RGB,
for instance.

The refresh path could not import the function where it was: it lived in an
API-edge module, and importing one of those executes route registration as a
side effect. Same reason ``platform/`` reaches ingest helpers through a port
rather than through a router.
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

    fix(#1334): retrievable all along and simply never read out of this
    response. Titiler answers ``crs`` as an OGC CRS URI
    (``http://www.opengis.net/def/crs/EPSG/0/<code>``) — verified against a
    live 2.2.1 instance. GDAL's CRS parser accepts that URI form directly, so
    the WKT round-trips through the same ``rasterio.crs.CRS`` every other
    ingest path already writes ``crs_wkt`` from (``raster/cog.py``).

    fix(#1376): the version is explicit because ``crs_wkt`` is published as
    the STAC Projection Extension's ``proj:wkt2`` and rasterio's default
    export is WKT1_GDAL. ``raster/cog.py`` asks for the same version, and
    migration ``0041`` converted the rows written before either did, so the
    column carries one dialect no matter which path or era produced a row.

    fix(#1334 review): both keys come off the SAME parsed ``CRS`` object, on
    purpose. The caller's other source for a raster's EPSG is the STAC
    item's own ``proj:code``/``proj:epsg`` — the PUBLISHER's claim about the
    file, read at import or refresh time from whatever document it happened
    to be describing itself with then. This function's ``crs`` came from
    Titiler actually opening the CURRENT bytes at the CURRENT href, which is
    ground truth about what is actually being served. A stale or wrong item
    declaration would otherwise have this probe write a WKT describing one
    projection beside a caller-supplied EPSG naming another, and
    ``RasterAsset.to_stac_properties()`` would publish both as ``proj:wkt2``
    and ``proj:code`` — a raster describing itself two contradictory ways in
    GeoLens's OWN STAC export. Deriving ``epsg`` from the same object the WKT
    came from makes the two agree by construction; the caller uses it in
    preference to the item's declared value and falls back to that only when
    the probe yields no EPSG (an unusual custom CRS, or no probe at all).

    fix(#1334 review): ``res_x``/``res_y`` are deliberately NOT derived here.
    The obvious computation — ``bounds`` (also in the dataset's own
    projection) divided by pixel dimensions — is only the true per-pixel
    resolution for an axis-aligned raster. This response carries no affine
    transform to check that against, so a rotated or sheared remote COG would
    silently get a resolution inflated by however far its bounding envelope
    exceeds its own footprint — indistinguishable, in this payload, from a
    correct value. fix(#1375): they now come from ``_geotransform`` and a
    SECOND Titiler endpoint that does carry the transform, which is why this
    one still refuses to guess at them.

    Individual failures degrade to None rather than raising: this is
    descriptive metadata for a UI card, not something a failed probe should
    abort over.
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

    fix(#1375): ``/cog/info`` carries no affine transform, which is why
    ``_georeferencing`` refuses to derive a resolution from its bounding
    envelope. ``/cog/stac`` does carry one — rio-stac writes the projection
    extension's ``proj:transform`` as the 9-element affine — and it is the
    SAME six numbers ``raster/cog.py`` reads off ``rasterio``'s
    ``src.transform`` on the local-upload path. So this is not an
    approximation of what a local ingest would have stored: both paths hand
    those numbers to the same ``pixel_size_from_affine``, and elements 1 and 3
    are the ``transform.b``/``transform.d`` both test to set ``is_rotated``. A
    rotated remote COG is now recorded as rotated rather than defaulting to
    the column's ``false``.

    fix(#1375 review): the resolution is the pixel VECTORS' lengths, not
    elements 0 and 4 on their own — see ``pixel_size_from_affine`` for why
    those two understate a rotated raster by 13% at 30°. The review caught it
    here; the local path had the same shape and was corrected with it, so the
    two agree on the right number rather than on the wrong one.

    Endpoint choice, since two of them expose georeferencing: ``/cog/validate``
    (rio-cogeo) reports ``GEO.Resolution`` and it is the same
    ``(transform.a, transform.e)`` pair, but it publishes no ``b``/``d``, so
    it cannot answer the rotation question this function exists to settle.
    Verified against titiler 2.2.1 / rio-tiler 9.4.2 / rio-stac, the pinned
    image: a 30°-rotated COG returns
    ``[8.66, -5.0, ..., 5.0, -8.66, ...]`` where the axis-aligned twin
    returns ``[10.0, 0.0, ..., 0.0, -10.0, ...]``, while ``/cog/info``'s
    ``bounds`` for that same rotated file describe a 3497 m envelope around a
    2560 m footprint (the 37% overstatement #1334 declined to publish).

    Returns an EMPTY dict, not one full of Nones, when the transform is
    missing or malformed: absent keys leave the row's columns untouched,
    where a None would assert "measured, and there is no value".
    """
    props = item.get("properties") or {}
    transform = props.get("proj:transform")
    # 9 elements in practice (the affine's bottom row is included); the first
    # six are the only ones with content, and >= 6 accepts either spelling.
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

    fix(#1334 review, round 3): "the probe returned no EPSG" is not the same
    question as "the probe returned no CRS at all", and the two callers'
    first attempt at this answered the wrong one — falling back to
    ``declared`` whenever ``probe["epsg"]`` was None, which also fires for a
    custom or exotic CRS that Titiler opened successfully but that PROJ
    cannot map to an authority code. That case answers ``crs_wkt`` with
    something real and ``epsg`` with None; falling back to a DECLARED code
    there would pair the probed WKT with a code that may name a different
    projection — reproducing on this row the exact contradiction this
    reconciliation exists to prevent, just with a null-vs-populated EPSG
    instead of two populated ones.

    The declared value is trustworthy only when the probe established
    NOTHING about the CRS — no ``crs_wkt`` at all, from a failed probe or an
    unparseable ``crs`` string. Whatever the probe DID establish, including
    "a WKT with no mappable EPSG", is what a caller must keep rather than
    patch over with an unrelated source.
    """
    if probe.get("crs_wkt") is not None:
        return probe.get("epsg")
    return declared


async def fetch_cog_info(url: str) -> dict | None:
    """Fetch COG metadata + statistics from Titiler for a remote asset URL.

    Returns dict with band_count, dtype, width, height, crs_wkt, band_info
    (with min/max per band for rescaling), res_x/res_y/is_rotated, or None on
    failure. The georeferencing keys are absent rather than None when their
    endpoint could not be read — see ``_georeferencing`` and ``_geotransform``.

    fix(#1271 review): None deliberately collapses every failure shape.
    A non-200 from Titiler is NOT proof the origin was attempted — the
    extension allowlist (CPL_VSIL_CURL_ALLOWED_EXTENSIONS) rejects some
    assets before any upstream fetch, and telling that apart from a relayed
    upstream error means parsing Titiler's opaque 500 bodies, which is the
    connector-completeness contract this feature refuses everywhere else.
    So the import stamps last_checked_at only on success (info in hand IS
    proof), and every failure leaves the field NULL for the probe to
    settle: under-stamping a real contact is recoverable, fabricating one
    for a never-contacted origin is not.

    SEC-OBSV-02 (sec-audit 2026-05-21): SSRF protection here is a DUAL GATE.
    Both gates MUST be preserved when adding new callers -- bypassing either
    is an SSRF regression:

    Gate 1 (caller-side): EVERY caller of _fetch_cog_info MUST first call
    app.platform.security.validate_url_for_ssrf(url) before
    passing the URL here. The import-flow call at line 454 satisfies this;
    any new caller MUST add the same pre-validation.

    Gate 2 (Titiler-side): docker-compose's Titiler service sets
    CPL_VSIL_CURL_ALLOWED_EXTENSIONS=.tif,.tiff,.cog,.vrt -- even if a
    malicious URL slips past Gate 1, Titiler's own GDAL VSI clamp rejects
    non-raster file extensions.

    Removing Gate 1 OR loosening Gate 2 must be a deliberate audit-tracked
    decision, not a refactor side-effect. fix(#1375) added a third request to
    the same internal Titiler service for the same already-validated ``url``,
    inside both gates and adding no origin this function did not already
    reach; a caller that reached a new origin would need its own Gate 1.
    """
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0)
        ) as client:
            # Fetch structural info
            info_resp = await client.get(
                build_titiler_cog_url("info", query={"url": url})
            )
            if info_resp.status_code != 200:
                return None
            info = info_resp.json()

            band_count = info.get("count", 1)
            dtype = info.get("dtype")

            # Fetch statistics for rescaling
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
            except Exception:  # broad: per-band stats optional — Titiler payload shape varies; defaults are fine
                pass  # stats are optional — rendering will fall back to defaults

            # fix(#1375): the affine transform, from the one COG endpoint
            # that publishes it. `with_raster`/`with_eo` are OFF because
            # their defaults make this a PIXEL read — rio-stac downsamples
            # to `max_size` to compute per-band statistics, which this call
            # has no use for and which fetch_cog_info already has its own
            # /cog/statistics request for. Measured against the pinned 2.2.1
            # image on a 2048x2048 3-band COG: 7 ms with them off, 90 ms
            # with them on.
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
            except Exception:  # broad: same contract as the stats call above — a resolution GeoLens could not measure is a blank display, not a failed probe
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
    except Exception as exc:  # broad: Titiler info call — httpx/JSON parse can throw varied errors; degrade to None
        logger.debug(
            "Failed to fetch COG info from Titiler",
            url=url,
            error=redact_exception_text(exc),
        )
        return None
