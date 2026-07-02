#!/usr/bin/env python3
"""Seed GeoLens with the marketing "showcase" maps.

Builds capability-showcase maps from public, openly-licensed data:

  1. Manhattan Skyline   - 3D fill-extrusion by real building height + graduated color
                           (NYC Open Data Building Footprints, Socrata 5zhs-2jue)
  2. New York Income     - data-driven quantile choropleth
                           (USDA ERS Atlas of Rural & Small-Town America)
  3. World Airports      - client-clustered points, categorical by airport class
                           (OurAirports, public domain)
  4. Recent Earthquakes  - graduated circles by magnitude + magnitude-weighted heatmap
                           (USGS M4.5+ feed)
  5. World Countries     - GDP quantile choropleth + graduated city dots; companion
                           places/admin-1 datasets for catalog breadth (Natural Earth)
  6. World Rivers        - line + casing, width by scalerank (Natural Earth 1:10m)
  7. The Matterhorn      - 3D terrain mesh + hillshade from a VRT mosaic of COG tiles
                           (swisstopo swissALTI3D 2m lidar, OGD)   [--with-terrain]
  8. Sentinel-2 NYC      - true-color COGs imported BY REFERENCE from a STAC API
                           (Element84 Earth Search)                [--with-sentinel2]
  9. Restless Earth      - composite story hero: magnitude-graded quakes + heatmap over
                           PB2002 tectonic plate boundaries (categorical by class), major
                           cities and GDP context; popups everywhere; Ask-AI-ready columns
                           (depth_km, tsunami, felt, sig, plate velocity). Reuses the
                           earthquakes/countries datasets, ingests plates + major cities.
 10. Discover the World  - a collection of the above + a private-dataset embed-token demo

Maintenance: --refresh-quakes re-downloads the USGS feed and swaps it into the two
earthquake datasets in place (map styles/IDs untouched), then exits. Run it on the
demo every week or two or "last 30 days" quietly goes stale.

Everything here is reproducible against a fresh stack. The flows and the
non-obvious gotchas they encode were verified live against the running API.

More gotchas the new builders encode:
  * render_mode is its own field (cluster/heatmap/symbol/...) and COEXISTS with
    style_config.mode (categorical/graduated). Cluster styling lives in
    style_config.builder as SNAKE_CASE keys (cluster_radius, cluster_color, ...).
  * Client clustering only engages for POINT datasets with <=5000 features (the
    features.geojson endpoint hard-caps at 5000); over it the viewer silently falls
    back to unclustered circles. Filter point datasets under the cap.
  * Graduated SIZE (circle-radius/line-width) uses style_config target='radius'/'width'
    with a parallel `sizes` array (not `colors`).
  * Sentinel-2 by-reference import is POST /api/services/stac/import (storage_backend
    remote, zero download) - NOT the manifest raster_cog path (that downloads). Query
    the Element84 STAC API directly with httpx; the backend /search proxy 502s (SSRF
    IP-pin). True color = raster_geolens + style_config {'builder':{}} + NO render_mode.
  * Embed tokens are per-MAP (snapshot of the map's layer datasets at mint time); add
    the layer BEFORE minting. A private dataset cannot get a public /m/ share URL, so
    the private-embed demo keeps the map private and uses the X-Embed-Token header.

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
  * Terrain only deforms where the DEM source has tiles. Outside the footprint
    MapLibre fills the mesh at the mapbox-encoding floor (-10000 m), so a small
    DEM looks like a floating slab. Keep draped vectors clipped to the DEM bbox
    and frame the camera inside it (both done for the Matterhorn below).
  * A line + a wider casing under it = TWO LAYERS on the SAME dataset. Map-sync
    dedupes the tile source per dataset (SF-04), so two layers off one dataset
    render as two MapLibre lines sharing one source - no need to ingest twice.
    Done for the Matterhorn route and World Rivers below.
  * The live viewer's layer stack draws LOWER sort_order ON TOP (the inverse of
    the backend style order), so the line you want on top gets the LOWER
    sort_order: route=1 over casing=2, with peaks=3 underneath.
"""

import argparse
import csv
import io
import json
import os
import sys
import time
from datetime import datetime, timezone

try:
    import httpx
except ImportError:
    print(
        "Missing required package. Install with:\n  pip install httpx", file=sys.stderr
    )
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
# swissALTI3D regional extent for the Matterhorn 3D-terrain showcase.
# A larger DEM footprint moves the MapLibre 3D-terrain "pedestal" — the vertical
# wall where the mesh drops to the -10000 m out-of-coverage void at the data edge
# — well off-screen, so the camera can pan/zoom around the massif freely instead
# of being pinned tight on the summit (the old ~3 km / 3x3-tile box). Tile count
# scales with area; each ~1 km tile is a separate download + ingest job:
#   8x8 km  -> ~62 tiles   (this default; ~2 STAC pages)
#   12x10 km -> ~109 tiles (more roam, longer seed)
#   19x17 km -> ~244 tiles
# The structural, dataset-agnostic fix is still a global base DEM (terrain
# pedestal plan); this just makes the flagship showcase roamable now.
SWISSALTI_BBOX = "7.61,45.94,7.72,46.01"
SWISSALTI_STAC = (
    "https://data.geo.admin.ch/api/stac/v1/collections/"
    f"ch.swisstopo.swissalti3d/items?bbox={SWISSALTI_BBOX}&limit=100"
)
# OurAirports (public domain) - 85k airports; filtered to <5000 for client clustering.
OURAIRPORTS_CSV = "https://davidmegginson.github.io/ourairports-data/airports.csv"
# USGS M4.5+ past 30 days (~500 significant quakes; public domain).
USGS_QUAKES = (
    "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_month.geojson"
)
# Natural Earth (public domain), pinned tag v5.1.2 for reproducibility.
NE_BASE = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/"
)
NE_COUNTRIES = NE_BASE + "ne_50m_admin_0_countries.geojson"
NE_PLACES = NE_BASE + "ne_50m_populated_places.geojson"
NE_RIVERS = NE_BASE + "ne_10m_rivers_lake_centerlines.geojson"
NE_ADMIN1 = NE_BASE + "ne_50m_admin_1_states_provinces.geojson"
# PB2002 plate-boundary steps (Peter Bird 2003, via Hugo Ahlenius/Nordpil; open data).
# The *steps* file (not boundaries) carries per-segment STEPCLASS + relative velocity.
PB2002_STEPS = (
    "https://raw.githubusercontent.com/fraxen/tectonicplates/master/GeoJSON/"
    "PB2002_steps.json"
)
# Element84 Earth Search STAC (sentinel-2-l2a true-color COGs, by reference).
SENTINEL_STAC = "https://earth-search.aws.element84.com/v1"
SENTINEL_BBOX = [-74.30, 40.55, -73.65, 41.00]  # NYC metro (W, S, E, N)


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
        r = self.client.post(
            f"{self.base}/api/ingest/upload", headers=self.h, files=files
        )
        r.raise_for_status()
        return r.json()["job_id"]

    def preview(self, job_id: str) -> dict:
        r = self.client.post(f"{self.base}/api/ingest/preview/{job_id}", headers=self.h)
        r.raise_for_status()
        return r.json()

    def commit(
        self,
        job_id: str,
        title: str,
        summary: str,
        srid: int = 4326,
        visibility: str = "public",
    ) -> None:
        r = self.client.post(
            f"{self.base}/api/ingest/commit/{job_id}",
            headers=self.h,
            json={
                "title": title,
                "summary": summary,
                "visibility": visibility,
                "srid_override": srid,
            },
        )
        r.raise_for_status()

    def poll(self, job_id: str, timeout: int = 240) -> dict:
        start = time.monotonic()
        while True:
            r = self.client.get(f"{self.base}/api/jobs/{job_id}", headers=self.h)
            r.raise_for_status()
            j = r.json()
            if j.get("status") in (
                "complete",
                "failed",
            ):  # terminal status is "complete"
                if j["status"] == "failed":
                    raise RuntimeError(f"job {job_id} failed: {j.get('error_message')}")
                return j
            if time.monotonic() - start > timeout:
                raise TimeoutError(f"job {job_id} did not finish in {timeout}s")
            time.sleep(2)

    def ingest_geojson(
        self,
        name: str,
        data: bytes,
        title: str,
        summary: str,
        visibility: str = "public",
    ) -> str:
        job = self.upload_geojson(name, data)
        self.preview(job)
        self.commit(job, title, summary, visibility=visibility)
        return self.poll(job)["dataset_id"]

    def reupload_geojson(self, dataset_id: str, name: str, data: bytes) -> None:
        """Swap a dataset's data in place (upload -> preview -> commit -> poll).

        NOTE: on instances with a max_datasets_per_user override (the demo),
        reupload is quota-gated like upload — raise the quota first.
        """
        files = {"file": (name, io.BytesIO(data), "application/geo+json")}
        r = self.client.post(
            f"{self.base}/api/datasets/{dataset_id}/reupload",
            headers=self.h,
            files=files,
        )
        r.raise_for_status()
        job = r.json()["job_id"]
        self.client.post(
            f"{self.base}/api/datasets/{dataset_id}/reupload/{job}/preview",
            headers=self.h,
        ).raise_for_status()
        self.client.post(
            f"{self.base}/api/datasets/{dataset_id}/reupload/{job}/commit",
            headers=self.h,
            json={},
        ).raise_for_status()
        self.poll(job)

    def create_map(self, name: str, description: str) -> str:
        r = self.client.post(
            f"{self.base}/api/maps",
            headers=self.h,
            json={"name": name, "description": description},
        )
        r.raise_for_status()
        return r.json()["id"]

    def list_maps(self) -> list[str]:
        """Return a list of map names from the catalog (up to 200)."""
        r = self.client.get(f"{self.base}/api/maps?limit=200", headers=self.h)
        r.raise_for_status()
        data = r.json()
        # Response shape: {"maps": [...], "total": N}
        return [item["name"] for item in data.get("maps", data.get("items", []))]

    def list_datasets(self) -> list[str]:
        """Return a list of dataset titles from the catalog (up to 200)."""
        r = self.client.get(f"{self.base}/api/datasets?limit=200", headers=self.h)
        r.raise_for_status()
        data = r.json()
        # Response shape: {"datasets": [...], "total": N}
        return [item["title"] for item in data.get("datasets", data.get("items", []))]

    def set_view(self, map_id: str, **fields) -> None:
        # PUT (not PATCH); bearing must be within [-180, 180].
        r = self.client.put(
            f"{self.base}/api/maps/{map_id}", headers=self.h, json=fields
        )
        r.raise_for_status()

    def add_layer(self, map_id: str, body: dict) -> dict:
        r = self.client.post(
            f"{self.base}/api/maps/{map_id}/layers", headers=self.h, json=body
        )
        r.raise_for_status()
        return r.json()

    def patch_dataset(self, dataset_id: str, **fields) -> None:
        r = self.client.patch(
            f"{self.base}/api/datasets/{dataset_id}", headers=self.h, json=fields
        )
        r.raise_for_status()

    def manifest_apply(self, manifest: dict) -> list:
        r = self.client.post(
            f"{self.base}/api/ingest/manifest/apply", headers=self.h, json=manifest
        )
        r.raise_for_status()
        return r.json().get("results", [])

    def vrt_create(self, source_ids: list, title: str, summary: str) -> str:
        r = self.client.post(
            f"{self.base}/api/ingest/vrt/create",
            headers=self.h,
            json={
                "source_dataset_ids": source_ids,
                "vrt_type": "mosaic",
                "resolution_strategy": "finest",
                "title": title,
                "summary": summary,
                "visibility": "public",
            },
        )
        r.raise_for_status()
        return r.json()["job_id"]

    def datasets_by_title(self) -> dict[str, str]:
        """Map dataset title -> id (list_datasets returns only titles)."""
        r = self.client.get(f"{self.base}/api/datasets?limit=200", headers=self.h)
        r.raise_for_status()
        d = r.json()
        return {x["title"]: x["id"] for x in d.get("datasets", d.get("items", []))}

    def collections_by_name(self) -> dict[str, str]:
        """Map collection name -> id (name is UNIQUE in the catalog model)."""
        # Trailing slash required (redirect_slashes=False).
        r = self.client.get(f"{self.base}/api/catalog/collections/", headers=self.h)
        r.raise_for_status()
        return {c["name"]: c["id"] for c in r.json().get("collections", [])}

    def create_collection(self, name: str, description: str) -> str:
        # Collections have NO visibility/title/summary - only name (unique) + description.
        r = self.client.post(
            f"{self.base}/api/catalog/collections/",
            headers=self.h,
            json={"name": name, "description": description},
        )
        r.raise_for_status()
        return r.json()["id"]

    def add_to_collection(self, collection_id: str, dataset_ids: list) -> int:
        # Trailing slash required; returns count of NEWLY added (idempotent).
        r = self.client.post(
            f"{self.base}/api/catalog/collections/{collection_id}/datasets/",
            headers=self.h,
            json={"dataset_ids": dataset_ids},
        )
        r.raise_for_status()
        return r.json()["added"]

    def mint_embed_token(self, map_id: str, name: str) -> dict:
        # Per-MAP token; community edition allows only default 30-day/no-origin.
        # raw_token is returned ONLY here. Map must have >=1 layer.
        r = self.client.post(
            f"{self.base}/api/maps/{map_id}/embed-tokens",
            headers=self.h,
            json={"name": name},
        )
        r.raise_for_status()
        return r.json()

    def stac_import(self, url: str, items: list, visibility: str = "public") -> list:
        """Register STAC items as raster datasets BY REFERENCE (no download)."""
        r = self.client.post(
            f"{self.base}/api/services/stac/import",
            headers=self.h,
            json={"url": url, "items": items, "visibility": visibility},
        )
        r.raise_for_status()
        return r.json().get("results", r.json())


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


def quake_feed() -> tuple[bytes, int]:
    """USGS M4.5+ 30-day feed, slimmed + enriched for styling, popups and Ask AI.

    Beyond mag/place, keeps the fields that make the dataset interrogable:
    depth_km (geometry Z; USGS depth is already km), time_utc (human-readable,
    lexicographically sortable in SQL), felt (DYFI report count), tsunami (0/1)
    and sig (USGS significance 0-1000).
    """
    fc = json.loads(fetch(USGS_QUAKES))
    for feat in fc["features"]:
        p = feat["properties"]
        try:
            mag = float(p["mag"]) if p.get("mag") is not None else None
        except (TypeError, ValueError):
            mag = None
        coords = (feat.get("geometry") or {}).get("coordinates") or []
        depth = (
            round(float(coords[2]), 1)
            if len(coords) > 2 and coords[2] is not None
            else None
        )
        ms = p.get("time")
        time_utc = (
            datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime(
                "%Y-%m-%d %H:%M UTC"
            )
            if isinstance(ms, (int, float))
            else None
        )
        feat["properties"] = {
            "mag": mag,
            "place": p.get("place"),
            "time_utc": time_utc,
            "depth_km": depth,
            "felt": p.get("felt"),
            "tsunami": p.get("tsunami"),
            "sig": p.get("sig"),
        }
    return json.dumps(fc).encode(), len(fc["features"])


OVERPASS_URL = "https://overpass-api.de/api/interpreter"


def fetch_osm_overlays(bbox: tuple) -> tuple:
    """Fetch OSM hiking/climbing routes + named peaks within `bbox` (W, S, E, N),
    CLIPPED to the bbox, as two GeoJSON FeatureCollections (routes, peaks).

    Why the clip matters: any vector draped on MapLibre terrain must stay inside
    the DEM footprint. Outside the footprint there are no DEM tiles, and MapLibre
    renders those areas at the mapbox-encoding floor (-10000 m), so a line leaving
    the footprint would plunge into that void. We keep only the in-bbox vertices.

    Best-effort: returns empty FeatureCollections (so the terrain map still builds)
    if Overpass is unreachable.
    """
    w, s, e, n = bbox
    empty = {"type": "FeatureCollection", "features": []}
    q = (
        "[out:json][timeout:60];"
        f'(way["highway"~"path|footway|track|steps"]({s},{w},{n},{e}););out geom;'
        f'node["natural"="peak"]({s},{w},{n},{e});out;'
    )
    try:
        # Overpass rejects requests without a User-Agent (HTTP 406).
        r = httpx.post(
            OVERPASS_URL,
            data={"data": q},
            timeout=120.0,
            headers={"User-Agent": "geolens-showcase-seeder/1.0"},
        )
        r.raise_for_status()
        elements = r.json().get("elements", [])
    except Exception as ex:  # noqa: BLE001 - overlays are best-effort decoration
        print(f"  ! OSM overlay fetch failed ({ex}); building terrain without trails")
        return dict(empty), dict(empty)

    def inside(lat, lng):
        return s <= lat <= n and w <= lng <= e

    def emit(run, tags, out):
        if len(run) >= 2:
            out.append(
                {
                    "type": "Feature",
                    "properties": {
                        "name": tags.get("name") or tags.get("ref") or "Alpine route",
                        "sac_scale": tags.get("sac_scale", ""),
                    },
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[p["lon"], p["lat"]] for p in run],
                    },
                }
            )

    routes = []
    for el in elements:
        if el.get("type") != "way":
            continue
        tags = el.get("tags", {})
        run = []
        for p in el.get("geometry") or []:
            if inside(p["lat"], p["lon"]):
                run.append(p)
            else:
                emit(run, tags, routes)
                run = []
        emit(run, tags, routes)

    peaks = []
    for el in elements:
        if el.get("type") != "node" or "lat" not in el:
            continue
        if not inside(el["lat"], el["lon"]):
            continue
        t = el.get("tags", {})
        nm = t.get("name")
        ele = t.get("ele", "")
        if not nm or nm == "peak":  # skip unnamed summits
            continue
        peaks.append(
            {
                "type": "Feature",
                "properties": {
                    "label": f"{nm} ({ele} m)" if ele else nm,
                    "name": nm,
                    "ele": ele,
                },
                "geometry": {"type": "Point", "coordinates": [el["lon"], el["lat"]]},
            }
        )

    return (
        {"type": "FeatureCollection", "features": routes},
        {"type": "FeatureCollection", "features": peaks},
    )


# --- idempotency helpers (DEMO-02, Phase 1226) --------------------------------


def _map_exists(api: Api, name: str) -> bool:
    """Return True if a map with the given name already exists in the catalog."""
    return name in api.list_maps()


def _dataset_exists(api: Api, title: str) -> bool:
    """Return True if a dataset with the given title already exists."""
    return title in api.list_datasets()


# --- showcase builders -------------------------------------------------------


def build_manhattan(api: Api, force: bool = False) -> str:
    if not force and _map_exists(api, "Manhattan Skyline - Real Roof Heights"):
        print("  [skip] Manhattan Skyline - Real Roof Heights already exists")
        return "(skipped)"
    print("\n[1/3] Manhattan Skyline (3D extrusion)")
    print("  downloading NYC building footprints...")
    fc = json.loads(fetch(NYC_BUILDINGS))
    # Coerce Socrata string-numbers to real floats and trim noise properties.
    keep_f = ["height_roof", "ground_elevation", "shape_area"]
    for feat in fc["features"]:
        p = feat["properties"]
        np = {
            "name": p.get("name"),
            "feature_code": p.get("feature_code"),
            "bin": p.get("bin"),
            "construction_year": p.get("construction_year"),
        }
        for k in keep_f:
            v = p.get(k)
            try:
                np[k] = float(v) if v not in (None, "") else None
            except (TypeError, ValueError):
                np[k] = None
        feat["properties"] = np
    data = json.dumps(fc).encode()
    print(f"  ingesting {len(fc['features'])} buildings...")
    ds = api.ingest_geojson(
        "manhattan_skyline.geojson",
        data,
        "Manhattan Building Heights",
        "NYC building footprints (Lower + Midtown Manhattan) with roof "
        "heights in feet. Source: NYC Open Data (5zhs-2jue).",
    )
    map_id = api.create_map(
        "Manhattan Skyline - Real Roof Heights",
        "Every NYC building footprint in Lower + Midtown Manhattan, extruded to its true "
        "surveyed roof height and color-graded by height. Source: NYC Open Data.",
    )
    # column is lowercased on ingest: height_roof (already lowercase here)
    plasma = [
        "interpolate",
        ["linear"],
        ["to-number", ["get", "height_roof"], 0],
        0,
        "#0d0887",
        60,
        "#5601a4",
        120,
        "#900da3",
        250,
        "#cb4679",
        450,
        "#ed7953",
        750,
        "#fdb42f",
        1200,
        "#f0f921",
    ]
    api.add_layer(
        map_id,
        {
            "dataset_id": ds,
            "sort_order": 0,
            "opacity": 1.0,
            "display_name": "Buildings (3D by roof height)",
            "paint": {"fill-color": plasma, "fill-opacity": 0.9},
            "style_config": {
                "mode": "graduated",
                "column": "height_roof",
                "ramp": "Plasma",
                "target": "color",
                "method": "quantile",
                # breaks/colors mirror the interpolate stops above EXACTLY so the
                # discrete legend matches the smooth fill (incl. the 750-1200 band
                # and the #fdb42f stop the legend previously dropped).
                "breaks": [60, 120, 250, 450, 750, 1200],
                "colors": [
                    "#0d0887",
                    "#5601a4",
                    "#900da3",
                    "#cb4679",
                    "#ed7953",
                    "#fdb42f",
                    "#f0f921",
                ],
                "colorLabel": "Roof height (ft)",
                "builder": {
                    "height_column": "height_roof",
                    "height_scale": 0.3048,  # feet -> meters
                    "extrusion_min_zoom": 13,
                    "extrusion_opacity": 0.92,
                    "stroke_disabled": True,
                },
            },
        },
    )
    # Publish in this final PUT (maps default to private) so the showcase URLs
    # open for anonymous viewers; all referenced datasets are committed public.
    api.set_view(
        map_id,
        visibility="public",
        center_lng=-73.978,
        center_lat=40.753,
        zoom=15.0,
        pitch=62,
        bearing=-28,
        basemap_style="openfreemap-dark",
        show_basemap_labels=False,
    )
    print(f"  -> map {map_id}")
    return map_id


def build_income(api: Api, force: bool = False) -> str:
    if not force and _map_exists(api, "New York Income by County"):
        print("  [skip] New York Income by County already exists")
        return "(skipped)"
    print("\n[2/3] New York Income (data-driven choropleth)")
    print("  downloading USDA ERS county income...")
    data = fetch(USDA_INCOME)
    ds = api.ingest_geojson(
        "ny_income.geojson",
        data,
        "New York Median Household Income by County",
        "Median household income (2017-21 ACS) for all 62 NY counties. "
        "Source: USDA ERS Atlas of Rural & Small-Town America.",
    )
    map_id = api.create_map(
        "New York Income by County",
        "Median household income across all 62 New York counties (2017-21 ACS).",
    )
    # Quantile (sextile) breaks computed from the data give equal-count classes
    # = maximum contrast. Column is LOWERCASED on ingest.
    col = "median_hh_inc_acs"
    vals = sorted(
        f["properties"]["Median_HH_Inc_ACS"]
        for f in json.loads(data)["features"]
        if f["properties"].get("Median_HH_Inc_ACS") is not None
    )
    n = len(vals)
    breaks = [vals[max(0, round(n * k / 6) - 1)] for k in range(1, 6)]
    colors = [
        "#440154",
        "#414487",
        "#2a788e",
        "#22a884",
        "#7ad151",
        "#fde725",
    ]  # viridis 6
    api.add_layer(
        map_id,
        {
            "dataset_id": ds,
            "sort_order": 0,
            "opacity": 0.9,
            "display_name": "Median household income",
            # fill-opacity 1.0 so the 0.9 layer opacity is the single opacity knob;
            # 0.9 * 0.9 would otherwise compound to 0.81 and desync from the outline.
            "paint": {
                "fill-color": step_expr(col, breaks, colors),
                "fill-opacity": 1.0,
                "_outline-color": "#0b0f14",
                "_outline-width": 0.5,
            },
            "style_config": {
                "mode": "graduated",
                "column": col,
                "ramp": "Viridis",
                "target": "color",
                "method": "quantile",
                "breaks": breaks,
                "colors": colors,
                "colorLabel": "Median household income ($)",
                "builder": {"outline_color": "#0b0f14", "outline_width": 0.5},
            },
        },
    )
    api.set_view(
        map_id,
        visibility="public",
        center_lng=-75.4,
        center_lat=42.6,
        zoom=6.2,
        pitch=0,
        bearing=0,
        basemap_style="openfreemap-positron",
        show_basemap_labels=True,
    )
    print(f"  -> map {map_id}  (breaks={breaks})")
    return map_id


def fetch_swissalti_tiles() -> dict:
    """Return {tag: href} for every swissALTI3D 2m (EPSG:2056, 2024) COG tile
    intersecting SWISSALTI_BBOX, following STAC pagination.

    The swisstopo STAC API caps a page at ~100 features, so a regional AOI spans
    several pages — follow rel="next" until exhausted. Each 1 km tile exposes
    both a 0.5 m and a 2 m asset; we keep the 2 m (`_2_2056_`) COG, keyed by its
    EEEE-NNNN tag (e.g. 2617-1091) so re-runs dedupe to one dataset per tile.
    """
    tiles: dict[str, str] = {}
    url = SWISSALTI_STAC
    while url:
        page = json.loads(fetch(url))
        for f in page.get("features", []):
            for a in f.get("assets", {}).values():
                href = a.get("href", "")
                if (
                    href.endswith(".tif")
                    and "_2_2056_" in href
                    and "swissalti3d_2024_" in href
                ):
                    tag = os.path.basename(href).split("_")[2]  # e.g. 2617-1091
                    tiles[tag] = href
        url = next(
            (l["href"] for l in page.get("links", []) if l.get("rel") == "next"),
            None,
        )
    return tiles


def build_matterhorn(api: Api, force: bool = False) -> str:
    if not force and _map_exists(api, "The Matterhorn"):
        print("  [skip] The Matterhorn already exists")
        return "(skipped)"
    print("\n[3/3] The Matterhorn (3D terrain + hillshade via regional VRT mosaic)")
    print("  querying swissALTI3D STAC (regional AOI)...")
    tiles = fetch_swissalti_tiles()
    if not tiles:
        raise RuntimeError("no swissALTI3D 2m tiles matched the regional AOI")
    print(f"  registering {len(tiles)} COG tiles via manifest (downloads each)...")
    manifest = {
        "manifest_version": "1",
        "catalog": {"title": "Swiss Alps Terrain (Matterhorn)"},
        "datasets": [
            {
                "key": f"swissalti3d-{tag}",
                "title": f"swissALTI3D 2m {tag} (Matterhorn)",
                "sources": [{"type": "raster_cog", "uri": uri, "format": "geotiff"}],
                "metadata": {
                    "crs": "EPSG:2056",
                    "organization": "swisstopo",
                    "license": "swisstopo OGD",
                    "tags": ["dem", "swissalti3d", "matterhorn"],
                },
                "publication": {"intent": "ready"},
            }
            for tag, uri in sorted(tiles.items())
        ],
        "dry_run": False,
    }
    results = api.manifest_apply(manifest)
    # The manifest API returns 200 with per-entry action results; a failed entry
    # is action="error" (no job_id). Abort before mosaicking rather than silently
    # build a VRT from a partial tile set. Resolve each tile's dataset_id by
    # polling queued jobs (create/update) or reusing the dataset_id of already-
    # ingested tiles (action="skip" on a re-run).
    errored = [r for r in results if r.get("action") == "error"]
    if errored:
        detail = "; ".join(
            f"{r.get('dataset_key')}: {r.get('message') or r.get('errors')}"
            for r in errored
        )
        raise RuntimeError(
            f"{len(errored)}/{len(results)} swissALTI3D manifest entries failed: {detail}"
        )
    tile_ids = []
    for r in results:
        if r.get("job_id"):
            tile_ids.append(api.poll(r["job_id"])["dataset_id"])
        elif r.get("dataset_id"):
            tile_ids.append(r["dataset_id"])
    if len(tile_ids) != len(tiles):
        raise RuntimeError(
            f"expected {len(tiles)} swissALTI3D tiles but only {len(tile_ids)} resolved to "
            "datasets; aborting before VRT mosaic"
        )
    print(f"  mosaicking {len(tile_ids)} tiles into a VRT...")
    vrt_job = api.vrt_create(
        tile_ids,
        "swissALTI3D Matterhorn DEM (2m mosaic)",
        "VRT mosaic of swissALTI3D 2m tiles around the Matterhorn. swisstopo OGD.",
    )
    vrt_ds = api.poll(vrt_job)["dataset_id"]
    # A VRT does NOT inherit is_dem from its sources - set it or terrain won't engage.
    api.patch_dataset(vrt_ds, is_dem=True)
    map_id = api.create_map(
        "The Matterhorn - swissALTI3D 3D Terrain",
        "A razor-sharp 3D terrain mesh of the Matterhorn from swisstopo swissALTI3D 2m lidar, "
        "mosaicked from COG tiles via VRT. swisstopo OGD.",
    )
    api.add_layer(
        map_id,
        {
            "dataset_id": vrt_ds,
            "sort_order": 0,
            "opacity": 1.0,
            "display_name": "swissALTI3D relief",
            "layer_type": "raster_geolens",
            "style_config": {"render_mode": "hillshade", "builder": {}},
            # illumination-anchor "map" keeps the NW (315 deg) lighting geographically
            # fixed instead of rotating with the camera on the bearing -150 / pitch 66 view.
            "paint": {
                "hillshade-illumination-direction": 315,
                "hillshade-illumination-anchor": "map",
                "hillshade-exaggeration": 0.75,
                "hillshade-shadow-color": "#16203a",
                "hillshade-highlight-color": "#ffffff",
                "hillshade-accent-color": "#3a4a63",
            },
        },
    )
    # Drape OSM climbing routes + named peaks on the terrain. Clip to the DEM
    # footprint (W,S,E,N of the swissALTI3D tile grid) so vectors sit on the mesh
    # rather than plunging into the out-of-coverage void (see fetch_osm_overlays).
    routes_fc, peaks_fc = fetch_osm_overlays((7.645, 45.961, 7.684, 45.988))
    if routes_fc["features"]:
        routes_bytes = json.dumps(routes_fc).encode()
        # A white casing under the red route makes it pop on the busy hillshade.
        # The casing is a second LAYER on the SAME dataset (map-sync dedupes the
        # tile source per dataset), not a duplicate dataset. The live viewer's
        # stack draws LOWER sort_order ON TOP, so the route (wanted on top) takes
        # the lower sort_order and the casing the higher.
        routes_ds = api.ingest_geojson(
            "matterhorn_routes.geojson",
            routes_bytes,
            "Matterhorn Climbing Routes",
            "OSM alpine routes clipped to the swissALTI3D DEM footprint (incl. the "
            "Lion Ridge / cresta Leone Cervino). Source: OpenStreetMap contributors.",
        )
        api.add_layer(
            map_id,
            {
                "dataset_id": routes_ds,
                "sort_order": 1,
                "opacity": 1.0,
                "display_name": "Climbing routes (OSM)",
                "paint": {
                    "line-color": "#ff3b30",
                    "line-width": 3.5,
                    "line-opacity": 1.0,
                },
                "layout": {"line-cap": "round", "line-join": "round"},
            },
        )
        api.add_layer(
            map_id,
            {
                "dataset_id": routes_ds,
                "sort_order": 2,
                "opacity": 1.0,
                "display_name": "Route casing",
                "paint": {
                    "line-color": "#ffffff",
                    "line-width": 7.0,
                    "line-opacity": 0.95,
                },
                "layout": {"line-cap": "round", "line-join": "round"},
            },
        )
        print(
            f"  + {len(routes_fc['features'])} route segments (white-cased) on the terrain"
        )
    if peaks_fc["features"]:
        peaks_ds = api.ingest_geojson(
            "matterhorn_peaks.geojson",
            json.dumps(peaks_fc).encode(),
            "Matterhorn Peaks",
            "Named summits within the swissALTI3D DEM footprint. Source: OpenStreetMap.",
        )
        api.add_layer(
            map_id,
            {
                "dataset_id": peaks_ds,
                "sort_order": 3,
                "opacity": 1.0,
                "display_name": "Peaks",
                # POINT marker (circle) + a single-column text label "Name (ele m)".
                "paint": {
                    "circle-color": "#ffffff",
                    "circle-radius": 4,
                    "circle-stroke-color": "#0b0f14",
                    "circle-stroke-width": 1.5,
                },
                "label_config": {
                    "column": "label",
                    "fontSize": 12,
                    "textColor": "#0b0f14",
                    "haloColor": "#ffffff",
                    "haloWidth": 1.8,
                    "textAnchor": "bottom",
                    "textOffset": [0, -0.8],
                    "allowOverlap": False,
                },
            },
        )
        print(f"  + {len(peaks_fc['features'])} named peaks labeled")
    # Initial view frames the summit, but the regional DEM (~8x8 km, SWISSALTI_BBOX)
    # now extends ~4 km past the Matterhorn in every direction, so the user can
    # zoom out and pan around the massif before reaching the data edge / -10000 m
    # void — no longer pinned tight on the peak. Exaggeration stays 1.0 (true
    # vertical scale; the swissALTI3D relief is dramatic enough on its own, and
    # true scale keeps any far-edge pedestal honest). The structural,
    # dataset-agnostic fix remains a global base DEM (terrain pedestal plan).
    api.set_view(
        map_id,
        visibility="public",
        terrain_config={
            "enabled": True,
            "source_dataset_id": vrt_ds,
            "exaggeration": 1.0,
        },
        center_lng=7.6586,
        center_lat=45.9750,
        zoom=14.0,
        pitch=66,
        bearing=-150,
        basemap_style="openfreemap-positron",
        show_basemap_labels=False,
    )
    print(f"  -> map {map_id}")
    return map_id


def build_airports(api: Api, force: bool = False) -> str:
    if not force and _map_exists(api, "World Airports"):
        print("  [skip] World Airports already exists")
        return "(skipped)"
    print("\n[airports] World Airports (clustered, categorical by class)")
    print("  downloading OurAirports CSV...")
    rows = list(csv.DictReader(io.StringIO(fetch(OURAIRPORTS_CSV).decode("utf-8"))))
    # Filter to large+medium with scheduled service => ~3.3k (<=5000 client-cluster cap).
    feats = []
    for r in rows:
        if r.get("type") not in ("large_airport", "medium_airport"):
            continue
        if r.get("scheduled_service") != "yes":
            continue
        try:
            lng, lat = float(r["longitude_deg"]), float(r["latitude_deg"])
        except (TypeError, ValueError, KeyError):
            continue
        try:
            elev = float(r["elevation_ft"]) if r.get("elevation_ft") else None
        except (TypeError, ValueError):
            elev = None
        feats.append(
            {
                "type": "Feature",
                "properties": {
                    "type": r.get("type"),
                    "name": r.get("name"),
                    "iso_country": r.get("iso_country"),
                    "municipality": r.get("municipality"),
                    "iata_code": r.get("iata_code"),
                    "elevation_ft": elev,
                },
                "geometry": {"type": "Point", "coordinates": [lng, lat]},
            }
        )
    if len(feats) > 5000:
        # The cluster cap is hard (features.geojson returns at most 5000); over it the
        # live viewer silently drops the data and falls back to unclustered circles.
        raise RuntimeError(
            f"airports filter yielded {len(feats)} features (>5000 cluster cap); "
            "tighten the filter (e.g. large_airport only)"
        )
    print(f"  ingesting {len(feats)} airports...")
    data = json.dumps({"type": "FeatureCollection", "features": feats}).encode()
    ds = api.ingest_geojson(
        "world_airports.geojson",
        data,
        "World Airports (large + medium, scheduled)",
        "Large and medium airports with scheduled passenger service. "
        "Source: OurAirports (public domain).",
    )
    map_id = api.create_map(
        "World Airports",
        "Several thousand of the world's busiest airports, clustered at low zoom and "
        "colored by airport class once you zoom in. Source: OurAirports.",
    )
    # column lowercased on ingest: "type" (already lowercase). Categorical match expr
    # mirrors the frontend buildCategoricalExpression (case-null-guard + match + fallback).
    match = [
        "case",
        ["==", ["get", "type"], None],
        "#94a3b8",
        [
            "match",
            ["get", "type"],
            "large_airport",
            "#1b9e77",
            "medium_airport",
            "#d95f02",
            "#94a3b8",
        ],
    ]
    api.add_layer(
        map_id,
        {
            "dataset_id": ds,
            "sort_order": 0,
            "opacity": 1.0,
            "display_name": "Airports (clustered, by class)",
            "paint": {
                "circle-color": match,
                "circle-radius": 5,
                "circle-stroke-color": "#0b0f14",
                "circle-stroke-width": 1,
                "circle-opacity": 0.95,
            },
            "style_config": {
                "mode": "categorical",
                "column": "type",
                "ramp": "Dark2",
                "categories": [
                    {
                        "value": "large_airport",
                        "color": "#1b9e77",
                        "label": "Large hub",
                    },
                    {"value": "medium_airport", "color": "#d95f02", "label": "Medium"},
                ],
                # render_mode and mode coexist; the viewer auto-creates the cluster
                # circle + count companion layers from style_config.builder (snake_case).
                "render_mode": "cluster",
                "builder": {
                    "cluster_radius": 48,
                    "cluster_max_zoom": 14,
                    "cluster_color": "#334155",
                    "cluster_text_color": "#ffffff",
                    "cluster_text_size": 12,
                },
            },
        },
    )
    api.set_view(
        map_id,
        visibility="public",
        center_lng=0,
        center_lat=25,
        zoom=1.4,
        pitch=0,
        bearing=0,
        basemap_style="openfreemap-dark",
        show_basemap_labels=True,
    )
    print(f"  -> map {map_id}")
    return map_id


def build_earthquakes(api: Api, force: bool = False) -> str:
    if not force and _map_exists(api, "Recent Earthquakes"):
        print("  [skip] Recent Earthquakes already exists")
        return "(skipped)"
    print("\n[earthquakes] Recent Earthquakes (graduated circles + heatmap)")
    print("  downloading USGS M4.5+ feed...")
    data, n = quake_feed()
    # GeoLens renders ONE MapLibre layer per dataset, so the graduated-circle layer and
    # the heatmap layer come from the SAME geometry ingested as TWO datasets (the proven
    # casing pattern from build_matterhorn) rather than two layers off one dataset.
    print(f"  ingesting {n} quakes (x2: circles + heatmap)...")
    circles_ds = api.ingest_geojson(
        "recent_quakes.geojson",
        data,
        "Recent Earthquakes (M4.5+, last 30 days)",
        "Significant earthquakes (M4.5+) from the last 30 days. "
        "Source: USGS Earthquake Hazards Program (public domain).",
    )
    heat_ds = api.ingest_geojson(
        "recent_quakes_heat.geojson",
        data,
        "Recent Earthquakes - Heatmap source",
        "Same M4.5+ quake geometry as the graduated-circle dataset, ingested "
        "separately so MapLibre renders it as its own heatmap layer.",
    )
    map_id = api.create_map(
        "Recent Earthquakes",
        "M4.5+ earthquakes from the last 30 days - graduated by magnitude over a "
        "magnitude-weighted heatmap. Source: USGS.",
    )
    # Lower sort_order draws ON TOP in the live viewer, so circles (0) sit above heatmap (1).
    radius = ["step", ["to-number", ["get", "mag"], 0], 4, 5.0, 7, 6.0, 11, 7.0, 16]
    api.add_layer(
        map_id,
        {
            "dataset_id": circles_ds,
            "sort_order": 0,
            "opacity": 1.0,
            "display_name": "Magnitude (graduated)",
            "paint": {
                "circle-radius": radius,
                "circle-color": "#ef4444",
                "circle-opacity": 0.85,
                "circle-stroke-color": "#7f1d1d",
                "circle-stroke-width": 0.5,
            },
            "style_config": {
                "mode": "graduated",
                "column": "mag",
                "ramp": "YlOrRd",
                "target": "radius",
                "method": "manual",
                "breaks": [5.0, 6.0, 7.0],
                "sizes": [4, 7, 11, 16],
                "sizeLabel": "Magnitude",
            },
        },
    )
    api.add_layer(
        map_id,
        {
            "dataset_id": heat_ds,
            "sort_order": 1,
            "opacity": 1.0,
            "display_name": "Magnitude heatmap",
            "paint": {
                "heatmap-radius": 28,
                # weight expression references ['get','mag'] so the low-zoom tile cols=
                # opt-in includes the magnitude column.
                "heatmap-weight": [
                    "interpolate",
                    ["linear"],
                    ["to-number", ["get", "mag"], 0],
                    4,
                    0.1,
                    8,
                    1,
                ],
                "heatmap-intensity": 1,
                "heatmap-opacity": 0.75,
                "heatmap-color": [
                    "interpolate",
                    ["linear"],
                    ["heatmap-density"],
                    0,
                    "rgba(0,0,0,0)",
                    0.2,
                    "#ffffb2",
                    0.4,
                    "#fecc5c",
                    0.6,
                    "#fd8d3c",
                    0.8,
                    "#f03b20",
                    1.0,
                    "#bd0026",
                ],
            },
            "style_config": {
                "mode": "graduated",
                "column": "",
                "ramp": "YlOrRd",
                "render_mode": "heatmap",
                "builder": {"heatmap_ramp": "YlOrRd"},
            },
        },
    )
    api.set_view(
        map_id,
        visibility="public",
        center_lng=150,
        center_lat=5,
        zoom=1.6,
        pitch=0,
        bearing=0,
        basemap_style="openfreemap-dark",
        show_basemap_labels=True,
    )
    print(f"  -> map {map_id}")
    return map_id


def build_countries(api: Api, force: bool = False) -> str:
    if not force and _map_exists(api, "World Countries"):
        print("  [skip] World Countries already exists")
        return "(skipped)"
    print("\n[countries] World Countries (choropleth + companion catalog datasets)")
    print("  downloading Natural Earth admin-0...")
    fc = json.loads(fetch(NE_COUNTRIES))
    # Trim the 168-column admin-0 table to a handful of useful, styled props.
    # Source props are UPPERCASE -> lowercased on ingest; reference the lowercased name.
    keep = [
        "NAME",
        "NAME_LONG",
        "POP_EST",
        "GDP_MD",
        "CONTINENT",
        "SUBREGION",
        "ECONOMY",
        "INCOME_GRP",
        "ISO_A3",
    ]
    gdps = []
    for feat in fc["features"]:
        p = feat["properties"]
        feat["properties"] = {k: p.get(k) for k in keep}
        g = p.get("GDP_MD")
        # NE uses -99 / 0 sentinels for missing GDP; exclude from the quantile breaks.
        if isinstance(g, (int, float)) and g > 0:
            gdps.append(float(g))
    data = json.dumps(fc).encode()
    print(f"  ingesting {len(fc['features'])} countries...")
    ds = api.ingest_geojson(
        "world_countries.geojson",
        data,
        "World Countries (Natural Earth 1:50m)",
        "All world countries with population, GDP, economy class and income group. "
        "Source: Natural Earth admin-0, 1:50m (public domain).",
    )
    map_id = api.create_map(
        "World Countries",
        "Every country graded by GDP, with the world's major cities sized by population. "
        "Source: Natural Earth.",
    )
    # Quantile (sextile) choropleth over the lowercased gdp_md column.
    col = "gdp_md"
    vals = sorted(gdps)
    m = len(vals)
    breaks = [vals[max(0, round(m * k / 6) - 1)] for k in range(1, 6)]
    colors = ["#440154", "#414487", "#2a788e", "#22a884", "#7ad151", "#fde725"]
    api.add_layer(
        map_id,
        {
            "dataset_id": ds,
            "sort_order": 1,
            "opacity": 1.0,
            "display_name": "GDP (USD millions)",
            "paint": {
                "fill-color": step_expr(col, breaks, colors),
                "fill-opacity": 0.85,
                "_outline-color": "#0b0f14",
                "_outline-width": 0.4,
            },
            "style_config": {
                "mode": "graduated",
                "column": col,
                "ramp": "Viridis",
                "target": "color",
                "method": "quantile",
                "breaks": breaks,
                "colors": colors,
                "colorLabel": "GDP (USD millions)",
                "builder": {"outline_color": "#0b0f14", "outline_width": 0.4},
            },
        },
    )
    # Companion 1: populated places, added as a graduated city-dot layer (catalog breadth
    # + a richer map). pop_max drives circle radius.
    print("  + companion: populated places...")
    places = json.loads(fetch(NE_PLACES))
    places_ds = api.ingest_geojson(
        "world_places.geojson",
        json.dumps(places).encode(),
        "World Populated Places (Natural Earth 1:50m)",
        "Cities and towns worldwide with population and admin context. "
        "Source: Natural Earth populated places, 1:50m (public domain).",
    )
    city_radius = [
        "step",
        ["to-number", ["get", "pop_max"], 0],
        1.5,
        250000,
        3,
        1000000,
        5,
        5000000,
        8,
    ]
    api.add_layer(
        map_id,
        {
            "dataset_id": places_ds,
            "sort_order": 0,
            "opacity": 1.0,
            "display_name": "Cities (by population)",
            "paint": {
                "circle-radius": city_radius,
                "circle-color": "#fde725",
                "circle-opacity": 0.9,
                "circle-stroke-color": "#0b0f14",
                "circle-stroke-width": 0.5,
            },
            "style_config": {
                "mode": "graduated",
                "column": "pop_max",
                "ramp": "YlOrRd",
                "target": "radius",
                "method": "manual",
                "breaks": [250000, 1000000, 5000000],
                "sizes": [1.5, 3, 5, 8],
                "sizeLabel": "Population",
            },
        },
    )
    # Companion 2: admin-1 states/provinces, committed SUMMARY-LESS so the AI metadata
    # generator has a dataset to enrich (catalog-only; not added to the map).
    print(
        "  + companion: admin-1 states/provinces (summary-less, for AI-metadata demo)..."
    )
    admin1 = fetch(NE_ADMIN1)
    api.ingest_geojson(
        "world_admin1.geojson",
        admin1,
        "World States & Provinces (Natural Earth 1:50m)",
        "",  # intentionally blank: raw material for the AI metadata-generation demo.
    )
    api.set_view(
        map_id,
        visibility="public",
        center_lng=10,
        center_lat=28,
        zoom=1.7,
        pitch=0,
        bearing=0,
        basemap_style="openfreemap-positron",
        show_basemap_labels=False,
    )
    print(f"  -> map {map_id}  (gdp breaks={breaks})")
    return map_id


def build_rivers(api: Api, force: bool = False) -> str:
    if not force and _map_exists(api, "World Rivers"):
        print("  [skip] World Rivers already exists")
        return "(skipped)"
    print("\n[rivers] World Rivers (line + casing, width by scalerank)")
    print("  downloading Natural Earth rivers...")
    rivers = fetch(NE_RIVERS)
    # Casing = a second LAYER on the SAME dataset (a wider, darker line drawn
    # underneath), not a duplicate dataset.
    line_ds = api.ingest_geojson(
        "world_rivers.geojson",
        rivers,
        "World Rivers & Lake Centerlines (Natural Earth 10m)",
        "Major rivers and lake centerlines worldwide, ranked by prominence. "
        "Source: Natural Earth, 1:10m (public domain).",
    )
    map_id = api.create_map(
        "World Rivers",
        "The world's major rivers, drawn thicker the more prominent they are "
        "(by Natural Earth scalerank), with a soft casing for contrast.",
    )
    # scalerank: lower = more major = wider. Width thickens with zoom. Lowercased column.
    line_width = [
        "interpolate",
        ["linear"],
        ["zoom"],
        2,
        ["step", ["to-number", ["get", "scalerank"], 10], 1.4, 4, 0.9, 7, 0.5],
        8,
        ["step", ["to-number", ["get", "scalerank"], 10], 4.0, 4, 2.5, 7, 1.4],
    ]
    casing_width = ["interpolate", ["linear"], ["zoom"], 2, 2.6, 8, 6.5]
    # Lower sort_order draws ON TOP: the colored line (1) over the casing (2).
    api.add_layer(
        map_id,
        {
            "dataset_id": line_ds,
            "sort_order": 1,
            "opacity": 1.0,
            "display_name": "Rivers",
            "paint": {
                "line-color": "#38bdf8",
                "line-width": line_width,
                "line-opacity": 0.95,
            },
            "layout": {"line-cap": "round", "line-join": "round"},
        },
    )
    api.add_layer(
        map_id,
        {
            "dataset_id": line_ds,
            "sort_order": 2,
            "opacity": 1.0,
            "display_name": "River casing",
            "paint": {
                "line-color": "#0c2233",
                "line-width": casing_width,
                "line-opacity": 0.7,
            },
            "layout": {"line-cap": "round", "line-join": "round"},
        },
    )
    api.set_view(
        map_id,
        visibility="public",
        center_lng=12,
        center_lat=30,
        zoom=1.9,
        pitch=0,
        bearing=0,
        basemap_style="openfreemap-dark",
        show_basemap_labels=False,
    )
    print(f"  -> map {map_id}")
    return map_id


def build_restless_earth(api: Api, force: bool = False) -> str:
    """The composite storytelling hero: quakes over the plate boundaries that
    spawn them, with exposed cities and GDP context.

    Reuses the earthquake + countries datasets by title (run those builders
    first; the default sequence does) and ingests two of its own:

      * Tectonic Plate Boundaries (PB2002 steps) - per-segment boundary class
        (subduction/convergent/divergent/transform) + relative velocity, so the
        layer is both categorically styled AND Ask-AI-queryable.
      * World Major Cities (500k+) - a slim, purpose-built subset of Natural
        Earth populated places (name/country/pop_max/is_capital/timezone).
        The full 1251-place / 130-column NE dataset reads as visual noise at
        world zoom and drowns the AI SQL generator in irrelevant columns.

    Style-spec notes (all verified live):
      * zoom+data composite expressions (interpolate-by-zoom whose outputs are
        step-by-property) scale circles/lines smoothly from world view to city
        view without losing the data encoding.
      * M7+ quakes get a white highlight ring via a step on circle-stroke-*.
      * The heatmap radius/intensity interpolate by zoom so regional views
        don't fragment into per-point blobs (fixed 28px only worked at z1.6).
      * Heatmap + GDP stay OUT of the legend (context layers); the legend
        budget goes to the three story layers.
    """
    name = "Restless Earth - 30 Days of Quakes and the Cities Nearby"
    if not force and _map_exists(api, name):
        print(f"  [skip] {name} already exists")
        return "(skipped)"
    print("\n[restless] Restless Earth (quakes + plates + cities + GDP)")
    by_title = api.datasets_by_title()
    needed = {
        "quakes": "Recent Earthquakes (M4.5+, last 30 days)",
        "heat": "Recent Earthquakes - Heatmap source",
        "countries": "World Countries (Natural Earth 1:50m)",
    }
    missing = [t for t in needed.values() if t not in by_title]
    if missing:
        print(f"  [skip] missing datasets (run earthquakes + countries first): {missing}")
        return "(skipped)"
    ds = {k: by_title[t] for k, t in needed.items()}

    # --- own dataset 1: PB2002 plate-boundary steps (idempotent by title) ----
    plates_title = "Tectonic Plate Boundaries (PB2002)"
    if plates_title in by_title:
        ds["plates"] = by_title[plates_title]
        print("  [reuse] plate boundaries dataset")
    else:
        print("  downloading PB2002 plate-boundary steps...")
        fc = json.loads(fetch(PB2002_STEPS))
        # Collapse the 7 Bird (2003) step classes into 4 story-level types;
        # subduction zones stay their own class (that is where megaquakes live).
        type_of = {
            "SUB": "subduction zone",
            "OCB": "convergent",
            "CCB": "convergent",
            "OSR": "divergent",
            "CRB": "divergent",
            "OTF": "transform",
            "CTF": "transform",
        }
        for feat in fc["features"]:
            p = feat["properties"]
            cls = p.get("STEPCLASS")
            feat["properties"] = {
                "boundary": p.get("PLATEBOUND"),
                "boundary_type": type_of.get(cls, "other"),
                "class_code": cls,
                "velocity_mm_yr": p.get("VELOCITYLE"),
            }
        print(f"  ingesting {len(fc['features'])} boundary segments...")
        ds["plates"] = api.ingest_geojson(
            "plate_boundaries.geojson",
            json.dumps(fc).encode(),
            plates_title,
            "Tectonic plate boundary segments classified as subduction zone, "
            "convergent, divergent or transform, with relative plate velocity "
            "(mm/yr). Source: Peter Bird (2003) PB2002 via Nordpil (open data).",
        )

    # --- own dataset 2: slim major-cities subset (idempotent by title) -------
    cities_title = "World Major Cities (500k+)"
    if cities_title in by_title:
        ds["cities"] = by_title[cities_title]
        print("  [reuse] major cities dataset")
    else:
        print("  downloading Natural Earth populated places...")
        fc = json.loads(fetch(NE_PLACES))
        feats = []
        for feat in fc["features"]:
            p = feat["properties"]
            pop = p.get("POP_MAX") or p.get("pop_max") or 0
            if not isinstance(pop, (int, float)) or pop < 500000:
                continue
            fcla = (p.get("FEATURECLA") or p.get("featurecla") or "")
            feats.append(
                {
                    "type": "Feature",
                    "properties": {
                        "name": p.get("NAME") or p.get("name"),
                        "country": p.get("ADM0NAME") or p.get("adm0name"),
                        "pop_max": pop,
                        "is_capital": fcla.startswith("Admin-0 capital"),
                        "timezone": p.get("TIMEZONE") or p.get("timezone"),
                    },
                    "geometry": feat["geometry"],
                }
            )
        print(f"  ingesting {len(feats)} major cities...")
        ds["cities"] = api.ingest_geojson(
            "world_major_cities.geojson",
            json.dumps({"type": "FeatureCollection", "features": feats}).encode(),
            cities_title,
            "Cities with 500k+ inhabitants: name, country, population, capital "
            "flag and timezone. Slimmed from Natural Earth populated places "
            "1:50m (public domain) for the Restless Earth showcase.",
        )

    map_id = api.create_map(
        name,
        "Thirty days of M4.5+ earthquakes over the tectonic plate boundaries "
        "that spawn them - sized and colored by magnitude, with white rings on "
        "the M7+ giants. Major cities show the exposure; the dim choropleth is "
        "national GDP. Click anything, or open Ask AI: which quakes triggered "
        "tsunami warnings? Which boundary type produced the strongest shocks? "
        "Sources: USGS, PB2002 (Bird 2003), Natural Earth.",
    )

    def mag_step(v0, v1, v2, v3):
        return ["step", ["to-number", ["get", "mag"], 0], v0, 5.0, v1, 6.0, v2, 7.0, v3]

    # Magnitude double-encoded: size AND color (same class breaks, and the color
    # ramp deliberately matches the heatmap stops so the two quake layers read
    # as one visual system). Viewer draws LOWER sort_order ON TOP.
    quake_colors = ["#fecc5c", "#fd8d3c", "#f03b20", "#bd0026"]
    api.add_layer(
        map_id,
        {
            "dataset_id": ds["quakes"],
            "sort_order": 0,
            "opacity": 1.0,
            "display_name": "Earthquakes (by magnitude)",
            "paint": {
                "circle-radius": [
                    "interpolate", ["linear"], ["zoom"],
                    1.2, mag_step(2.5, 4.5, 7, 11),
                    6, mag_step(5, 9, 14, 22),
                ],
                "circle-color": mag_step(*quake_colors),
                "circle-opacity": 0.9,
                "circle-stroke-color": mag_step(
                    "#7f1d1d", "#7f1d1d", "#7f1d1d", "#ffffff"
                ),
                "circle-stroke-width": mag_step(0.4, 0.4, 0.6, 1.5),
            },
            "style_config": {
                "mode": "graduated",
                "column": "mag",
                "ramp": "YlOrRd",
                "target": "radius",
                "method": "manual",
                "breaks": [5.0, 6.0, 7.0],
                "sizes": [3, 5, 8, 12],
                "colors": quake_colors,
                "sizeLabel": "Magnitude",
            },
            "popup_config": {
                "enabled": True,
                "expression": "M{mag} - {place}",
                "visible_fields": ["depth_km", "time_utc", "felt", "tsunami"],
            },
        },
    )

    def pop_step(v0, v1, v2, v3):
        return [
            "step", ["to-number", ["get", "pop_max"], 0],
            v0, 1000000, v1, 5000000, v2, 10000000, v3,
        ]

    api.add_layer(
        map_id,
        {
            "dataset_id": ds["cities"],
            "sort_order": 1,
            "opacity": 1.0,
            "display_name": "Major cities (by population)",
            "paint": {
                "circle-radius": [
                    "interpolate", ["linear"], ["zoom"],
                    1.5, pop_step(1.6, 2.8, 4.5, 6.5),
                    6, pop_step(3.5, 6, 9, 13),
                ],
                # Silver "city lights" on the dark basemap; below-5M cities fade
                # back at world zoom so the quake story stays on top.
                "circle-color": "#e2e8f0",
                "circle-opacity": [
                    "interpolate", ["linear"], ["zoom"],
                    1.5,
                    ["case",
                     [">=", ["to-number", ["get", "pop_max"], 0], 5000000],
                     0.95, 0.55],
                    4, 0.95,
                ],
                "circle-stroke-color": "#0b0f14",
                "circle-stroke-width": 0.6,
            },
            "style_config": {
                "mode": "graduated",
                "column": "pop_max",
                "ramp": "YlOrRd",
                "target": "radius",
                "method": "manual",
                "breaks": [1000000, 5000000, 10000000],
                "sizes": [1.6, 2.8, 4.5, 6.5],
                "sizeLabel": "Population",
            },
            "popup_config": {
                "enabled": True,
                "expression": "{name}",
                "visible_fields": ["country", "pop_max", "is_capital"],
            },
        },
    )

    # Categorical line color, mirroring the frontend buildCategoricalExpression
    # (null guard + match + fallback) like the airports layer does.
    btype_color = [
        "case",
        ["==", ["get", "boundary_type"], None],
        "#94a3b8",
        [
            "match", ["get", "boundary_type"],
            "subduction zone", "#e879f9",
            "convergent", "#c084fc",
            "divergent", "#4ade80",
            "transform", "#22d3ee",
            "#94a3b8",
        ],
    ]
    def btype_width(sub, rest):
        return ["match", ["get", "boundary_type"], "subduction zone", sub, rest]

    api.add_layer(
        map_id,
        {
            "dataset_id": ds["plates"],
            "sort_order": 2,
            "opacity": 1.0,
            "display_name": "Plate boundaries",
            "paint": {
                "line-color": btype_color,
                "line-width": [
                    "interpolate", ["linear"], ["zoom"],
                    1, btype_width(1.6, 0.9),
                    6, btype_width(3.2, 1.8),
                ],
                "line-opacity": 0.85,
                "line-blur": 0.4,
            },
            "layout": {"line-cap": "round", "line-join": "round"},
            "style_config": {
                "mode": "categorical",
                "column": "boundary_type",
                "ramp": "Dark2",
                "categories": [
                    {"value": "subduction zone", "color": "#e879f9",
                     "label": "Subduction zone"},
                    {"value": "convergent", "color": "#c084fc",
                     "label": "Convergent"},
                    {"value": "divergent", "color": "#4ade80",
                     "label": "Divergent (ridge/rift)"},
                    {"value": "transform", "color": "#22d3ee",
                     "label": "Transform fault"},
                ],
            },
            "popup_config": {
                "enabled": True,
                "expression": "{boundary} plate boundary",
                "visible_fields": ["boundary_type", "velocity_mm_yr"],
            },
        },
    )
    api.add_layer(
        map_id,
        {
            "dataset_id": ds["heat"],
            "sort_order": 3,
            "opacity": 1.0,
            "display_name": "Quake intensity (heatmap)",
            "show_in_legend": False,
            "paint": {
                "heatmap-radius": [
                    "interpolate", ["linear"], ["zoom"], 0, 15, 3, 30, 6, 50,
                ],
                "heatmap-weight": [
                    "interpolate", ["linear"], ["to-number", ["get", "mag"], 0],
                    4, 0.1, 8, 1,
                ],
                "heatmap-intensity": [
                    "interpolate", ["linear"], ["zoom"], 0, 0.9, 6, 2,
                ],
                "heatmap-opacity": 0.7,
                "heatmap-color": [
                    "interpolate", ["linear"], ["heatmap-density"],
                    0, "rgba(0,0,0,0)",
                    0.2, "#ffffb2",
                    0.4, "#fecc5c",
                    0.6, "#fd8d3c",
                    0.8, "#f03b20",
                    1.0, "#bd0026",
                ],
            },
            "style_config": {
                "mode": "graduated",
                "column": "",
                "ramp": "YlOrRd",
                "render_mode": "heatmap",
                "builder": {"heatmap_ramp": "YlOrRd"},
            },
        },
    )
    gdp_breaks = [3000, 25000, 100000, 500000, 2000000]
    gdp_colors = ["#440154", "#414487", "#2a788e", "#22a884", "#7ad151", "#fde725"]
    api.add_layer(
        map_id,
        {
            "dataset_id": ds["countries"],
            "sort_order": 4,
            "opacity": 0.35,
            "display_name": "GDP (USD millions)",
            "show_in_legend": False,
            "paint": {
                "fill-color": step_expr("gdp_md", gdp_breaks, gdp_colors),
                "fill-opacity": 0.85,
            },
            "style_config": {
                "mode": "graduated",
                "column": "gdp_md",
                "ramp": "Viridis",
                "target": "color",
                "method": "manual",
                "breaks": gdp_breaks,
                "colors": gdp_colors,
                "colorLabel": "GDP (USD millions)",
                "builder": {"outline_color": "#0b0f14", "outline_width": 0.4},
            },
            "popup_config": {
                "enabled": True,
                "expression": "{name}",
                "visible_fields": ["gdp_md", "pop_est"],
            },
        },
    )
    api.set_view(
        map_id,
        visibility="public",
        center_lng=150,
        center_lat=5,
        zoom=1.6,
        pitch=0,
        bearing=0,
        basemap_style="openfreemap-dark",
        show_basemap_labels=True,
    )
    print(f"  -> map {map_id}")
    return map_id


def build_sentinel2(api: Api, force: bool = False) -> str:
    if not force and _map_exists(api, "Sentinel-2 True Color - NYC"):
        print("  [skip] Sentinel-2 True Color - NYC already exists")
        return "(skipped)"
    print("\n[sentinel2] Sentinel-2 True Color over NYC (COGs by reference)")
    print("  querying Element84 STAC directly...")
    # Query the STAC API DIRECTLY (the backend /services/stac/search proxy 502s on the
    # SSRF IP-pin against Element84's CloudFront edge).
    body = {
        "collections": ["sentinel-2-l2a"],
        "bbox": SENTINEL_BBOX,
        "query": {"eo:cloud_cover": {"lt": 10}},
        "sortby": [{"field": "properties.datetime", "direction": "desc"}],
        "limit": 24,
    }
    r = httpx.post(f"{SENTINEL_STAC}/search", json=body, timeout=60.0)
    r.raise_for_status()
    feats = r.json().get("features", [])
    items, seen_dates = [], set()
    for f in feats:
        a = (f.get("assets") or {}).get("visual")  # TCI COG
        if not a or not a.get("href"):
            continue
        dt = f["properties"].get("datetime", "")
        day = dt[:10]
        if day in seen_dates:  # one scene per date keeps the mosaic clean
            continue
        seen_dates.add(day)
        items.append(
            {
                "id": f["id"],
                "collection": f.get("collection", "sentinel-2-l2a"),
                "title": f"Sentinel-2 TCI {f['id']}",
                "data_asset_href": a["href"],
                "bbox": f.get("bbox"),
                "epsg": f["properties"].get("proj:epsg"),
                "datetime_start": dt,
                "datetime_end": dt,
                "keywords": [
                    "sentinel-2",
                    "true-color",
                    "imagery",
                    "esa",
                    "copernicus",
                ],
            }
        )
        if len(items) >= 6:
            break
    if not items:
        raise RuntimeError("no low-cloud Sentinel-2 TCI items matched the NYC AOI")
    print(f"  importing {len(items)} TCI COGs by reference (no download)...")
    results = api.stac_import(SENTINEL_STAC, items, visibility="public")
    errored = [r for r in results if r.get("status") == "error"]
    if errored:
        detail = "; ".join(r.get("error") or r.get("item_id", "?") for r in errored)
        raise RuntimeError(
            f"{len(errored)}/{len(results)} STAC imports failed: {detail}"
        )
    # 'created' results carry dataset_id; 'skipped' (the COG was already imported, e.g.
    # a prior partial run) carry only item_id and no dataset_id, and the backend dedupe
    # on source_url means --force won't re-create them. Resolve skipped items back to
    # their existing dataset by the title we assigned ("Sentinel-2 TCI {id}").
    id_to_title = {it["id"]: it["title"] for it in items}
    by_title = None
    ds_ids = []
    for r in results:
        if r.get("dataset_id"):
            ds_ids.append(r["dataset_id"])
        elif r.get("status") == "skipped":
            if by_title is None:
                by_title = api.datasets_by_title()
            existing = by_title.get(id_to_title.get(r.get("item_id"), ""))
            if existing:
                ds_ids.append(existing)
    if not ds_ids:
        raise RuntimeError(
            "STAC import resolved no dataset_ids (skipped items not found by title); "
            "remove the existing Sentinel-2 datasets and retry"
        )
    map_id = api.create_map(
        "Sentinel-2 True Color - NYC",
        "Recent low-cloud Sentinel-2 L2A true-color imagery over New York, streamed by "
        "reference from the AWS Earth Search open COG mirror (ESA Copernicus). No download "
        "- Titiler renders the cloud-optimized GeoTIFFs directly.",
    )
    for i, ds_id in enumerate(ds_ids):
        api.add_layer(
            map_id,
            {
                "dataset_id": ds_id,
                "sort_order": i,
                "opacity": 1.0,
                "display_name": f"Sentinel-2 scene {i + 1}",
                "layer_type": "raster_geolens",
                # true color = NO render_mode, no paint (default RGB path).
                "style_config": {"builder": {}},
            },
        )
    api.set_view(
        map_id,
        visibility="public",
        center_lng=-73.97,
        center_lat=40.78,
        zoom=9.5,
        pitch=0,
        bearing=0,
        basemap_style="openfreemap-positron",
        show_basemap_labels=True,
    )
    print(f"  -> map {map_id}  ({len(ds_ids)} scenes)")
    return map_id


# A tiny inline private dataset for the embed-token capability demo (no external fetch
# so it is fully reproducible).
PRIVATE_VIP_FC = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"name": "HQ - Manhattan", "tier": "gold"},
            "geometry": {"type": "Point", "coordinates": [-73.9857, 40.7484]},
        },
        {
            "type": "Feature",
            "properties": {"name": "Field office - Brooklyn", "tier": "silver"},
            "geometry": {"type": "Point", "coordinates": [-73.9442, 40.6782]},
        },
    ],
}


def build_collection(api: Api, force: bool = False) -> str:
    # Collection.name is UNIQUE -> creating a second "Discover the World" 409s. On a
    # --force reseed (no down -v) reuse the existing collection instead of recreating;
    # add_to_collection is idempotent, so re-adding members is a no-op.
    existing = api.collections_by_name()
    if "Discover the World" in existing:
        if not force:
            print("  [skip] Discover the World collection already exists")
            return "(skipped)"
        coll_id = existing["Discover the World"]
        print("\n[collection] reusing existing 'Discover the World' (--force)")
    else:
        print("\n[collection] Discover the World + private-dataset embed-token demo")
        coll_id = api.create_collection(
            "Discover the World",
            "A guided tour of the GeoLens showcase - the NYC skyline, New York income, "
            "world countries, rivers and airports - grouped into one browsable collection.",
        )
    titles = api.datasets_by_title()
    wanted = [
        "Manhattan Building Heights",
        "New York Median Household Income by County",
        "World Countries (Natural Earth 1:50m)",
        "World Airports (large + medium, scheduled)",
        "World Rivers & Lake Centerlines (Natural Earth 10m)",
        "Recent Earthquakes (M4.5+, last 30 days)",
        # restless-earth datasets:
        "Tectonic Plate Boundaries (PB2002)",
        "World Major Cities (500k+)",
        # present only with --with-terrain:
        "swissALTI3D Matterhorn DEM (2m mosaic)",
    ]
    member_ids = [titles[t] for t in wanted if t in titles]
    added = api.add_to_collection(coll_id, member_ids) if member_ids else 0
    print(f"  + {added} datasets added to the collection")

    # Private-dataset embed-token demo. A PUBLIC share URL is impossible with a private
    # dataset (publishing the map 400s), so keep the map PRIVATE and demonstrate the
    # X-Embed-Token header, which grants tile access to the scoped private dataset.
    print("  building the private embed-token capability demo...")
    priv_ds = api.ingest_geojson(
        "vip_sites_private.geojson",
        json.dumps(PRIVATE_VIP_FC).encode(),
        "Private Embed Demo - VIP Sites",
        "A private dataset shown ONLY to holders of a scoped embed token "
        "(X-Embed-Token). Demonstrates token-gated access to non-public data.",
        visibility="private",
    )
    map_id = api.create_map(
        "Private Embed Demo",
        "A private map (kept unpublished) used to mint a scoped embed token over a "
        "private dataset.",
    )
    layer = api.add_layer(
        map_id,
        {
            "dataset_id": priv_ds,
            "sort_order": 0,
            "opacity": 1.0,
            "display_name": "VIP sites (private)",
            "paint": {
                "circle-color": "#ff3b30",
                "circle-radius": 7,
                "circle-stroke-color": "#ffffff",
                "circle-stroke-width": 1.5,
            },
        },
    )
    table_name = layer.get("dataset_table_name")
    # scoped_dataset_ids is a SNAPSHOT of the map's layers at mint time -> add the layer
    # BEFORE minting. raw_token is returned ONLY here.
    tok = api.mint_embed_token(map_id, "Discover the World - private embed demo")
    raw = tok.get("raw_token")
    print(f"  collection: {coll_id}  ({added} datasets)")
    print(f"  embed token (private dataset): {raw}")
    print(f"  scoped datasets: {tok.get('scoped_dataset_ids')}")
    print(f"  expires: {tok.get('expires_at')}")
    if table_name and raw:
        print("  demo: this serves the PRIVATE dataset with NO login:")
        print(
            f"    curl -H 'X-Embed-Token: {raw}' "
            f"{api.base}/api/tiles/data.{table_name}/12/1205/1539.pbf"
        )
    return coll_id


def main() -> int:
    ap = argparse.ArgumentParser(description="Seed GeoLens marketing showcase maps.")
    ap.add_argument(
        "--base-url",
        default=os.environ.get(
            "GEOLENS_BASE_URL",
            os.environ.get("GEOLENS_URL", DEFAULT_BASE_URL),
        ),
    )
    ap.add_argument(
        "--username", default=os.environ.get("GEOLENS_ADMIN_USERNAME", "admin")
    )
    ap.add_argument(
        "--password", default=os.environ.get("GEOLENS_ADMIN_PASSWORD")
    )
    ap.add_argument(
        "--with-terrain",
        action="store_true",
        help="also build the Matterhorn terrain hero (downloads ~9 COG tiles)",
    )
    ap.add_argument(
        "--with-sentinel2",
        action="store_true",
        help="also build the Sentinel-2 true-color hero (needs Titiler->S3 egress at view time)",
    )
    ap.add_argument(
        "--only",
        choices=[
            "manhattan",
            "income",
            "matterhorn",
            "airports",
            "earthquakes",
            "countries",
            "rivers",
            "restless",
            "sentinel2",
            "collection",
        ],
        help="build only one showcase map",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="re-create showcase maps/datasets even if they already exist",
    )
    ap.add_argument(
        "--refresh-quakes",
        action="store_true",
        help="swap a fresh USGS 30-day feed into the earthquake datasets, then exit",
    )
    args = ap.parse_args()
    if not args.password:
        ap.error("--password or GEOLENS_ADMIN_PASSWORD is required")

    print(f"Logging in to {args.base_url} as {args.username}...")
    api = Api.login(args.base_url, args.username, args.password)

    if args.refresh_quakes:
        by_title = api.datasets_by_title()
        data, n = quake_feed()
        print(f"Refreshing {n} quakes into the earthquake datasets...")
        for title in (
            "Recent Earthquakes (M4.5+, last 30 days)",
            "Recent Earthquakes - Heatmap source",
        ):
            if title not in by_title:
                print(f"  [skip] no dataset titled {title!r}")
                continue
            api.reupload_geojson(by_title[title], "recent_quakes.geojson", data)
            print(f"  refreshed: {title}")
        return 0

    fns = {
        "manhattan": build_manhattan,
        "income": build_income,
        "matterhorn": build_matterhorn,
        "airports": build_airports,
        "earthquakes": build_earthquakes,
        "countries": build_countries,
        "rivers": build_rivers,
        "restless": build_restless_earth,
        "sentinel2": build_sentinel2,
        "collection": build_collection,
    }

    built = {}
    try:
        if args.only:
            builders = [(args.only, fns[args.only])]
        else:
            builders = [
                ("manhattan", build_manhattan),
                ("income", build_income),
                ("airports", build_airports),
                ("earthquakes", build_earthquakes),
                ("countries", build_countries),
                ("rivers", build_rivers),
                # restless AFTER earthquakes + countries: it reuses their datasets.
                ("restless", build_restless_earth),
            ]
            if args.with_terrain:
                builders.append(("matterhorn", build_matterhorn))
            if args.with_sentinel2:
                builders.append(("sentinel2", build_sentinel2))
            # collection LAST: it references the datasets the others create.
            builders.append(("collection", build_collection))
        for name, fn in builders:
            result = fn(api, force=args.force)
            if result and result != "(skipped)":
                built[name] = result
            else:
                print(f"  {name}: already exists, skipped (use --force to recreate)")
    except (httpx.HTTPStatusError, RuntimeError, TimeoutError) as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        if isinstance(e, httpx.HTTPStatusError):
            print(e.response.text[:500], file=sys.stderr)
        return 1

    print("\nDone. Showcase:")
    for name, mid in built.items():
        # build_collection returns a collection id, not a map id.
        path = "collections" if name == "collection" else "maps"
        print(f"  {name:12s} {args.base_url}/{path}/{mid}")
    if not args.only and (not args.with_terrain or not args.with_sentinel2):
        extra = []
        if not args.with_terrain:
            extra.append("--with-terrain (Matterhorn 3D)")
        if not args.with_sentinel2:
            extra.append("--with-sentinel2 (Sentinel-2 true color)")
        print(f"\n(Add {' and '.join(extra)} for the remaining heroes.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
