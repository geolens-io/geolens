#!/usr/bin/env python3
"""Seed GeoLens with the marketing "showcase" maps.

Six hero maps, every one carrying capabilities no other map shows, plus a
private embed-token demo and two themed collections. All data is public and
openly licensed; every flow was verified against the live API.

  1. Restless Earth        - the composite story hero: 30 days of M4.5+ quakes
                             (size+color double-encoded, white M7+ rings) over
                             PB2002 plate boundaries SPLIT into solid colliding
                             vs DASHED spreading/sliding layers (per-layer
                             filters + line-dasharray), 900 significant
                             volcanic eruptions since 4360 BC (NCEI, layer
                             filter: VEI>=4 or 100+ deaths), glowing major
                             cities with zoom-gated labels, a zoom-adaptive
                             heatmap, and the ETOPO 2022 global relief COG
                             rendered with a server-side colormap + stretch.
  2. Manhattan             - 3D fill-extrusion at true surveyed roof height,
                             colored by CONSTRUCTION ERA (height=form,
                             age=story), over the MTA subway in official route
                             colors with ADA-coded stations that fade in past
                             z12.5 (zoom-interpolated opacity).
  3. The Matterhorn        - 3D terrain mesh + hillshade + hypsometric tint
                             from a VRT mosaic of swissALTI3D 2m lidar COGs,
                             with dashed alpine climbing routes (white-cased)
                             and labeled peaks.                [--no-terrain]
  4. Hurricane Alley       - every major (Cat 3+) Atlantic hurricane since
                             1950 from NOAA HURDAT2, per-6h-segment categorical
                             color by Saffir-Simpson, width by wind, direction
                             arrows (render_mode 'arrow'), line-center storm
                             name labels.
  5. Everything That Fell  - all ~32k located meteorite landings; SERVER-SIDE
     From the Sky            cluster tiles (the >5000-point tier, with
                             fix(#403) attribute projection) - count-graded
                             cluster bubbles over mass-graded circles with
                             Fell/Found categorical color and popups.
  6. New York From Orbit   - recent low-cloud Sentinel-2 true-color COGs
                             imported BY REFERENCE from the Element84 STAC API
                             (zero download; Titiler needs S3 egress at view
                             time).                          [--no-sentinel2]

  Catalog-only datasets (no map; fuel for the AI + search demos): World
  Countries, NY income by county (the scripted AI-styling canvas - ask the AI
  to build the choropleth live), and a summary-LESS admin-1 dataset for the
  AI metadata-generation demo.

  Collections: "Restless Planet" (physical earth) and "Human World" (built
  world), plus the Private Embed Demo (X-Embed-Token over a private dataset).

Maintenance: --refresh-quakes re-downloads the USGS feed and swaps it into the
two earthquake datasets in place (map styles/IDs untouched), then exits. Run it
on the demo every week or two or "last 30 days" quietly goes stale.

Upgrading an existing instance: run with --prune to delete the retired
first-generation showcase maps/datasets (see RETIRED_* below), then seed.

Requires: pip install httpx

GOTCHAS this script encodes (learned the hard way, all verified live):
  * A plain GeoJSON URL is NOT a "service" - the service connector only takes
    WFS / ArcGIS Feature Service / OGC API Features. DOWNLOAD + /ingest/upload.
  * Socrata serialises numbers as STRINGS ("53.84"); coerce numeric columns
    before upload or GDAL ingests them as text (breaks graduated styling).
  * GeoLens LOWERCASES column names on ingest - reference the lowercased name
    in every paint/style/filter/label/popup expression.
  * NYC height_roof is in FEET -> height_scale = 0.3048.
  * A job's terminal status is "complete" (not "completed").
  * Map camera is set via PUT /maps/{id}; bearing must be within [-180, 180].
  * A VRT mosaic does NOT inherit is_dem - PATCH it or terrain won't engage.
    Conversely a single-band elevation raster MAY be auto-flagged is_dem on
    ingest, and colormap/stretch DO NOT apply to DEMs (they render terrainrgb)
    - so ETOPO is explicitly PATCHed to is_dem=false after ingest.
  * The live viewer draws LOWER sort_order ON TOP (inverse of backend order).
  * paint may contain ONLY real MapLibre keys plus the documented '_'-prefixed
    builder aliases (_colormap, _stretch, _pmin, _pmax, _sigma, _hypso-enabled,
    _hypso-ramp, _height_column, ...). Any other '_key' is a 422. The server
    moves the aliases into style_config.builder (snake_case) on save.
  * render_mode lives in style_config and COEXISTS with style_config.mode.
    Valid: cluster | heatmap | symbol | arrow | terrain | hillshade | image.
    It is NOT validated server-side - a typo silently no-ops.
  * Clustering: <=5000 features uses a client GeoJSON source; ABOVE 5000 the
    viewer automatically switches to server-side cluster MVT tiles - large
    datasets cluster fine. Cluster knobs are snake_case in style_config.builder
    (cluster_radius, cluster_max_zoom, cluster_color, cluster_color_ramp, ...).
    Layer `filter` is NOT applied to cluster bubbles (by design, #394).
  * Per-layer zoom gating: do NOT persist layout._minzoom/_maxzoom - MapLibre
    addLayer validation rejects unknown layout properties, which crashes the
    whole layer on the viewer reload path (verified live 2026-07-04). Use a
    zoom-interpolated *-opacity expression instead (stations layer below).
  * Layer filters use the canonical grammar: comparisons over ['get', f]
    (numeric ones may wrap in to-number), ['in', ['get', f],
    ['literal', [...]]] for membership. Legacy bare-field 'in' is a 422.
  * label_config keys are camelCase (column, fontSize, minZoom, placement:
    point|line|line-center, textAnchor, textOffset, haloColor, haloWidth,
    allowOverlap). text-field is a SINGLE column - precompute display strings
    at ingest when composition is needed.
  * popup_config = {enabled, expression: '{col} ...' title template,
    visible_fields: [...]}. Heatmap layers never get popups or labels.
  * A line + a wider casing under it = TWO LAYERS on the SAME dataset
    (map-sync dedupes the tile source per dataset).
  * Sentinel-2 by-reference import is POST /api/services/stac/import (remote,
    zero download) - NOT the manifest raster_cog path (that downloads; used
    deliberately for the ETOPO + swissALTI3D ingests). Query Element84
    directly with httpx; the backend /search proxy 502s (SSRF IP-pin).
  * Embed tokens are per-MAP snapshots of the map's layer datasets at mint
    time; add the layer BEFORE minting. A private dataset cannot get a public
    share URL, so the embed demo keeps its map private.
  * Overpass rejects requests without a User-Agent (HTTP 406).
  * Any column referenced by style_config.column, paint/filter ['get', ...],
    label_config.column or popup fields is auto-opted into vector tiles at
    low zoom (cols=) - no dataset tile_columns tuning needed.
"""

import argparse
import csv
import io
import json
import os
import re
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
# MTA open data (NY State portal). Lines = one MultiLineString per service;
# stations carry ADA flags, structure type and served routes.
MTA_LINES = "https://data.ny.gov/resource/s692-irgq.geojson?$limit=60"
MTA_STATIONS = "https://data.ny.gov/resource/39hk-dx4f.geojson?$limit=600"
USDA_INCOME = (
    "https://gisportal.ers.usda.gov/server/rest/services/Rural_Atlas_Data/Income/"
    "MapServer/0/query?where=State%3D%27NY%27"
    "&outFields=County,State,Median_HH_Inc_ACS,PerCapitaInc"
    "&returnGeometry=true&outSR=4326&f=geojson"
)
# swissALTI3D regional extent for the Matterhorn 3D-terrain showcase.
# A larger DEM footprint moves the MapLibre 3D-terrain "pedestal" (the wall
# where the mesh drops to the -10000 m out-of-coverage void) off-screen so the
# camera can roam the massif. Tile count scales with area (~62 tiles here);
# each ~1 km tile is a separate download + ingest job.
SWISSALTI_BBOX = "7.61,45.94,7.72,46.01"
SWISSALTI_STAC = (
    "https://data.geo.admin.ch/api/stac/v1/collections/"
    f"ch.swisstopo.swissalti3d/items?bbox={SWISSALTI_BBOX}&limit=100"
)
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
NE_ADMIN1 = NE_BASE + "ne_50m_admin_1_states_provinces.geojson"
# PB2002 plate-boundary steps (Peter Bird 2003, via Hugo Ahlenius/Nordpil; the
# *steps* file - not boundaries - carries per-segment STEPCLASS + velocity).
PB2002_STEPS = (
    "https://raw.githubusercontent.com/fraxen/tectonicplates/master/GeoJSON/"
    "PB2002_steps.json"
)
# NOAA NCEI Significant Volcanic Eruptions (4360 BC-present; US-gov public
# domain - deliberately used INSTEAD of Smithsonian GVP's WFS, whose terms of
# use are non-commercial). Paginated JSON API, 200 items/page.
NCEI_VOLCANOES = (
    "https://www.ngdc.noaa.gov/hazel/hazard-service/api/v1/volcanoes"
    "?itemsPerPage=200&page={page}"
)
# NOAA NHC HURDAT2 Atlantic best-track database (plain text, public domain).
# Filename embeds the release date - update when NHC cuts a new revision.
HURDAT2_ATLANTIC = "https://www.nhc.noaa.gov/data/hurdat/hurdat2-1851-2024-040425.txt"
# NASA / Meteoritical Society meteorite landings. NOTE: the old Socrata
# endpoint (data.nasa.gov/resource/gh4g-9sfh) is DEAD; this is the current
# post-migration home.
METEORITES_CSV = (
    "https://data.nasa.gov/docs/legacy/meteorite_landings/Meteorite_Landings.csv"
)
# NOAA NCEI ETOPO 2022 global relief (60 arc-second, ice surface; ~466 MB
# GeoTIFF). Ingested via the manifest raster_cog path: the server downloads
# it during the manifest/apply REQUEST (no client upload), then converts to
# COG in the worker job.
ETOPO_2022 = (
    "https://www.ngdc.noaa.gov/mgg/global/relief/ETOPO2022/data/60s/"
    "60s_surface_elev_gtif/ETOPO_2022_v1_60s_N90W180_surface.tif"
)
# Element84 Earth Search STAC (sentinel-2-l2a true-color COGs, by reference).
SENTINEL_STAC = "https://earth-search.aws.element84.com/v1"
SENTINEL_BBOX = [-74.30, 40.55, -73.65, 41.00]  # NYC metro (W, S, E, N)

# Official MTA route colors (hardcoded - the service feed carries no colors).
MTA_ROUTE_COLORS = {
    "1": "#EE352E",
    "2": "#EE352E",
    "3": "#EE352E",
    "4": "#00933C",
    "5": "#00933C",
    "6": "#00933C",
    "7": "#B933AD",
    "A": "#0039A6",
    "C": "#0039A6",
    "E": "#0039A6",
    "B": "#FF6319",
    "D": "#FF6319",
    "F": "#FF6319",
    "M": "#FF6319",
    "G": "#6CBE45",
    "J": "#996633",
    "Z": "#996633",
    "L": "#A7A9AC",
    "N": "#FCCC0A",
    "Q": "#FCCC0A",
    "R": "#FCCC0A",
    "W": "#FCCC0A",
    # The feed's shuttles are SF/ST/SR (no bare "S" service exists) and the
    # Lexington express variant is "5 Peak" (verified against the live feed).
    "S": "#808183",
    "SF": "#808183",
    "ST": "#808183",
    "SR": "#808183",
    "5 Peak": "#00933C",
    "SIR": "#0078C6",
}

# --- first-generation showcase content replaced by this script ----------------
# `--prune` deletes these BY EXACT NAME/TITLE before seeding. Maps first (frees
# layer references), then datasets, then collections.

RETIRED_MAPS = [
    "Manhattan Skyline - Real Roof Heights",
    "New York Income by County",
    "World Airports",
    "Recent Earthquakes",
    "World Countries",
    "World Rivers",
    "Restless Earth - 30 Days of Quakes and the Cities Nearby",
    "The Matterhorn - swissALTI3D 3D Terrain",
    "Sentinel-2 True Color - NYC",
    "Private Embed Demo",
]
RETIRED_DATASETS = [
    "World Airports (large + medium, scheduled)",
    "World Rivers & Lake Centerlines (Natural Earth 10m)",
    "World Rivers - Casing",
    "World Populated Places (Natural Earth 1:50m)",
    "World Ports (Natural Earth 1:10m)",
    "World Lakes (Natural Earth 1:50m)",
    "States & Provinces (Admin-1, Natural Earth 1:50m)",
    "Matterhorn Route Casing",
    "Private Embed Demo - VIP Sites",
]
RETIRED_COLLECTIONS = ["Discover the World"]


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

    def poll(self, job_id: str, timeout: int = 300) -> dict:
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
        timeout: int = 300,
    ) -> str:
        job = self.upload_geojson(name, data)
        self.preview(job)
        self.commit(job, title, summary, visibility=visibility)
        return self.poll(job, timeout=timeout)["dataset_id"]

    def reupload_geojson(self, dataset_id: str, name: str, data: bytes) -> None:
        """Swap a dataset's data in place (upload -> preview -> commit -> poll).

        NOTE: on instances with a max_datasets_per_user override (the demo),
        reupload is quota-gated like upload - raise the quota first.
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

    def list_maps(self) -> dict[str, str]:
        """Map name -> id from the catalog (up to 200)."""
        r = self.client.get(f"{self.base}/api/maps?limit=200", headers=self.h)
        r.raise_for_status()
        data = r.json()
        return {m["name"]: m["id"] for m in data.get("maps", data.get("items", []))}

    def list_datasets_full(self) -> list[dict]:
        """All datasets, PAGINATED - this seeder alone creates ~85 datasets
        (62 DEM tiles + vectors + scenes), and a single limit=200 page would
        silently hide older titles once an instance crosses 200, breaking
        every title-based reuse/refresh path."""
        out: list[dict] = []
        skip = 0
        while True:
            r = self.client.get(
                f"{self.base}/api/datasets?limit=200&skip={skip}", headers=self.h
            )
            r.raise_for_status()
            d = r.json()
            page = d.get("datasets", d.get("items", []))
            out.extend(page)
            total = d.get("total", len(out))
            if not page or len(out) >= total:
                return out
            skip += len(page)

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

    def dataset_record_id(self, dataset_id: str) -> str:
        # Keywords hang off the catalog RECORD, not the dataset, and the two ids
        # differ - resolve the parent record_id from the dataset detail.
        r = self.client.get(f"{self.base}/api/datasets/{dataset_id}", headers=self.h)
        r.raise_for_status()
        return r.json()["record_id"]

    def existing_keywords(self, record_id: str) -> set[str]:
        r = self.client.get(
            f"{self.base}/api/records/{record_id}/keywords/", headers=self.h
        )
        r.raise_for_status()
        return {k["keyword"] for k in r.json().get("keywords", [])}

    def add_keyword(self, record_id: str, keyword: str) -> None:
        # One keyword per POST (KeywordCreate); keyword_type "theme" matches the
        # ISO MD_KeywordTypeCode default for free-text subject tags.
        r = self.client.post(
            f"{self.base}/api/records/{record_id}/keywords/",
            headers=self.h,
            json={"keyword": keyword, "keyword_type": "theme"},
        )
        r.raise_for_status()

    def delete_map(self, map_id: str) -> None:
        r = self.client.delete(f"{self.base}/api/maps/{map_id}", headers=self.h)
        r.raise_for_status()

    def delete_dataset(self, dataset_id: str, title: str) -> None:
        # DELETE requires the exact title as a confirmation body.
        r = self.client.request(
            "DELETE",
            f"{self.base}/api/datasets/{dataset_id}",
            headers=self.h,
            json={"confirm_title": title},
        )
        r.raise_for_status()

    def delete_collection(self, collection_id: str) -> None:
        r = self.client.delete(
            f"{self.base}/api/catalog/collections/{collection_id}", headers=self.h
        )
        r.raise_for_status()

    def visibility_check(self, map_id: str) -> dict:
        r = self.client.get(
            f"{self.base}/api/maps/{map_id}/visibility-check/", headers=self.h
        )
        r.raise_for_status()
        return r.json()

    def manifest_apply(self, manifest: dict) -> list:
        # The manifest endpoint downloads each remote source INSIDE this
        # request (staging happens before the response, not in the worker),
        # so a 466 MB ETOPO pull or 62 sequential DEM tiles must fit in the
        # HTTP timeout - give it a long one.
        r = self.client.post(
            f"{self.base}/api/ingest/manifest/apply",
            headers=self.h,
            json=manifest,
            timeout=httpx.Timeout(2400.0, connect=30.0),
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
        """Map dataset title -> id.

        fix(#389): /api/datasets orders newest-first and titles are NOT unique
        - a --force reseed creates fresh datasets alongside same-titled
        predecessors. Keep the FIRST (newest) match so lookups resolve to the
        freshly created dataset, not a stale duplicate.
        """
        out: dict[str, str] = {}
        for x in self.list_datasets_full():
            out.setdefault(x["title"], x["id"])
        return out

    def dataset_columns(self, dataset_id: str) -> set:
        """Column names of a dataset (from the detail endpoint's column_info)."""
        r = self.client.get(f"{self.base}/api/datasets/{dataset_id}", headers=self.h)
        r.raise_for_status()
        return {c["name"] for c in (r.json().get("column_info") or [])}

    def dataset_feature_count(self, dataset_id: str) -> int | None:
        r = self.client.get(f"{self.base}/api/datasets/{dataset_id}", headers=self.h)
        r.raise_for_status()
        return r.json().get("feature_count")

    def collections_by_name(self) -> dict[str, str]:
        """Map collection name -> id (name is UNIQUE in the catalog model)."""
        # Trailing slash required (redirect_slashes=False).
        r = self.client.get(f"{self.base}/api/catalog/collections/", headers=self.h)
        r.raise_for_status()
        return {c["name"]: c["id"] for c in r.json().get("collections", [])}

    def create_collection(self, name: str, description: str) -> str:
        # Collections have NO visibility/title/summary - only name (unique) +
        # description.
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
    r = httpx.get(
        url,
        follow_redirects=True,
        timeout=180.0,
        headers={"User-Agent": "geolens-showcase-seeder/2.0"},
    )
    r.raise_for_status()
    return r.content


def step_expr(column: str, breaks: list, colors: list) -> list:
    """A MapLibre `step` expression (N colors, N-1 breaks) over a numeric column."""
    expr = ["step", ["to-number", ["get", column], 0], colors[0]]
    for b, c in zip(breaks, colors[1:]):
        expr += [b, c]
    return expr


def warn_if_hidden_layers(api: Api, map_id: str, name: str) -> None:
    """Self-check: a public showcase map must not reference non-public data."""
    try:
        v = api.visibility_check(map_id)
    except httpx.HTTPStatusError:
        return
    if v.get("has_non_public"):
        print(
            f"  ! WARNING: {name} references non-public datasets: "
            f"{v.get('non_public_datasets')}"
        )


# --- data feeds ----------------------------------------------------------------


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


def volcano_feed() -> tuple[bytes, int]:
    """NCEI Significant Volcanic Eruptions (4360 BC-present) as GeoJSON points.

    ~900 eruptions that caused fatalities/damage, VEI>=6, a tsunami or a
    significant quake. Negative years are BCE; year_label is precomputed for
    popups (labels/popups take a single column - compose at ingest).
    """
    feats = []
    page = 1
    while True:
        d = json.loads(fetch(NCEI_VOLCANOES.format(page=page)))
        for it in d.get("items", []):
            lat, lng = it.get("latitude"), it.get("longitude")
            if lat is None or lng is None:
                continue
            year = it.get("year")
            year_label = (
                f"{abs(year)} BC" if isinstance(year, int) and year < 0 else str(year)
            )
            feats.append(
                {
                    "type": "Feature",
                    "properties": {
                        "name": it.get("name"),
                        "country": it.get("country"),
                        "year": year,
                        "year_label": year_label,
                        "vei": it.get("vei"),
                        "deaths": it.get("deathsTotal"),
                        "damage_musd": it.get("damageMillionsDollarsTotal"),
                        "morphology": it.get("morphology"),
                        "elevation_m": it.get("elevation"),
                    },
                    "geometry": {"type": "Point", "coordinates": [lng, lat]},
                }
            )
        if page >= int(d.get("totalPages", 1)):
            break
        page += 1
    fc = {"type": "FeatureCollection", "features": feats}
    return json.dumps(fc).encode(), len(feats)


_SSHS = [
    (137, "Cat 5"),
    (113, "Cat 4"),
    (96, "Cat 3"),
    (83, "Cat 2"),
    (64, "Cat 1"),
    (34, "TS"),
]


def _sshs(wind_kt: int) -> str:
    for floor, label in _SSHS:
        if wind_kt >= floor:
            return label
    return "TD"


def hurdat2_feed(min_year: int = 1950, min_peak_kt: int = 96) -> tuple[bytes, int, int]:
    """NOAA HURDAT2 Atlantic best tracks -> per-6h-SEGMENT LineString GeoJSON.

    Keeps storms from `min_year` whose peak intensity reached `min_peak_kt`
    (96 kt = Cat 3, "major hurricane"). Each segment carries the storm name,
    season, status, wind, pressure and Saffir-Simpson category AT that leg, so
    a single track changes color/width as the storm intensifies and decays.
    Returns (geojson_bytes, n_storms, n_segments).
    """
    txt = fetch(HURDAT2_ATLANTIC).decode("ascii", "replace")
    storms: list[tuple[str, int, list[dict]]] = []
    name, year, fixes = "", 0, []
    for line in txt.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if not parts or not parts[0]:
            continue
        if parts[0][:2] in ("AL", "EP", "CP") and len(parts[0]) == 8:
            if fixes:
                storms.append((name, year, fixes))
            name = parts[1].title() if parts[1] != "UNNAMED" else "Unnamed"
            year = int(parts[0][4:8])
            fixes = []
            continue
        if len(parts) < 9:
            continue
        try:
            lat = float(parts[4][:-1]) * (1 if parts[4][-1] == "N" else -1)
            lng = float(parts[5][:-1]) * (1 if parts[5][-1] in ("E",) else -1)
            wind = int(parts[6])
        except (ValueError, IndexError):
            continue
        pres = int(parts[7]) if parts[7].lstrip("-").isdigit() else -999
        fixes.append(
            {
                "date": parts[0],
                "landfall": parts[2] == "L",
                "status": parts[3],
                "lat": lat,
                "lng": lng,
                "wind": wind,
                "pres": None if pres <= 0 else pres,
            }
        )
    if fixes:
        storms.append((name, year, fixes))

    feats, n_storms = [], 0
    for name, year, fixes in storms:
        if year < min_year or not fixes:
            continue
        if max(f["wind"] for f in fixes) < min_peak_kt:
            continue
        n_storms += 1
        for a, b in zip(fixes, fixes[1:]):
            # Guard against bogus jumps (there are none in the Atlantic basin,
            # but a malformed row would otherwise draw a line across the map).
            if abs(a["lng"] - b["lng"]) > 90 or abs(a["lat"] - b["lat"]) > 30:
                continue
            feats.append(
                {
                    "type": "Feature",
                    "properties": {
                        "name": name,
                        "season": year,
                        "month": int(a["date"][4:6]),
                        "status": a["status"],
                        "wind_kt": a["wind"],
                        "pressure_mb": a["pres"],
                        "category": _sshs(a["wind"]),
                        "landfall": 1 if (a["landfall"] or b["landfall"]) else 0,
                    },
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[a["lng"], a["lat"]], [b["lng"], b["lat"]]],
                    },
                }
            )
    fc = {"type": "FeatureCollection", "features": feats}
    return json.dumps(fc).encode(), n_storms, len(feats)


def meteorite_feed() -> tuple[bytes, int]:
    """NASA/Meteoritical Society meteorite landings CSV -> GeoJSON points.

    Drops rows without coordinates, the known (0,0) bogus-location rows, and
    out-of-range positions (the CSV includes Meridiani Planum - found on MARS
    by the Opportunity rover - at reclong 354.5); parses year out of the
    US-style timestamp; precomputes mass_kg (mass is grams upstream).

    The FULL ~32k located set ships deliberately: above 5,000 features the
    viewer switches to server-side cluster tiles, and fix(#403) made that
    path project the cols=-requested attribute columns onto unclustered
    features - so Fell/Found colors, mass-graded radii and popups work past
    cluster max zoom. Requires a backend at or after that fix.
    """
    rows = csv.DictReader(io.StringIO(fetch(METEORITES_CSV).decode("utf-8-sig")))
    feats = []
    for r in rows:
        try:
            lat, lng = float(r["reclat"]), float(r["reclong"])
        except (TypeError, ValueError, KeyError):
            continue
        if (lat, lng) == (0.0, 0.0):
            continue
        if abs(lat) > 90 or abs(lng) > 180:
            continue  # Mars rocks and other off-planet coordinates
        m = re.search(r"\b(\d{4})\b", r.get("year") or "")
        year = int(m.group(1)) if m else None
        if year is not None and not (600 <= year <= 2026):
            year = None
        try:
            mass_g = float(r.get("mass (g)") or "")
        except ValueError:
            mass_g = None
        feats.append(
            {
                "type": "Feature",
                "properties": {
                    "name": r.get("name"),
                    "recclass": r.get("recclass"),
                    "mass_kg": round(mass_g / 1000.0, 3) if mass_g else None,
                    "year": year,
                    "fall": r.get("fall"),
                },
                "geometry": {"type": "Point", "coordinates": [lng, lat]},
            }
        )
    fc = {"type": "FeatureCollection", "features": feats}
    return json.dumps(fc).encode(), len(feats)


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
            headers={"User-Agent": "geolens-showcase-seeder/2.0"},
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


def fetch_swissalti_tiles() -> dict:
    """Return {tag: href} for every swissALTI3D 2m (EPSG:2056, 2024) COG tile
    intersecting SWISSALTI_BBOX, following STAC pagination.

    The swisstopo STAC API caps a page at ~100 features, so a regional AOI spans
    several pages - follow rel="next" until exhausted. Each 1 km tile exposes
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
            (
                link["href"]
                for link in page.get("links", [])
                if link.get("rel") == "next"
            ),
            None,
        )
    return tiles


# --- idempotency helpers -------------------------------------------------------


def _map_exists(api: Api, name: str) -> bool:
    return name in api.list_maps()


def _get_or_ingest(
    api: Api,
    by_title: dict,
    title: str,
    filename: str,
    data_fn,
    summary: str,
    force: bool = False,
    timeout: int = 300,
) -> str:
    """Reuse a dataset by title, or ingest it from data_fn() (bytes)."""
    if not force and title in by_title:
        print(f"  [reuse] {title}")
        return by_title[title]
    data = data_fn()
    print(f"  ingesting {title} ({len(data) // 1024} KB)...")
    ds = api.ingest_geojson(filename, data, title, summary, timeout=timeout)
    by_title[title] = ds
    return ds


# --- prune ----------------------------------------------------------------------


def prune(api: Api) -> None:
    """Delete the retired first-generation showcase content by exact name."""
    print("\n[prune] removing retired first-generation showcase content")
    maps = api.list_maps()
    for name in RETIRED_MAPS:
        if name in maps:
            api.delete_map(maps[name])
            print(f"  - map: {name}")
    for d in api.list_datasets_full():
        if d["title"] in RETIRED_DATASETS:
            try:
                api.delete_dataset(d["id"], d["title"])
                print(f"  - dataset: {d['title']}")
            except httpx.HTTPStatusError as e:
                print(f"  ! could not delete dataset {d['title']}: {e}")
    colls = api.collections_by_name()
    for name in RETIRED_COLLECTIONS:
        if name in colls:
            try:
                api.delete_collection(colls[name])
                print(f"  - collection: {name}")
            except httpx.HTTPStatusError as e:
                print(f"  ! could not delete collection {name}: {e}")


# --- showcase builders -----------------------------------------------------------


def build_catalog(api: Api, force: bool = False) -> str:
    """Catalog-only datasets - no maps. These exist to fuel the AI demos:

    * World Countries: rich numeric/categorical columns for AI add_layer /
      query_data ("GDP of Japan?", "color countries by income group").
    * NY income by county: the scripted AI-styling canvas - ask the AI to
      build the choropleth live instead of shipping a static one.
    * Admin-1 states/provinces committed SUMMARY-LESS: raw material for the
      AI metadata-generation demo.
    """
    print("\n[catalog] AI-demo + search-breadth datasets (no maps)")
    by_title = api.datasets_by_title()

    def countries_bytes() -> bytes:
        fc = json.loads(fetch(NE_COUNTRIES))
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
        for feat in fc["features"]:
            p = feat["properties"]
            feat["properties"] = {k: p.get(k) for k in keep}
        return json.dumps(fc).encode()

    _get_or_ingest(
        api,
        by_title,
        "World Countries (Natural Earth 1:50m)",
        "world_countries.geojson",
        countries_bytes,
        "All world countries with population, GDP, economy class and income "
        "group. Source: Natural Earth admin-0, 1:50m (public domain).",
        force=force,
    )
    _get_or_ingest(
        api,
        by_title,
        "New York Median Household Income by County",
        "ny_income.geojson",
        lambda: fetch(USDA_INCOME),
        "Median household income (2017-21 ACS) for all 62 NY counties. "
        "Source: USDA ERS Atlas of Rural & Small-Town America.",
        force=force,
    )
    if force or "World States & Provinces (Natural Earth 1:50m)" not in by_title:
        # Intentionally blank summary: raw material for the AI metadata demo.
        print(
            "  ingesting World States & Provinces (summary-less, AI-metadata demo)..."
        )
        api.ingest_geojson(
            "world_admin1.geojson",
            fetch(NE_ADMIN1),
            "World States & Provinces (Natural Earth 1:50m)",
            "",
        )
    else:
        print("  [reuse] World States & Provinces (Natural Earth 1:50m)")
    return "(catalog)"


def build_restless_earth(
    api: Api, force: bool = False, with_oceans: bool = True
) -> str:
    """The world hero: quakes + eruptions + plate boundaries + exposed cities,
    on the actual relief of the planet.

    Style-spec notes (all verified live):
      * zoom+data composite expressions (interpolate-by-zoom whose outputs are
        step-by-property) scale circles smoothly from world to city view.
      * M7+ quakes get a white highlight ring via a step on circle-stroke-*.
      * The plate boundaries render as TWO layers off ONE dataset, split by
        per-layer `filter`: colliding boundaries solid, spreading/sliding
        boundaries dashed (line-dasharray).
      * The volcano layer's `filter` keeps the full 900-eruption dataset
        Ask-AI-queryable while the MAP shows only the consequential ones.
      * Heatmap + relief stay OUT of the legend (context layers).
      * ETOPO is PATCHed is_dem=false so the server-side colormap + stretch
        applies (DEM-flagged rasters render terrainrgb and ignore colormaps).
    """
    name = "Restless Earth"
    if not force and _map_exists(api, name):
        print(f"  [skip] {name} already exists")
        return "(skipped)"
    print("\n[restless] Restless Earth (quakes + volcanoes + plates + relief)")
    by_title = api.datasets_by_title()

    # --- earthquakes (two datasets: circles + heatmap source) -----------------
    quakes_title = "Recent Earthquakes (M4.5+, last 30 days)"
    heat_title = "Recent Earthquakes - Heatmap source"
    if not force and quakes_title in by_title and heat_title in by_title:
        print("  [reuse] earthquake datasets")
        # Instances seeded before the feed enrichment carry quake datasets
        # with only mag/place/time - detect and refresh in place (fix #389).
        if "depth_km" not in api.dataset_columns(by_title[quakes_title]):
            print("  quake datasets predate the enriched feed - refreshing...")
            qdata, qn = quake_feed()
            api.reupload_geojson(by_title[quakes_title], "recent_quakes.geojson", qdata)
            api.reupload_geojson(
                by_title[heat_title], "recent_quakes_heat.geojson", qdata
            )
            print(f"  refreshed {qn} quakes into both datasets")
    else:
        qdata, qn = quake_feed()
        print(f"  ingesting {qn} quakes (x2: circles + heatmap)...")
        # GeoLens renders ONE MapLibre layer per dataset; the graduated-circle
        # layer and the heatmap layer need the same geometry as TWO datasets.
        by_title[quakes_title] = api.ingest_geojson(
            "recent_quakes.geojson",
            qdata,
            quakes_title,
            "Significant earthquakes (M4.5+) from the last 30 days: magnitude, "
            "depth, felt reports, tsunami flag and USGS significance. "
            "Source: USGS Earthquake Hazards Program (public domain).",
        )
        by_title[heat_title] = api.ingest_geojson(
            "recent_quakes_heat.geojson",
            qdata,
            heat_title,
            "Same M4.5+ quake geometry as the graduated-circle dataset, ingested "
            "separately so MapLibre renders it as its own heatmap layer.",
        )

    # --- plate boundaries ------------------------------------------------------
    plates_title = "Tectonic Plate Boundaries (PB2002)"

    def plates_bytes() -> bytes:
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
        return json.dumps(fc).encode()

    plates_ds = _get_or_ingest(
        api,
        by_title,
        plates_title,
        "plate_boundaries.geojson",
        plates_bytes,
        "Tectonic plate boundary segments classified as subduction zone, "
        "convergent, divergent or transform, with relative plate velocity "
        "(mm/yr). Source: Peter Bird (2003) PB2002 via Nordpil (open data).",
        force=force,
    )

    # --- major cities ------------------------------------------------------------
    cities_title = "World Major Cities (500k+)"

    def cities_bytes() -> bytes:
        fc = json.loads(fetch(NE_PLACES))
        feats = []
        for feat in fc["features"]:
            p = feat["properties"]
            pop = p.get("POP_MAX") or p.get("pop_max") or 0
            if not isinstance(pop, (int, float)) or pop < 500000:
                continue
            fcla = p.get("FEATURECLA") or p.get("featurecla") or ""
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
        return json.dumps({"type": "FeatureCollection", "features": feats}).encode()

    cities_ds = _get_or_ingest(
        api,
        by_title,
        cities_title,
        "world_major_cities.geojson",
        cities_bytes,
        "Cities with 500k+ inhabitants: name, country, population, capital "
        "flag and timezone. Slimmed from Natural Earth populated places "
        "1:50m (public domain).",
        force=force,
    )

    # --- volcanic eruptions -------------------------------------------------------
    volcano_title = "Significant Volcanic Eruptions (NCEI, 4360 BC-present)"

    def volcano_bytes() -> bytes:
        data, n = volcano_feed()
        print(f"  ({n} eruptions from NCEI)")
        return data

    volcano_ds = _get_or_ingest(
        api,
        by_title,
        volcano_title,
        "significant_eruptions.geojson",
        volcano_bytes,
        "Volcanic eruptions since 4360 BC that caused deaths or major damage, "
        "reached VEI 6+, or triggered a tsunami/quake: year, VEI, deaths, "
        "damage and volcano morphology. Source: NOAA NCEI Significant "
        "Volcanic Eruptions Database (public domain).",
        force=force,
    )

    # --- ETOPO 2022 global relief (optional; worker-side ~466 MB download) --------
    etopo_ds = None
    etopo_title = "ETOPO 2022 Global Relief (60 arc-second)"
    if with_oceans:
        if not force and etopo_title in by_title:
            print("  [reuse] ETOPO 2022 global relief")
            etopo_ds = by_title[etopo_title]
        else:
            print("  registering ETOPO 2022 via manifest (server pulls ~466 MB)...")
            results = api.manifest_apply(
                {
                    "manifest_version": "1",
                    "catalog": {"title": "ETOPO 2022 Global Relief"},
                    "datasets": [
                        {
                            "key": "etopo-2022-60s",
                            "title": etopo_title,
                            "sources": [
                                {
                                    "type": "raster_cog",
                                    "uri": ETOPO_2022,
                                    "format": "geotiff",
                                }
                            ],
                            "metadata": {
                                "crs": "EPSG:4326",
                                "organization": "NOAA NCEI",
                                "license": "US public domain (cite NOAA NCEI)",
                                "tags": ["bathymetry", "relief", "etopo", "global"],
                            },
                            # "published" -> visibility public + record_status
                            # published; "ready" would leave the dataset
                            # PRIVATE and block publishing any map layering it.
                            "publication": {"intent": "published"},
                        }
                    ],
                    "dry_run": False,
                }
            )
            res = results[0] if results else {}
            if res.get("action") == "error":
                raise RuntimeError(f"ETOPO manifest failed: {res.get('message')}")
            if res.get("job_id"):
                etopo_ds = api.poll(res["job_id"], timeout=2400)["dataset_id"]
            else:
                etopo_ds = res.get("dataset_id")
        if etopo_ds:
            # Single-band elevation may be auto-flagged is_dem on ingest, and
            # colormap/stretch do NOT apply to DEMs - force it off so the
            # viridis relief render engages. Also force public/published: this
            # heals instances that ingested ETOPO under an intent:"ready"
            # manifest (which left it private and blocked map publishing).
            api.patch_dataset(
                etopo_ds,
                is_dem=False,
                visibility="public",
                record_status="published",
            )

    # --- the map --------------------------------------------------------------------
    map_id = api.create_map(
        name,
        "Thirty days of M4.5+ earthquakes and 6,000 years of deadly volcanic "
        "eruptions, on the tectonic plate boundaries that spawn them - solid "
        "where plates collide, dashed where they spread and slide - over the "
        "real relief of the planet (ETOPO 2022). Watch the mid-Atlantic ridge "
        "line up with the dashed divergent boundary. Click anything, or open "
        "Ask AI: which quakes triggered tsunami warnings? What was the "
        "deadliest eruption? Sources: USGS, NOAA NCEI, PB2002 (Bird 2003), "
        "Natural Earth.",
    )

    def mag_step(v0, v1, v2, v3):
        return ["step", ["to-number", ["get", "mag"], 0], v0, 5.0, v1, 6.0, v2, 7.0, v3]

    # Magnitude double-encoded: size AND color (the ramp deliberately matches
    # the heatmap stops so the two quake layers read as one visual system).
    quake_colors = ["#fecc5c", "#fd8d3c", "#f03b20", "#bd0026"]
    api.add_layer(
        map_id,
        {
            "dataset_id": by_title[quakes_title],
            "sort_order": 0,
            "opacity": 1.0,
            "display_name": "Earthquakes (last 30 days, by magnitude)",
            "paint": {
                "circle-radius": [
                    "interpolate",
                    ["linear"],
                    ["zoom"],
                    1.2,
                    mag_step(2.5, 4.5, 7, 11),
                    6,
                    mag_step(5, 9, 14, 22),
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
    # Volcanoes: white-hot vents with an ember ring, sized by VEI. The layer
    # FILTER shows only consequential eruptions (VEI>=4 or 100+ deaths) while
    # the full 900-event dataset stays Ask-AI-queryable.
    api.add_layer(
        map_id,
        {
            "dataset_id": volcano_ds,
            "sort_order": 1,
            "opacity": 1.0,
            "display_name": "Major eruptions (VEI 4+ or 100+ deaths)",
            "filter": [
                "any",
                [">=", ["to-number", ["get", "vei"], 0], 4],
                [">=", ["to-number", ["get", "deaths"], 0], 100],
            ],
            "paint": {
                "circle-radius": [
                    "step",
                    ["to-number", ["get", "vei"], 0],
                    3.2,
                    5,
                    4.5,
                    6,
                    6.5,
                    7,
                    9,
                ],
                "circle-color": "#fff7ed",
                "circle-opacity": 0.95,
                "circle-stroke-color": "#ea580c",
                "circle-stroke-width": 1.6,
            },
            "popup_config": {
                "enabled": True,
                "expression": "{name} - {year_label}",
                "visible_fields": [
                    "vei",
                    "deaths",
                    "damage_musd",
                    "country",
                    "morphology",
                ],
            },
        },
    )
    api.add_layer(
        map_id,
        {
            "dataset_id": cities_ds,
            "sort_order": 2,
            "opacity": 1.0,
            "display_name": "Major cities (by population)",
            "paint": {
                "circle-radius": [
                    "interpolate",
                    ["linear"],
                    ["zoom"],
                    1.5,
                    [
                        "step",
                        ["to-number", ["get", "pop_max"], 0],
                        1.6,
                        1000000,
                        2.8,
                        5000000,
                        4.5,
                        10000000,
                        6.5,
                    ],
                    6,
                    [
                        "step",
                        ["to-number", ["get", "pop_max"], 0],
                        3.5,
                        1000000,
                        6,
                        5000000,
                        9,
                        10000000,
                        13,
                    ],
                ],
                # Soft-edged silver "city lights" on the dark basemap.
                "circle-color": "#e2e8f0",
                "circle-blur": 0.35,
                "circle-opacity": [
                    "interpolate",
                    ["linear"],
                    ["zoom"],
                    1.5,
                    [
                        "case",
                        [">=", ["to-number", ["get", "pop_max"], 0], 5000000],
                        0.95,
                        0.55,
                    ],
                    4,
                    0.95,
                ],
                "circle-stroke-color": "#0b0f14",
                "circle-stroke-width": 0.5,
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
            # Zoom-gated name labels: nothing at world view, silver labels once
            # regional zoom gives them room (collision culling handles density).
            "label_config": {
                "column": "name",
                "fontSize": 11,
                "minZoom": 4,
                "textColor": "#e2e8f0",
                "haloColor": "#0b0f14",
                "haloWidth": 1.6,
                "textAnchor": "top",
                "textOffset": [0, 0.5],
                "allowOverlap": False,
            },
            "popup_config": {
                "enabled": True,
                "expression": "{name}",
                "visible_fields": ["country", "pop_max", "is_capital"],
            },
        },
    )

    # Plate boundaries: ONE dataset, TWO layers split by per-layer filter -
    # solid lines where plates collide, dashed where they spread or slide.
    def btype_width(sub, rest):
        return ["match", ["get", "boundary_type"], "subduction zone", sub, rest]

    api.add_layer(
        map_id,
        {
            "dataset_id": plates_ds,
            "sort_order": 3,
            "opacity": 1.0,
            "display_name": "Colliding boundaries (solid)",
            "filter": [
                "in",
                ["get", "boundary_type"],
                ["literal", ["subduction zone", "convergent"]],
            ],
            "paint": {
                "line-color": [
                    "case",
                    ["==", ["get", "boundary_type"], None],
                    "#94a3b8",
                    [
                        "match",
                        ["get", "boundary_type"],
                        "subduction zone",
                        "#e879f9",
                        "convergent",
                        "#c084fc",
                        "#94a3b8",
                    ],
                ],
                "line-width": [
                    "interpolate",
                    ["linear"],
                    ["zoom"],
                    1,
                    btype_width(1.6, 0.9),
                    6,
                    btype_width(3.2, 1.8),
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
                    {
                        "value": "subduction zone",
                        "color": "#e879f9",
                        "label": "Subduction zone",
                    },
                    {"value": "convergent", "color": "#c084fc", "label": "Convergent"},
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
            "dataset_id": plates_ds,
            "sort_order": 4,
            "opacity": 1.0,
            "display_name": "Spreading & sliding boundaries (dashed)",
            "filter": [
                "in",
                ["get", "boundary_type"],
                ["literal", ["divergent", "transform"]],
            ],
            "paint": {
                "line-color": [
                    "case",
                    ["==", ["get", "boundary_type"], None],
                    "#94a3b8",
                    [
                        "match",
                        ["get", "boundary_type"],
                        "divergent",
                        "#4ade80",
                        "transform",
                        "#22d3ee",
                        "#94a3b8",
                    ],
                ],
                "line-width": [
                    "interpolate",
                    ["linear"],
                    ["zoom"],
                    1,
                    1.0,
                    6,
                    2.0,
                ],
                "line-dasharray": [2.2, 1.6],
                "line-opacity": 0.85,
            },
            "layout": {"line-cap": "round", "line-join": "round"},
            "style_config": {
                "mode": "categorical",
                "column": "boundary_type",
                "ramp": "Dark2",
                "categories": [
                    {
                        "value": "divergent",
                        "color": "#4ade80",
                        "label": "Divergent (ridge/rift)",
                    },
                    {
                        "value": "transform",
                        "color": "#22d3ee",
                        "label": "Transform fault",
                    },
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
            "dataset_id": by_title[heat_title],
            "sort_order": 5,
            "opacity": 1.0,
            "display_name": "Quake intensity (heatmap)",
            "show_in_legend": False,
            "paint": {
                "heatmap-radius": [
                    "interpolate",
                    ["linear"],
                    ["zoom"],
                    0,
                    15,
                    3,
                    30,
                    6,
                    50,
                ],
                "heatmap-weight": [
                    "interpolate",
                    ["linear"],
                    ["to-number", ["get", "mag"], 0],
                    4,
                    0.1,
                    8,
                    1,
                ],
                "heatmap-intensity": [
                    "interpolate",
                    ["linear"],
                    ["zoom"],
                    0,
                    0.9,
                    6,
                    2,
                ],
                "heatmap-opacity": 0.7,
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
    if etopo_ds:
        api.add_layer(
            map_id,
            {
                "dataset_id": etopo_ds,
                "sort_order": 6,
                "opacity": 0.55,
                "display_name": "Global relief (ETOPO 2022)",
                "show_in_legend": False,
                "layer_type": "raster_geolens",
                # Server-side single-band styling: the '_'-prefixed builder
                # aliases are moved into style_config.builder on save and drive
                # colormap_name/stretch on the Titiler tile URL.
                "paint": {
                    "_colormap": "viridis",
                    "_stretch": "percentile",
                    "_pmin": 2,
                    "_pmax": 98,
                },
                "style_config": {"builder": {}},
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
    warn_if_hidden_layers(api, map_id, name)
    print(f"  -> map {map_id}")
    return map_id


def build_manhattan(api: Api, force: bool = False) -> str:
    """The city hero: 3D extrusion at TRUE surveyed height, colored by
    construction ERA (height carries the form, color carries the story), over
    the subway in official MTA route colors with ADA-coded stations.

    * Stations fade in past ~z12.5 via zoom-interpolated circle-opacity so
      the city view stays clean (layout._minzoom would crash the viewer).
    * Socrata serialises numbers as strings - height_roof, construction_year
      and the stations' ada flag are all coerced before upload.
    * Era is a precomputed STRING column: the graduated legend abbreviates
      numeric breaks (1900 -> "1.9K"), so year breaks are unreadable there.
    """
    name = "Manhattan - A Century of Skyline"
    if not force and _map_exists(api, name):
        print(f"  [skip] {name} already exists")
        return "(skipped)"
    print("\n[manhattan] Manhattan (3D by height, colored by era, + subway)")
    by_title = api.datasets_by_title()

    def buildings_bytes() -> bytes:
        fc = json.loads(fetch(NYC_BUILDINGS))
        keep_f = ["height_roof", "ground_elevation", "shape_area"]
        for feat in fc["features"]:
            p = feat["properties"]
            np = {
                "name": p.get("name"),
                "feature_code": p.get("feature_code"),
                "bin": p.get("bin"),
            }
            for k in keep_f:
                v = p.get(k)
                try:
                    np[k] = float(v) if v not in (None, "") else None
                except (TypeError, ValueError):
                    np[k] = None
            try:
                yr = int(float(p.get("construction_year")))
                np["construction_year"] = yr if 1600 <= yr <= 2026 else None
            except (TypeError, ValueError):
                np["construction_year"] = None
            # Precompute the era as a STRING column: the legend's numeric
            # formatter abbreviates graduated breaks (1900 -> "1.9K"), so a
            # year-break graduated legend is unreadable - categorical era
            # strings render verbatim.
            yr = np["construction_year"]
            if yr is None:
                era = "Unknown"
            elif yr < 1900:
                era = "Pre-1900"
            elif yr < 1930:
                era = "1900-1929"
            elif yr < 1950:
                era = "1930-1949"
            elif yr < 1980:
                era = "1950-1979"
            elif yr < 2000:
                era = "1980-1999"
            elif yr < 2015:
                era = "2000-2014"
            else:
                era = "2015+"
            np["era"] = era
            # Popup titles take a single template; precompute a display title
            # since most footprints have no building name.
            np["title"] = np["name"] or (
                f"Built {np['construction_year']}"
                if np["construction_year"]
                else "Building"
            )
            feat["properties"] = np
        # Sanity floor: the bbox normally yields ~22k buildings, but NYC Open
        # Data periodically serves a TRUNCATED snapshot mid-replace (observed
        # 2026-07-04: table capped at exactly 200,000 rows -> 3,887 in-bbox).
        # Fail loudly rather than silently seed (or overwrite) a thin skyline.
        if len(fc["features"]) < 10000:
            raise RuntimeError(
                f"NYC building feed returned only {len(fc['features'])} "
                "features (expected ~22k) - the 5zhs-2jue table is likely a "
                "truncated mid-replace snapshot; re-run the manhattan builder "
                "later"
            )
        return json.dumps(fc).encode()

    buildings_ds = _get_or_ingest(
        api,
        by_title,
        "Manhattan Building Heights",
        "manhattan_skyline.geojson",
        buildings_bytes,
        "NYC building footprints (Lower + Midtown Manhattan) with surveyed "
        "roof heights (feet) and construction year. Source: NYC Open Data "
        "(5zhs-2jue).",
        force=force,
        timeout=600,
    )
    # A --force rebuild against a REUSED pre-2026-07 dataset would miss the new
    # era/title columns; refresh in place if they are absent.
    if "era" not in api.dataset_columns(buildings_ds):
        print("  buildings dataset predates the era-color feed - refreshing...")
        api.reupload_geojson(
            buildings_ds, "manhattan_skyline.geojson", buildings_bytes()
        )

    def subway_lines_bytes() -> bytes:
        fc = json.loads(fetch(MTA_LINES))
        for feat in fc["features"]:
            p = feat["properties"]
            feat["properties"] = {
                "service": p.get("service"),
                "service_name": p.get("service_name"),
            }
        return json.dumps(fc).encode()

    lines_ds = _get_or_ingest(
        api,
        by_title,
        "NYC Subway Lines (MTA)",
        "nyc_subway_lines.geojson",
        subway_lines_bytes,
        "New York City subway service geometries, one feature per service. "
        "Source: MTA via data.ny.gov (open data, attribute MTA).",
        force=force,
    )

    def stations_bytes() -> bytes:
        fc = json.loads(fetch(MTA_STATIONS))
        for feat in fc["features"]:
            p = feat["properties"]
            try:
                ada = int(p.get("ada") or 0)
            except (TypeError, ValueError):
                ada = 0
            feat["properties"] = {
                "stop_name": p.get("stop_name"),
                "daytime_routes": p.get("daytime_routes"),
                "division": p.get("division"),
                "structure": p.get("structure"),
                "borough": p.get("borough"),
                "ada": ada,
            }
        return json.dumps(fc).encode()

    stations_ds = _get_or_ingest(
        api,
        by_title,
        "NYC Subway Stations (MTA)",
        "nyc_subway_stations.geojson",
        stations_bytes,
        "All 496 NYC subway stations with served routes, structure type, "
        "borough and ADA accessibility. Source: MTA via data.ny.gov (open "
        "data, attribute MTA).",
        force=force,
    )

    map_id = api.create_map(
        name,
        "Every building in Lower + Midtown Manhattan extruded to its true "
        "surveyed roof height and colored by WHEN it was built - brick-brown "
        "pre-war, steel-gray mid-century, glass-blue this millennium - with "
        "the subway threading beneath in official MTA colors and ADA-coded "
        "stations. Ask AI: what share of stations are wheelchair-accessible? "
        "Which decade built the tallest towers? Sources: NYC Open Data, MTA.",
    )
    # Era color: brick -> deco amber -> midcentury steel -> glass. The
    # extrusion companion takes its color from paint.fill-color, so the era
    # ramp carries into 3D automatically. Categorical era STRINGS (not year
    # breaks): the graduated legend abbreviates numbers (1900 -> "1.9K").
    eras = [
        ("Pre-1900", "#7c2d12"),  # brick
        ("1900-1929", "#b45309"),
        ("1930-1949", "#d97706"),  # deco
        ("1950-1979", "#94a3b8"),  # steel
        ("1980-1999", "#60a5fa"),  # blue glass
        ("2000-2014", "#22d3ee"),
        ("2015+", "#a5f3fc"),  # ice glass
    ]
    era_match: list = ["match", ["get", "era"]]
    for era_value, era_color in eras:
        era_match += [era_value, era_color]
    era_match.append("#334155")  # Unknown
    api.add_layer(
        map_id,
        {
            "dataset_id": buildings_ds,
            "sort_order": 2,
            "opacity": 1.0,
            "display_name": "Buildings (3D height, colored by era)",
            "paint": {
                "fill-color": [
                    "case",
                    ["==", ["get", "era"], None],
                    "#334155",
                    era_match,
                ],
                "fill-opacity": 0.92,
            },
            "style_config": {
                "mode": "categorical",
                "column": "era",
                "ramp": "Plasma",
                "categories": [{"value": v, "color": c, "label": v} for v, c in eras],
                "builder": {
                    "height_column": "height_roof",
                    "height_scale": 0.3048,  # feet -> meters
                    "extrusion_min_zoom": 13,
                    "extrusion_opacity": 0.92,
                    "stroke_disabled": True,
                },
            },
            "popup_config": {
                "enabled": True,
                "expression": "{title}",
                "visible_fields": [
                    "construction_year",
                    "height_roof",
                    "ground_elevation",
                    "feature_code",
                ],
            },
        },
    )
    # Subway services in official route colors (hardcoded palette - the feed
    # carries no colors). Single legend swatch; the per-route color story is
    # the map itself.
    service_match: list = ["match", ["get", "service"]]
    for svc, color in MTA_ROUTE_COLORS.items():
        service_match += [svc, color]
    service_match.append("#808183")
    api.add_layer(
        map_id,
        {
            "dataset_id": lines_ds,
            "sort_order": 1,
            "opacity": 0.95,
            "display_name": "Subway (official MTA colors)",
            "paint": {
                "line-color": [
                    "case",
                    ["==", ["get", "service"], None],
                    "#808183",
                    service_match,
                ],
                "line-width": [
                    "interpolate",
                    ["linear"],
                    ["zoom"],
                    10,
                    1.2,
                    14,
                    3.2,
                    16,
                    5,
                ],
                "line-opacity": 0.95,
            },
            "layout": {"line-cap": "round", "line-join": "round"},
            "popup_config": {
                "enabled": True,
                "expression": "{service} train - {service_name}",
                "visible_fields": [],
            },
        },
    )
    api.add_layer(
        map_id,
        {
            "dataset_id": stations_ds,
            "sort_order": 0,
            "opacity": 1.0,
            "display_name": "Stations (green = ADA accessible)",
            # Zoom-gated via zoom-interpolated opacity, NOT layout._minzoom:
            # MapLibre's addLayer validation rejects unknown layout properties,
            # so a persisted underscore layout key crashes the whole layer on
            # the viewer path (verified live 2026-07-04).
            "paint": {
                "circle-radius": [
                    "interpolate",
                    ["linear"],
                    ["zoom"],
                    12.5,
                    2.5,
                    16,
                    5.5,
                ],
                "circle-color": [
                    "match",
                    ["to-number", ["get", "ada"], 0],
                    1,
                    "#22c55e",
                    # ada=2 = partially accessible (e.g. one direction only)
                    2,
                    "#a3e635",
                    "#94a3b8",
                ],
                "circle-stroke-color": "#0b0f14",
                "circle-stroke-width": 1,
                # Stations fade in past ~z12.5 so the city view stays clean.
                "circle-opacity": [
                    "interpolate",
                    ["linear"],
                    ["zoom"],
                    12.3,
                    0,
                    12.9,
                    0.95,
                ],
                "circle-stroke-opacity": [
                    "interpolate",
                    ["linear"],
                    ["zoom"],
                    12.3,
                    0,
                    12.9,
                    1,
                ],
            },
            "style_config": {
                "mode": "categorical",
                "column": "ada",
                "ramp": "Dark2",
                "categories": [
                    {"value": 1, "color": "#22c55e", "label": "ADA accessible"},
                    {
                        "value": 2,
                        "color": "#a3e635",
                        "label": "Partially accessible",
                    },
                    {"value": 0, "color": "#94a3b8", "label": "Not accessible"},
                ],
            },
            "popup_config": {
                "enabled": True,
                "expression": "{stop_name}",
                "visible_fields": [
                    "daytime_routes",
                    "structure",
                    "borough",
                    "ada",
                ],
            },
        },
    )
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
    warn_if_hidden_layers(api, map_id, name)
    print(f"  -> map {map_id}")
    return map_id


def build_hurricanes(api: Api, force: bool = False) -> str:
    """The line-story hero: every major Atlantic hurricane since 1950 from
    NOAA HURDAT2, drawn as per-6-hour segments so each track changes color and
    width as the storm intensifies and decays.

    Capabilities on display nothing else shows: render_mode 'arrow'
    (direction-of-motion arrows along the track), per-segment categorical
    line color, data-driven line width, line-center name labels.
    """
    name = "Hurricane Alley - 75 Years of Major Atlantic Storms"
    if not force and _map_exists(api, name):
        print(f"  [skip] {name} already exists")
        return "(skipped)"
    print("\n[hurricanes] Hurricane Alley (HURDAT2 majors since 1950)")
    by_title = api.datasets_by_title()

    def tracks_bytes() -> bytes:
        data, n_storms, n_segs = hurdat2_feed()
        print(f"  ({n_storms} major storms, {n_segs} track segments)")
        return data

    tracks_ds = _get_or_ingest(
        api,
        by_title,
        "Atlantic Hurricane Tracks (HURDAT2, majors since 1950)",
        "atlantic_hurricanes.geojson",
        tracks_bytes,
        "Six-hourly best-track segments for every Atlantic hurricane since "
        "1950 that reached Category 3+: name, season, per-segment wind, "
        "pressure, Saffir-Simpson category and landfall flag. Source: NOAA "
        "NHC HURDAT2 (public domain).",
        force=force,
        timeout=600,
    )

    map_id = api.create_map(
        name,
        "Every Atlantic hurricane since 1950 that reached Category 3, drawn "
        "segment by segment: tracks warm from blue tropical storm to magenta "
        "Category 5 as each storm intensifies, arrows show direction of "
        "motion, and the width follows wind speed. Find Katrina, Andrew, "
        "Maria and Ian - or ask AI: which season had the most Category 5 "
        "segments? How many majors made landfall? Source: NOAA NHC HURDAT2.",
    )
    cat_colors = {
        "TD": "#9ca3af",
        "TS": "#60a5fa",
        "Cat 1": "#facc15",
        "Cat 2": "#fb923c",
        "Cat 3": "#f97316",
        "Cat 4": "#ef4444",
        "Cat 5": "#c026d3",
    }
    cat_match: list = ["match", ["get", "category"]]
    for k, v in cat_colors.items():
        cat_match += [k, v]
    cat_match.append("#9ca3af")
    # Direction-of-motion arrows go on a SEPARATE Cat 5-filtered layer: arrows
    # render per segment and cannot be zoom-gated, so arrow mode on all 9.5k
    # segments carpets the long extratropical legs in arrow soup at world
    # zoom (verified live 2026-07-04). Filtering to the rare Cat 5 legs keeps
    # them sparse and meaningful - the layer filter propagates to the arrow
    # companion.
    api.add_layer(
        map_id,
        {
            "dataset_id": tracks_ds,
            "sort_order": 0,
            "opacity": 1.0,
            "display_name": "Category 5 legs (arrows = motion)",
            "show_in_legend": False,
            "filter": ["==", ["get", "category"], "Cat 5"],
            "style_config": {
                "render_mode": "arrow",
                "builder": {
                    # White arrows read clearly against the magenta Cat-5 line;
                    # the old dark-purple (#701a75) was nearly invisible on it.
                    "arrow_color": "#ffffff",
                    "arrow_size": 16,
                    "arrow_spacing": 90,
                },
            },
            "paint": {
                "line-color": "#c026d3",
                "line-width": [
                    "interpolate",
                    ["linear"],
                    ["zoom"],
                    2,
                    2.8,
                    7,
                    6,
                ],
                "line-opacity": 0.9,
            },
            "layout": {"line-cap": "round", "line-join": "round"},
            # No popup on the highlight layer: it overlaps the storm-tracks layer
            # on every Cat-5 segment, so enabling both made the feature popup pager
            # show each Cat-5 leg twice. The storm-tracks layer below owns popups.
            "popup_config": {"enabled": False},
        },
    )
    api.add_layer(
        map_id,
        {
            "dataset_id": tracks_ds,
            "sort_order": 1,
            # Single source of dimming: layer opacity 1.0 × line-opacity 0.85 keeps
            # the intended ~0.85. The old 0.9 compounded to a washed-out 0.765.
            "opacity": 1.0,
            "display_name": "Storm tracks (by intensity at each leg)",
            "style_config": {
                "mode": "categorical",
                "column": "category",
                # These colors are hand-picked (Saffir-Simpson), not a named ramp;
                # "custom" keeps the ramp picker honest instead of falsely showing
                # Dark2 selected. TD is included so the legend matches the paint
                # (which already colors TD via cat_colors) — degenerate/weak legs
                # are no longer an unlabeled gray on the map.
                "ramp": "custom",
                "categories": [
                    {"value": "TD", "color": "#9ca3af", "label": "Tropical depression"},
                    {"value": "TS", "color": "#60a5fa", "label": "Tropical storm"},
                    {"value": "Cat 1", "color": "#facc15", "label": "Category 1"},
                    {"value": "Cat 2", "color": "#fb923c", "label": "Category 2"},
                    {"value": "Cat 3", "color": "#f97316", "label": "Category 3"},
                    {"value": "Cat 4", "color": "#ef4444", "label": "Category 4"},
                    {"value": "Cat 5", "color": "#c026d3", "label": "Category 5"},
                ],
            },
            "paint": {
                "line-color": [
                    "case",
                    ["==", ["get", "category"], None],
                    "#9ca3af",
                    cat_match,
                ],
                "line-width": [
                    "interpolate",
                    ["linear"],
                    ["zoom"],
                    2,
                    [
                        "step",
                        ["to-number", ["get", "wind_kt"], 0],
                        0.7,
                        64,
                        1.1,
                        96,
                        1.8,
                        137,
                        2.8,
                    ],
                    7,
                    [
                        "step",
                        ["to-number", ["get", "wind_kt"], 0],
                        1.8,
                        64,
                        2.8,
                        96,
                        4.2,
                        137,
                        6,
                    ],
                ],
                "line-opacity": 0.85,
            },
            "layout": {"line-cap": "round", "line-join": "round"},
            "label_config": {
                "column": "name",
                "fontSize": 11,
                # Raised from 4.2: at world/basin zoom, labelling every 6-hour
                # segment carpeted the map in repeated storm names. From ~z6 the
                # view is regional and names read instead of collide.
                "minZoom": 6,
                "placement": "line-center",
                "textColor": "#334155",
                "haloColor": "#ffffff",
                "haloWidth": 1.6,
                "allowOverlap": False,
            },
            "popup_config": {
                "enabled": True,
                "expression": "{name} ({season})",
                "visible_fields": [
                    "category",
                    "wind_kt",
                    "pressure_mb",
                    "status",
                    "landfall",
                ],
            },
        },
    )
    api.set_view(
        map_id,
        visibility="public",
        center_lng=-55,
        center_lat=28,
        zoom=2.8,
        pitch=0,
        bearing=0,
        basemap_style="openfreemap-positron",
        show_basemap_labels=True,
    )
    warn_if_hidden_layers(api, map_id, name)
    print(f"  -> map {map_id}")
    return map_id


def build_meteorites(api: Api, force: bool = False) -> str:
    """The cluster hero: all ~32k located meteorite landings.

    Above 5,000 points the viewer switches from client GeoJSON clustering to
    SERVER-SIDE cluster tiles - this map exists to show that tier at full
    scale. fix(#403) made those tiles project the cols=-requested attribute
    columns onto unclustered features, so the Fell/Found colors, mass-graded
    radii and popups keep working past cluster max zoom (requires a backend
    at or after that fix). Count-graded cluster bubbles split apart on zoom
    into mass-graded circles colored Fell vs Found.
    """
    name = "Everything That Fell From the Sky"
    print("\n[meteorites] Everything That Fell From the Sky (server-side clusters)")
    by_title = api.datasets_by_title()

    def meteorites_bytes() -> bytes:
        data, n = meteorite_feed()
        print(f"  ({n} located meteorites)")
        return data

    met_title = "Meteorite Landings (Meteoritical Society)"
    # Heal instances seeded while the dataset was capped at 4,800 (the interim
    # workaround for attribute-less cluster tiles) BEFORE the map-exists skip,
    # so upgrades reach existing instances: swap the full feed in place,
    # keeping the dataset id / layer wiring.
    if not force and met_title in by_title:
        fc = api.dataset_feature_count(by_title[met_title])
        if fc and fc < 20000:
            print(f"  dataset has {fc} features (capped-era seed) - swapping in the full feed...")
            api.reupload_geojson(
                by_title[met_title], "meteorite_landings.geojson", meteorites_bytes()
            )

    if not force and _map_exists(api, name):
        print(f"  [skip] {name} already exists")
        return "(skipped)"

    met_ds = _get_or_ingest(
        api,
        by_title,
        met_title,
        "meteorite_landings.geojson",
        meteorites_bytes,
        "Every meteorite recovery with coordinates: name, classification, "
        "mass, year, and whether it was seen falling ('Fell') or found "
        "later. Source: NASA Open Data / The Meteoritical Society (public "
        "domain).",
        force=force,
        timeout=900,
    )

    map_id = api.create_map(
        name,
        "All ~32,000 located meteorites humanity has ever recovered, from "
        "gram-scale chondrites to the 60-tonne Hoba iron. Clusters split "
        "apart as you zoom; amber dots were SEEN falling, gray ones found "
        "later - note the Antarctic collection-expedition stripes and the "
        "Saharan hot-desert clusters. Ask AI: the heaviest meteorite? The "
        "most common class? How many observed falls since 1950? Source: "
        "NASA / Meteoritical Society.",
    )
    api.add_layer(
        map_id,
        {
            "dataset_id": met_ds,
            "sort_order": 0,
            "opacity": 1.0,
            "display_name": "Meteorites (amber = seen falling)",
            "paint": {
                "circle-radius": [
                    "step",
                    ["to-number", ["get", "mass_kg"], 0],
                    3,
                    1,
                    4.5,
                    10,
                    6,
                    100,
                    9,
                    1000,
                    13,
                ],
                "circle-color": [
                    "case",
                    ["==", ["get", "fall"], None],
                    "#94a3b8",
                    [
                        "match",
                        ["get", "fall"],
                        "Fell",
                        "#f59e0b",
                        "Found",
                        "#94a3b8",
                        "#94a3b8",
                    ],
                ],
                "circle-opacity": 0.9,
                "circle-stroke-color": "#1e293b",
                "circle-stroke-width": 0.7,
            },
            "style_config": {
                "mode": "categorical",
                "column": "fall",
                "ramp": "Dark2",
                "render_mode": "cluster",
                "categories": [
                    {"value": "Fell", "color": "#f59e0b", "label": "Seen falling"},
                    {"value": "Found", "color": "#94a3b8", "label": "Found later"},
                ],
                # >5000 features -> the viewer uses server-side cluster tiles
                # with these knobs (snake_case builder keys).
                "builder": {
                    "cluster_radius": 44,
                    "cluster_max_zoom": 8,
                    "cluster_color": "#6366f1",
                    "cluster_text_color": "#ffffff",
                    "cluster_text_size": 12,
                    "cluster_color_ramp": [
                        {"count": 25, "color": "#818cf8"},
                        {"count": 250, "color": "#6366f1"},
                        {"count": 2500, "color": "#4338ca"},
                    ],
                },
            },
            "popup_config": {
                "enabled": True,
                "expression": "{name}",
                "visible_fields": ["recclass", "mass_kg", "year", "fall"],
            },
        },
    )
    api.set_view(
        map_id,
        visibility="public",
        center_lng=12,
        center_lat=18,
        zoom=1.7,
        pitch=0,
        bearing=0,
        basemap_style="openfreemap-positron",
        show_basemap_labels=True,
    )
    warn_if_hidden_layers(api, map_id, name)
    print(f"  -> map {map_id}")
    return map_id


def build_matterhorn(api: Api, force: bool = False) -> str:
    """The terrain hero: 3D mesh + hillshade + hypsometric tint from a VRT
    mosaic of swissALTI3D 2m lidar COGs, with dashed alpine climbing routes
    (white-cased, the classic Swiss-map convention) and labeled peaks."""
    name = "The Matterhorn in 3D"
    if not force and _map_exists(api, name):
        print(f"  [skip] {name} already exists")
        return "(skipped)"
    print("\n[matterhorn] The Matterhorn (3D terrain via regional VRT mosaic)")
    by_title = api.datasets_by_title()
    vrt_title = "swissALTI3D Matterhorn DEM (2m mosaic)"
    if not force and vrt_title in by_title:
        print("  [reuse] existing DEM mosaic")
        vrt_ds = by_title[vrt_title]
    else:
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
                    "sources": [
                        {"type": "raster_cog", "uri": uri, "format": "geotiff"}
                    ],
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
        # A failed entry is action="error" (no job_id). Abort before mosaicking
        # rather than silently building a VRT from a partial tile set; reuse
        # the dataset_id of already-ingested tiles (action="skip" on a re-run).
        errored = [r for r in results if r.get("action") == "error"]
        if errored:
            detail = "; ".join(
                f"{r.get('dataset_key')}: {r.get('message') or r.get('errors')}"
                for r in errored
            )
            raise RuntimeError(
                f"{len(errored)}/{len(results)} swissALTI3D manifest entries "
                f"failed: {detail}"
            )
        tile_ids = []
        for r in results:
            if r.get("job_id"):
                tile_ids.append(api.poll(r["job_id"])["dataset_id"])
            elif r.get("dataset_id"):
                tile_ids.append(r["dataset_id"])
        if len(tile_ids) != len(tiles):
            raise RuntimeError(
                f"expected {len(tiles)} swissALTI3D tiles but only "
                f"{len(tile_ids)} resolved to datasets; aborting before VRT"
            )
        print(f"  mosaicking {len(tile_ids)} tiles into a VRT...")
        vrt_job = api.vrt_create(
            tile_ids,
            vrt_title,
            "VRT mosaic of swissALTI3D 2m tiles around the Matterhorn. swisstopo OGD.",
        )
        vrt_ds = api.poll(vrt_job, timeout=600)["dataset_id"]
    # A VRT does NOT inherit is_dem from its sources - set it or terrain won't
    # engage.
    api.patch_dataset(vrt_ds, is_dem=True)
    map_id = api.create_map(
        name,
        "A razor-sharp 3D terrain mesh of the Matterhorn from swisstopo "
        "swissALTI3D 2m lidar - 62 cloud-optimized GeoTIFF tiles mosaicked "
        "into one VRT, lit by a geographically-anchored hillshade with a "
        "hypsometric elevation tint. Dashed red lines are real climbing "
        "routes from OpenStreetMap (the Lion Ridge among them); flags mark "
        "the named summits. swisstopo OGD / OSM contributors.",
    )
    api.add_layer(
        map_id,
        {
            "dataset_id": vrt_ds,
            # Highest sort_order = BOTTOM of the stack (viewer draws lower
            # sort_order on top) - the relief sits under routes/casing/peaks.
            "sort_order": 4,
            "opacity": 1.0,
            "display_name": "swissALTI3D relief",
            "layer_type": "raster_geolens",
            "style_config": {"render_mode": "hillshade", "builder": {}},
            # illumination-anchor "map" keeps the NW (315 deg) lighting fixed
            # geographically instead of rotating with the bearing -150 camera.
            # _hypso-enabled adds the color-relief companion under the
            # hillshade (fixed 0-4000 m elevation ramp) - the "snowline hint".
            "paint": {
                "hillshade-illumination-direction": 315,
                "hillshade-illumination-anchor": "map",
                "hillshade-exaggeration": 0.75,
                "hillshade-shadow-color": "#16203a",
                "hillshade-highlight-color": "#ffffff",
                "hillshade-accent-color": "#3a4a63",
                "_hypso-enabled": True,
                "_hypso-ramp": "Viridis",
            },
        },
    )
    # Drape OSM climbing routes + named peaks on the terrain. Clip to the DEM
    # footprint so vectors sit on the mesh rather than plunging into the
    # out-of-coverage void (see fetch_osm_overlays).
    routes_fc, peaks_fc = fetch_osm_overlays((7.645, 45.961, 7.684, 45.988))
    if routes_fc["features"]:
        # Dashed red route over a solid white casing - the classic alpine-map
        # convention. TWO layers on the SAME dataset (map-sync dedupes the tile
        # source); the viewer draws LOWER sort_order ON TOP, so the dashed
        # route takes 1 and the casing 2.
        routes_ds = _get_or_ingest(
            api,
            by_title,
            "Matterhorn Climbing Routes",
            "matterhorn_routes.geojson",
            lambda: json.dumps(routes_fc).encode(),
            "OSM alpine routes clipped to the swissALTI3D DEM footprint (incl. "
            "the Lion Ridge / cresta Leone Cervino). Source: OpenStreetMap "
            "contributors.",
            force=force,
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
                    "line-width": 3.0,
                    "line-dasharray": [2.4, 1.8],
                    "line-opacity": 1.0,
                },
                "layout": {"line-cap": "round", "line-join": "round"},
                "popup_config": {
                    "enabled": True,
                    "expression": "{name}",
                    "visible_fields": ["sac_scale"],
                },
            },
        )
        api.add_layer(
            map_id,
            {
                "dataset_id": routes_ds,
                "sort_order": 2,
                "opacity": 1.0,
                "display_name": "Route casing",
                "show_in_legend": False,
                "paint": {
                    "line-color": "#ffffff",
                    "line-width": 6.5,
                    "line-opacity": 0.95,
                },
                "layout": {"line-cap": "round", "line-join": "round"},
            },
        )
        print(f"  + {len(routes_fc['features'])} route segments (dashed, cased)")
    if peaks_fc["features"]:
        peaks_ds = _get_or_ingest(
            api,
            by_title,
            "Matterhorn Peaks",
            "matterhorn_peaks.geojson",
            lambda: json.dumps(peaks_fc).encode(),
            "Named summits within the swissALTI3D DEM footprint. Source: "
            "OpenStreetMap.",
            force=force,
        )
        api.add_layer(
            map_id,
            {
                "dataset_id": peaks_ds,
                "sort_order": 3,
                "opacity": 1.0,
                "display_name": "Peaks",
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
                "popup_config": {
                    "enabled": True,
                    "expression": "{name}",
                    "visible_fields": ["ele"],
                },
            },
        )
        print(f"  + {len(peaks_fc['features'])} named peaks labeled")
    # Frame the summit; the regional DEM (~8x8 km) extends ~4 km past the
    # Matterhorn in every direction so the camera can roam before hitting the
    # data edge. Exaggeration 1.0: the relief is dramatic enough honestly.
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
    warn_if_hidden_layers(api, map_id, name)
    print(f"  -> map {map_id}")
    return map_id


def build_sentinel2(api: Api, force: bool = False) -> str:
    """The by-reference hero: recent low-cloud Sentinel-2 true color over NYC,
    streamed straight from the AWS open-data COGs - zero download at seed
    time; Titiler needs S3 egress at VIEW time."""
    name = "New York From Orbit - Sentinel-2, by Reference"
    if not force and _map_exists(api, name):
        print(f"  [skip] {name} already exists")
        return "(skipped)"
    print("\n[sentinel2] New York From Orbit (COGs by reference)")
    # Query the STAC API DIRECTLY (the backend /services/stac/search proxy 502s
    # on the SSRF IP-pin against Element84's CloudFront edge). Collection-1
    # (sentinel-2-c1-l2a) supersedes the legacy sentinel-2-l2a collection and
    # is where NEW acquisitions land - fall back to legacy only if c1 returns
    # nothing for the AOI.
    feats: list = []
    for collection in ("sentinel-2-c1-l2a", "sentinel-2-l2a"):
        body = {
            "collections": [collection],
            "bbox": SENTINEL_BBOX,
            "query": {"eo:cloud_cover": {"lt": 10}},
            "sortby": [{"field": "properties.datetime", "direction": "desc"}],
            "limit": 24,
        }
        r = httpx.post(f"{SENTINEL_STAC}/search", json=body, timeout=60.0)
        r.raise_for_status()
        feats = r.json().get("features", [])
        if feats:
            break
    if feats:
        newest = feats[0]["properties"].get("datetime", "?")[:10]
        print(f"  newest low-cloud scene: {newest} ({collection})")
    items, seen_tiles = [], set()
    for f in feats:
        a = (f.get("assets") or {}).get("visual")  # TCI COG
        if not a or not a.get("href"):
            continue
        dt = f["properties"].get("datetime", "")
        # One scene per MGRS tile, newest first - a per-DATE dedupe stacked
        # revisits of the SAME tile and left neighboring tiles uncovered, so
        # half the metro showed basemap instead of imagery.
        tile = f["properties"].get("grid:code") or (
            f["id"].split("_")[1] if "_" in f["id"] else f["id"]
        )
        if tile in seen_tiles:
            continue
        seen_tiles.add(tile)
        # Collection-1 items use projection-extension v2 "proj:code"
        # ("EPSG:32618"); legacy items carry integer "proj:epsg".
        epsg = f["properties"].get("proj:epsg")
        if epsg is None:
            code = f["properties"].get("proj:code") or ""
            epsg = int(code.split(":")[1]) if code.upper().startswith("EPSG:") else None
        items.append(
            {
                "id": f["id"],
                "collection": f.get("collection", "sentinel-2-l2a"),
                "title": f"Sentinel-2 TCI {f['id']}",
                "data_asset_href": a["href"],
                "bbox": f.get("bbox"),
                "epsg": epsg,
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
    errored = [x for x in results if x.get("status") == "error"]
    if errored:
        detail = "; ".join(x.get("error") or x.get("item_id", "?") for x in errored)
        raise RuntimeError(
            f"{len(errored)}/{len(results)} STAC imports failed: {detail}"
        )
    # 'created' results carry dataset_id; 'skipped' (already imported - the
    # backend dedupes on source_url, so --force cannot re-create them) resolve
    # back to the existing dataset by the title we assigned.
    id_to_title = {it["id"]: it["title"] for it in items}
    id_to_date = {it["id"]: it["datetime_start"][:10] for it in items}
    by_title = None
    scenes = []  # (dataset_id, capture_date)
    for x in results:
        item_id = x.get("item_id")
        if x.get("dataset_id"):
            scenes.append((x["dataset_id"], id_to_date.get(item_id, "?")))
        elif x.get("status") == "skipped":
            if by_title is None:
                by_title = api.datasets_by_title()
            existing = by_title.get(id_to_title.get(item_id, ""))
            if existing:
                scenes.append((existing, id_to_date.get(item_id, "?")))
    if not scenes:
        raise RuntimeError(
            "STAC import resolved no dataset_ids (skipped items not found by "
            "title); remove the existing Sentinel-2 datasets and retry"
        )
    map_id = api.create_map(
        name,
        "Recent low-cloud Sentinel-2 true-color scenes over New York, "
        "streamed BY REFERENCE from the AWS Earth Search open-data archive - "
        "no file was downloaded to build this map; Titiler reads the "
        "cloud-optimized GeoTIFFs straight from S3, newest scene on top. "
        "ESA Copernicus / Element84 Earth Search.",
    )
    for i, (ds_id, day) in enumerate(scenes):
        api.add_layer(
            map_id,
            {
                "dataset_id": ds_id,
                "sort_order": i,  # newest first = on top (results are date-desc)
                "opacity": 1.0,
                "display_name": f"Sentinel-2 - {day}",
                "layer_type": "raster_geolens",
                # true color = NO render_mode, no paint (default RGB path).
                "style_config": {"builder": {}},
            },
        )
    api.set_view(
        map_id,
        visibility="public",
        center_lng=-73.97,
        center_lat=40.72,
        zoom=10.2,
        pitch=0,
        bearing=0,
        basemap_style="openfreemap-positron",
        show_basemap_labels=True,
    )
    warn_if_hidden_layers(api, map_id, name)
    print(f"  -> map {map_id}  ({len(scenes)} scenes)")
    return map_id


# A tiny inline private dataset for the embed-token capability demo (no external
# fetch so it is fully reproducible).
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


def build_embed_demo(api: Api, force: bool = False) -> str:
    """Private-dataset embed-token capability demo. A PUBLIC share URL is
    impossible with a private dataset (publishing the map 400s), so the map
    stays PRIVATE and the X-Embed-Token header grants scoped tile access."""
    name = "Private Embed Demo"
    if not force and _map_exists(api, name):
        print("  [skip] Private Embed Demo already exists")
        return "(skipped)"
    print("\n[embed] private-dataset embed-token demo")
    priv_ds = api.ingest_geojson(
        "vip_sites_private.geojson",
        json.dumps(PRIVATE_VIP_FC).encode(),
        "Private Embed Demo - VIP Sites",
        "A private dataset shown ONLY to holders of a scoped embed token "
        "(X-Embed-Token). Demonstrates token-gated access to non-public data.",
        visibility="private",
    )
    map_id = api.create_map(
        name,
        "A private map (kept unpublished) used to mint a scoped embed token "
        "over a private dataset.",
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
    # scoped_dataset_ids is a SNAPSHOT of the map's layers at mint time -> the
    # layer is added BEFORE minting. raw_token is returned ONLY here.
    tok = api.mint_embed_token(map_id, "Showcase - private embed demo")
    raw = tok.get("raw_token")
    print(f"  embed token (private dataset): {raw}")
    print(f"  scoped datasets: {tok.get('scoped_dataset_ids')}")
    print(f"  expires: {tok.get('expires_at')}")
    if table_name and raw:
        print("  demo: this serves the PRIVATE dataset with NO login:")
        print(
            f"    curl -H 'X-Embed-Token: {raw}' "
            f"{api.base}/api/tiles/data.{table_name}/12/1205/1539.pbf"
        )
    return map_id


# Collection membership: dataset TITLES per collection. Missing titles (e.g.
# terrain skipped) are silently ignored; add_to_collection is idempotent, so
# membership tops up on every run (fix #389).
COLLECTIONS = {
    "Restless Planet": (
        "The physical earth: earthquakes, volcanic eruptions, plate "
        "boundaries, hurricane tracks, meteorite falls, global relief and "
        "alpine lidar terrain.",
        [
            "Recent Earthquakes (M4.5+, last 30 days)",
            "Recent Earthquakes - Heatmap source",
            "Tectonic Plate Boundaries (PB2002)",
            "Significant Volcanic Eruptions (NCEI, 4360 BC-present)",
            "Atlantic Hurricane Tracks (HURDAT2, majors since 1950)",
            "Meteorite Landings (Meteoritical Society)",
            "ETOPO 2022 Global Relief (60 arc-second)",
            "swissALTI3D Matterhorn DEM (2m mosaic)",
        ],
    ),
    "Human World": (
        "The built world: Manhattan's skyline and subway, world cities and "
        "countries, incomes, and fresh satellite imagery of New York.",
        [
            "Manhattan Building Heights",
            "NYC Subway Lines (MTA)",
            "NYC Subway Stations (MTA)",
            "World Major Cities (500k+)",
            "World Countries (Natural Earth 1:50m)",
            "New York Median Household Income by County",
            "World States & Provinces (Natural Earth 1:50m)",
        ],
    ),
}


def build_collections(api: Api, force: bool = False) -> str:
    """Two themed collections. Collection.name is UNIQUE -> reuse on re-runs;
    membership top-up is idempotent."""
    print("\n[collections] Restless Planet + Human World")
    existing = api.collections_by_name()
    titles = api.datasets_by_title()
    ids = []
    for cname, (desc, wanted) in COLLECTIONS.items():
        coll_id = existing.get(cname) or api.create_collection(cname, desc)
        member_ids = [titles[t] for t in wanted if t in titles]
        added = api.add_to_collection(coll_id, member_ids) if member_ids else 0
        print(f"  {cname}: +{added} datasets ({len(member_ids)} referenced)")
        ids.append(coll_id)
    return ids[0] if ids else "(none)"


# Per-dataset catalog metadata for the hand-seeded showcase datasets. The
# ingest flow (ingest_geojson / manifest) only sets title + summary, so every
# one of these defaulted to license "proprietary" with zero keywords - which
# reads as a proprietary raster dump and contradicts the open sources their
# own summaries cite (fix(#614): proprietary licenses + empty keyword facets on
# the demo, flagged in the 2026-07-20 pre-launch audit).
# Licenses are each dataset's real upstream terms; keywords power the faceted-
# search sidebar. "World States & Provinces" is intentionally omitted - it is
# the summary-less canvas for the AI metadata-generation demo and must stay bare.
SHOWCASE_METADATA: dict[str, dict] = {
    "World Countries (Natural Earth 1:50m)": {
        "license": "Natural Earth (public domain)",
        "keywords": ["countries", "boundaries", "admin-0", "natural earth"],
    },
    "World Major Cities (500k+)": {
        "license": "Natural Earth (public domain)",
        "keywords": ["cities", "populated places", "urban", "natural earth"],
    },
    "Manhattan Building Heights": {
        "license": "NYC Open Data (public domain)",
        "keywords": ["buildings", "3d", "heights", "manhattan", "nyc"],
    },
    "NYC Subway Lines (MTA)": {
        "license": "MTA open data (data.ny.gov)",
        "keywords": ["subway", "transit", "mta", "nyc", "rail"],
    },
    "NYC Subway Stations (MTA)": {
        "license": "MTA open data (data.ny.gov)",
        "keywords": [
            "subway",
            "stations",
            "transit",
            "mta",
            "nyc",
            "ada",
            "accessibility",
        ],
    },
    "New York Median Household Income by County": {
        "license": "US Census Bureau, ACS 2017-21 (public domain)",
        "keywords": ["census", "income", "demographics", "acs", "new york"],
    },
    "Recent Earthquakes (M4.5+, last 30 days)": {
        "license": "USGS Earthquake Hazards Program (US public domain)",
        "keywords": ["earthquakes", "seismic", "usgs", "hazards", "magnitude"],
    },
    "Recent Earthquakes - Heatmap source": {
        "license": "USGS Earthquake Hazards Program (US public domain)",
        "keywords": ["earthquakes", "seismic", "usgs", "density", "heatmap"],
        # fix(#614): the old summary read as an internal rendering workaround;
        # describe it as the map's density layer instead.
        "summary": (
            "USGS M4.5+ earthquakes from the last 30 days, styled as the "
            "magnitude-weighted heat surface on the Restless Earth map. "
            "Source: USGS Earthquake Hazards Program (public domain)."
        ),
    },
    "Tectonic Plate Boundaries (PB2002)": {
        "license": "Peter Bird (2003), PB2002 - free for research, please cite",
        "keywords": ["plate tectonics", "geology", "boundaries", "pb2002"],
    },
    "Significant Volcanic Eruptions (NCEI, 4360 BC-present)": {
        "license": "NOAA NCEI (US public domain)",
        "keywords": ["volcanoes", "eruptions", "hazards", "geology", "ncei"],
    },
    "Atlantic Hurricane Tracks (HURDAT2, majors since 1950)": {
        "license": "NOAA NHC HURDAT2 (US public domain)",
        "keywords": [
            "hurricanes",
            "tropical cyclones",
            "noaa",
            "hurdat2",
            "storms",
        ],
    },
    "Meteorite Landings (Meteoritical Society)": {
        "license": "NASA open data (public domain)",
        "keywords": ["meteorites", "impacts", "nasa", "meteoritical society"],
    },
    "Matterhorn Climbing Routes": {
        "license": "(C) OpenStreetMap contributors (ODbL)",
        "keywords": ["climbing", "alpinism", "routes", "osm", "matterhorn"],
    },
    "Matterhorn Peaks": {
        "license": "(C) OpenStreetMap contributors (ODbL)",
        "keywords": ["peaks", "summits", "mountains", "osm", "matterhorn"],
    },
    "ETOPO 2022 Global Relief (60 arc-second)": {
        "license": "US public domain (NOAA NCEI)",
        "keywords": ["bathymetry", "relief", "etopo", "global", "elevation"],
    },
    "swissALTI3D Matterhorn DEM (2m mosaic)": {
        "license": "swisstopo OGD",
        "keywords": ["terrain", "dem", "elevation", "swisstopo", "matterhorn"],
    },
}


def enrich_showcase_metadata(api: "Api") -> None:
    """Backfill license + keywords (and, where noted, a cleaner summary) on the
    hand-seeded showcase datasets.

    Idempotent: the license/summary PATCH is a plain overwrite and keywords are
    added only when absent, so re-running the seeder never duplicates. Only
    datasets that actually exist are touched, so this composes with --only. Each
    dataset is isolated the same way the builders are - one flaky PATCH must not
    skip the rest - and the whole pass is best-effort: it never fails the seed.

    Iterates every dataset rather than a title->newest-id map: titles are NOT
    unique (a --force reseed leaves same-titled predecessors, see
    datasets_by_title), and enriching only the newest would leave the older
    public duplicates still "proprietary"/keyword-less - the exact pollution
    this fixes. Every matching copy gets patched.
    """
    for ds in api.list_datasets_full():
        spec = SHOWCASE_METADATA.get(ds["title"])
        if not spec:
            continue
        title, dataset_id = ds["title"], ds["id"]
        try:
            fields = {"license": spec["license"]}
            if spec.get("summary"):
                fields["summary"] = spec["summary"]
            api.patch_dataset(dataset_id, **fields)
            record_id = api.dataset_record_id(dataset_id)
            have = api.existing_keywords(record_id)
            for kw in spec.get("keywords", ()):
                if kw not in have:
                    api.add_keyword(record_id, kw)
            print(f"  enriched metadata: {title}")
        except (httpx.HTTPStatusError, httpx.TimeoutException) as e:
            print(
                f"  WARNING: metadata enrich failed for {title!r}: {e}", file=sys.stderr
            )


def main() -> int:
    ap = argparse.ArgumentParser(description="Seed GeoLens showcase maps.")
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
    ap.add_argument("--password", default=os.environ.get("GEOLENS_ADMIN_PASSWORD"))
    ap.add_argument(
        "--no-terrain",
        action="store_true",
        help="skip the Matterhorn terrain hero (fastest seed; ~62 COG downloads)",
    )
    ap.add_argument(
        "--no-sentinel2",
        action="store_true",
        help="skip the Sentinel-2 by-reference map (needs Titiler->S3 egress "
        "at view time)",
    )
    ap.add_argument(
        "--no-oceans",
        action="store_true",
        help="skip the ETOPO 2022 relief layer (saves a ~466 MB worker download)",
    )
    ap.add_argument(
        "--only",
        choices=[
            "catalog",
            "restless",
            "manhattan",
            "hurricanes",
            "meteorites",
            "matterhorn",
            "sentinel2",
            "collections",
            "embed",
        ],
        help="build only one showcase item",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="re-create showcase maps/datasets even if they already exist",
    )
    ap.add_argument(
        "--prune",
        action="store_true",
        help="first delete the retired first-generation showcase maps/datasets",
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

    if args.prune:
        prune(api)

    fns = {
        "catalog": build_catalog,
        "restless": lambda a, force=False: build_restless_earth(
            a, force=force, with_oceans=not args.no_oceans
        ),
        "manhattan": build_manhattan,
        "hurricanes": build_hurricanes,
        "meteorites": build_meteorites,
        "matterhorn": build_matterhorn,
        "sentinel2": build_sentinel2,
        "collections": build_collections,
        "embed": build_embed_demo,
    }

    built = {}
    failed = {}
    if args.only:
        builders = [(args.only, fns[args.only])]
    else:
        builders = [
            ("catalog", fns["catalog"]),
            ("restless", fns["restless"]),
            ("manhattan", fns["manhattan"]),
            ("hurricanes", fns["hurricanes"]),
            ("meteorites", fns["meteorites"]),
        ]
        if not args.no_terrain:
            builders.append(("matterhorn", fns["matterhorn"]))
        if not args.no_sentinel2:
            builders.append(("sentinel2", fns["sentinel2"]))
        # collections + embed LAST: they reference the datasets above.
        builders.append(("collections", fns["collections"]))
        builders.append(("embed", fns["embed"]))
    for bname, fn in builders:
        # One flaky upstream must not kill the whole seed (e.g. the NYC
        # buildings table mid-replace): isolate each builder, report at end.
        # httpx.TimeoutException is NOT builtins.TimeoutError - catch both.
        try:
            result = fn(api, force=args.force)
        except (
            httpx.HTTPStatusError,
            httpx.TimeoutException,
            RuntimeError,
            TimeoutError,
        ) as e:
            print(f"\nERROR in [{bname}]: {e}", file=sys.stderr)
            if isinstance(e, httpx.HTTPStatusError):
                print(e.response.text[:500], file=sys.stderr)
            failed[bname] = str(e)
            continue
        if result and result != "(skipped)":
            built[bname] = result
        else:
            print(f"  {bname}: already exists, skipped (use --force to recreate)")

    # Backfill license + keywords on whatever showcase datasets now exist (the
    # ingest flow leaves them "proprietary" with no keywords). Best-effort and
    # self-isolating - see enrich_showcase_metadata - so it never fails the seed.
    print("\nEnriching catalog metadata (license + keywords)...")
    enrich_showcase_metadata(api)

    print("\nDone. Showcase:")
    for bname, mid in built.items():
        if bname in ("catalog",):
            continue
        path = "collections" if bname == "collections" else "maps"
        print(f"  {bname:12s} {args.base_url}/{path}/{mid}")
    if not args.only:
        skipped = []
        if args.no_terrain:
            skipped.append("--no-terrain (Matterhorn)")
        if args.no_sentinel2:
            skipped.append("--no-sentinel2 (Sentinel-2)")
        if args.no_oceans:
            skipped.append("--no-oceans (ETOPO relief layer)")
        if skipped:
            print(
                f"\n(Skipped: {', '.join(skipped)} - re-run without the flag to add.)"
            )
    if failed:
        print("\nFAILED builders (re-run each with --only when resolved):")
        for bname, msg in failed.items():
            print(f"  {bname}: {msg[:200]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
