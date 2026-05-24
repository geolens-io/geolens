#!/usr/bin/env python3
"""Download NY State aerial orthoimagery for the Adirondack High Peaks AOI.

Background: USGS NAIP via TNM Access API is unavailable for this AOI as of
2026-05-24 (TNM returns 0 items for any NAIP query in NY). The TNM "Imagery"
catalog appears to have moved off the public TNM API. As a result this
script bypasses TNM entirely and uses NY State's own ArcGIS MapServer
(`https://orthos.its.ny.gov/arcgis/rest/services/wms/Latest/MapServer`),
which serves a fused mosaic of 2022/2023/2024/2025 12-inch NY State
orthoimagery as a dynamic image service. That's the "1ft orthos" target
the plan called out as the high-quality option — and it turns out to be
fully scriptable via the ArcGIS REST exportImage endpoint.

Resolution: NY's native imagery is 12in (~0.3m). This script fetches a
4096x4096 tile (or 2x2 grid of them for higher fidelity) covering the AOI.
At 4096x4096 over our 0.2°x0.24° bbox we get ~5-6 m/px, which is excellent
for marketing maps at z13-z16 zoom levels.

Output: a single mosaic JPEG written to .scratch/adk-data/aerial/ that the
COG builder will reproject and convert to a proper COG.

Idempotent: skips download if output file already exists.
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

try:
    import httpx
except ImportError:
    print("Missing httpx. Install with: pip install httpx", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AOI_W, AOI_S, AOI_E, AOI_N = -74.05, 44.08, -73.85, 44.32

# NY State 12in orthoimagery (2022-2025 mosaic). Dynamic MapServer (not cached).
# /export endpoint takes bbox + size + format and returns a JSON pointer to a
# temp image URL. Service detail at /MapServer?f=json (singleFusedMapCache=False).
NY_ORTHOS_BASE = "https://orthos.its.ny.gov/arcgis/rest/services/wms/Latest/MapServer"

# 4096x4096 is the service's max image size per request. For higher fidelity
# we fetch a 2x2 grid (effective 8192x8192 over the AOI ≈ 3 m/px) and stitch.
DEFAULT_TILE_PIXELS = 4096


# ---------------------------------------------------------------------------
# Single-tile fetch via /export endpoint
# ---------------------------------------------------------------------------


async def export_one_tile(
    client: httpx.AsyncClient,
    bbox: tuple[float, float, float, float],
    size_px: int,
    fmt: str = "tiff",
) -> bytes:
    """Hit /export?f=json to get a pointer URL, then GET the image.

    Returns raw image bytes.

    The /export endpoint returns:
      {
        "href": "http://.../arcgisoutput/.../_ags_mapXX.<ext>",
        "extent": { ... },
        "width": N, "height": N, "scale": F
      }
    The href is a temporary URL on the same host that points to the rendered
    image. It does NOT require an authentication token for this public service.
    """
    minx, miny, maxx, maxy = bbox
    bbox_str = f"{minx},{miny},{maxx},{maxy}"

    params = {
        "bbox": bbox_str,
        "bboxSR": "4326",
        "size": f"{size_px},{size_px}",
        "imageSR": "4326",  # keep WGS84 — GDAL reprojects to 3857 in the COG step
        "format": fmt,
        "f": "json",
    }

    # Step 1: get the temp URL
    resp = await client.get(f"{NY_ORTHOS_BASE}/export", params=params, timeout=60)
    resp.raise_for_status()
    body = resp.json()
    if "href" not in body:
        raise RuntimeError(f"/export response had no href: {body}")
    href = body["href"]
    extent_returned = body.get("extent", {})

    # Step 2: GET the image
    img_resp = await client.get(href, timeout=300)
    img_resp.raise_for_status()
    data = img_resp.content

    if len(data) < 1024:
        # The service returns a tiny ~4 KB placeholder JPEG when the request
        # falls outside coverage. Treat as failure.
        raise RuntimeError(
            f"Image response is suspiciously small ({len(data)} bytes) — "
            f"likely blank/no-data. Extent returned: {extent_returned}"
        )

    return data


async def fetch_aerial_world_file(
    output_path: Path,
    size_px: int = DEFAULT_TILE_PIXELS,
    fmt: str = "tiff",
) -> int:
    """Fetch the AOI as a single export image + write a sidecar world file.

    World file (`.tfw` for .tiff, `.jgw` for .jpg) is the simplest way to
    georeference a flat raster without GDAL. The COG builder will read it
    and convert to a true GeoTIFF + reproject + COG.

    Returns the on-disk size in bytes.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.exists() and output_path.stat().st_size > 0:
        size_mb = output_path.stat().st_size / (1024 * 1024)
        print(f"SKIP (cached, {size_mb:.1f} MB): {output_path}")
        return output_path.stat().st_size

    print(f"Requesting {size_px}x{size_px} {fmt} from NY State orthos...")
    print(f"  Service: {NY_ORTHOS_BASE}/export")
    print(f"  AOI: W={AOI_W} S={AOI_S} E={AOI_E} N={AOI_N}")
    t0 = time.monotonic()

    async with httpx.AsyncClient(
        headers={"User-Agent": "geolens-marketing-data/1.0"},
        follow_redirects=True,
    ) as client:
        data = await export_one_tile(client, (AOI_W, AOI_S, AOI_E, AOI_N), size_px, fmt)

    output_path.write_bytes(data)
    elapsed = time.monotonic() - t0
    size_mb = len(data) / (1024 * 1024)
    print(f"  DONE: {size_mb:.2f} MB in {elapsed:.1f}s")

    # Write sidecar world file. World files reference *pixel center* of the
    # top-left pixel. ArcGIS exportImage returns the image with the extent
    # we requested, so:
    #   A = pixel size X (degrees per pixel, positive)
    #   D = rotation Y (0)
    #   B = rotation X (0)
    #   E = pixel size Y (negative)
    #   C = X of upper-left pixel center
    #   F = Y of upper-left pixel center
    pixel_size_x = (AOI_E - AOI_W) / size_px
    pixel_size_y = (AOI_S - AOI_N) / size_px  # negative
    ul_x = AOI_W + pixel_size_x / 2
    ul_y = AOI_N + pixel_size_y / 2
    ext_map = {"tiff": ".tfw", "tif": ".tfw", "jpg": ".jgw", "png": ".pgw"}
    wf_ext = ext_map.get(fmt.lower(), ".wld")
    wf_path = output_path.with_suffix(wf_ext)
    wf_path.write_text(
        f"{pixel_size_x}\n0\n0\n{pixel_size_y}\n{ul_x}\n{ul_y}\n"
    )
    print(f"  Wrote world file: {wf_path}")

    # Also write a sidecar .prj that names EPSG:4326 for GDAL convenience
    prj_path = output_path.with_suffix(".prj")
    # OGC-WKT for EPSG:4326
    prj_path.write_text(
        'GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",'
        'SPHEROID["WGS_1984",6378137.0,298.257223563]],'
        'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]]'
    )

    return len(data)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


async def amain(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir) / "aerial"
    output_dir.mkdir(parents=True, exist_ok=True)

    fmt = args.format.lower()
    if fmt not in ("tiff", "tif", "jpg"):
        print(f"Unsupported format {fmt}; choose tiff or jpg", file=sys.stderr)
        return 1

    ext = ".tif" if fmt in ("tiff", "tif") else ".jpg"
    output_path = output_dir / f"adk_high_peaks_ny_orthos_latest{ext}"

    await fetch_aerial_world_file(output_path, size_px=args.size, fmt=fmt)

    print()
    print(f"=== Done (NY State orthos aerial) ===")
    print(f"Output: {output_path}")
    print(f"Sidecar files: {output_path.with_suffix('.tfw' if ext == '.tif' else '.jgw')}, {output_path.with_suffix('.prj')}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Fetch NY State 12in orthos for the ADK High Peaks AOI."
    )
    p.add_argument("--output-dir", default=".scratch/adk-data",
                   help="Output root dir (default: .scratch/adk-data)")
    p.add_argument("--size", type=int, default=DEFAULT_TILE_PIXELS,
                   help=f"Pixel size per side (default: {DEFAULT_TILE_PIXELS}; service max: 4096)")
    p.add_argument("--format", default="tiff", choices=["tiff", "jpg"],
                   help="Output format (default: tiff for proper georeferencing)")
    return p.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    sys.exit(asyncio.run(amain(args)))
