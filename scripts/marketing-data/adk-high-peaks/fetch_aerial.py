#!/usr/bin/env python3
"""Download aerial orthoimagery for the Adirondack High Peaks AOI.

The pipeline is TNM-first: it queries the TNM Access API for NAIP GeoTIFF
products over the AOI and writes the exact response to
`.scratch/adk-data/aerial/tnm_naip_query.json`. If TNM publishes matching
NAIP, the script downloads those GeoTIFFs to `aerial/naip_tiles/` for the COG
builder to mosaic.

As of 2026-05-24, TNM returns 0 NAIP items for this NY AOI, so `--source auto`
falls back to NY State's public 12-inch orthos MapServer. The fallback now
fetches a tiled grid of 4096x4096 exports instead of the single soft 3.5 MB
render used in the original 260524-o57 pass.

Idempotent: skips download if output file already exists.
"""

import argparse
import asyncio
import json
import sys
import time
import urllib.parse
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
AOI_BBOX = f"{AOI_W},{AOI_S},{AOI_E},{AOI_N}"

TNM_API = "https://tnmaccess.nationalmap.gov/api/v1/products"
TNM_NAIP_DATASET = "USDA National Agriculture Imagery Program (NAIP)"
# NY State 12in orthoimagery (2022-2025 mosaic). Dynamic MapServer (not cached).
# /export endpoint takes bbox + size + format and returns a JSON pointer to a
# temp image URL. Service detail at /MapServer?f=json (singleFusedMapCache=False).
NY_ORTHOS_BASE = "https://orthos.its.ny.gov/arcgis/rest/services/wms/Latest/MapServer"

# 4096x4096 is the service's max image size per request. For higher fidelity
# we fetch a 2x2 grid (effective 8192x8192 over the AOI ≈ 3 m/px) and stitch.
DEFAULT_TILE_PIXELS = 4096


async def query_tnm_naip(client: httpx.AsyncClient, evidence_path: Path) -> list[dict]:
    """Query TNM for NAIP GeoTIFF products and persist exact evidence."""
    params = {
        "datasets": TNM_NAIP_DATASET,
        "bbox": AOI_BBOX,
        "prodFormats": "GeoTIFF",
        "max": 100,
        "outputFormat": "JSON",
    }
    resp = await client.get(TNM_API, params=params, timeout=60)
    resp.raise_for_status()
    body = resp.json()
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps({
        "queried_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "endpoint": TNM_API,
        "params": params,
        "url": f"{TNM_API}?{urllib.parse.urlencode(params)}",
        "response": body,
    }, indent=2))
    return body.get("items", [])


async def download_tnm_products(client: httpx.AsyncClient, items: list[dict], output_dir: Path) -> int:
    """Download TNM product GeoTIFFs to output_dir. Returns file count."""
    output_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for index, item in enumerate(items, 1):
        url = item.get("downloadURL")
        if not url:
            continue
        filename = url.rsplit("/", 1)[-1] or f"tnm_naip_{index}.tif"
        dest = output_dir / filename
        if dest.exists() and dest.stat().st_size > 0:
            print(f"  SKIP TNM NAIP (cached): {dest.name}")
            count += 1
            continue
        print(f"  Downloading TNM NAIP {index}/{len(items)}: {filename}")
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        async with client.stream("GET", url, timeout=httpx.Timeout(connect=30.0, write=None, read=600.0, pool=30.0)) as resp:
            resp.raise_for_status()
            with open(tmp, "wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=1 << 20):
                    f.write(chunk)
        tmp.rename(dest)
        count += 1
    (output_dir / "tnm_naip_manifest.json").write_text(json.dumps(items, indent=2))
    return count


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


def tile_bbox(row: int, col: int, grid: int) -> tuple[float, float, float, float]:
    lon_step = (AOI_E - AOI_W) / grid
    lat_step = (AOI_N - AOI_S) / grid
    minx = AOI_W + col * lon_step
    maxx = minx + lon_step
    maxy = AOI_N - row * lat_step
    miny = maxy - lat_step
    return (minx, miny, maxx, maxy)


def write_world_files(output_path: Path, bbox: tuple[float, float, float, float], size_px: int, fmt: str) -> None:
    minx, miny, maxx, maxy = bbox
    pixel_size_x = (maxx - minx) / size_px
    pixel_size_y = (miny - maxy) / size_px
    ul_x = minx + pixel_size_x / 2
    ul_y = maxy + pixel_size_y / 2
    ext_map = {"tiff": ".tfw", "tif": ".tfw", "jpg": ".jgw", "png": ".pgw"}
    wf_path = output_path.with_suffix(ext_map.get(fmt.lower(), ".wld"))
    wf_path.write_text(f"{pixel_size_x}\n0\n0\n{pixel_size_y}\n{ul_x}\n{ul_y}\n")
    output_path.with_suffix(".prj").write_text(
        'GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",'
        'SPHEROID["WGS_1984",6378137.0,298.257223563]],'
        'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]]'
    )


async def fetch_ny_orthos_grid(output_dir: Path, *, grid: int, size_px: int, fmt: str, force: bool = False) -> int:
    """Fetch a grid of NY orthos tiles. Returns number of tile files present."""
    output_dir.mkdir(parents=True, exist_ok=True)
    ext = ".tif" if fmt in ("tiff", "tif") else ".jpg"
    manifest = {
        "source": NY_ORTHOS_BASE,
        "grid": grid,
        "tile_pixels": size_px,
        "aoi_bbox": [AOI_W, AOI_S, AOI_E, AOI_N],
        "tiles": [],
    }
    async with httpx.AsyncClient(
        headers={"User-Agent": "geolens-marketing-data/1.0"},
        follow_redirects=True,
    ) as client:
        for row in range(grid):
            for col in range(grid):
                bbox = tile_bbox(row, col, grid)
                tile_path = output_dir / f"adk_high_peaks_ny_orthos_r{row:02d}_c{col:02d}{ext}"
                manifest["tiles"].append({"row": row, "col": col, "bbox": bbox, "path": str(tile_path)})
                if tile_path.exists() and tile_path.stat().st_size > 0 and not force:
                    print(f"  SKIP NY orthos tile r{row} c{col}: {tile_path.name}")
                    continue
                print(f"  Fetching NY orthos tile r{row} c{col} bbox={bbox}")
                data = await export_one_tile(client, bbox, size_px, fmt)
                tile_path.write_bytes(data)
                write_world_files(tile_path, bbox, size_px, fmt)
                print(f"    wrote {tile_path.name} ({len(data) / (1024 * 1024):.2f} MB)")
    (output_dir / "ny_orthos_grid_manifest.json").write_text(json.dumps(manifest, indent=2))
    return len(list(output_dir.glob(f"*{ext}")))


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

    async with httpx.AsyncClient(
        headers={"User-Agent": "geolens-marketing-data/1.0"},
        follow_redirects=True,
    ) as client:
        if args.source in ("auto", "tnm-naip"):
            print("Querying TNM Access API for NAIP GeoTIFF products...")
            items = await query_tnm_naip(client, output_dir / "tnm_naip_query.json")
            print(f"  TNM NAIP items: {len(items)}")
            if items:
                count = await download_tnm_products(client, items, output_dir / "naip_tiles")
                print(f"=== Done (TNM NAIP) ===")
                print(f"Output tiles: {output_dir / 'naip_tiles'} ({count} files)")
                return 0
            if args.source == "tnm-naip":
                print("TNM returned no NAIP GeoTIFF products for this AOI. Evidence written to tnm_naip_query.json.", file=sys.stderr)
                return 1

    if args.source in ("auto", "ny-orthos"):
        grid_dir = output_dir / "ny_orthos_tiles"
        count = await fetch_ny_orthos_grid(
            grid_dir,
            grid=args.grid,
            size_px=args.size,
            fmt=fmt,
            force=args.force,
        )
        print()
        print(f"=== Done (NY State orthos tiled fallback) ===")
        print(f"Output tiles: {grid_dir} ({count} files)")
        print(f"TNM evidence: {output_dir / 'tnm_naip_query.json'}")
        return 0

    return 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Fetch TNM NAIP or NY State orthos for the ADK High Peaks AOI."
    )
    p.add_argument("--output-dir", default=".scratch/adk-data",
                   help="Output root dir (default: .scratch/adk-data)")
    p.add_argument("--source", choices=["auto", "tnm-naip", "ny-orthos"], default="auto",
                   help="Aerial source strategy (default: TNM NAIP first, NY orthos fallback)")
    p.add_argument("--grid", type=int, default=4,
                   help="NY orthos fallback grid dimension (default: 4 -> 16 tiles)")
    p.add_argument("--size", type=int, default=DEFAULT_TILE_PIXELS,
                   help=f"Pixel size per side (default: {DEFAULT_TILE_PIXELS}; service max: 4096)")
    p.add_argument("--format", default="tiff", choices=["tiff", "jpg"],
                   help="Output format (default: tiff for proper georeferencing)")
    p.add_argument("--force", action="store_true", help="Redownload existing NY orthos fallback tiles")
    return p.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    sys.exit(asyncio.run(amain(args)))
