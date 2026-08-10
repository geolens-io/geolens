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
    correct value. The local-upload path can tell the two apart
    (``raster/cog.py`` reads ``transform.b``/``transform.d`` to set
    ``is_rotated``); nothing here can. A wrong number that LOOKS like a
    measurement is worse than the blank "—" it would replace, so it stays
    unset until there is a source that can rule rotation out. Tracked as
    #1375.

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
    (with min/max per band for rescaling), or None on failure.

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
    app.modules.catalog.sources.security.validate_url_for_ssrf(url) before
    passing the URL here. The import-flow call at line 454 satisfies this;
    any new caller MUST add the same pre-validation.

    Gate 2 (Titiler-side): docker-compose's Titiler service sets
    CPL_VSIL_CURL_ALLOWED_EXTENSIONS=.tif,.tiff,.cog,.vrt -- even if a
    malicious URL slips past Gate 1, Titiler's own GDAL VSI clamp rejects
    non-raster file extensions.

    Removing Gate 1 OR loosening Gate 2 must be a deliberate audit-tracked
    decision, not a refactor side-effect.
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

            return {
                "band_count": band_count,
                "dtype": dtype,
                "width": info.get("width"),
                "height": info.get("height"),
                "nodata": info.get("nodata"),
                "band_info": band_info or None,
                **_georeferencing(info),
            }
    except Exception as exc:  # broad: Titiler info call — httpx/JSON parse can throw varied errors; degrade to None
        logger.debug("Failed to fetch COG info from Titiler", url=url, error=str(exc))
        return None
