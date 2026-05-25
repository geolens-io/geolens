#!/usr/bin/env python3
"""Download vector datasets for the Adirondack High Peaks marketing maps.

Pulls authoritative public vectors from ArcGIS REST services and writes WGS84
GeoJSON. Most layers are clipped server-side by AOI envelope. The complete
46er peaks layer is generated from APA's GNIS-derived Summits FeatureServer
using the canonical 46er list, so the map can show the broader High Peaks
context rather than only the 12 peaks inside the first 260524-o57 AOI.

Datasets:
  1. APA Adirondack Park Boundary (the "Blue Line") — APA_Administrator's
     canonical polygon, services2.arcgis.com/8krRUWgifzA4cgL3/...
  2. NYSDEC Hiking Trails (layer 1 of item ab5d56644a404b41bac8d72f32017e4e
     on data.gis.ny.gov) — the trails LineString feature class.
  3. APA Adirondack Park Land Classification (state-land Wilderness / Wild
     Forest / Primitive / Canoe categories).
  4. USGS NHD Flowline Large Scale — streams/rivers/canals.
  5. USGS NHD Waterbody Large Scale — lakes/ponds/reservoirs.
  6. Complete ADK 46er peaks — generated from APA Summits layers 0, 1, and 2.

All three are downloaded as full datasets then clipped to AOI by ogr2ogr in
the COG-builder docker container (no host GDAL needed). Clipped output is
written next to the raw download as `*_aoi.geojson`.

Idempotent: skips downloads when target file already exists.
"""

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

try:
    import httpx
except ImportError:
    print("Missing httpx. Install with: pip install httpx", file=sys.stderr)
    sys.exit(1)

AOI = {"xmin": -74.05, "ymin": 44.08, "xmax": -73.85, "ymax": 44.32}
NHD_SERVICE = "https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer"
APA_SUMMITS_SERVICE = "https://services2.arcgis.com/8krRUWgifzA4cgL3/arcgis/rest/services/Summits/FeatureServer"

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
    {
        "key": "nhd_flowlines",
        "title": "USGS NHD Flowline — Large Scale",
        "feature_server": NHD_SERVICE,
        "layer_id": 6,
        "filename": "nhd_flowlines.geojson",
        "owner": "USGS TNM National Hydrography Dataset",
        "aoi_filter": True,
    },
    {
        "key": "nhd_waterbodies",
        "title": "USGS NHD Waterbody — Large Scale",
        "feature_server": NHD_SERVICE,
        "layer_id": 12,
        "filename": "nhd_waterbodies.geojson",
        "owner": "USGS TNM National Hydrography Dataset",
        "aoi_filter": True,
    },
]

OFFICIAL_46ERS = [
    {"rank": 1, "name": "Mt. Marcy", "elev_ft": 5344, "aliases": ["Mount Marcy", "Mt. Marcy"]},
    {"rank": 2, "name": "Algonquin Peak", "elev_ft": 5114, "aliases": ["Algonquin Peak"]},
    {"rank": 3, "name": "Mt. Haystack", "elev_ft": 4960, "aliases": ["Mount Haystack", "Haystack Mountain"]},
    {"rank": 4, "name": "Mt. Skylight", "elev_ft": 4926, "aliases": ["Mount Skylight", "Skylight"]},
    {"rank": 5, "name": "Whiteface Mountain", "elev_ft": 4867, "aliases": ["Whiteface Mountain"]},
    {"rank": 6, "name": "Dix Mountain", "elev_ft": 4857, "aliases": ["Dix Mountain", "Dix"]},
    {"rank": 7, "name": "Gray Peak", "elev_ft": 4840, "aliases": ["Gray Peak"]},
    {"rank": 8, "name": "Iroquois Peak", "elev_ft": 4840, "aliases": ["Iroquois Peak"]},
    {"rank": 9, "name": "Basin Mountain", "elev_ft": 4827, "aliases": ["Basin Mountain"]},
    {"rank": 10, "name": "Gothics", "elev_ft": 4736, "aliases": ["Gothics"]},
    {"rank": 11, "name": "Mt. Colden", "elev_ft": 4714, "aliases": ["Mount Colden", "Mt. Colden"]},
    {"rank": 12, "name": "Giant Mountain", "elev_ft": 4627, "aliases": ["Giant Mountain"]},
    {"rank": 13, "name": "Nippletop", "elev_ft": 4620, "aliases": ["Nippletop"]},
    {"rank": 14, "name": "Santanoni Peak", "elev_ft": 4607, "aliases": ["Santanoni Peak"]},
    {"rank": 15, "name": "Mt. Redfield", "elev_ft": 4606, "aliases": ["Mount Redfield", "Mt. Redfield"]},
    {"rank": 16, "name": "Wright Peak", "elev_ft": 4580, "aliases": ["Wright Peak"]},
    {"rank": 17, "name": "Saddleback Mountain", "elev_ft": 4515, "aliases": ["Saddleback Mountain"]},
    {"rank": 18, "name": "Panther Peak", "elev_ft": 4442, "aliases": ["Panther Peak"]},
    {"rank": 19, "name": "Tabletop Mountain", "elev_ft": 4413, "aliases": ["Tabletop Mountain", "Table Top Mountain"]},
    {"rank": 20, "name": "Rocky Peak Ridge", "elev_ft": 4400, "aliases": ["Rocky Peak Ridge"]},
    {"rank": 21, "name": "Macomb Mountain", "elev_ft": 4405, "aliases": ["Macomb Mountain"]},
    {"rank": 22, "name": "Armstrong Mountain", "elev_ft": 4400, "aliases": ["Armstrong Mountain"]},
    {"rank": 23, "name": "Hough Peak", "elev_ft": 4400, "aliases": ["Hough Peak"]},
    {"rank": 24, "name": "Seward Mountain", "elev_ft": 4361, "aliases": ["Seward Mountain"]},
    {"rank": 25, "name": "Mt. Marshall", "elev_ft": 4360, "aliases": ["Mount Marshall", "Mt. Marshall"]},
    {"rank": 26, "name": "Allen Mountain", "elev_ft": 4340, "aliases": ["Allen Mountain"]},
    {"rank": 27, "name": "Big Slide Mountain", "elev_ft": 4240, "aliases": ["Big Slide Mountain"]},
    {"rank": 28, "name": "Esther Mountain", "elev_ft": 4240, "aliases": ["Esther Mountain"]},
    {"rank": 29, "name": "Upper Wolfjaw Mountain", "elev_ft": 4185, "aliases": ["Upper Wolfjaw Mountain"]},
    {"rank": 30, "name": "Lower Wolfjaw Mountain", "elev_ft": 4175, "aliases": ["Lower Wolfjaw Mountain"]},
    {"rank": 31, "name": "Street Mountain", "elev_ft": 4166, "aliases": ["Street Mountain"]},
    {"rank": 32, "name": "Phelps Mountain", "elev_ft": 4161, "aliases": ["Phelps Mountain"]},
    {"rank": 33, "name": "Donaldson Mountain", "elev_ft": 4140, "aliases": ["Donaldson Mountain"]},
    {"rank": 34, "name": "Seymour Mountain", "elev_ft": 4120, "aliases": ["Seymour Mountain"]},
    {"rank": 35, "name": "Sawteeth", "elev_ft": 4100, "aliases": ["Sawteeth"]},
    {"rank": 36, "name": "Cascade Mountain", "elev_ft": 4098, "aliases": ["Cascade Mountain"]},
    {"rank": 37, "name": "South Dix", "elev_ft": 4060, "aliases": ["South Dix", "Carson Peak"]},
    {"rank": 38, "name": "Porter Mountain", "elev_ft": 4059, "aliases": ["Porter Mountain"]},
    {"rank": 39, "name": "Mount Colvin", "elev_ft": 4057, "aliases": ["Mount Colvin", "Colvin Mountain"]},
    {"rank": 40, "name": "Mount Emmons", "elev_ft": 4040, "aliases": ["Mount Emmons"]},
    {"rank": 41, "name": "Dial Mountain", "elev_ft": 4020, "aliases": ["Dial Mountain"]},
    {"rank": 42, "name": "Grace Peak", "elev_ft": 4012, "aliases": ["Grace Peak", "East Dix"]},
    {"rank": 43, "name": "Blake Peak", "elev_ft": 3960, "aliases": ["Blake Peak"]},
    {"rank": 44, "name": "Cliff Mountain", "elev_ft": 3960, "aliases": ["Cliff Mountain"]},
    {"rank": 45, "name": "Nye Mountain", "elev_ft": 3895, "aliases": ["Nye Mountain"]},
    {"rank": 46, "name": "Couchsachraga Peak", "elev_ft": 3820, "aliases": ["Couchsachraga Peak"]},
]


def _name_key(value: str) -> str:
    normalized = value.lower().replace("&", "and")
    normalized = re.sub(r"\b(mount|mt\.?|mountain|peak)\b", "", normalized)
    return re.sub(r"[^a-z0-9]+", "", normalized)


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


async def fetch_complete_46er_peaks(client: httpx.AsyncClient, output_dir: Path) -> dict:
    """Generate complete 46er peaks from APA Summits layers.

    APA's Summits service is GNIS-derived and public. Layers 0, 1, and 2 cover
    all official 46ers, including the historically listed peaks now surveyed
    below 4000 ft. We preserve the official 46er rank/elevation while carrying
    the source GNIS/APA attributes for traceability.
    """
    out_path = output_dir / "adk_46er_peaks.geojson"
    if out_path.exists() and out_path.stat().st_size > 0:
        with open(out_path) as f:
            data = json.load(f)
        return {
            "key": "adk_46er_peaks",
            "path": str(out_path),
            "features": len(data.get("features", [])),
            "skipped": True,
        }

    source_by_key: dict[str, dict] = {}
    for layer_id in (0, 1, 2):
        gj = await query_geojson(
            client,
            APA_SUMMITS_SERVICE,
            layer_id,
            AOI,
            use_aoi_filter=False,
        )
        for feature in gj.get("features", []):
            source_name = str(feature.get("properties", {}).get("FEATURE_NA") or "")
            if source_name:
                source_by_key.setdefault(_name_key(source_name), feature)

    features = []
    missing = []
    for peak in OFFICIAL_46ERS:
        source = None
        for alias in peak["aliases"]:
            source = source_by_key.get(_name_key(alias))
            if source:
                break
        if source is None:
            missing.append(peak["name"])
            continue
        props = dict(source.get("properties") or {})
        props.update(
            {
                "name": peak["name"],
                "elev_ft": peak["elev_ft"],
                "rank": peak["rank"],
                "is_official_46er": True,
                "source_name": props.get("FEATURE_NA"),
                "source_elev_ft": props.get("ELEV_IN_FT"),
            }
        )
        features.append(
            {
                "type": "Feature",
                "geometry": source.get("geometry"),
                "properties": props,
            }
        )

    if missing:
        raise RuntimeError(f"APA Summits source is missing official 46er peaks: {', '.join(missing)}")

    collection = {
        "type": "FeatureCollection",
        "name": "ADK 46er High Peaks (complete official list)",
        "metadata": {
            "description": "Complete official Adirondack 46er list generated from APA Summits FeatureServer layers 0, 1, and 2.",
            "source": APA_SUMMITS_SERVICE,
            "compiled": time.strftime("%Y-%m-%d"),
            "feature_count": len(features),
        },
        "features": features,
    }
    out_path.write_text(json.dumps(collection, indent=2))
    return {
        "key": "adk_46er_peaks",
        "path": str(out_path),
        "features": len(features),
        "skipped": False,
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
        results.append(await fetch_complete_46er_peaks(client, output_dir))

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
    p = argparse.ArgumentParser(description="Fetch ADK vectors from ArcGIS REST services")
    p.add_argument("--output-dir", default=".scratch/adk-data",
                   help="Output root dir (default: .scratch/adk-data)")
    return p.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    sys.exit(asyncio.run(amain(args)))
