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


async def fetch_cog_info(url: str) -> dict | None:
    """Fetch COG metadata + statistics from Titiler for a remote asset URL.

    Returns dict with band_count, dtype, width, height, band_info (with
    min/max per band for rescaling), or None on failure.

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
            }
    except Exception as exc:  # broad: Titiler info call — httpx/JSON parse can throw varied errors; degrade to None
        logger.debug("Failed to fetch COG info from Titiler", url=url, error=str(exc))
        return None
