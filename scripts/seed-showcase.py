#!/usr/bin/env python3
"""Seed GeoLens with the marketing "showcase" maps.

Builds three capability-showcase maps from public, openly-licensed data:

  1. Manhattan Skyline   - 3D fill-extrusion by real building height + graduated color
                           (NYC Open Data Building Footprints, Socrata 5zhs-2jue)
  2. New York Income     - data-driven quantile choropleth
                           (USDA ERS Atlas of Rural & Small-Town America)
  3. The Matterhorn      - 3D terrain mesh + hillshade from a VRT mosaic of COG tiles
                           (swisstopo swissALTI3D 2m lidar, OGD)   [--with-terrain]

Everything here is reproducible against a fresh stack. The flows and the
non-obvious gotchas they encode were verified live against the running API.

Requires: pip install httpx

GOTCHAS this script encodes (learned the hard way):
  * A plain GeoJSON URL is NOT a "service" - the service connector (probe/preview)
    only accepts WFS / ArcGIS Feature Service / OGC API Features. For Socrata or
    ArcGIS-query GeoJSON, DOWNLOAD the file then use the /ingest/upload path.
  * Socrata serialises numbers as STRINGS ("53.84"); coerce numeric columns to real
    numbers before upload or GDAL ingests them as text (breaks graduated styling).
  * NYC height_roof is in FEET -> heightScale = 0.3048 or the skyline triples.
  * GeoLens LOWERCASES column names on ingest. Reference the lowercased name in
    every paint/style expression (Median_HH_Inc_ACS -> median_hh_inc_acs).
  * A job's terminal status is "complete" (not "completed").
  * Map camera is set via PUT /maps/{id}; bearing must be within [-180, 180].
  * A VRT mosaic does NOT inherit is_dem from its source tiles - PATCH the VRT
    dataset {"is_dem": true} or map terrain silently refuses to engage.
"""

import argparse
import io
import json
import os
import sys
import time

try:
    import httpx
except ImportError:
    print("Missing required package. Install with:\n  pip install httpx", file=sys.stderr)
    sys.exit(1)

DEFAULT_BASE_URL = "http://localhost:8080"

# --- public data sources -----------------------------------------------------

NYC_BUILDINGS = (
    "https://data.cityofnewyork.us/resource/5zhs-2jue.geojson"
    "?$where=height_roof>0 AND within_box(the_geom,40.770,-74.020,40.700,-73.965)"
    "&$limit=50000"
)
USDA_INCOME = (
    "https://gisportal.ers.usda.gov/server/rest/services/Rural_Atlas_Data/Income/"
    "MapServer/0/query?where=State%3D%27NY%27"
    "&outFields=County,State,Median_HH_Inc_ACS,PerCapitaInc"
    "&returnGeometry=true&outSR=4326&f=geojson"
)
SWISSALTI_STAC = (
    "https://data.geo.admin.ch/api/stac/v1/collections/"
    "ch.swisstopo.swissalti3d/items?bbox=7.645,45.968,7.675,45.987&limit=30"
)


# --- API helpers -------------------------------------------------------------


class Api:
    def __init__(self, base_url: str, token: str):
        self.base = base_url.rstrip("/")
        self.client = httpx.Client(timeout=180.0, follow_redirects=True)
        self.h = {"Authorization": f"Bearer {token}"}

    @classmethod
    def login(cls, base_url: str, username: str, password: str) -> "Api":
        # NOTE: login is form-encoded, not JSON.
        r = httpx.post(
            f"{base_url.rstrip('/')}/api/auth/login",
            data={"username": username, "password": password},
            timeout=60.0,
        )
        r.raise_for_status()
        return cls(base_url, r.json()["access_token"])

    def upload_geojson(self, name: str, data: bytes) -> str:
        files = {"file": (name, io.BytesIO(data), "application/geo+json")}
        r = self.client.post(f"{self.base}/api/ingest/upload", headers=self.h, files=files)
        r.raise_for_status()
        return r.json()["job_id"]

    def preview(self, job_id: str) -> dict:
        r = self.client.post(f"{self.base}/api/ingest/preview/{job_id}", headers=self.h)
        r.raise_for_status()
        return r.json()

    def commit(self, job_id: str, title: str, summary: str, srid: int = 4326) -> None:
        r = self.client.post(
            f"{self.base}/api/ingest/commit/{job_id}",
            headers=self.h,
            json={"title": title, "summary": summary, "visibility": "public",
                  "srid_override": srid},
        )
        r.raise_for_status()

    def poll(self, job_id: str, timeout: int = 240) -> dict:
        start = time.monotonic()
        while True:
            r = self.client.get(f"{self.base}/api/jobs/{job_id}", headers=self.h)
            r.raise_for_status()
            j = r.json()
            if j.get("status") in ("complete", "failed"):  # terminal status is "complete"
                if j["status"] == "failed":
                    raise RuntimeError(f"job {job_id} failed: {j.get('error_message')}")
                return j
            if time.monotonic() - start > timeout:
                raise TimeoutError(f"job {job_id} did not finish in {timeout}s")
            time.sleep(2)

    def ingest_geojson(self, name: str, data: bytes, title: str, summary: str) -> str:
        job = self.upload_geojson(name, data)
        self.preview(job)
        self.commit(job, title, summary)
        return self.poll(job)["dataset_id"]

    def create_map(self, name: str, description: str) -> str:
        r = self.client.post(f"{self.base}/api/maps", headers=self.h,
                             json={"name": name, "description": description})
        r.raise_for_status()
        return r.json()["id"]

    def set_view(self, map_id: str, **fields) -> None:
        # PUT (not PATCH); bearing must be within [-180, 180].
        r = self.client.put(f"{self.base}/api/maps/{map_id}", headers=self.h, json=fields)
        r.raise_for_status()

    def add_layer(self, map_id: str, body: dict) -> dict:
        r = self.client.post(f"{self.base}/api/maps/{map_id}/layers", headers=self.h, json=body)
        r.raise_for_status()
        return r.json()

    def patch_dataset(self, dataset_id: str, **fields) -> None:
        r = self.client.patch(f"{self.base}/api/datasets/{dataset_id}", headers=self.h, json=fields)
        r.raise_for_status()

    def manifest_apply(self, manifest: dict) -> list:
        r = self.client.post(f"{self.base}/api/ingest/manifest/apply", headers=self.h, json=manifest)
        r.raise_for_status()
        return r.json().get("results", [])

    def vrt_create(self, source_ids: list, title: str, summary: str) -> str:
        r = self.client.post(
            f"{self.base}/api/ingest/vrt/create", headers=self.h,
            json={"source_dataset_ids": source_ids, "vrt_type": "mosaic",
                  "resolution_strategy": "finest", "title": title, "summary": summary,
                  "visibility": "public"},
        )
        r.raise_for_status()
        return r.json()["job_id"]


def fetch(url: str) -> bytes:
    r = httpx.get(url, follow_redirects=True, timeout=120.0)
    r.raise_for_status()
    return r.content


def step_expr(column: str, breaks: list, colors: list) -> list:
    """A MapLibre `step` expression (N colors, N-1 breaks) over a numeric column."""
    expr = ["step", ["to-number", ["get", column], 0], colors[0]]
    for b, c in zip(breaks, colors[1:]):
        expr += [b, c]
    return expr


# --- showcase builders -------------------------------------------------------


def build_manhattan(api: Api) -> str:
    print("\n[1/3] Manhattan Skyline (3D extrusion)")
    print("  downloading NYC building footprints...")
    fc = json.loads(fetch(NYC_BUILDINGS))
    # Coerce Socrata string-numbers to real floats and trim noise properties.
    keep_f = ["height_roof", "ground_elevation", "shape_area"]
    for feat in fc["features"]:
        p = feat["properties"]
        np = {"name": p.get("name"), "feature_code": p.get("feature_code"),
              "bin": p.get("bin"), "construction_year": p.get("construction_year")}
        for k in keep_f:
            v = p.get(k)
            try:
                np[k] = float(v) if v not in (None, "") else None
            except (TypeError, ValueError):
                np[k] = None
        feat["properties"] = np
    data = json.dumps(fc).encode()
    print(f"  ingesting {len(fc['features'])} buildings...")
    ds = api.ingest_geojson("manhattan_skyline.geojson", data,
                            "Manhattan Building Heights",
                            "NYC building footprints (Lower + Midtown Manhattan) with roof "
                            "heights in feet. Source: NYC Open Data (5zhs-2jue).")
    map_id = api.create_map(
        "Manhattan Skyline - Real Roof Heights",
        "Every NYC building footprint in Lower + Midtown Manhattan, extruded to its true "
        "surveyed roof height and color-graded by height. Source: NYC Open Data.")
    # column is lowercased on ingest: height_roof (already lowercase here)
    plasma = ["interpolate", ["linear"], ["to-number", ["get", "height_roof"], 0],
              0, "#0d0887", 60, "#5601a4", 120, "#900da3", 250, "#cb4679",
              450, "#ed7953", 750, "#fdb42f", 1200, "#f0f921"]
    api.add_layer(map_id, {
        "dataset_id": ds, "sort_order": 0, "opacity": 1.0,
        "display_name": "Buildings (3D by roof height)",
        "paint": {"fill-color": plasma, "fill-opacity": 0.9},
        "style_config": {
            "mode": "graduated", "column": "height_roof", "ramp": "Plasma",
            "target": "color", "method": "quantile",
            # breaks/colors mirror the interpolate stops above EXACTLY so the
            # discrete legend matches the smooth fill (incl. the 750-1200 band
            # and the #fdb42f stop the legend previously dropped).
            "breaks": [60, 120, 250, 450, 750, 1200],
            "colors": ["#0d0887", "#5601a4", "#900da3", "#cb4679", "#ed7953", "#fdb42f", "#f0f921"],
            "colorLabel": "Roof height (ft)",
            "builder": {
                "height_column": "height_roof",
                "height_scale": 0.3048,          # feet -> meters
                "extrusion_min_zoom": 13,
                "extrusion_opacity": 0.92,
                "stroke_disabled": True,
            },
        },
    })
    api.set_view(map_id, center_lng=-73.978, center_lat=40.753, zoom=15.0,
                 pitch=62, bearing=-28, basemap_style="openfreemap-dark",
                 show_basemap_labels=False)
    print(f"  -> map {map_id}")
    return map_id


def build_income(api: Api) -> str:
    print("\n[2/3] New York Income (data-driven choropleth)")
    print("  downloading USDA ERS county income...")
    data = fetch(USDA_INCOME)
    ds = api.ingest_geojson("ny_income.geojson", data,
                            "New York Median Household Income by County",
                            "Median household income (2017-21 ACS) for all 62 NY counties. "
                            "Source: USDA ERS Atlas of Rural & Small-Town America.")
    map_id = api.create_map(
        "New York Income by County",
        "Median household income across all 62 New York counties (2017-21 ACS).")
    # Quantile (sextile) breaks computed from the data give equal-count classes
    # = maximum contrast. Column is LOWERCASED on ingest.
    col = "median_hh_inc_acs"
    vals = sorted(f["properties"]["Median_HH_Inc_ACS"] for f in json.loads(data)["features"]
                  if f["properties"].get("Median_HH_Inc_ACS") is not None)
    n = len(vals)
    breaks = [vals[max(0, round(n * k / 6) - 1)] for k in range(1, 6)]
    colors = ["#440154", "#414487", "#2a788e", "#22a884", "#7ad151", "#fde725"]  # viridis 6
    api.add_layer(map_id, {
        "dataset_id": ds, "sort_order": 0, "opacity": 0.9,
        "display_name": "Median household income",
        # fill-opacity 1.0 so the 0.9 layer opacity is the single opacity knob;
        # 0.9 * 0.9 would otherwise compound to 0.81 and desync from the outline.
        "paint": {"fill-color": step_expr(col, breaks, colors), "fill-opacity": 1.0,
                  "_outline-color": "#0b0f14", "_outline-width": 0.5},
        "style_config": {
            "mode": "graduated", "column": col, "ramp": "Viridis", "target": "color",
            "method": "quantile", "breaks": breaks, "colors": colors,
            "colorLabel": "Median household income ($)",
            "builder": {"outline_color": "#0b0f14", "outline_width": 0.5},
        },
    })
    api.set_view(map_id, center_lng=-75.4, center_lat=42.6, zoom=6.2,
                 pitch=0, bearing=0, basemap_style="openfreemap-positron",
                 show_basemap_labels=True)
    print(f"  -> map {map_id}  (breaks={breaks})")
    return map_id


def build_matterhorn(api: Api) -> str:
    print("\n[3/3] The Matterhorn (3D terrain + hillshade via VRT mosaic)")
    print("  querying swissALTI3D STAC...")
    feats = json.loads(fetch(SWISSALTI_STAC))["features"]
    tiles = {}
    for f in feats:
        for a in f.get("assets", {}).values():
            href = a.get("href", "")
            if href.endswith(".tif") and "_2_2056_" in href and "swissalti3d_2024_" in href:
                tag = os.path.basename(href).split("_")[2]  # e.g. 2617-1091
                e, nn = tag.split("-")
                if e in ("2616", "2617", "2618") and nn in ("1090", "1091", "1092"):
                    tiles[tag] = href
    if not tiles:
        raise RuntimeError("no swissALTI3D tiles matched the summit AOI")
    print(f"  registering {len(tiles)} COG tiles via manifest (downloads each)...")
    manifest = {
        "manifest_version": "1",
        "catalog": {"title": "Swiss Alps Terrain (Matterhorn)"},
        "datasets": [{
            "key": f"swissalti3d-{tag}", "title": f"swissALTI3D 2m {tag} (Matterhorn)",
            "sources": [{"type": "raster_cog", "uri": uri, "format": "geotiff"}],
            "metadata": {"crs": "EPSG:2056", "organization": "swisstopo",
                         "license": "swisstopo OGD", "tags": ["dem", "swissalti3d", "matterhorn"]},
            "publication": {"intent": "ready"},
        } for tag, uri in sorted(tiles.items())],
        "dry_run": False,
    }
    results = api.manifest_apply(manifest)
    tile_ids = [api.poll(r["job_id"])["dataset_id"] for r in results if r.get("job_id")]
    print(f"  mosaicking {len(tile_ids)} tiles into a VRT...")
    vrt_job = api.vrt_create(tile_ids, "swissALTI3D Matterhorn DEM (2m mosaic)",
                             "VRT mosaic of swissALTI3D 2m tiles around the Matterhorn. swisstopo OGD.")
    vrt_ds = api.poll(vrt_job)["dataset_id"]
    # A VRT does NOT inherit is_dem from its sources - set it or terrain won't engage.
    api.patch_dataset(vrt_ds, is_dem=True)
    map_id = api.create_map(
        "The Matterhorn - swissALTI3D 3D Terrain",
        "A razor-sharp 3D terrain mesh of the Matterhorn from swisstopo swissALTI3D 2m lidar, "
        "mosaicked from COG tiles via VRT. swisstopo OGD.")
    api.add_layer(map_id, {
        "dataset_id": vrt_ds, "sort_order": 0, "opacity": 1.0,
        "display_name": "swissALTI3D relief", "layer_type": "raster_geolens",
        "style_config": {"render_mode": "hillshade", "builder": {}},
        # illumination-anchor "map" keeps the NW (315 deg) lighting geographically
        # fixed instead of rotating with the camera on the bearing -150 / pitch 66 view.
        "paint": {"hillshade-illumination-direction": 315, "hillshade-illumination-anchor": "map",
                  "hillshade-exaggeration": 0.75,
                  "hillshade-shadow-color": "#16203a", "hillshade-highlight-color": "#ffffff",
                  "hillshade-accent-color": "#3a4a63"},
    })
    api.set_view(map_id, terrain_config={"enabled": True, "source_dataset_id": vrt_ds,
                                         "exaggeration": 1.6},
                 center_lng=7.6605, center_lat=45.9725, zoom=14.0, pitch=66, bearing=-150,
                 basemap_style="openfreemap-positron", show_basemap_labels=False)
    print(f"  -> map {map_id}")
    return map_id


def main() -> int:
    ap = argparse.ArgumentParser(description="Seed GeoLens marketing showcase maps.")
    ap.add_argument("--base-url", default=os.environ.get("GEOLENS_URL", DEFAULT_BASE_URL))
    ap.add_argument("--username", default=os.environ.get("GEOLENS_ADMIN_USERNAME", "admin"))
    ap.add_argument("--password", default=os.environ.get("GEOLENS_ADMIN_PASSWORD", "admin"))
    ap.add_argument("--with-terrain", action="store_true",
                    help="also build the Matterhorn terrain hero (downloads ~9 COG tiles)")
    ap.add_argument("--only", choices=["manhattan", "income", "matterhorn"],
                    help="build only one showcase map")
    args = ap.parse_args()

    print(f"Logging in to {args.base_url} as {args.username}...")
    api = Api.login(args.base_url, args.username, args.password)

    built = {}
    try:
        if args.only:
            fn = {"manhattan": build_manhattan, "income": build_income,
                  "matterhorn": build_matterhorn}[args.only]
            built[args.only] = fn(api)
        else:
            built["manhattan"] = build_manhattan(api)
            built["income"] = build_income(api)
            if args.with_terrain:
                built["matterhorn"] = build_matterhorn(api)
    except (httpx.HTTPStatusError, RuntimeError, TimeoutError) as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        if isinstance(e, httpx.HTTPStatusError):
            print(e.response.text[:500], file=sys.stderr)
        return 1

    print("\nDone. Showcase maps:")
    for name, mid in built.items():
        print(f"  {name:10s} {args.base_url}/maps/{mid}")
    if not args.with_terrain and not args.only:
        print("\n(Run with --with-terrain to also build the Matterhorn 3D terrain hero.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
