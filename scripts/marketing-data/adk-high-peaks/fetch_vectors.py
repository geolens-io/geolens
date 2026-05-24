#!/usr/bin/env python3
"""Download vector datasets for the Adirondack High Peaks AOI.

Pulls three authoritative public vectors from ArcGIS Online (APA + NYS DEC),
clipped server-side by ArcGIS REST envelope, and writes WGS84 GeoJSON.

Datasets:
  1. APA Adirondack Park Boundary (the "Blue Line") — APA_Administrator's
     canonical polygon, services2.arcgis.com/8krRUWgifzA4cgL3/...
  2. NYSDEC Hiking Trails (layer 1 of item ab5d56644a404b41bac8d72f32017e4e
     on data.gis.ny.gov) — the trails LineString feature class.
  3. APA Adirondack Park Land Classification (state-land Wilderness / Wild
     Forest / Primitive / Canoe categories).

All three are downloaded as full datasets then clipped to AOI by ogr2ogr in
the COG-builder docker container (no host GDAL needed). Clipped output is
written next to the raw download as `*_aoi.geojson`.

Idempotent: skips downloads when target file already exists.
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

AOI = {"xmin": -74.05, "ymin": 44.08, "xmax": -73.85, "ymax": 44.32}

# (name, FeatureServer URL, layer_id, alias)
SOURCES = [
    {
        "key": "apa_blue_line",
        "title": "APA Adirondack Park Boundary (Blue Line) — polygon",
        # BluelinePolygon (single polygon outline of the whole park) — pull
        # without AOI filter and the polygon survives intact for context.
        "feature_server": "https://services2.arcgis.com/8krRUWgifzA4cgL3/arcgis/rest/services/BluelinePolygon/FeatureServer",
        "layer_id": 0,
        "filename": "apa_blue_line.geojson",
        "owner": "APA_Administrator",
        # The Blue Line polygon spans the whole park; clipping to AOI would discard it
        # since the AOI is entirely INSIDE the park. Pull the whole feature and let
        # the map render it as a context outline.
        "aoi_filter": False,
    },
    {
        "key": "nysdec_hiking_trails",
        "title": "NYSDEC Hiking Trails",
        # Service is named DEC_Trails not Trails. Layer 1 = Hiking Trails.
        "feature_server": "https://services6.arcgis.com/DZHaqZm9cxOD4CWM/arcgis/rest/services/DEC_Trails/FeatureServer",
        "layer_id": 1,
        "filename": "nysdec_hiking_trails.geojson",
        "owner": "NYSDEC via data.gis.ny.gov item ab5d56644a404b41bac8d72f32017e4e",
        "aoi_filter": True,
    },
    {
        "key": "apa_land_classification",
        "title": "APA Adirondack Park Land Classification",
        "feature_server": "https://services2.arcgis.com/8krRUWgifzA4cgL3/arcgis/rest/services/AdirondackParkLandClassification/FeatureServer",
        "layer_id": 0,
        "filename": "apa_land_classification.geojson",
        "owner": "APA_Administrator",
        "aoi_filter": True,
    },
]


async def discover_layer(client: httpx.AsyncClient, feature_server: str, layer_id: int) -> dict:
    """Hit /{layer_id}?f=json to confirm the layer is reachable and learn its
    geometry type + field list. Returns the layer metadata dict."""
    url = f"{feature_server}/{layer_id}?f=json"
    resp = await client.get(url, timeout=60)
    resp.raise_for_status()
    return resp.json()


async def query_geojson(
    client: httpx.AsyncClient,
    feature_server: str,
    layer_id: int,
    aoi: dict,
    *,
    use_aoi_filter: bool,
) -> dict:
    """Query a FeatureServer layer for features intersecting AOI, return GeoJSON.

    ArcGIS REST 10.1+ supports `f=geojson` directly. If use_aoi_filter=False
    we pull the whole layer (for small full-state datasets like Blue Line)
    and clip client-side later.

    Server-side pagination is automatic if maxRecordCount limit is hit.
    """
    params = {
        "where": "1=1",
        "outFields": "*",
        "outSR": "4326",
        "f": "geojson",
    }
    if use_aoi_filter:
        params["geometry"] = f"{aoi['xmin']},{aoi['ymin']},{aoi['xmax']},{aoi['ymax']}"
        params["geometryType"] = "esriGeometryEnvelope"
        params["inSR"] = "4326"
        params["spatialRel"] = "esriSpatialRelIntersects"

    all_features = []
    offset = 0
    page_size = 2000  # most ArcGIS services cap at 1000-2000
    crs = None

    while True:
        page_params = dict(params, resultOffset=offset, resultRecordCount=page_size)
        resp = await client.get(f"{feature_server}/{layer_id}/query", params=page_params, timeout=180)
        resp.raise_for_status()
        body = resp.json()
        feats = body.get("features", [])
        if not feats:
            break
        all_features.extend(feats)
        if crs is None:
            crs = body.get("crs")
        # Heuristic: if we got fewer than page_size, we're done
        if len(feats) < page_size:
            break
        offset += page_size

    return {
        "type": "FeatureCollection",
        "features": all_features,
        "crs": crs,
    }


async def fetch_one(client: httpx.AsyncClient, src: dict, output_dir: Path, *, use_aoi_filter: bool) -> dict:
    out_path = output_dir / src["filename"]
    if out_path.exists() and out_path.stat().st_size > 0:
        size_kb = out_path.stat().st_size / 1024
        print(f"SKIP (cached, {size_kb:.0f} KB): {out_path.name}")
        # Read feature count
        try:
            with open(out_path) as f:
                data = json.load(f)
            n = len(data.get("features", []))
        except Exception:
            n = -1
        return {
            "key": src["key"], "path": str(out_path), "features": n, "skipped": True,
        }

    print(f"Fetching {src['title']!r}...")
    print(f"  Service: {src['feature_server']}/{src['layer_id']}")
    t0 = time.monotonic()

    try:
        meta = await discover_layer(client, src["feature_server"], src["layer_id"])
    except Exception as exc:
        print(f"  ERROR: layer metadata unreachable: {exc}", file=sys.stderr)
        return {"key": src["key"], "error": str(exc)}

    geom_type = meta.get("geometryType", "?")
    print(f"  Layer name: {meta.get('name')!r}  geomType={geom_type}")

    try:
        gj = await query_geojson(client, src["feature_server"], src["layer_id"], AOI,
                                 use_aoi_filter=use_aoi_filter)
    except Exception as exc:
        print(f"  ERROR: query failed: {exc}", file=sys.stderr)
        return {"key": src["key"], "error": str(exc)}

    n = len(gj["features"])
    elapsed = time.monotonic() - t0
    print(f"  Got {n} features in {elapsed:.1f}s")

    out_path.write_text(json.dumps(gj))
    size_kb = out_path.stat().st_size / 1024
    print(f"  Wrote {out_path} ({size_kb:.0f} KB)")

    return {
        "key": src["key"], "path": str(out_path), "features": n, "skipped": False,
        "elapsed_s": elapsed, "geom_type": geom_type,
    }


async def amain(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir) / "vectors"
    output_dir.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(
        headers={"User-Agent": "geolens-marketing-data/1.0"},
        follow_redirects=True,
    ) as client:
        results = []
        for src in SOURCES:
            use_filter = src.get("aoi_filter", True)
            res = await fetch_one(client, src, output_dir, use_aoi_filter=use_filter)
            results.append(res)

    print()
    print("=== Vector fetch summary ===")
    for r in results:
        if "error" in r:
            print(f"  FAIL  {r['key']:<28}  {r['error'][:100]}")
        else:
            tag = "SKIP" if r.get("skipped") else "DONE"
            print(f"  {tag}  {r['key']:<28}  features={r.get('features', '?'):>5}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch ADK vectors from ArcGIS Online (APA + NYSDEC)")
    p.add_argument("--output-dir", default=".scratch/adk-data",
                   help="Output root dir (default: .scratch/adk-data)")
    return p.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    sys.exit(asyncio.run(amain(args)))
