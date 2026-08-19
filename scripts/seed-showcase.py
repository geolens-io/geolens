#!/usr/bin/env python3
"""Seed GeoLens with the marketing "showcase" maps.

Seven hero maps, every one carrying capabilities no other map shows, plus a
private embed-token demo and two themed collections. All data is public and
openly licensed; every flow was verified against the live API.

  1. Restless Earth        - the composite story hero: a LIVE USGS earthquake
                             service (M2.5+, rolling 30 days, refreshed on
                             demand rather than re-uploaded) with magnitude
                             size+color double-encoded and white M7+ rings, over
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
                             1950 from NOAA HURDAT2 (through the 2025 season),
                             per-6h-segment categorical
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
  7. Hurricane Exposure    - the ANALYSIS hero, and the only showcase map whose
                             headline is a computed result rather than a
                             rendering: the Category 3+ legs of the HURDAT2
                             tracks BUFFERED 100 km, INTERSECTED with Atlantic-
                             basin admin-1 regions, then DISSOLVED per region so
                             the fill grades by how many distinct major storms
                             reached it. Every step runs through the real
                             /analysis/materialize/ API, so each derived
                             dataset's provenance panel shows the operation
                             chain that built it - that chain is the feature on
                             display, the map is the vehicle.

  Three of the maps render on the GLOBE projection (Restless Earth, Everything
  That Fell From the Sky, Hurricane Alley): all three tell global stories that
  Mercator distorts. See GLOBE_PROJECTION_MAPS - the regional maps stay
  Mercator, which is what they want.

  Catalog-only datasets (no map; fuel for the AI + search demos): World
  Countries, NY income by county (the scripted AI-styling canvas - ask the AI
  to build the choropleth live), and a summary-LESS admin-1 dataset for the
  AI metadata-generation demo.

  Collections: "Restless Planet" (physical earth) and "Human World" (built
  world), plus the Private Embed Demo (X-Embed-Token over a private dataset).

Maintenance:
  --refresh-quakes    asks the server to re-pull both earthquake datasets from
                      their bound USGS service, then exits. Community has no
                      refresh scheduler, so this is the demo's cron job - run it
                      weekly or "last 30 days" quietly goes stale.
  --refresh-hurdat2   re-fetches the HURDAT2 file into both track datasets and
                      rebuilds the derived exposure chain, then exits. Run it
                      after NHC publishes a new season (usually spring).
  --prune-userdata    reports what a cleanup would delete (visitor-uploaded
                      maps/datasets); add --execute to actually delete.

Upgrading an existing instance: run with --prune to delete the retired
first-generation showcase maps/datasets (see RETIRED_* below), then seed.
--force rebuilds a showcase map that already exists - except the four in
PINNED_MAP_NAMES, whose ids and share token the geolens-examples repo links.
--force-pinned lifts that pin. What it then costs differs by map: New York From
Orbit (Sentinel-2) has its existing row and share links DELETED before the
rebuild, so that uuid is gone; the other three get a fresh row beside the old
one, which keeps its id and share links until someone removes it. Either way the
examples' references have to be moved onto the new ids.

Requires: pip install httpx

GOTCHAS this script encodes (learned the hard way, all verified live):
  * A plain GeoJSON URL is NOT a "service" - the service connector only takes
    WFS / ArcGIS / OGC API Features. DOWNLOAD + /ingest/upload for those.
  * ArcGIS MapServer URLs ARE accepted, not just FeatureServer: probing
    .../MapServer/0 returns service_type "ArcGIS MapServer" and auto-selects
    layer 0 (selected_layer_id). The probe NORMALIZES the url by dropping the
    trailing layer number - send back probe["url"], not the url you typed.
  * A service binding is created two ways off the SAME request body (url,
    service_type, layer_name, layer_title, layer_id, object_id_field, all read
    off the probe): POST /services/preview/ makes a NEW dataset (then the
    ordinary /ingest/commit/{job}), and POST /datasets/{id}/reupload/service/
    preview CONVERTS an existing one. Conversion is IN PLACE - dataset id,
    record id, table name and every map layer survive it (atomic staging-table
    swap server-side), so a converted dataset needs no map rewiring.
  * Only ONE dataset per owner + service_type + url + layer may be created
    through /services/preview/: a second import of the same layer is refused
    with 409 `duplicate_source`. The CONVERSION door has no such guard (both
    verified live). This showcase binds one USGS layer twice - circles and
    heatmap - so every service dataset it creates is a one-point stub that is
    immediately converted, never a /services/preview/ import.
  * Connectors have NO server-side attribute filter: `where=1=1` is hardcoded
    (sources/adapters/arcgis.py, sources/preview.py). You take the WHOLE layer
    or nothing - which is why the quakes feed is M2.5+ and not M4.5+.
  * A refresh REBUILDS column_info from the service wholesale, so styles must
    speak the SERVICE's column vocabulary permanently. Never bridge a name
    change with the column-rename endpoints: the next refresh discards the
    rename and the style silently points at a column that no longer exists.
    The USGS service's names are depth_num and event_time_utc_date_fmt (the
    seeder-era depth_km / time_utc are gone); mag, place, felt, tsunami and sig
    survive by name. Column names are lowercased on ingest as always.
  * Refresh is MANUAL-ONLY in Community - the codebase registers no periodic
    tasks at all (platform/refresh/credentials.py). The demo therefore needs an
    external cron calling --refresh-quakes; nothing refreshes on its own.
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
  * fill-pattern takes a builtin sprite id ('geolens-fill-hatch' and four
    siblings, FILL_PATTERN_IDS in layer-adapters/fill-pattern-images.ts) and
    rides in PAINT. The builder makes fill-color and fill-pattern mutually
    exclusive and stashes the colour in builder.fillColorSaved, but the API
    accepts BOTH, and paint's fill-color then wins as the pattern tint - which
    is what an API-authored layer wants (verified live).
  * folderGroupId / folderGroupName / folderGroupExpanded are style_config
    .BUILDER keys (not top-level style_config), and grouping is expressed by
    layers SHARING one group id. The server canonicalizes builder keys to
    snake_case on save, so what comes BACK is folder_group_id whichever
    spelling went in - this script writes the snake_case form, like every other
    builder key it sets, so a read and a write compare directly.
  * An unknown style_config.builder key is accepted silently (no validation) -
    a typo is a no-op, never a 422. Same failure mode as render_mode.
  * Map name is settable via the ordinary PUT /maps/{id}. Builders skip a map
    by NAME, so renaming one needs a rename-aware lookup (old name present +
    new name absent -> PUT the rename) or the next run builds a duplicate.
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
  * basemap_config is NOT merged server-side. PUT /maps/{id} dumps the whole
    submodel, so every field you omit is rewritten to its DEFAULT - a
    {"projection": "globe"} PUT silently resets label_mode, opacity,
    background_color and sublayer_overrides. Read the stored config first and
    PUT it back with the one key changed (apply_globe_projection).
  * basemap_config is additive-or-422 (extra="forbid"): one unknown key rejects
    the WHOLE config, and projection takes only "mercator" | "globe".
  * The analysis API has NO attribute filter - not on preview, not on
    materialize. To analyse a subset (the Cat 3+ legs here) you ingest that
    subset as its own dataset first.
  * Analysis is POST /datasets/{id}/analysis/materialize/ -> {job_id}; poll
    /jobs/{job_id} and read dataset_id off the terminal job, exactly like an
    ingest. Materialize registers the output PRIVATE - PATCH it public or a
    public map cannot show it.
  * Provenance is redacted per requester (visible_derived_from): if any dataset
    in the chain is not visible to the viewer, derived_from is dropped whole
    rather than stubbed. Every intermediate must be public or the anonymous
    visitor sees an empty provenance panel - which is the one thing the
    Hurricane Exposure map exists to show.
  * Analysis input ceilings that bite here: an intersect OVERLAY layer is
    capped at 1,000 features (hence one buffered corridor per storm, not per
    leg), intersect sources at 100k, dissolve at 250k, buffer at 500k, and a
    buffer distance at 100 km exactly.
  * intersect refuses two layers sharing ANY column name, and reserves
    source_gid; dissolve reserves source_count and groups by a single column.
"""

import argparse
import csv
import io
import json
import os
import re
import sys
import time

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
# USGS "Recent Earthquakes" ArcGIS MapServer, layer 0 = "M2.5+ Recent
# Earthquakes" (rolling 30-day window, ~2,300 features, OID field OBJECTID;
# public domain). Bound as a LIVE SERVICE rather than downloaded, so the demo
# refreshes through the server instead of being re-uploaded.
#
# M2.5+ and not M4.5+ deliberately: the connector has no server-side filter
# (where=1=1 is hardcoded), so the choice is this whole layer or none of it.
# The wider feed is the better demo anyway - ~2,300 points instead of ~500 give
# the heatmap and the graduated circles something to actually show.
USGS_QUAKES_SERVICE = (
    "https://earthquake.usgs.gov/arcgis/rest/services/eq/Recent_Earthquakes/MapServer/0"
)
# Natural Earth (public domain), pinned tag v5.1.2 for reproducibility.
NE_BASE = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/"
)
NE_COUNTRIES = NE_BASE + "ne_50m_admin_0_countries.geojson"
NE_PLACES = NE_BASE + "ne_50m_populated_places.geojson"
NE_ADMIN1 = NE_BASE + "ne_50m_admin_1_states_provinces.geojson"
# The 1:10m admin-1 file, and 1:50m is NOT a substitute for it here: at 1:50m
# Natural Earth subdivides only NINE large countries (Russia, the USA, India,
# Indonesia, China, Brazil, Canada, Australia, South Africa), so the Caribbean
# and Central America - the whole heart of hurricane alley - have no admin-1
# polygons at all. Verified against the pinned file: 294 features, 9 countries.
# The 1:10m file is a ~39 MB one-off download that filters to ~480 basin
# regions across 47 countries and ~3 MB ingested.
NE_ADMIN1_10M = NE_BASE + "ne_10m_admin_1_states_provinces.geojson"
NE_RIVERS = NE_BASE + "ne_50m_rivers_lake_centerlines.geojson"
NE_LAKES = NE_BASE + "ne_50m_lakes.geojson"
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
# NOAA NHC HURDAT2 Atlantic best-track database (plain text, public domain),
# now through the 2025 season. The filename embeds the release date - update it
# when NHC cuts a new revision, and note that NHC changed the suffix format
# from MMDDYY (040425) to MMDDYYYY (02272026) with this release, so a script
# that pattern-matched the old six-digit form will not find the new file.
# A bump here only reaches an existing instance through --refresh-hurdat2:
# a plain seed reuses both track datasets by title and never re-downloads.
HURDAT2_ATLANTIC = "https://www.nhc.noaa.gov/data/hurdat/hurdat2-1851-2025-02272026.txt"
# Atlantic hurricane basin coastline window (W, S, E, N) for the exposure map's
# admin polygons: Gulf of Mexico, Caribbean, Bahamas, the US/Canadian eastern
# seaboard, Bermuda and the northern coast of South America. Cut from the
# Natural Earth admin-1 file rather than downloaded separately - it is the same
# pinned public-domain source the catalog datasets use. Deliberately generous:
# it only bounds what is OFFERED to the intersect, and the intersect itself
# decides what is actually coastal by keeping the regions a storm corridor
# reaches. An inland province in range that no major storm touched simply does
# not survive.
ATLANTIC_BASIN_BBOX = (-105.0, 5.0, -40.0, 50.0)
# 100 km, the analysis API's MAX_BUFFER_METERS exactly. Wide enough that the
# damaging quadrant of a major hurricane reaches the coast in the buffer,
# narrow enough that the exposed regions stay a coastal ribbon.
EXPOSURE_BUFFER_METERS = 100_000
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

# --- renamed showcase content -------------------------------------------------
# Titles and map names that CHANGED after instances were already seeded. Each
# pair is (current, legacy): every lookup tries the current name first and falls
# back to the legacy one, then renames what it found. One run migrates a live
# instance; every run after that finds the current name and does nothing.
#
# Renames are not cosmetic here. Both of these were claims that went false:
# the quakes feed became M2.5+ when it moved to the live USGS service, and
# "75 Years" stopped being true the moment the 2025 season landed. The new
# hurricane name carries no year count at all so it cannot rot again.

# The quakes datasets. The heatmap counterpart is deliberately NOT renamed - its
# title never named a magnitude, so there is nothing in it to go stale (only its
# summary mentioned M4.5+, and that is corrected in SHOWCASE_METADATA).
QUAKES_TITLE = "Recent Earthquakes (M2.5+, last 30 days)"
QUAKES_TITLE_LEGACY = "Recent Earthquakes (M4.5+, last 30 days)"
QUAKES_HEAT_TITLE = "Recent Earthquakes - Heatmap source"

HURRICANE_MAP = "Hurricane Alley - Major Atlantic Storms Since 1950"
HURRICANE_MAP_LEGACY = "Hurricane Alley - 75 Years of Major Atlantic Storms"

# The two HURDAT2 track datasets. Titles are stable (neither carries a year
# count), but --refresh-hurdat2 resolves both by title, so they are named once.
HURDAT2_TRACKS_TITLE = "Atlantic Hurricane Tracks (HURDAT2, majors since 1950)"
HURDAT2_LEGS_TITLE = "Major Hurricane Tracks (Cat 3+ legs, one per storm)"

# --- map descriptions that must survive a rename or a re-seed ------------------
# A map description is written at CREATE time and never again, so a builder that
# skips an existing map leaves whatever text was there when the instance was
# first seeded. Restless Earth's said M4.5+ and a downloaded feed, both of which
# stopped being true when the quakes moved to the live M2.5+ service - and this
# text is what the catalog and any shared-map view show. Defined here so the
# builder and the migration pass write the same words.
MAP_DESCRIPTIONS: dict[str, str] = {
    "Restless Earth": (
        "Thirty days of M2.5+ earthquakes, read live from the USGS service, and "
        "6,000 years of deadly volcanic eruptions, on the tectonic plate "
        "boundaries that spawn them - solid where plates collide, dashed where "
        "they spread and slide - over the real relief of the planet (ETOPO "
        "2022). Watch the mid-Atlantic ridge line up with the dashed divergent "
        "boundary. Click anything, or open Ask AI: which quakes triggered "
        "tsunami warnings? What was the deadliest eruption? Sources: USGS, "
        "NOAA NCEI, PB2002 (Bird 2003), Natural Earth."
    ),
}

# Dataset summaries for the two quake bindings. Written by exactly ONE thing,
# the origin-gated enrichment pass, and never at creation - a summary describing
# a live service must not exist before the binding does. A fresh dataset is
# committed with _SERVICE_STUB_SUMMARY, which claims nothing, and these arrive
# once origin proves the conversion landed. That also repairs an instance seeded
# before the service conversion, which would otherwise keep telling visitors
# these are M4.5+ downloads forever.
QUAKE_SUMMARIES: dict[str, str] = {
    QUAKES_TITLE: (
        "Earthquakes of magnitude 2.5 and above from the last 30 days, read "
        "LIVE from the USGS Recent Earthquakes map service: magnitude, depth, "
        "felt reports, tsunami flag and USGS significance. Refreshes in place "
        "from the service rather than being re-uploaded. Source: USGS "
        "Earthquake Hazards Program (public domain)."
    ),
    QUAKES_HEAT_TITLE: (
        "The same live USGS M2.5+ earthquake feed as the graduated-circle "
        "dataset, bound separately so MapLibre renders it as its own "
        "magnitude-weighted heat surface on the Restless Earth map. Source: "
        "USGS Earthquake Hazards Program (public domain)."
    ),
}

# --- the quake layers' service vocabulary --------------------------------------
# Defined once because TWO places write them: build_restless_earth when it
# creates the map, and the styling pass when it repairs a map that already
# exists. An instance seeded before the service conversion carries layers whose
# popup still lists depth_km and time_utc - columns the service does not have
# and a refresh will never bring back - so the stored styles have to be
# migrated, not just written correctly for new maps. Two copies of these values
# would drift the moment one was edited.
QUAKE_POPUP_FIELDS = [
    "depth_num",
    "event_time_utc_date_fmt",
    "felt",
    "tsunami",
    "sig",
]
QUAKE_POPUP_CONFIG = {
    "enabled": True,
    "expression": "M{mag} - {place}",
    "visible_fields": QUAKE_POPUP_FIELDS,
}
# Ramp from 2.5, the floor of the live service's feed. It used to start at 4,
# the floor of the old M4.5+ download; left there, every quake in the 2.5-4
# band - most of the ~2,300 - pins to the same minimum weight and the surface
# grades by density alone instead of by magnitude.
QUAKE_HEATMAP_WEIGHT = [
    "interpolate",
    ["linear"],
    ["to-number", ["get", "mag"], 0],
    2.5,
    0.05,
    8,
    1,
]

# --- externally pinned content -------------------------------------------------
# These four are referenced from OUTSIDE this repo by UUID or by the table name
# their title derives (the subway lines dataset backs `data.nyc_subway_lines_mta`,
# the meteorites dataset backs `data.meteorite_landings_meteoritical_society`).
# A metadata PATCH is safe; a retitle, delete or re-ingest is NOT - it breaks the
# external reference silently. --prune-userdata hard-keeps them regardless of
# owner, and nothing here may be added to RETIRED_DATASETS.
#
# What the DATASET pin does not cover: --force still ingests a fresh copy under
# a NEW id (_get_or_ingest), because re-ingest is what --force means everywhere
# in this file. Only the map pin below overrides --force. So a forced re-seed of
# one of these titles needs the examples' fixtures.json updated with the new
# collection id afterwards - the pin keeps a prune from taking it, not you.
#
# fix(#1607): before editing any list in this section, or re-ingesting a showcase
# dataset, diff it against geolens-examples `ci/fixtures.json` and the map UUIDs
# in that repo's `index.html`. Those are the list of what the examples actually
# load; this section only mirrors it, and the examples' own preflight
# (`ci/check-fixtures.mjs`) going red is the only signal today that it drifted.
PINNED_DATASET_TITLES = (
    "NYC Subway Lines (MTA)",  # title derives data.nyc_subway_lines_mta - NEVER rename
    "NYC Subway Stations (MTA)",
    "swissALTI3D Matterhorn DEM (2m mosaic)",
    # fix(#1607): maplibre/features-viewport.html opens on this one and pages it
    # by viewport, the vector-tile handoff reads its MVT by table name, and
    # search/catalog.html's fixture expects "space rocks that fell to earth" to
    # find it - a re-ingest under a new id breaks all three at once.
    "Meteorite Landings (Meteoritical Society)",
)

# Pinned titles the seeder did NOT create and expects a VISITOR to own.
# fix(#1487): MNMAP_PLUTO is hand-uploaded on the demo, and the geolens-examples
# MCP transcripts quote it, so a prune that deletes it breaks a published
# walkthrough - the dry run behind #1487 listed it for deletion, which is what
# this tuple exists to prevent. A separate tuple rather than an entry above because
# the two classes carry OPPOSITE ownership expectations: the three above are
# admin-created, so a foreign copy is by definition a title-squatter and is
# reported as one; for these, foreign ownership IS the expected state, and no
# ownership signal can tell the genuine visitor upload from a squatting one -
# so every dataset bearing the title is hard-kept and counted as pinned, and
# over-keeping a squatter is the accepted cost (deleting the real one breaks
# the walkthrough; keeping a fake one frees nothing).
PINNED_FOREIGN_DATASET_TITLES = ("MNMAP_PLUTO",)

# fix(#1607): maps the examples address by an id THIS seeder minted, so the row
# itself has to survive - a map of the same name built beside it is not the same
# map. geolens-examples deep-links three from its gallery and embeds the fourth
# by share token:
#
#   Restless Earth                    /m/NDuwpSJc3yx4Exic5Na48xO-8bpjWiaIofJefpjqfbU
#   Manhattan - A Century of Skyline  /maps/dcae16bd-40bd-494e-bf2f-cfb378735257
#   The Matterhorn in 3D              /maps/1c5e021a-8ede-4ebe-a06c-92322208de45
#   New York From Orbit               /maps/1c4207ab-b1c0-4309-9924-c1ea355003a3
#
# Building one of these again mints a fresh uuid and leaves the share tokens on
# the row they were minted against, so every link above keeps resolving to the
# OLD map while the seeder's later passes work on the new one - and nothing
# inside this repo can see that. So: --force KEEPS a pinned map that already
# exists (_keep_existing_map), --prune and --prune-userdata hard-keep it, and no
# path that keeps a map re-mints or revokes its share/embed tokens.
#
# --force-pinned lifts the pin, and only that. It does not replace the pinned
# row: the builder then behaves exactly as --force does for any other map, which
# for every builder except build_sentinel2 means create_map() beside the row that
# is already there (build_sentinel2 deletes the stale rows under the same name
# first, so there the old row and its links do go). The surviving row keeps the
# uuid and the share token the links above use until someone prunes or deletes
# it by hand. An operator who uses the flag therefore has to move the references
# in geolens-examples (ci/fixtures.json, index.html) onto the new ids, or keep
# the old row and let the new one sit beside it.
PINNED_MAP_NAMES = (
    "Restless Earth",
    "Manhattan - A Century of Skyline",
    "The Matterhorn in 3D",
    "New York From Orbit - Sentinel-2, by Reference",
)

# --- globe projection ---------------------------------------------------------
# The showcase maps whose story is GLOBAL, where Mercator actively misleads:
# plate boundaries and quake belts, the worldwide meteorite scatter, and storm
# tracks curving across an ocean basin. The regional maps (Manhattan, the
# Matterhorn, New York From Orbit) are deliberately absent - a globe buys a
# city or a massif nothing and costs the viewer a familiar frame.
#
# This is the ONE place the set is written down, and apply_globe_projection
# reads it after the builders run rather than each builder setting its own
# camera field. Builders skip a map that already exists, so a creation-time
# setting would never reach an instance that was seeded before this landed -
# which is every instance that matters, including the live demo.
GLOBE_PROJECTION_MAPS = (
    "Restless Earth",
    "Everything That Fell From the Sky",
    HURRICANE_MAP,
)


# --- API helpers -------------------------------------------------------------


class Api:
    def __init__(self, base_url: str, token: str):
        self.base = base_url.rstrip("/")
        self.client = httpx.Client(timeout=180.0, follow_redirects=True)
        self.h = {"Authorization": f"Bearer {token}"}
        # This token's identity as the SERVER has it, not as it was typed on
        # the command line: the two lookups below scope to what this account
        # owns, and a login spelling that differs from the stored username
        # would match nothing - and "none of my content exists" is exactly what
        # makes every builder rebuild from scratch. Both keys are kept because
        # the two list endpoints expose different ones: datasets carry the
        # owner's uuid (created_by), maps only the display name
        # (created_by_username). Trailing slash required
        # (redirect_slashes=False).
        r = self.client.get(f"{self.base}/api/auth/me/", headers=self.h)
        r.raise_for_status()
        me = r.json()
        self.username = me["username"]
        self.user_id = me["id"]
        self.roles = me.get("roles") or []

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
            # Terminal status is "complete" (not "completed"). "cancelled" is
            # terminal too and is NOT a success: an analysis job loses its lease
            # if the worker dies, and without this the seeder waited out the
            # whole timeout for a job that had already stopped.
            if j.get("status") in ("complete", "failed", "cancelled"):
                if j["status"] != "complete":
                    raise RuntimeError(
                        f"job {job_id} {j['status']}: {j.get('error_message')}"
                    )
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
        self.reupload_commit(dataset_id, job)
        self.poll(job)

    def reupload_commit(self, dataset_id: str, job_id: str) -> None:
        """Commit a staged reupload. Shared by the file and the service paths -
        both stage into the same job and swap through the same door."""
        self.client.post(
            f"{self.base}/api/datasets/{dataset_id}/reupload/{job_id}/commit",
            headers=self.h,
            json={},
        ).raise_for_status()

    # --- live service bindings -------------------------------------------------

    def probe_service(self, url: str) -> dict:
        """Ask the server what a remote service exposes.

        Returns {service_type, url, layers[], selected_layer_id}. Two fields of
        the response are load-bearing downstream: `url` is NORMALIZED (probing
        .../MapServer/0 returns .../MapServer), and `selected_layer_id` echoes
        the layer number that was in the input URL. Send both back verbatim.
        """
        r = self.client.post(
            f"{self.base}/api/services/probe/", headers=self.h, json={"url": url}
        )
        r.raise_for_status()
        return r.json()

    # NOTE: there is no wrapper for POST /services/preview/ (stage a NEW
    # dataset from a service layer) on purpose. It permits only one dataset per
    # owner+service+layer and 409s on a second, and this seeder binds one USGS
    # layer twice - so every dataset it creates goes through the conversion
    # door instead. See ingest_service.

    def service_reupload_preview(self, dataset_id: str, body: dict) -> dict:
        """Stage a service binding over an EXISTING dataset (same body shape as
        service_preview). Returns {job_id, schema_diff, ...}; the swap itself
        happens at reupload_commit and preserves the dataset id."""
        r = self.client.post(
            f"{self.base}/api/datasets/{dataset_id}/reupload/service/preview",
            headers=self.h,
            json=body,
        )
        r.raise_for_status()
        return r.json()

    def refresh_dataset(self, dataset_id: str) -> dict:
        """Re-pull a dataset from its OWN stored origin binding.

        The body carries no source pointer by design - the server reads where
        the data comes from off the dataset, so this cannot re-point anything.
        Returns {run_id, job_id, origin_kind, trigger, ...}; the run is the
        durable history row the Source panel shows, the job is what to poll.
        """
        r = self.client.post(
            f"{self.base}/api/datasets/{dataset_id}/refresh",
            headers=self.h,
            json={},
        )
        r.raise_for_status()
        return r.json()

    def create_map(self, name: str, description: str) -> str:
        r = self.client.post(
            f"{self.base}/api/maps",
            headers=self.h,
            json={"name": name, "description": description},
        )
        r.raise_for_status()
        return r.json()["id"]

    def list_maps(self) -> dict[str, str]:
        """This account's OWN maps, name -> id, newest-created match winning.

        A map name is not a key, and three separate things follow from that
        (fix(#1404 review)):

        * Keep the FIRST match and only maps this account created. `--force`
          creates a SECOND map with the same name rather than replacing the
          first, and an admin token sees every user's maps, so a plain
          name->id comprehension resolves to whichever duplicate the page
          happened to end on. That is the same rule datasets_by_title already
          applies to titles for the same reason (fix(#389)) - the maps side
          just never had a caller that MUTATED what it resolved. It does now:
          _map_exists would read a stranger's map as "already built", prune
          would delete it, and apply_globe_projection would project it while
          the real showcase map stayed Mercator.
        * Sort by created_at, not the endpoint's updated_at default. The
          default order is mutable - apply_globe_projection's own PUT bumps
          updated_at and reshuffles the list - so it cannot answer which
          duplicate is the one this seeder just made.
        * PAGINATE, exactly like list_own_datasets: a single limit=200 page
          silently hides a showcase map once an instance crosses 200 maps, and
          every caller reads that absence as "not built yet".
        """
        out: dict[str, str] = {}
        seen = 0
        while True:
            r = self.client.get(
                f"{self.base}/api/maps?limit=200&skip={seen}"
                "&sort_by=created_at&sort_dir=desc",
                headers=self.h,
            )
            r.raise_for_status()
            d = r.json()
            page = d.get("maps", d.get("items", []))
            for m in page:
                if m.get("created_by_username") == self.username:
                    out.setdefault(m["name"], m["id"])
            # Count ROWS SEEN, not entries kept - the owner filter drops rows,
            # so len(out) would stall the loop short of the last page.
            seen += len(page)
            total = d.get("total")
            if not page or total is None or seen >= total:
                return out

    def list_own_datasets(self) -> list[dict]:
        """This account's OWN datasets, PAGINATED.

        Paginated because this seeder alone creates ~85 datasets (62 DEM tiles
        + vectors + scenes), and a single limit=200 page would silently hide
        older titles once an instance crosses 200, breaking every title-based
        reuse/refresh path.

        Scoped to `created_by` for the same reason list_maps is scoped
        (fix(#1404 review)): a title is not a key, an admin token sees every
        user's datasets, and all three callers here MUTATE what they resolve.
        Unscoped, _get_or_analyze would publish and rewrite the summary of a
        stranger's same-titled dataset and then build the showcase chain on it,
        enrich_showcase_metadata would overwrite its license, and prune would
        delete it. Reusing someone else's dataset is not safe even read-only:
        they can make it private or delete it, and the public showcase map
        breaks with it.
        """
        out: list[dict] = []
        seen = 0
        while True:
            r = self.client.get(
                f"{self.base}/api/datasets?limit=200&skip={seen}", headers=self.h
            )
            r.raise_for_status()
            d = r.json()
            page = d.get("datasets", d.get("items", []))
            out.extend(x for x in page if x.get("created_by") == self.user_id)
            # Count ROWS SEEN, not rows kept - the owner filter drops rows, so
            # len(out) would end the loop before the last page.
            seen += len(page)
            total = d.get("total")
            if not page or total is None or seen >= total:
                return out

    def get_map(self, map_id: str) -> dict:
        r = self.client.get(f"{self.base}/api/maps/{map_id}", headers=self.h)
        r.raise_for_status()
        return r.json()

    def set_view(self, map_id: str, **fields) -> None:
        # PUT (not PATCH); bearing must be within [-180, 180]. Omitted scalars
        # are left alone, but a basemap_config that IS sent is replaced whole -
        # see apply_globe_projection.
        r = self.client.put(
            f"{self.base}/api/maps/{map_id}", headers=self.h, json=fields
        )
        r.raise_for_status()

    def analysis_materialize(
        self, dataset_id: str, operation: str, title: str, timeout: int = 1800, **params
    ) -> str:
        """Run a provenance-tracked analysis operation; return the new dataset.

        Same async shape as an ingest - the POST returns a job handle and the
        derived dataset_id only shows up on the terminal job. Generous default
        timeout: analysis runs at a deliberately lower queue priority than
        uploads, so a busy instance can leave one queued for a while.
        """
        r = self.client.post(
            f"{self.base}/api/datasets/{dataset_id}/analysis/materialize/",
            headers=self.h,
            json={"operation": operation, "title": title, **params},
        )
        r.raise_for_status()
        return self.poll(r.json()["job_id"], timeout=timeout)["dataset_id"]

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

    def delete_layer(self, map_id: str, layer_id: str) -> None:
        r = self.client.delete(
            f"{self.base}/api/maps/{map_id}/layers/{layer_id}", headers=self.h
        )
        r.raise_for_status()

    def list_all_maps(self) -> list[dict]:
        """EVERY map on the instance, not just this account's - the prune report
        exists to find what other people left behind. Paginated for the same
        reason list_maps is; see there."""
        out: list[dict] = []
        seen = 0
        while True:
            r = self.client.get(
                f"{self.base}/api/maps?limit=200&skip={seen}"
                "&sort_by=created_at&sort_dir=desc",
                headers=self.h,
            )
            r.raise_for_status()
            d = r.json()
            page = d.get("maps", d.get("items", []))
            out.extend(page)
            seen += len(page)
            total = d.get("total")
            if not page or total is None or seen >= total:
                return out

    def list_all_datasets(self) -> list[dict]:
        """EVERY dataset on the instance. Same rationale as list_all_maps."""
        out: list[dict] = []
        seen = 0
        while True:
            r = self.client.get(
                f"{self.base}/api/datasets?limit=200&skip={seen}", headers=self.h
            )
            r.raise_for_status()
            d = r.json()
            page = d.get("datasets", d.get("items", []))
            out.extend(page)
            seen += len(page)
            total = d.get("total")
            if not page or total is None or seen >= total:
                return out

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
        """This account's own datasets, title -> id, newest match winning.

        fix(#389): /api/datasets orders newest-first and titles are NOT unique
        - a --force reseed creates fresh datasets alongside same-titled
        predecessors. Keep the FIRST (newest) match so lookups resolve to the
        freshly created dataset, not a stale duplicate.

        Ownership scoping comes from list_own_datasets - see there for why a
        stranger's same-titled dataset must not resolve here.
        """
        out: dict[str, str] = {}
        for x in self.list_own_datasets():
            out.setdefault(x["title"], x["id"])
        return out

    def dataset_detail(self, dataset_id: str) -> dict:
        r = self.client.get(f"{self.base}/api/datasets/{dataset_id}", headers=self.h)
        r.raise_for_status()
        return r.json()

    def dataset_columns(self, dataset_id: str) -> set:
        """Column names of a dataset (from the detail endpoint's column_info)."""
        return {
            c["name"]
            for c in (self.dataset_detail(dataset_id).get("column_info") or [])
        }

    def dataset_feature_count(self, dataset_id: str) -> int | None:
        return self.dataset_detail(dataset_id).get("feature_count")

    def dataset_origin(self, dataset_id: str) -> str | None:
        """How the data entered the catalog: upload | postgis | service | stac |
        created. Computed server-side from source_format + record_type, not
        stored, and null for collections and VRTs."""
        return self.dataset_detail(dataset_id).get("origin")

    def list_collections(self) -> list[dict]:
        # Trailing slash required (redirect_slashes=False).
        r = self.client.get(f"{self.base}/api/catalog/collections/", headers=self.h)
        r.raise_for_status()
        return r.json().get("collections", [])

    def collections_by_name(self) -> dict[str, str]:
        """Map collection name -> id (name is UNIQUE in the catalog model)."""
        return {c["name"]: c["id"] for c in self.list_collections()}

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

    def update_collection(self, collection_id: str, **fields) -> None:
        # PATCH (no trailing slash on the item route, unlike the list route).
        r = self.client.patch(
            f"{self.base}/api/catalog/collections/{collection_id}",
            headers=self.h,
            json=fields,
        )
        r.raise_for_status()

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


def service_binding_body(api: Api, service_url: str) -> dict:
    """Probe a service URL and shape the request body both binding doors take.

    One function because /services/preview/ (new dataset) and
    /datasets/{id}/reupload/service/preview (convert an existing one) take the
    IDENTICAL body, and the fields all come from the probe rather than from
    anything the caller knows: sending a hand-written url or a guessed
    object_id_field is how pagination silently breaks on a big layer.
    """
    probe = api.probe_service(service_url)
    layers = probe.get("layers") or []
    if not layers:
        raise RuntimeError(f"service exposed no layers: {service_url}")
    selected = probe.get("selected_layer_id")
    layer = next(
        (x for x in layers if x.get("layer_id") == selected and selected is not None),
        layers[0],
    )
    return {
        "url": probe["url"],
        "service_type": probe["service_type"],
        "layer_name": layer["name"],
        "layer_title": layer.get("title"),
        "layer_id": layer.get("layer_id"),
        "object_id_field": layer.get("object_id_field"),
    }


def _print_schema_diff(diff: dict, indent: str = "    ") -> None:
    """Show what a staged service swap would do to the columns and row count.

    Worth printing rather than assuming: this is the moment a service quietly
    renames a column out from under a style, and the diff is the only place it
    is visible before the swap commits.
    """
    old, new = diff.get("row_count_old"), diff.get("row_count_new")
    delta = diff.get("row_count_delta")
    shown = f"{delta:+d}" if isinstance(delta, int) else "?"
    print(f"{indent}rows {old} -> {new} ({shown})")
    for label, key in (("+", "columns_added"), ("-", "columns_removed")):
        names = [c["name"] for c in (diff.get(key) or [])]
        if names:
            print(f"{indent}{label}columns: {', '.join(sorted(names))}")
    for tc in diff.get("type_changes") or []:
        print(
            f"{indent}~type {tc.get('name')}: {tc.get('old_type')} -> {tc.get('new_type')}"
        )


# A single throwaway point: the thing a brand-new service-bound dataset is
# created FROM. It never survives, and nothing ever reads it - the conversion
# that follows replaces the whole table before the dataset reaches a map.
_SERVICE_STUB_FC = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"placeholder": 1},
            "geometry": {"type": "Point", "coordinates": [0, 0]},
        }
    ],
}

# The summary a stub is COMMITTED with, and it claims nothing on purpose.
# Same class as the gated metadata and the gated map wording, on the one path
# neither of those covers: creation. A summary written here lands BEFORE the
# conversion that would make a live-service claim true, and the origin gates in
# enrich_showcase_metadata only decide whether to OVERWRITE a summary later -
# they cannot un-write one already committed. So a transient conversion failure
# on a fresh seed would leave a public dataset describing a live USGS service
# over a single placeholder point at Null Island. This text is true at the
# moment it is written and stays true if the binding never completes; the real
# description arrives from QUAKE_SUMMARIES once origin proves the binding.
_SERVICE_STUB_SUMMARY = (
    "Earthquake data; binding to the live USGS Recent Earthquakes service."
)


def ingest_service(api: Api, service_url: str, title: str, timeout: int = 900) -> str:
    """Create a NEW dataset bound to a live service layer, by CONVERSION.

    The obvious door is POST /services/preview/, and it cannot be used here.
    It allows one dataset per (owner, service_type, url, layer) and refuses a
    second import of the same layer with 409 `duplicate_source` (the
    existing_stmt guard in sources/router.py). The showcase binds this one USGS
    layer TWICE on purpose, once for the graduated circles and once for the
    heatmap surface, so the second import would always fail. The reupload
    conversion door carries no such guard; both behaviours were verified live.

    So a new dataset is created as a one-point stub and immediately converted.
    The title is the real one from the first write, since it is the idempotency
    key every later lookup depends on, and the conversion swaps every row before
    the dataset is layered onto a map.

    The SUMMARY is not, and this function takes no summary parameter at all. The
    one it would be handed describes a live service, and it would be committed a
    step before that became true - so a transient conversion failure would leave
    a public dataset making a claim nothing downstream can retract, because the
    origin gates in enrich_showcase_metadata choose whether to overwrite a
    summary and cannot un-write one. Making the caller unable to pass a summary
    removes the mistake instead of trusting every future caller to avoid it. The
    real description arrives from the origin-gated enrichment pass later in the
    same run.

    Both datasets go through this, rather than importing the first properly and
    converting only the second. Any "the first one imports" rule breaks as soon
    as only the OTHER dataset exists - delete the circles dataset on a seeded
    instance and the import collides with the heatmap's binding instead. One
    path has no such edge.
    """
    print(f"  binding {title} to the live service...")
    dataset_id = api.ingest_geojson(
        "service_stub.geojson",
        json.dumps(_SERVICE_STUB_FC).encode(),
        title,
        _SERVICE_STUB_SUMMARY,
        timeout=timeout,
    )
    convert_to_service(api, dataset_id, service_url, title, timeout=timeout)
    return dataset_id


def convert_to_service(
    api: Api, dataset_id: str, service_url: str, label: str, timeout: int = 900
) -> bool:
    """Re-point an existing dataset at a live service, IN PLACE.

    Idempotent by the dataset's own origin: a dataset already reading from a
    service is left alone, so this is safe to run on every seed. Returns True
    when it actually converted something.

    In place is the whole point. The swap happens server-side against a staging
    table, so the dataset id, the record id, the physical table name and every
    map layer pointing at it all survive - a converted showcase dataset needs no
    map rewiring, and the demo's URLs keep working.
    """
    if api.dataset_origin(dataset_id) == "service":
        print(f"  [ok] {label} already reads from a live service")
        return False
    print(f"  converting {label} to a live service binding...")
    body = service_binding_body(api, service_url)
    staged = api.service_reupload_preview(dataset_id, body)
    _print_schema_diff(staged["schema_diff"])
    api.reupload_commit(dataset_id, staged["job_id"])
    api.poll(staged["job_id"], timeout=timeout)
    return True


def refresh_and_report(
    api: Api, dataset_id: str, label: str, timeout: int = 900
) -> bool:
    """Ask the server to re-pull one dataset from its origin, and say how it went.

    Best-effort per dataset: one dataset whose upstream is briefly down must not
    abort a refresh sweep over the others.
    """
    try:
        run = api.refresh_dataset(dataset_id)
        api.poll(run["job_id"], timeout=timeout)
    except (
        httpx.HTTPStatusError,
        httpx.TimeoutException,
        RuntimeError,
        TimeoutError,
    ) as e:
        # Surface the API's structured refusal code (e.g. origin_unavailable
        # vs refresh_not_applicable) - the bare httpx status line hides the
        # difference between "binding incomplete" and "wrong dataset kind",
        # which is the difference between re-importing and giving up.
        detail = ""
        if isinstance(e, httpx.HTTPStatusError):
            try:
                body = e.response.json().get("detail")
                if isinstance(body, dict) and body.get("code"):
                    detail = f" [{body['code']}]"
            except (ValueError, KeyError):
                pass
        print(f"  ! refresh FAILED for {label}: {e}{detail}", file=sys.stderr)
        return False
    # The refresh SUCCEEDED at this point. The count is decoration on the log
    # line, so it gets its own guard: letting a transient failure here escape
    # would report a completed refresh as failed, and worse, this helper is
    # called from refresh_sentinel2_scenes outside main()'s builder isolation,
    # where an exception would abort an otherwise finished seed and skip every
    # remaining scene.
    try:
        n = api.dataset_feature_count(dataset_id)
    except (httpx.HTTPStatusError, httpx.TimeoutException):
        n = "?"
    print(f"  refreshed {label} from its {run['origin_kind']} origin ({n} features)")
    return True


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


def _hurdat2_storms() -> list[tuple[str, int, list[dict]]]:
    """Parse the HURDAT2 best-track text into (name, season, fixes) tuples.

    Shared by every HURDAT2 feed below so the record layout is read in exactly
    one place: the format is positional and undocumented in the file itself, so
    a second copy of this parser is a second thing to keep correct.
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
    return storms


def _hurdat2_leg_is_sane(a: dict, b: dict) -> bool:
    """Reject bogus position jumps between two consecutive fixes.

    There are none in the Atlantic basin, but a malformed row would otherwise
    draw a line across the map - and, on the exposure map, buffer a 100 km
    corridor along it.
    """
    return abs(a["lng"] - b["lng"]) <= 90 and abs(a["lat"] - b["lat"]) <= 30


def hurdat2_feed(min_year: int = 1950, min_peak_kt: int = 96) -> tuple[bytes, int, int]:
    """NOAA HURDAT2 Atlantic best tracks -> per-6h-SEGMENT LineString GeoJSON.

    Keeps storms from `min_year` whose peak intensity reached `min_peak_kt`
    (96 kt = Cat 3, "major hurricane"). Each segment carries the storm name,
    season, status, wind, pressure and Saffir-Simpson category AT that leg, so
    a single track changes color/width as the storm intensifies and decays.
    Returns (geojson_bytes, n_storms, n_segments).
    """
    feats, n_storms = [], 0
    for name, year, fixes in _hurdat2_storms():
        if year < min_year or not fixes:
            continue
        if max(f["wind"] for f in fixes) < min_peak_kt:
            continue
        n_storms += 1
        for a, b in zip(fixes, fixes[1:]):
            if not _hurdat2_leg_is_sane(a, b):
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


def hurdat2_major_leg_feed(
    min_year: int = 1950, min_kt: int = 96
) -> tuple[bytes, int, int]:
    """HURDAT2 -> ONE MultiLineString per storm, holding only its Cat 3+ legs.

    The buffer input for the Hurricane Exposure map, and shaped by two hard
    constraints rather than by taste:

    * The analysis API has no attribute filter, so "the Category 3+ segments"
      has to exist as its own dataset before it can be buffered.
    * A buffer is 1:1, and the buffered corridors are then the OVERLAY layer of
      an intersect, which is capped at 1,000 features. One feature per STORM
      (~260 since 1950) stays comfortably inside that; one per 6-hour leg
      (~1,900) would too, but it would also make the intersect emit one row per
      leg, and then a region's row count would be "legs that reached me", not
      "storms that reached me" - which is the number the map grades on.

    A leg is Cat 3+ when the fix it starts at is, the same rule the Hurricane
    Alley map colors by, so these are exactly that map's orange-through-magenta
    legs. Returns (geojson_bytes, n_storms, n_legs).
    """
    feats, n_legs = [], 0
    for name, year, fixes in _hurdat2_storms():
        if year < min_year or not fixes:
            continue
        legs = [
            [[a["lng"], a["lat"]], [b["lng"], b["lat"]]]
            for a, b in zip(fixes, fixes[1:])
            if a["wind"] >= min_kt and _hurdat2_leg_is_sane(a, b)
        ]
        if not legs:
            continue
        n_legs += len(legs)
        peak = max(f["wind"] for f in fixes)
        feats.append(
            {
                "type": "Feature",
                "properties": {
                    "name": name,
                    "season": year,
                    "peak_wind_kt": peak,
                    "peak_category": _sshs(peak),
                    "major_legs": len(legs),
                    "landfall": 1 if any(f["landfall"] for f in fixes) else 0,
                },
                "geometry": {"type": "MultiLineString", "coordinates": legs},
            }
        )
    fc = {"type": "FeatureCollection", "features": feats}
    return json.dumps(fc).encode(), len(feats), n_legs


def _geom_bbox(geom: dict) -> tuple[float, float, float, float] | None:
    """(minx, miny, maxx, maxy) of a GeoJSON geometry, or None if it has no
    coordinates. Natural Earth carries no per-feature bbox, so it is walked."""
    xs: list[float] = []
    ys: list[float] = []

    def walk(coords) -> None:
        if coords and isinstance(coords[0], (int, float)):
            xs.append(coords[0])
            ys.append(coords[1])
            return
        for part in coords or ():
            walk(part)

    walk((geom or {}).get("coordinates") or [])
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def coastal_regions_feed() -> tuple[bytes, int]:
    """Natural Earth admin-1 -> the Atlantic-basin regions, as intersect input.

    Two output columns only, and the names matter: intersect REFUSES two layers
    that share any column name, and the overlay side carries the HURDAT2 track
    columns (name, season, peak_wind_kt, peak_category, major_legs, landfall).
    So the admin-1 name lands as `region`, never as `name`.

    `region` is also the dissolve key, which groups on a single column, so it
    has to identify a region on its own: names repeat across countries (there
    is more than one Cordoba), and two regions sharing a name would dissolve
    into one polygon holding both. Repeats are qualified with their country;
    unique names are left clean so the popup reads "Florida", not
    "Florida (United States of America)".
    """
    fc = json.loads(fetch(NE_ADMIN1_10M))
    west, south, east, north = ATLANTIC_BASIN_BBOX
    kept = []
    for feat in fc["features"]:
        box = _geom_bbox(feat.get("geometry") or {})
        if box is None:
            continue
        minx, miny, maxx, maxy = box
        if maxx < west or minx > east or maxy < south or miny > north:
            continue
        p = feat["properties"]
        name = p.get("name") or p.get("name_en") or p.get("gn_name")
        country = p.get("admin")
        if not name or not country:
            continue
        kept.append((feat, str(name), str(country)))

    seen: dict[str, int] = {}
    for _, name, _country in kept:
        seen[name] = seen.get(name, 0) + 1
    feats = []
    for feat, name, country in kept:
        feats.append(
            {
                "type": "Feature",
                "properties": {
                    "region": name if seen[name] == 1 else f"{name} ({country})",
                    "country": country,
                },
                "geometry": feat["geometry"],
            }
        )
    return json.dumps({"type": "FeatureCollection", "features": feats}).encode(), len(
        feats
    )


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


def _keep_existing_map(
    name: str, exists: bool, force: bool, force_pinned: bool
) -> bool:
    """Whether a builder must leave the map row that is already there alone.

    fix(#1607). Pure - no API call, no printing - so the whole truth table is
    testable, and ONE function rather than a condition spelled out in each
    builder, so a builder added later cannot quietly grow its own rule and drop
    a pinned map's uuid on the floor:

        not exists                      -> False  build it
        exists, no force                -> True   the long-standing skip
        exists, force, not pinned       -> False  --force means recreate
        exists, force, pinned           -> True   its id/share token are
                                                  addressed from outside this
                                                  repo (PINNED_MAP_NAMES)
        exists, force, pinned, override -> False  --force-pinned

    False on that last line means only that this function stops holding the
    builder back, and what the builder does with that freedom is not uniform.
    For every builder but build_sentinel2 it is create_map() beside the
    existing row, so after --force --force-pinned the old map is still there,
    still holding the uuid and the share token geolens-examples links, while
    the name resolves to the fresh row; moving those references onto the new
    ids, or deleting the old row, is the operator's job. build_sentinel2 is the
    exception in BOTH directions: this same False sends it through the
    stale-map loop, which deletes every row under the name - and their share
    links - before rebuilding, so there --force-pinned really does destroy the
    externally referenced uuid.

    True is likewise not the whole story for one caller. Six of the seven
    builders that own a pinned-eligible map treat True as "return, do nothing",
    which is right for them: their layers point at datasets this seeder can
    refresh in place, so there is no repair a rebuild would perform that a
    plain re-run does not. build_sentinel2 is different - its layers point at
    scenes imported BY REFERENCE, and `--only sentinel2 --force` is the
    documented repair for an instance seeded before item_href was sent. So it
    reads this True as "keep the ROW", not "do nothing": it runs the whole
    force path and rebinds the existing map's layers in place
    (_replace_map_layers), which is the only shape that repairs the scenes
    without minting the new uuid --force-pinned would (fix(#1607 review r2)).
    """
    if not exists:
        return False
    if not force:
        return True
    return name in PINNED_MAP_NAMES and not force_pinned


def _announce_kept_map(name: str, force: bool, note: str = "") -> str:
    """The one line a builder prints when _keep_existing_map said keep.

    Returns the marker the builder returns, so the sentence printed here and
    the outcome main() reports cannot drift apart: a pinned keep is "(pinned)"
    and an ordinary skip is "(skipped)". They read the same to a builder and
    differently to the operator, which is the point - "use --force to recreate"
    is the opposite of what --force does to a pinned map
    (fix(#1607 review r2)).

    Separate from the decision so that stays pure. The force case has to name
    the flag that lifts the pin: an operator who typed --force and watched
    nothing happen will otherwise go delete the map by hand, which is the exact
    outcome the pin exists to prevent. It also has to say what the flag really
    does, because "recreate" would be a promise this seeder does not keep - the
    builder builds a fresh row and leaves this one standing. That is true of
    every builder that reaches this line: build_sentinel2, whose --force-pinned
    path does delete the row, never prints it under force (it repairs instead
    of returning), so the sentence cannot be read against the wrong map.
    """
    if force:
        print(
            f"  [pinned] {name} kept as-is: geolens-examples addresses this map "
            "by id (see PINNED_MAP_NAMES). --force-pinned lifts the pin, which "
            "builds a FRESH map beside this one; this row keeps its id and "
            "share links until you move those references or delete it"
        )
        return "(pinned)"
    print(f"  [skip] {name} already exists{note}")
    return "(skipped)"


def _rename_map_if_needed(api: Api, name: str, legacy: str) -> None:
    """Migrate a map that was created under an older name.

    Builders skip by NAME, so a rename without this leaves the old map sitting
    there under its old name while the builder happily creates a second one
    beside it - two Hurricane Alleys, one of them stale, on every instance that
    was seeded before the rename. Renaming only when the old name exists AND the
    new one does not keeps that from happening in either direction.
    """
    maps = api.list_maps()
    if legacy in maps and name not in maps:
        api.set_view(maps[legacy], name=name)
        print(f"  renamed map {legacy!r} -> {name!r}")


def _replace_map_layers(api: Api, map_id: str, layers: list[dict]) -> int:
    """Swap a map's whole layer stack, leaving the map ROW alone.

    fix(#1607 review r2). This is what lets build_sentinel2 repair a pinned map
    under plain --force: a layer points at a dataset id, the scene re-import
    mints new ids, and the map's uuid and share tokens have to survive because
    geolens-examples addresses them. Delete-then-add is the only shape that
    rebinds the stack without a new map row.

    Deleting the scene datasets already cascades their layers away
    (MapLayer.dataset_id is ON DELETE CASCADE), so the delete pass here is not
    usually the one doing the work - it is what catches the layers that did NOT
    cascade, i.e. the ones whose scene was deliberately kept because another
    map shares it. Skipping the pass would leave those beside the fresh stack
    as duplicates.

    Returns the number of layers added.
    """
    for layer in api.get_map(map_id).get("layers", []):
        api.delete_layer(map_id, layer["id"])
    for body in layers:
        api.add_layer(map_id, body)
    return len(layers)


def _rows_to_rebind(newest: str | None, retained: list[str]) -> list[str]:
    """Every map row a pinned repair has to rebind, primary first, deduped.

    fix(#1607 review r4). `retained` is every same-named row the force path
    kept instead of deleting; `newest` is the one list_maps() resolves, which
    is what the seeder's other passes target and therefore the primary. They
    overlap in the ordinary case and must not be rebound twice.

    Older duplicates exist because --force used to stack a second map beside
    the first rather than replacing it. They are not cosmetic here: the scene
    deletion cascades EVERY retained row's layers away at once, so a row left
    unrebound keeps its uuid and becomes an EMPTY map. Guessing which
    duplicate the examples link is not possible from inside this repo, and it
    does not have to be - the loop that kept them already knows all their ids,
    so all of them get the fresh stack.
    """
    rows: list[str] = []
    for row_id in ([newest] if newest else []) + retained:
        if row_id not in rows:
            rows.append(row_id)
    return rows


def _rebind_pinned_rows(
    api: Api, rows: list[str], name: str, layers: list[dict], view: dict
) -> str:
    """Give every row in `rows` the same fresh layer stack and view.

    fix(#1607 review r4). Returns the primary (rows[0]) - the id the builder
    reports and the rest of the seeder resolves. Rebinding is deliberately not
    conditional on a row being a duplicate: an empty map and a stale map fail
    the same way for whoever follows the link, and the work is one small
    request per row.
    """
    for index, row_id in enumerate(rows):
        _replace_map_layers(api, row_id, layers)
        api.set_view(row_id, **view)
        warn_if_hidden_layers(api, row_id, name)
        if index:
            print(f"  [pinned] also rebound duplicate row {row_id}")
    return rows[0]


def _find_under_either_title(
    by_title: dict, title: str, legacy: str | None
) -> tuple[str | None, bool]:
    """Locate a dataset under its current title or the one it used to have.

    Finding and RENAMING are deliberately separate steps. A live instance was
    seeded under the old title and a plain lookup on the new one would miss it
    and ingest a duplicate alongside - but the rename must not happen until
    whatever the new title CLAIMS is actually true. See _adopt_title.

    Returns (dataset_id, found_under_legacy_title).
    """
    if title in by_title:
        return by_title[title], False
    if legacy and legacy in by_title:
        return by_title[legacy], True
    return None, False


def _adopt_title(api: Api, by_title: dict, dataset_id: str, title: str, legacy: str):
    """Move a dataset onto its new title, once the new title is true of it.

    Called only AFTER the work the title describes has succeeded. The title is
    not cosmetic here: it is the key SHOWCASE_METADATA is looked up by, so
    renaming first would have the enrichment pass write "read LIVE from the
    USGS service, M2.5+" over a dataset still holding the old M4.5 upload if
    the conversion between the two failed. The builders are isolated so one
    failure cannot kill a seed, which means the passes downstream run either
    way - so the rename has to be the last step, not the first.
    """
    api.patch_dataset(dataset_id, title=title)
    by_title[title] = dataset_id
    by_title.pop(legacy, None)
    print(f"  retitled {legacy!r} -> {title!r}")


def ensure_quake_datasets(api: Api, by_title: dict) -> tuple[str, str]:
    """The two earthquake datasets, bound to the live USGS service.

    Idempotent on every axis that can differ between instances:

    * A fresh instance has neither, and both are created straight from the
      service (no download, no upload).
    * A live instance has them under the OLD M4.5+ title holding UPLOADED
      GeoJSON. The title migrates first, then the data binding converts in
      place - dataset ids and map layers survive both, so the Restless Earth
      map keeps working through the upgrade without being touched.
    * An already-converted instance hits neither path and pays one GET each.

    --force does NOT reach here, deliberately. Everywhere else force means
    "re-ingest instead of reusing", but there is nothing to re-download from a
    service binding, and creating a second pair would orphan the datasets the
    Restless Earth map's layers point at. A stale binding is fixed by
    converting, which this already does on every run. fix(#1607): the map row
    is pinned for the same shape of reason - the examples embed it by share
    token, and a token belongs to a map id.

    Returns (circles_dataset_id, heatmap_dataset_id).
    """
    out: list[str] = []
    for title, legacy in (
        (QUAKES_TITLE, QUAKES_TITLE_LEGACY),
        (QUAKES_HEAT_TITLE, None),
    ):
        ds, under_legacy = _find_under_either_title(by_title, title, legacy)
        if ds is None:
            ds = ingest_service(api, USGS_QUAKES_SERVICE, title)
            by_title[title] = ds
        else:
            # Convert BEFORE renaming. If this raises, the dataset keeps its old
            # title, so the enrichment and styling passes downstream - which run
            # regardless, because builders are isolated - find no entry for it
            # and leave its M4.5 summary alone rather than advertising a live
            # M2.5 service over unconverted uploaded data.
            convert_to_service(api, ds, USGS_QUAKES_SERVICE, title)
            if under_legacy:
                _adopt_title(api, by_title, ds, title, legacy)
        out.append(ds)
    return out[0], out[1]


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


def _get_or_analyze(
    api: Api,
    by_title: dict,
    title: str,
    source_id: str,
    operation: str,
    summary: str,
    force: bool = False,
    timeout: int = 1800,
    **params,
) -> str:
    """Reuse a derived dataset by title, or compute it through the analysis API.

    The `_get_or_ingest` contract for the operations that BUILD data instead of
    uploading it, with one extra step: materialize registers its output PRIVATE
    and titled but summary-less, so the result is published and described here.
    Publishing every link is not cosmetic - provenance is redacted per viewer,
    and one private dataset anywhere in the chain blanks the panel for the
    anonymous visitor the showcase exists for.
    """
    if not force and title in by_title:
        print(f"  [reuse] {title}")
        ds = by_title[title]
    else:
        print(f"  {operation} -> {title}...")
        ds = api.analysis_materialize(
            source_id, operation, title, timeout=timeout, **params
        )
    # On BOTH paths, not just after a fresh materialize: a run that died between
    # the job completing and this line would otherwise leave a private,
    # summary-less dataset that every later run happily reuses.
    api.patch_dataset(ds, visibility="public", summary=summary)
    by_title[title] = ds
    return ds


# --- prune ----------------------------------------------------------------------


def prune(api: Api) -> None:
    """Delete the retired first-generation showcase content by exact name."""
    print("\n[prune] removing retired first-generation showcase content")
    maps = api.list_maps()
    for name in RETIRED_MAPS:
        if name not in maps:
            continue
        # fix(#1607): the retired and pinned lists are meant to be disjoint -
        # both pin tuples say so in words - but this is a delete keyed on a
        # name, so it checks instead of trusting the comment. Same below for
        # the titles.
        if name in PINNED_MAP_NAMES:
            print(f"  = kept, externally pinned (map): {name}")
            continue
        api.delete_map(maps[name])
        print(f"  - map: {name}")
    for d in api.list_own_datasets():
        if d["title"] in RETIRED_DATASETS:
            if d["title"] in PINNED_DATASET_TITLES + PINNED_FOREIGN_DATASET_TITLES:
                print(f"  = kept, externally pinned (dataset): {d['title']}")
                continue
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


# --- maintenance entry points ------------------------------------------------
# Each returns a process exit code and is terminal: main() runs one and exits.


def refresh_quakes(api: Api) -> int:
    """Re-pull both earthquake datasets from the USGS service they are bound to.

    Thin by design - the server owns everything about WHERE the data comes from,
    so this is two POSTs and two polls. Nothing is downloaded here and no
    geometry crosses the wire from this machine.

    This is the demo's cron job: Community registers no refresh scheduler, so
    "last 30 days" only stays true because something outside the app calls this.
    """
    print("Refreshing the earthquake datasets from their USGS service binding...")
    by_title = api.datasets_by_title()
    failed = 0
    for title, legacy in (
        (QUAKES_TITLE, QUAKES_TITLE_LEGACY),
        (QUAKES_HEAT_TITLE, None),
    ):
        ds, under_legacy = _find_under_either_title(by_title, title, legacy)
        if ds is None:
            # A failure, not a skip. This is the demo's cron entry point, so a
            # zero exit means "the quakes are current" to whatever is watching
            # it. Both datasets are required - the map has a circle layer and a
            # heatmap layer - so a missing one is a half-seeded instance that
            # needs a person, and it has to be visible as a non-zero exit.
            print(
                f"  ! no dataset titled {title!r} - the showcase is not fully "
                "seeded; run a normal seed",
                file=sys.stderr,
            )
            failed += 1
            continue
        origin = api.dataset_origin(ds)
        if origin != "service":
            # Refusing beats "refreshing" an upload-origin dataset into a 409:
            # this instance predates the service conversion and needs a seed run
            # (which converts in place) before a refresh means anything. No
            # rename either - the new title would claim a live service this
            # dataset is not yet reading from.
            print(
                f"  ! {title!r} still has origin {origin!r}, not 'service' - "
                "run a normal seed first to convert it",
                file=sys.stderr,
            )
            failed += 1
            continue
        # Origin proves the conversion already landed, so the new title is true
        # of this dataset now. A seed whose rename step failed after converting
        # is finished here rather than left half-migrated.
        if under_legacy:
            _adopt_title(api, by_title, ds, title, legacy)
        if not refresh_and_report(api, ds, title):
            failed += 1
    return 1 if failed else 0


def refresh_sentinel2_scenes(api: Api) -> None:
    """Refresh every imported Sentinel-2 scene from its STAC origin.

    Run at the end of a normal seed rather than as its own flag. The scenes are
    stac-origin and therefore refreshable, and firing one refresh each gives the
    Source panel a real run history to show - which is the point: a scene that
    has never been refreshed displays an empty panel, and the by-reference story
    this map exists to tell is exactly that the data is not a local copy.

    Best-effort and never fatal: this runs after everything is already built.
    """
    scenes = [
        d for d in api.list_own_datasets() if d["title"].startswith("Sentinel-2 TCI ")
    ]
    if not scenes:
        return
    print(f"\nRefreshing {len(scenes)} Sentinel-2 scenes from their STAC origin...")
    for d in scenes:
        refresh_and_report(api, d["id"], d["title"])


def refresh_hurdat2(api: Api) -> int:
    """Pull a new HURDAT2 release into the tracks, then rebuild what derives.

    Two different refresh mechanics, because the datasets are two different
    kinds of thing:

    * The two TRACK datasets are uploads, so they swap in place and keep their
      ids - the Hurricane Alley map and the exposure map's legs layer are
      untouched by this.
    * The three DERIVED datasets cannot be refreshed at all. Materialize always
      registers a NEW dataset, so there is no in-place door: a replacement
      chain is computed BESIDE the old one, the map layer is swapped onto it,
      and only then is the superseded chain deleted. The exposure MAP survives
      with its id intact, and a failure anywhere in the rebuild leaves the map
      untouched rather than half-torn-down.
    """
    print("Re-fetching HURDAT2 and rebuilding the derived exposure chain...")
    by_title = api.datasets_by_title()
    tracks_ds = by_title.get(HURDAT2_TRACKS_TITLE)
    legs_ds = by_title.get(HURDAT2_LEGS_TITLE)
    if tracks_ds is None or legs_ds is None:
        print(
            "  ! the HURDAT2 track datasets are not seeded yet - run a normal "
            "seed before refreshing them",
            file=sys.stderr,
        )
        return 1

    data, n_storms, n_segs = hurdat2_feed()
    print(f"  {n_storms} major storms, {n_segs} track segments")
    api.reupload_geojson(tracks_ds, "atlantic_hurricanes.geojson", data)
    print(f"  refreshed in place: {HURDAT2_TRACKS_TITLE}")
    data, n_storms, n_legs = hurdat2_major_leg_feed()
    print(f"  {n_storms} major storms, {n_legs} Category 3+ legs")
    api.reupload_geojson(legs_ds, "hurricane_major_legs.geojson", data)
    print(f"  refreshed in place: {HURDAT2_LEGS_TITLE}")

    map_id = api.list_maps().get(EXPOSURE_MAP)
    if map_id is None:
        print(f"  [skip] no {EXPOSURE_MAP!r} map - refreshed the tracks only")
        return 0

    # BUILD FIRST, then swap, then delete. Deleting up front would leave the
    # public exposure map without its headline layer for as long as the rebuild
    # takes, and permanently if the rebuild failed - a worker outage or an
    # analysis error would strand the demo mid-operation. Building beside the
    # old chain means any failure below leaves the MAP exactly as it was.
    # The cost is that the three derived datasets exist twice for the length of
    # the rebuild, which matters only on an instance with a tight dataset quota.
    #
    # The layer being replaced is found by NAME, not by dataset id. A run that
    # died between materializing and swapping leaves newer same-titled datasets
    # behind, so a title lookup would return an id the map has never pointed at,
    # match no layer, and the retry would stack a second choropleth on top of
    # the first instead of replacing it.
    old_layer_ids = [
        layer["id"]
        for layer in api.get_map(map_id).get("layers", [])
        if layer.get("display_name") == EXPOSURE_LAYER_NAME
    ]

    try:
        chain = _build_exposure_chain(api, by_title, force_analysis=True)
    except (httpx.HTTPStatusError, httpx.TimeoutException, RuntimeError, TimeoutError):
        # The tracks are already swapped and the chain is not, so the map's legs
        # layer is a season ahead of its choropleth until this succeeds. That is
        # inherent: reupload has no staging handle to roll back, and the chain
        # can only be computed FROM the updated legs. Say so plainly rather than
        # let a stack trace imply the map is untouched - re-running is the fix,
        # and re-running is safe.
        print(
            "\n  ! the track data was replaced but the exposure chain was NOT "
            "rebuilt.\n  ! The exposure map now shows new storm legs against a "
            "choropleth computed\n  ! from the previous release. Re-run "
            "--refresh-hurdat2 to finish; it is idempotent.",
            file=sys.stderr,
        )
        raise

    # Swap: the new layer goes on before the old one comes off, so the map is
    # never without an exposure layer.
    api.add_layer(map_id, _exposure_layer_body(chain["exposure"]))
    for layer_id in old_layer_ids:
        api.delete_layer(map_id, layer_id)
    print(f"  swapped in the rebuilt exposure layer on map {map_id}")

    # Now delete every chain-titled dataset EXCEPT the three just built. That
    # covers the superseded chain and also any orphans a previously failed run
    # materialized and never swapped in - a plain "delete the old ids" would
    # leave those behind to accumulate one set per failed attempt.
    keep = {chain["corridors"], chain["pieces"], chain["exposure"]}
    superseded = [
        d
        for d in api.list_own_datasets()
        if d["title"] in EXPOSURE_CHAIN_TITLES and d["id"] not in keep
    ]
    # Reverse dependency order: each derives from the one before it, so the
    # children have to go before their parents.
    order = {title: i for i, title in enumerate(EXPOSURE_CHAIN_TITLES)}
    for d in sorted(superseded, key=lambda x: -order[x["title"]]):
        try:
            api.delete_dataset(d["id"], d["title"])
            print(f"  deleted the superseded derived dataset: {d['title']}")
        except httpx.HTTPStatusError as e:
            # Not fatal: the map is already correct, and a leftover dataset
            # shows up in --prune-userdata rather than being silently lost.
            print(
                f"  ! could not delete the superseded {d['title']!r}: {e}",
                file=sys.stderr,
            )
    # The three derived datasets are BRAND NEW, so they carry ingest defaults:
    # a "proprietary" license and no keywords or theme categories. Without this
    # every successful refresh would quietly undo Part 2's catalog work on
    # exactly the datasets whose provenance the exposure map exists to show.
    # This is a terminal maintenance mode, so it never reaches main()'s pass.
    print("\nRe-enriching the rebuilt chain's catalog metadata...")
    enrich_showcase_metadata(api)

    # The context layer's hatch and the map's legend/notes live in the styling
    # pass, which is idempotent - run it so the rebuilt map matches a fresh one.
    apply_showcase_styling(api)
    return 0


def _showcase_dataset_titles() -> set[str]:
    """Every dataset title this seeder creates, has created, or renames through.

    Used only to decide whether an ADMIN-owned dataset is recognised content or
    a stray worth reporting. Deliberately generous: over-recognising something
    just leaves it out of a report, while under-recognising it would put a
    hand-uploaded dataset on a list that reads like a deletion candidate.
    """
    titles = set(SHOWCASE_METADATA) | set(PINNED_DATASET_TITLES) | set(RETIRED_DATASETS)
    titles |= set(PINNED_FOREIGN_DATASET_TITLES)
    titles |= {QUAKES_TITLE, QUAKES_TITLE_LEGACY, QUAKES_HEAT_TITLE}
    titles |= {
        "World States & Provinces (Natural Earth 1:50m)",
        "Private Embed Demo - VIP Sites",
    }
    for _description, members in COLLECTIONS.values():
        titles |= set(members)
    return titles


# The seeder also makes datasets whose titles carry a per-item suffix: one per
# swissALTI3D DEM tile (~62) and one per imported Sentinel-2 scene.
_SHOWCASE_TITLE_PREFIXES = ("swissALTI3D 2m ", "Sentinel-2 TCI ")


def _showcase_map_names() -> set[str]:
    """Every map name this seeder creates or has created."""
    names = {
        "Restless Earth",
        "Manhattan - A Century of Skyline",
        HURRICANE_MAP,
        HURRICANE_MAP_LEGACY,
        EXPOSURE_MAP,
        "Everything That Fell From the Sky",
        "The Matterhorn in 3D",
        "New York From Orbit - Sentinel-2, by Reference",
        "Private Embed Demo",
    } | set(RETIRED_MAPS)
    # fix(#1607): the pinned names are folded in separately, so one of them can
    # never read as a stray if the literals above are ever edited apart from
    # PINNED_MAP_NAMES.
    return names | set(PINNED_MAP_NAMES)


def _classify_userdata(api: Api, known_maps: set, recognised) -> dict:
    """Sort every map and dataset on the instance into the prune buckets.

    Separated from the reporting so the RULE is readable on its own - which
    matters more here than anywhere else in this file, because the difference
    between two of these buckets is the difference between deleting a
    visitor's upload and deleting the operator's.

    Ownership decides, with one override: the externally pinned maps and
    datasets are pulled out FIRST and land in their own buckets whoever owns
    them, so no later branch can reach them.
    """
    foreign_maps, stray_maps, ownerless_maps = [], [], []
    pinned_maps, pinned_map_impostors = [], []
    for m in api.list_all_maps():
        if m.get("name") in PINNED_MAP_NAMES:
            # fix(#1607): first, whoever owns it, for the same reason as the
            # pinned datasets below - the examples address these by the uuid
            # this seeder minted, and one of them by share token, so the ROW
            # has to survive. A name is no more proof of identity than a title
            # is, so a copy under another account is kept as well and reported
            # apart, rather than hiding among the real four.
            if m.get("created_by_username") == api.username:
                pinned_maps.append(m)
            else:
                pinned_map_impostors.append(m)
        # A NULL owner is not evidence of anything. Both Map.created_by and
        # Record.created_by are ON DELETE SET NULL, so deleting a user strips
        # ownership from everything they made and leaves it looking exactly
        # like someone else's content to a "not mine" test. Deleting on that
        # signal would destroy an operator's own work the moment their account
        # was removed, which is the one outcome this command must never
        # produce. Reported and kept, for a person to decide.
        elif m.get("created_by_username") is None:
            ownerless_maps.append(m)
        elif m.get("created_by_username") != api.username:
            foreign_maps.append(m)
        elif m.get("name") not in known_maps:
            stray_maps.append(m)

    foreign_datasets, stray_datasets, pinned, pinned_impostors = [], [], [], []
    ownerless_datasets = []
    for d in api.list_all_datasets():
        if d.get("title") in PINNED_FOREIGN_DATASET_TITLES:
            # Hard-kept whoever owns it, and counted as genuinely pinned even
            # though the owner is not the admin: foreign ownership is this
            # class's EXPECTED state (see the tuple), so the impostor split
            # below would misfile the real dataset as a squatter and invite
            # the manual deletion the pin exists to prevent.
            # fix(#1487 review): deliberately BEFORE the null-owner branch - a
            # pinned dataset whose creator account was deleted must not land in
            # the ownerless "review by hand" list, which reads as a deletion
            # candidate. The report labels the null owner honestly instead.
            pinned.append(d)
        elif d.get("title") in PINNED_DATASET_TITLES:
            # Never in the delete set, whoever owns it. A title is not proof of
            # identity though: titles are explicitly non-unique here, so a
            # visitor can upload something called "NYC Subway Lines (MTA)" and
            # inherit the exemption. Keeping it is still the right default -
            # deleting the real one breaks an external reference, and the cost
            # of keeping a squatter is that it survives a cleanup - but it is
            # reported separately so it cannot hide among the genuine three.
            if d.get("created_by") == api.user_id:
                pinned.append(d)
            else:
                pinned_impostors.append(d)
        elif d.get("created_by") is None:
            # Same reasoning as the maps above: ownerless is unknown, not
            # foreign.
            ownerless_datasets.append(d)
        elif d.get("created_by") != api.user_id:
            foreign_datasets.append(d)
        elif not recognised(d.get("title", "")):
            stray_datasets.append(d)

    return {
        "foreign_maps": foreign_maps,
        "stray_maps": stray_maps,
        "ownerless_maps": ownerless_maps,
        "pinned_maps": pinned_maps,
        "pinned_map_impostors": pinned_map_impostors,
        "foreign_datasets": foreign_datasets,
        "stray_datasets": stray_datasets,
        "ownerless_datasets": ownerless_datasets,
        "pinned": pinned,
        "pinned_impostors": pinned_impostors,
    }


def _report_pinned_maps(pinned_maps: list, impostors: list) -> None:
    """The pinned-map half of the prune report (fix(#1607)).

    Its own function so prune_userdata does not grow two more loops for a rule
    _classify_userdata has already applied. Owner is printed for the impostors
    only: for the real four it is always the seeder, and saying so on every
    line would bury the one row that needs a person.
    """
    print(f"\n  externally pinned maps, hard-kept: {len(pinned_maps)}")
    for m in pinned_maps:
        print(f"    = {m.get('name')!r}")
    if impostors:
        print(
            f"\n  !! kept, but NOT the seeder's: {len(impostors)} map(s) carry a "
            "pinned name while belonging to another account. The examples link "
            "the seeder's ids, so keeping these frees nothing - review by hand:"
        )
        for m in impostors:
            owner = m.get("created_by_username") or "?"
            print(f"    ? {m.get('name')!r}  (owner: {owner})")


def prune_userdata(api: Api, execute: bool = False) -> int:
    """Report - and with --execute, delete - content this seeder did not create.

    DRY RUN BY DEFAULT. `--prune-userdata` prints the report and deletes
    nothing; `--prune-userdata --execute` performs it. The dry run is the
    normal way to use this, and the flag pair exists because the delete set is
    computed from live ownership data that nobody can eyeball in advance.

    What the sets mean, and why ownership rather than titles decides:

    * OTHER USERS' maps and datasets are the delete set. On a public demo these
      are visitor uploads, and a title tells you nothing about them.
    * ADMIN-owned content the seeder does not recognise is reported as a stray
      and KEPT. The live demo carries hand-uploaded datasets that predate this
      script, and deleting one because this file has never heard of it is
      exactly the accident this split prevents.
    * Pinned MAPS are hard-kept whoever owns them: PINNED_MAP_NAMES, which the
      examples repo deep-links by uuid and embeds by share token. Deleting one
      breaks a published page in a way nothing in this repo can see.
    * Pinned datasets are hard-kept whoever owns them: PINNED_DATASET_TITLES
      (referenced from outside this repo by id or by the table name their title
      derives) and PINNED_FOREIGN_DATASET_TITLES (visitor-uploaded content that
      published walkthroughs quote; foreign ownership is their expected state,
      so they count as pinned rather than as impostors).
    * Collections are reported only, never deleted - a collection is a label
      over datasets, so deleting one destroys curation while freeing nothing.

    Maps are deleted before datasets: a map layer is a live reference to a
    dataset, and the dataset delete fails while one exists.
    """
    mode = "DELETING" if execute else "DRY RUN - deleting nothing"
    print(f"\n[prune-userdata] {mode}")
    print(f"  seeder account: {api.username} ({api.user_id})")

    known_datasets = _showcase_dataset_titles()
    known_maps = _showcase_map_names()

    def recognised(title: str) -> bool:
        return title in known_datasets or title.startswith(_SHOWCASE_TITLE_PREFIXES)

    buckets = _classify_userdata(api, known_maps, recognised)
    foreign_maps = buckets["foreign_maps"]
    stray_maps = buckets["stray_maps"]
    foreign_datasets = buckets["foreign_datasets"]
    stray_datasets = buckets["stray_datasets"]
    pinned_hits = buckets["pinned"]
    pinned_impostors = buckets["pinned_impostors"]
    pinned_maps = buckets["pinned_maps"]
    pinned_map_impostors = buckets["pinned_map_impostors"]
    ownerless_maps = buckets["ownerless_maps"]
    ownerless_datasets = buckets["ownerless_datasets"]

    def report(label, rows, key, owner_key):
        print(f"\n  {label}: {len(rows)}")
        for r in rows[:50]:
            print(f"    - {r.get(key)!r}  (owner: {r.get(owner_key) or '?'})")
        if len(rows) > 50:
            print(f"    ... and {len(rows) - 50} more")

    report(
        "maps owned by other users (delete set)",
        foreign_maps,
        "name",
        "created_by_username",
    )
    report(
        "datasets owned by other users (delete set)",
        foreign_datasets,
        "title",
        "created_by",
    )
    report(
        "admin-owned maps not in the showcase set (kept)",
        stray_maps,
        "name",
        "created_by_username",
    )
    report("admin-owned strays (kept)", stray_datasets, "title", "created_by")
    report(
        "maps with no owner - creator account deleted (kept, review by hand)",
        ownerless_maps,
        "name",
        "created_by_username",
    )
    report(
        "datasets with no owner - creator account deleted (kept, review by hand)",
        ownerless_datasets,
        "title",
        "created_by",
    )

    _report_pinned_maps(pinned_maps, pinned_map_impostors)

    # Ownership is still worth SHOWING for the expected-foreign pins: they are
    # trusted, but a cleanup audit that never mentions a kept dataset belongs
    # to another account would be hiding the one fact the pin class encodes.
    # fix(#1487 review): a NULL owner is a deleted creator account, not a
    # visitor - label it as the unknown it is instead of calling it expected.
    # It stays hard-kept either way; only the words change.
    pinned_foreign = [
        d for d in pinned_hits if d.get("created_by") not in (api.user_id, None)
    ]
    pinned_ownerless = [d for d in pinned_hits if d.get("created_by") is None]
    print(f"\n  externally pinned, hard-kept: {len(pinned_hits)}")
    for d in pinned_hits:
        owner = d.get("created_by")
        if owner is None:
            print(f"    = {d.get('title')!r}  (ownerless - creator account deleted)")
        elif owner != api.user_id:
            print(f"    = {d.get('title')!r}  (visitor-owned - expected for this title)")
        else:
            print(f"    = {d.get('title')!r}")
    if pinned_impostors:
        print(
            f"\n  !! kept, but NOT the seeder's: {len(pinned_impostors)} dataset(s) "
            "carry a pinned title while belonging to another account. Titles are "
            "not unique, so these inherited the exemption. Review them by hand:"
        )
        for d in pinned_impostors:
            print(f"    ? {d.get('title')!r}  (owner: {d.get('created_by') or '?'})")

    showcase_collections = set(COLLECTIONS) | set(RETIRED_COLLECTIONS)
    other_collections = [
        n for n in api.collections_by_name() if n not in showcase_collections
    ]
    print(
        f"\n  non-showcase collections (reported only, never deleted): {len(other_collections)}"
    )
    for n in other_collections:
        print(f"    ? {n!r}")

    if not execute:
        print(
            f"\n  SUMMARY (dry run): would delete {len(foreign_maps)} maps and "
            f"{len(foreign_datasets)} datasets; would keep {len(stray_maps)} "
            f"admin-owned maps, {len(stray_datasets)} admin-owned strays, "
            f"{len(pinned_maps) + len(pinned_map_impostors)} pinned maps and "
            f"{len(pinned_hits) + len(pinned_impostors)} pinned-title datasets "
            f"({len(pinned_foreign)} expected visitor-owned, "
            f"{len(pinned_ownerless)} ownerless, "
            f"{len(pinned_impostors)} impostors) and "
            f"{len(ownerless_maps) + len(ownerless_datasets)} ownerless items. "
            "Nothing was deleted. "
            "Re-run with --execute to perform it."
        )
        return 0

    deleted_maps = deleted_datasets = 0
    errors = 0
    for m in foreign_maps:
        try:
            api.delete_map(m["id"])
            deleted_maps += 1
        except httpx.HTTPStatusError as e:
            print(f"  ! could not delete map {m.get('name')!r}: {e}", file=sys.stderr)
            errors += 1
    for d in foreign_datasets:
        try:
            api.delete_dataset(d["id"], d["title"])
            deleted_datasets += 1
        except httpx.HTTPStatusError as e:
            print(
                f"  ! could not delete dataset {d.get('title')!r}: {e}", file=sys.stderr
            )
            errors += 1
    print(
        f"\n  SUMMARY: deleted {deleted_maps}/{len(foreign_maps)} maps and "
        f"{deleted_datasets}/{len(foreign_datasets)} datasets; kept "
        f"{len(stray_maps)} admin-owned maps, {len(stray_datasets)} admin-owned "
        f"strays, {len(pinned_maps) + len(pinned_map_impostors)} pinned maps, "
        f"{len(pinned_hits) + len(pinned_impostors)} pinned-title "
        f"datasets ({len(pinned_foreign)} expected visitor-owned, "
        f"{len(pinned_ownerless)} ownerless, "
        f"{len(pinned_impostors)} impostors) and "
        f"{len(ownerless_maps) + len(ownerless_datasets)} ownerless items. "
        f"{errors} error(s)."
    )
    return 1 if errors else 0


# --- showcase builders -----------------------------------------------------------


def build_catalog(api: Api, force: bool = False, force_pinned: bool = False) -> str:
    """Catalog-only datasets - no maps. These exist to fuel the AI demos:

    * World Countries: rich numeric/categorical columns for AI add_layer /
      query_data ("GDP of Japan?", "color countries by income group").
    * NY income by county: the scripted AI-styling canvas - ask the AI to
      build the choropleth live instead of shipping a static one.
    * Admin-1 states/provinces committed SUMMARY-LESS: raw material for the
      AI metadata-generation demo.
    * Rivers + lakes: the water/hydrology searches every GIS user types first.
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
    # fix(#626): water/hydrology terms (water, water bodies, rivers, lakes,
    # hydrology) were the top zero-result organic searches on the public demo,
    # and the README's own `q=hydrology` curl returned nothing - the showcase
    # had no aquatic data at all. Both files are ~800 KB and public domain.
    _get_or_ingest(
        api,
        by_title,
        "World Rivers & Lake Centerlines (Natural Earth 1:50m)",
        "world_rivers.geojson",
        lambda: fetch(NE_RIVERS),
        "Major rivers and lake centerlines worldwide - the global surface "
        "hydrology network, named and scale-ranked. Source: Natural Earth "
        "1:50m (public domain).",
        force=force,
    )
    _get_or_ingest(
        api,
        by_title,
        "World Lakes & Reservoirs (Natural Earth 1:50m)",
        "world_lakes.geojson",
        lambda: fetch(NE_LAKES),
        "Lakes and reservoirs worldwide - named inland water bodies with "
        "scale rank. Source: Natural Earth 1:50m (public domain).",
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
    api: Api, force: bool = False, with_oceans: bool = True, force_pinned: bool = False
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
    print("\n[restless] Restless Earth (quakes + volcanoes + plates + relief)")
    by_title = api.datasets_by_title()

    # --- earthquakes (two datasets: circles + heatmap source) -----------------
    # Both read from the LIVE USGS service. GeoLens renders one MapLibre layer
    # per dataset, so the graduated-circle layer and the heatmap layer need the
    # same geometry bound twice - each binding refreshes independently.
    #
    # Bound BEFORE the map-exists skip below, exactly the way build_meteorites
    # heals its dataset ahead of its own skip, and for a sharper reason. Every
    # instance that matters already HAS this map, so a conversion sitting after
    # the skip would run on a fresh instance and never on the live demo - the
    # one place the upgrade is for. It would also deadlock the escape hatch:
    # --refresh-quakes refuses an upload-origin dataset and tells the operator
    # to run a normal seed, and that seed would take the early return.
    quakes_ds, heat_ds = ensure_quake_datasets(api, by_title)

    if _keep_existing_map(name, _map_exists(api, name), force, force_pinned):
        return _announce_kept_map(name, force, " (quake bindings brought current)")

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
                                # Recorded on the ingest job's manifest
                                # metadata, which is where a required source
                                # credit belongs in the provenance trail. Note
                                # it does NOT reach the viewer today: the
                                # backend stores it as job_metadata
                                # ["manifest_attribution"] and no map-layer
                                # response carries an attribution field, so
                                # nothing renders it over the tiles yet.
                                "attribution": "NOAA NCEI",
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
    map_id = api.create_map(name, MAP_DESCRIPTIONS[name])

    def mag_step(v0, v1, v2, v3):
        return ["step", ["to-number", ["get", "mag"], 0], v0, 5.0, v1, 6.0, v2, 7.0, v3]

    # Magnitude double-encoded: size AND color (the ramp deliberately matches
    # the heatmap stops so the two quake layers read as one visual system).
    quake_colors = ["#fecc5c", "#fd8d3c", "#f03b20", "#bd0026"]
    api.add_layer(
        map_id,
        {
            "dataset_id": quakes_ds,
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
            # Service column vocabulary, not the old seeder-derived one: every
            # refresh rebuilds column_info from the service, so depth_km and
            # time_utc are gone for good and these names are permanent.
            "popup_config": QUAKE_POPUP_CONFIG,
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
            "dataset_id": heat_ds,
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
                "heatmap-weight": QUAKE_HEATMAP_WEIGHT,
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


def build_manhattan(api: Api, force: bool = False, force_pinned: bool = False) -> str:
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
    if _keep_existing_map(name, _map_exists(api, name), force, force_pinned):
        return _announce_kept_map(name, force)
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


def build_hurricanes(api: Api, force: bool = False, force_pinned: bool = False) -> str:
    """The line-story hero: every major Atlantic hurricane since 1950 from
    NOAA HURDAT2, drawn as per-6-hour segments so each track changes color and
    width as the storm intensifies and decays.

    Capabilities on display nothing else shows: render_mode 'arrow'
    (direction-of-motion arrows along the track), per-segment categorical
    line color, data-driven line width, line-center name labels.
    """
    name = HURRICANE_MAP
    # Migrate before the exists-check, or the check misses the renamed map and
    # builds a duplicate next to it.
    _rename_map_if_needed(api, name, HURRICANE_MAP_LEGACY)
    if _keep_existing_map(name, _map_exists(api, name), force, force_pinned):
        return _announce_kept_map(name, force)
    print("\n[hurricanes] Hurricane Alley (HURDAT2 majors since 1950)")
    by_title = api.datasets_by_title()

    def tracks_bytes() -> bytes:
        data, n_storms, n_segs = hurdat2_feed()
        print(f"  ({n_storms} major storms, {n_segs} track segments)")
        return data

    tracks_ds = _get_or_ingest(
        api,
        by_title,
        HURDAT2_TRACKS_TITLE,
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


# Exposure classes. Four colors, three breaks - step_expr's shape - over the
# number of DISTINCT major storms whose 100 km corridor reached a region.
# Chosen against the real distribution rather than by equal interval, measured
# on the 289 exposed regions the chain produces (2026-08-11): the counts run
# 1-23 and pile up in the middle (54 regions sit on exactly 7), so an equal
# interval over that range would flatten the whole Caribbean into one shade.
# These split it 87 / 83 / 113 / 6, and the top class IS the story - the six
# regions clearing 10 are the Gulf rim: Florida (23), Quintana Roo (16),
# Louisiana (15), Yucatan (13), Tamaulipas (11) and Texas (10).
EXPOSURE_BREAKS = [3, 6, 10]
EXPOSURE_COLORS = ["#fed976", "#feb24c", "#f03b20", "#800026"]


# The exposure chain's dataset titles, in DEPENDENCY order (each derives from
# the one before). --refresh-hurdat2 deletes them in reverse.
EXPOSURE_CHAIN_TITLES = (
    "Major Hurricane Corridors (100 km buffer)",
    "Coastal Regions Inside a Major Hurricane Corridor",
    "Hurricane Exposure by Coastal Region",
)
EXPOSURE_MAP = "Hurricane Exposure - Which Coasts the Major Storms Reach"
# The graded layer's display name, and the only stable handle on it. A refresh
# has to find the layer it is REPLACING, and it cannot do that by dataset id:
# the id it would look for comes from a title lookup, and a refresh that died
# after materializing but before swapping leaves a NEWER dataset under the same
# title, so the lookup returns an id the map has never referenced. Matching the
# name finds the layer whatever it currently points at.
EXPOSURE_LAYER_NAME = "Distinct major storms since 1950"


def _build_exposure_chain(
    api: Api, by_title: dict, force: bool = False, force_analysis: bool = False
) -> dict:
    """Build (or reuse) the datasets behind the Hurricane Exposure map.

    Split out of the map builder because --refresh-hurdat2 needs exactly this
    and nothing else: the derived datasets CANNOT be refreshed in place -
    materialize always registers a NEW dataset - so a season update deletes
    them and runs this again, while the map itself survives. Two callers, one
    definition of the chain, so a parameter change cannot reach one and miss
    the other.

    `force_analysis` recomputes the three DERIVED datasets while leaving the
    two ingested inputs reused. --refresh-hurdat2 needs exactly that split: it
    has already swapped the tracks in place, so re-ingesting them would be
    wasted work, but it must build a replacement chain BESIDE the old one
    rather than deleting first. Titles collide during that window, which is
    fine - datasets_by_title keeps the newest match - and the old ids are
    captured by the caller before this runs.

    Returns the five dataset ids by role.
    """

    def major_legs_bytes() -> bytes:
        data, n_storms, n_legs = hurdat2_major_leg_feed()
        print(f"  ({n_storms} major storms, {n_legs} Category 3+ legs)")
        # The corridors buffered from these become the intersect OVERLAY, which
        # is capped at 1,000 features. ~260 storms today; the 422 would be
        # clear, but a heads-up beats reading it off a failed job.
        if n_storms > 1000:
            print(
                f"  ! WARNING: {n_storms} storms exceeds the 1,000-feature "
                "overlay cap; the intersect will be refused",
                file=sys.stderr,
            )
        return data

    legs_ds = _get_or_ingest(
        api,
        by_title,
        HURDAT2_LEGS_TITLE,
        "hurricane_major_legs.geojson",
        major_legs_bytes,
        "Every Atlantic hurricane since 1950 that reached Category 3, reduced "
        "to the legs where it WAS Category 3 or stronger and merged into one "
        "track per storm. Peak wind, peak category and landfall flag per "
        "storm. Source: NOAA NHC HURDAT2 (public domain).",
        force=force,
        timeout=600,
    )

    def regions_bytes() -> bytes:
        data, n = coastal_regions_feed()
        print(f"  ({n} admin-1 regions in the Atlantic basin window)")
        return data

    regions_ds = _get_or_ingest(
        api,
        by_title,
        "Atlantic Basin Regions (Natural Earth admin-1)",
        "atlantic_basin_regions.geojson",
        regions_bytes,
        "States, provinces, parishes and island territories around the "
        "Atlantic hurricane basin - the Gulf of Mexico, the Caribbean, the "
        "eastern seaboard and the northern coast of South America. Source: "
        "Natural Earth admin-1, 1:10m (public domain).",
        force=force,
    )

    corridors_ds = _get_or_analyze(
        api,
        by_title,
        EXPOSURE_CHAIN_TITLES[0],
        legs_ds,
        "buffer",
        "The area within 100 km of a Category 3+ hurricane track, one corridor "
        "per storm. Computed in GeoLens with a geodesic buffer over the "
        "Category 3+ legs of the NOAA HURDAT2 best-track database.",
        force=force or force_analysis,
        distance_meters=EXPOSURE_BUFFER_METERS,
    )
    pieces_ds = _get_or_analyze(
        api,
        by_title,
        EXPOSURE_CHAIN_TITLES[1],
        regions_ds,
        "intersect",
        "One feature per region-and-storm pair: the part of an Atlantic basin "
        "region that fell inside a single major hurricane's 100 km corridor. "
        "Computed in GeoLens by intersecting the admin-1 regions with the "
        "buffered corridors.",
        force=force or force_analysis,
        mask_dataset_id=corridors_ds,
    )
    exposure_ds = _get_or_analyze(
        api,
        by_title,
        EXPOSURE_CHAIN_TITLES[2],
        pieces_ds,
        "dissolve",
        "The coastal footprint of every Atlantic basin region reached by a "
        "major hurricane since 1950, with source_count holding the number of "
        "DISTINCT Category 3+ storms that reached it. Computed in GeoLens by "
        "dissolving the region-by-storm intersections back to one feature per "
        "region.",
        force=force or force_analysis,
        by_field="region",
    )
    return {
        "legs": legs_ds,
        "regions": regions_ds,
        "corridors": corridors_ds,
        "pieces": pieces_ds,
        "exposure": exposure_ds,
    }


def _exposure_layer_body(exposure_ds: str) -> dict:
    """The graded exposure layer, as one reusable body.

    A function rather than a literal inside the builder because --refresh-hurdat2
    DELETES this layer (its dataset is replaced, not refreshed) and re-adds it.
    Re-adding through add_layer with the whole body, rather than PATCHing the
    existing layer, is deliberate: the layer-diff path has a known
    style-clobbering hazard, and a full POST cannot half-apply a style.
    """
    return {
        "dataset_id": exposure_ds,
        "sort_order": 0,
        "opacity": 1.0,
        "display_name": EXPOSURE_LAYER_NAME,
        "style_config": {
            "mode": "graduated",
            "column": "source_count",
            "ramp": "YlOrRd",
            "method": "manual",
            "breaks": EXPOSURE_BREAKS,
            "colors": EXPOSURE_COLORS,
            "colorLabel": "Distinct major storms",
        },
        "paint": {
            "fill-color": step_expr("source_count", EXPOSURE_BREAKS, EXPOSURE_COLORS),
            # Opaque enough to read as a choropleth, sheer enough that the
            # storm legs below still show through the darkest classes.
            "fill-opacity": 0.78,
            "fill-outline-color": "#7f1d1d",
        },
        "popup_config": {
            "enabled": True,
            "expression": "{region}",
            "visible_fields": ["source_count"],
        },
    }


def build_hurricane_exposure(
    api: Api, force: bool = False, force_pinned: bool = False
) -> str:
    """The analysis hero: the only showcase map that is a computed RESULT.

    Three real operations, each one a provenance-tracked derived dataset:

        Cat 3+ legs  --buffer 100 km-->  corridors
        coastal regions  --intersect corridors-->  exposed pieces
        exposed pieces  --dissolve by region-->  EXPOSURE

    The dissolve is what turns the pair rows into the map's number. Intersect
    emits exactly one row per (region, corridor) pair, and one corridor is one
    storm, so dissolve's generated `source_count` counts distinct major storms
    per region - while its union collapses that region's overlapping pieces
    into the single coastal footprint the fill is drawn on.

    Nothing here is styled by hand-computed data: open any of the three derived
    datasets and its provenance panel names the operation, the parameters and
    the layer it came from. That is the thing on display.
    """
    name = EXPOSURE_MAP
    if _keep_existing_map(name, _map_exists(api, name), force, force_pinned):
        return _announce_kept_map(name, force)
    print("\n[hurricane-exposure] buffer -> intersect -> dissolve (HURDAT2 majors)")
    by_title = api.datasets_by_title()
    chain = _build_exposure_chain(api, by_title, force=force)
    legs_ds, exposure_ds = chain["legs"], chain["exposure"]

    map_id = api.create_map(
        name,
        "Which coastlines the Atlantic's major hurricanes actually reach, and "
        "how often. Built entirely inside GeoLens from the NOAA HURDAT2 best "
        "tracks: the Category 3+ legs of every storm since 1950 buffered by "
        "100 km, intersected with the region boundaries, then dissolved so "
        "each region carries the number of distinct major storms that came "
        "within that corridor. Darker means more storms. Open the exposure "
        "layer's dataset and its provenance panel replays the whole chain - "
        "buffer, intersect, dissolve - with the parameters each step ran on.",
    )
    # Exposure ON TOP (the viewer draws LOWER sort_order on top), the legs that
    # generated it underneath, so the map reads as cause and effect: this
    # storm track produced that coastal footprint.
    api.add_layer(map_id, _exposure_layer_body(exposure_ds))
    api.add_layer(
        map_id,
        {
            "dataset_id": legs_ds,
            "sort_order": 1,
            "opacity": 1.0,
            "display_name": "Category 3+ storm legs (the buffered input)",
            "paint": {
                "line-color": "#1e293b",
                "line-width": ["interpolate", ["linear"], ["zoom"], 2, 0.8, 7, 2.6],
                "line-opacity": 0.75,
            },
            "layout": {"line-cap": "round", "line-join": "round"},
            "popup_config": {
                "enabled": True,
                "expression": "{name} ({season})",
                "visible_fields": ["peak_category", "peak_wind_kt", "major_legs"],
            },
        },
    )
    api.set_view(
        map_id,
        visibility="public",
        center_lng=-72,
        center_lat=25,
        zoom=3.2,
        pitch=0,
        bearing=0,
        basemap_style="openfreemap-positron",
        show_basemap_labels=True,
    )
    warn_if_hidden_layers(api, map_id, name)
    print(f"  -> map {map_id}")
    return map_id


def build_meteorites(api: Api, force: bool = False, force_pinned: bool = False) -> str:
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
            print(
                f"  dataset has {fc} features (capped-era seed) - swapping in the full feed..."
            )
            api.reupload_geojson(
                by_title[met_title], "meteorite_landings.geojson", meteorites_bytes()
            )

    if _keep_existing_map(name, _map_exists(api, name), force, force_pinned):
        return _announce_kept_map(name, force)

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


def build_matterhorn(api: Api, force: bool = False, force_pinned: bool = False) -> str:
    """The terrain hero: 3D mesh + hillshade + hypsometric tint from a VRT
    mosaic of swissALTI3D 2m lidar COGs, with dashed alpine climbing routes
    (white-cased, the classic Swiss-map convention) and labeled peaks."""
    name = "The Matterhorn in 3D"
    if _keep_existing_map(name, _map_exists(api, name), force, force_pinned):
        return _announce_kept_map(name, force)
    print("\n[matterhorn] The Matterhorn (3D terrain via regional VRT mosaic)")
    by_title = api.datasets_by_title()
    vrt_title = "swissALTI3D Matterhorn DEM (2m mosaic)"
    # fix(#1508): the DEM mosaic and its 62 tile rasters are reused even under
    # --force. The manifest endpoint refuses updates to existing raster
    # datasets ("Manifest raster updates are not supported"), so a forced
    # re-push aborted the whole builder before the map and OSM overlay steps —
    # which made --force useless for exactly the repair it exists for
    # (restoring the routes/peaks layers). Recreating the tiles for real would
    # mean deleting 62 datasets and re-downloading gigabytes; --force keeps
    # meaning "rebuild the MAP" here, like the vector builders rebuild cheap
    # datasets but nobody re-pulls ETOPO.
    if vrt_title in by_title:
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
                        # swisstopo OGD requires the source credit on display.
                        # Recorded in the manifest provenance for now - see the
                        # ETOPO note above: nothing renders it over the tiles
                        # yet, so the credit still has to be met elsewhere.
                        "attribution": "© swisstopo",
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


def build_sentinel2(api: Api, force: bool = False, force_pinned: bool = False) -> str:
    """The by-reference hero: recent low-cloud Sentinel-2 true color over NYC,
    streamed straight from the AWS open-data COGs - zero download at seed
    time; Titiler needs S3 egress at VIEW time.

    Alone among the builders this one does NOT return early on a pinned keep.
    `--only sentinel2 --force` is the documented repair for an instance seeded
    before item_href was sent, and this map is pinned, so an early return would
    leave that repair reachable only through --force-pinned - the one flag that
    mints the new uuid the examples must not get. Instead the pin is honoured
    by REUSING the row: the force preflight, the scene deletion and the STAC
    import all run exactly as they do without a pin, and only create_map is
    skipped, in favour of rebinding the existing map's layers in place
    (fix(#1607 review r2))."""
    name = "New York From Orbit - Sentinel-2, by Reference"
    keep_pinned_row = _keep_existing_map(
        name, _map_exists(api, name), force, force_pinned
    )
    if keep_pinned_row and not force:
        # The ordinary already-built skip; nothing to repair.
        return _announce_kept_map(name, force)
    if keep_pinned_row:
        print(
            f"  [pinned] {name} will be REPAIRED in place: its scenes are "
            "re-imported and its layers rebound, and the map keeps its id and "
            "share links (--force-pinned would DELETE this row and its share "
            "links first, then rebuild - this map is the one pinned map where "
            "the override destroys the id rather than leaving it behind)"
        )
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
                # feat(#1222): the item's rel=self link. The backend records it
                # as origin_ref.item_href, which is what makes the dataset
                # REFRESHABLE - without it every refresh 409s origin_unavailable.
                # The in-app import flow captures this server-side via the
                # search proxy; this direct-import path must supply it itself.
                # None-tolerant: a catalog that publishes no self link still
                # imports, it just cannot refresh (and the seed-end refresh
                # pass reports exactly that).
                "item_href": next(
                    (
                        link.get("href")
                        for link in f.get("links", [])
                        if link.get("rel") == "self"
                    ),
                    None,
                ),
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
    # href -> own dataset id for holdings the force preflight proved the
    # skip-fallback can use; consulted before the by-title fallback because
    # titles are NOT unique (see datasets_by_title) and the newest same-titled
    # row is not necessarily the row holding the asset (round 8).
    resolved_by_href: dict[str, str] = {}
    # Same-named rows the loop below kept instead of deleting. Every one of
    # them loses its layers to the scene cascade, so every one is rebound
    # (fix(#1607 review r4)).
    retained_rows: list[str] = []
    if force:
        # fix(#1493 review round 8): the shared-scene and conflict scans
        # below must see EVERY map and dataset. --username can select a
        # non-admin account, and non-admin listings are visibility-filtered -
        # a stranger's PRIVATE map layering one of these public scenes would
        # be invisible to the round-5 sweep and its imagery silently
        # cascaded away by the delete.
        if "admin" not in api.roles:
            raise RuntimeError(
                "force recreate requires an admin account: a non-admin "
                "listing cannot see other users' private maps, so the "
                "shared-scene protection would be blind"
            )
        # fix(#1493 review): --force must REBUILD, not duplicate - the import
        # endpoint dedupes on source_url and returns status="skipped" WITHOUT
        # updating origin_ref, so a rerun over existing scenes could never
        # record fresh bindings. Deleting the SCENES first is what makes
        # `--only sentinel2 --force` the supported repair for instances seeded
        # before item_href was sent.
        #
        # fix(#1607 review r2): the map ROW is a separate question from the
        # scenes, and since the name is pinned the two now part company. The
        # scene deletion and re-import below are what the repair actually is,
        # and they run unchanged; the map row is kept and rebound in place
        # (see _replace_map_layers at the end of this function), so the uuid
        # and share token geolens-examples links survive the repair. Only
        # --force-pinned goes back to deleting the row. Deleting a scene
        # cascades its layers away (MapLayer.dataset_id is ON DELETE CASCADE),
        # so the kept row is left layer-less in between rather than dangling.
        #
        # Three deliberate shapes here:
        #
        # * Runs AFTER the catalog search succeeded (round 3): a flaky
        #   Element84 must fail this builder BEFORE it destroys a working
        #   showcase, not after.
        # * Enumerates ALL owned maps under the name via list_all_maps()
        #   (round 2): list_maps() collapses a name to the newest id, and the
        #   old --force behavior could stack duplicates; deleting only the
        #   newest would cascade the survivors' layers away and leave husks.
        # * Deletes only scene datasets ATTACHED to those maps, intersected
        #   with own+prefix+raster (round 3): a bare title-prefix sweep would
        #   destroy an operator's unrelated same-prefixed import, and a bare
        #   attached-layer sweep would destroy a shared context dataset if a
        #   styling pass ever adds one to this map.
        # * Aborts BEFORE deleting when a selected asset is held by a dataset
        #   the rebuild can neither delete nor resolve (rounds 4+6): the
        #   import dedupe is instance-wide on asset href, and the
        #   skip-fallback below resolves own datasets by seeder title only.
        #   A holding survives the rebuild unless it is in the deletion set,
        #   and satisfies the fallback only if it is own-owned AND still
        #   carries the seeder title - anything else (a foreign import, an
        #   ownerless row, an own manual import or renamed scene) would
        #   dedupe-skip into a missing scene or an all-conflict raise after
        #   the maps were already gone. Keyed the same way the backend guard
        #   is (fix(#1286)): origin_ref.asset_href, source_url as fallback.
        # * Deletes datasets BEFORE maps (round 7): a scene serving a
        #   committed VRT or an in-progress generation makes its DELETE 409
        #   DependentVrtError, and that check is server-side only (origin_ref
        #   and derived_from expose no VRT sources client-side) - the delete
        #   itself is the only authoritative probe. Failing on it aborts with
        #   every stale map still standing, instead of discovering the block
        #   after the showcase is gone.
        stale_maps = [
            m["id"]
            for m in api.list_all_maps()
            if m.get("name") == name
            and m.get("created_by_username") == api.username
        ]
        own_titles = {d["id"]: d["title"] for d in api.list_own_datasets()}
        doomed: dict[str, str] = {}
        for map_id in stale_maps:
            for layer in api.get_map(map_id).get("layers", []):
                ds_id = layer.get("dataset_id")
                title = own_titles.get(ds_id, "")
                if (
                    layer.get("layer_type") == "raster_geolens"
                    and title.startswith("Sentinel-2 TCI ")
                ):
                    doomed[ds_id] = title
        if doomed:
            # fix(#1493 review round 5): a scene someone layered into ANY
            # other map is not ours to cascade away - keep it and say so. The
            # kept scene then rides the dedupe skip-fallback below if the
            # fresh search reselects its asset (reattached, still
            # unrefreshable, and flagged [origin_unavailable] by the
            # seed-end refresh report) - visible partial repair over silent
            # imagery loss in an unrelated map. Rewiring the other map's
            # layer to the replacement was rejected: mutating a map this
            # seeder does not own is the same overreach in a different coat.
            stale_set = set(stale_maps)
            for m in api.list_all_maps():
                if m["id"] in stale_set or not doomed:
                    continue
                for layer in api.get_map(m["id"]).get("layers", []):
                    ds_id = layer.get("dataset_id")
                    if ds_id in doomed:
                        print(
                            f"  [force] keeping scene {doomed[ds_id]!r} - "
                            f"also layered in map {m.get('name', m['id'])!r}"
                        )
                        doomed.pop(ds_id)
        # Preflight (rounds 4+6) - runs on the FINAL doomed set, after the
        # shared-scene exclusions, and before anything is deleted.
        href_to_title = {it["data_asset_href"]: it["title"] for it in items}
        conflicts = []
        for d in api.list_all_datasets():
            if d.get("source_format") != "stac":
                continue
            held = ((d.get("origin_ref") or {}).get("asset_href")) or d.get(
                "source_url"
            )
            if held not in href_to_title:
                continue
            if d["id"] in doomed:
                continue  # about to be deleted - this href is freed
            if (
                d.get("created_by") == api.user_id
                and d.get("title") == href_to_title[held]
            ):
                # Own + seeder-titled: resolvable. Record WHICH row holds the
                # href so the skipped-result resolution below can bind to it
                # directly - a newer same-titled own row would win the
                # by-title lookup and attach the wrong data (round 8).
                resolved_by_href[held] = d["id"]
                continue
            conflicts.append(d)
        if conflicts:
            names = ", ".join(
                f"{d['title']!r} (owner "
                f"{d.get('created_by_display') or d.get('created_by') or 'none'})"
                for d in conflicts[:4]
            )
            raise RuntimeError(
                f"force recreate aborted BEFORE deleting anything: "
                f"{len(conflicts)} selected scene(s) are held by datasets "
                f"this rebuild can neither delete nor resolve (foreign, "
                f"ownerless, or own-but-renamed/manual) - they would "
                f"dedupe-skip and leave the rebuilt map incomplete: {names}"
            )
        for ds_id, title in doomed.items():
            try:
                api.delete_dataset(ds_id, title)
            except httpx.HTTPStatusError as e:
                blockers = ""
                if e.response.status_code == 409:
                    try:
                        det = e.response.json().get("detail")
                        if isinstance(det, dict) and det.get("dependent_vrts"):
                            blockers = (
                                f" (dependent VRTs: {det['dependent_vrts']})"
                            )
                    except ValueError:
                        pass
                raise RuntimeError(
                    f"force recreate aborted: scene {title!r} could not be "
                    f"deleted{blockers}; the stale showcase maps were NOT "
                    f"deleted - resolve the dependency and rerun"
                ) from e
        if doomed:
            print(f"  [force] deleted {len(doomed)} attached scene datasets")
        for map_id in stale_maps:
            # fix(#1607): this loop is the line that actually destroys the uuid
            # the examples gallery links, so the decision is asked here rather
            # than inherited from a caller 250 lines up. Under a pinned repair
            # the row is kept and rebound below; --force-pinned is what turns
            # this back into a delete-and-recreate, and this delete is why the
            # --force-pinned help singles this map out: for the other three
            # pinned maps the override leaves the old row standing, and here it
            # does not (fix(#1607 review r3)).
            if _keep_existing_map(name, True, force, force_pinned):
                retained_rows.append(map_id)
                print(f"  [pinned] keeping map {map_id} - rebound in place below")
                continue
            api.delete_map(map_id)
            print(f"  [force] deleted existing map {map_id}")
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
    # to the row the force preflight proved holds the asset, falling back to
    # the title we assigned. The href binding comes first because titles are
    # not unique: a newer same-titled own row would win the by-title lookup
    # and attach the wrong data to the map (round 8).
    id_to_title = {it["id"]: it["title"] for it in items}
    id_to_date = {it["id"]: it["datetime_start"][:10] for it in items}
    id_to_href = {it["id"]: it["data_asset_href"] for it in items}
    by_title = None
    scenes = []  # (dataset_id, capture_date)
    for x in results:
        item_id = x.get("item_id")
        if x.get("dataset_id"):
            scenes.append((x["dataset_id"], id_to_date.get(item_id, "?")))
        elif x.get("status") == "skipped":
            held_id = resolved_by_href.get(id_to_href.get(item_id, ""))
            if held_id:
                scenes.append((held_id, id_to_date.get(item_id, "?")))
                continue
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
    layers = [
        {
            "dataset_id": ds_id,
            "sort_order": i,  # newest first = on top (results are date-desc)
            "opacity": 1.0,
            "display_name": f"Sentinel-2 - {day}",
            "layer_type": "raster_geolens",
            # true color = NO render_mode, no paint (default RGB path).
            "style_config": {"builder": {}},
        }
        for i, (ds_id, day) in enumerate(scenes)
    ]
    # fix(#1607 review r2): under a pinned repair the row the examples link is
    # reused instead of created. Resolved through list_maps(), which is what
    # every other pass in this seeder already targets (the globe projection,
    # the styling pass and the prune classifier all read it) - repairing a
    # different row would leave the seeder disagreeing with itself. Where an
    # older --force left duplicates under this name, list_maps() picks the
    # newest-created one; if the gallery links an older duplicate, that is a
    # by-hand reconciliation this seeder cannot make for you.
    #
    # Re-resolved HERE rather than carried down from the check at the top: the
    # STAC search and import sit in between, and a row that disappeared in that
    # window has no id left to preserve, so falling through to create_map is
    # the honest outcome rather than a KeyError.
    #
    # "Share links survive" is exact, and worth being exact about: the map row,
    # its uuid, its public /maps/{id} URL and any embed-token ROW are all still
    # there afterwards (verified on a dev instance: same id, same created_at,
    # same token id and hint). What a re-import cannot preserve is an embed
    # token's SCOPE - scoped_dataset_ids is a snapshot of the map's layers at
    # mint time (see build_embed_demo), so it still names the scenes this run
    # deleted and authorizes nothing. Re-mint the token if one is in use. Under
    # --force-pinned the token would not survive at all, so this is the better
    # end of a trade, not a clean one.
    rows = _rows_to_rebind(
        api.list_maps().get(name) if keep_pinned_row else None, retained_rows
    )
    if rows:
        print(
            f"  [pinned] reusing {len(rows)} existing row(s) "
            f"(ids and share links survive): {', '.join(rows)}"
        )
    else:
        rows = [
            api.create_map(
                name,
                "Recent low-cloud Sentinel-2 true-color scenes over New York, "
                "streamed BY REFERENCE from the AWS Earth Search open-data "
                "archive - no file was downloaded to build this map; Titiler "
                "reads the cloud-optimized GeoTIFFs straight from S3, newest "
                "scene on top. ESA Copernicus / Element84 Earth Search.",
            )
        ]
    map_id = _rebind_pinned_rows(
        api,
        rows,
        name,
        layers,
        {
            "visibility": "public",
            "center_lng": -73.97,
            "center_lat": 40.72,
            "zoom": 10.2,
            "pitch": 0,
            "bearing": 0,
            "basemap_style": "openfreemap-positron",
            "show_basemap_labels": True,
        },
    )
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


def build_embed_demo(api: Api, force: bool = False, force_pinned: bool = False) -> str:
    """Private-dataset embed-token capability demo. A PUBLIC share URL is
    impossible with a private dataset (publishing the map 400s), so the map
    stays PRIVATE and the X-Embed-Token header grants scoped tile access."""
    name = "Private Embed Demo"
    if _keep_existing_map(name, _map_exists(api, name), force, force_pinned):
        return _announce_kept_map(name, force)
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
        # Worded for the STAC surface as much as for the catalog. STAC exposes
        # only a collection's RASTER members, so this description used to
        # promise earthquakes and eruptions to a STAC client that could see
        # neither - it lists what the collection HOLDS without claiming what any
        # one surface will show.
        # No "live" here, deliberately. This text is written by a pass that
        # runs whether or not the service conversion succeeded, and unlike the
        # map notes it has no natural gate to hang on - a collection is a label
        # over datasets, not a view of one. Describing WHAT the collection
        # holds rather than HOW it is delivered is true of every instance,
        # which is the same trick that keeps the hurricane map name honest.
        "The physical earth: earthquakes, volcanic eruptions, plate boundaries, "
        "hurricane tracks and meteorite falls, alongside the global relief and "
        "alpine lidar terrain they play out on. Vector and raster members both; "
        "catalogue surfaces that carry only rasters will show the ETOPO relief "
        "and the swissALTI3D terrain.",
        [
            QUAKES_TITLE,
            QUAKES_HEAT_TITLE,
            "Tectonic Plate Boundaries (PB2002)",
            "Significant Volcanic Eruptions (NCEI, 4360 BC-present)",
            "Atlantic Hurricane Tracks (HURDAT2, majors since 1950)",
            "Major Hurricane Tracks (Cat 3+ legs, one per storm)",
            "Hurricane Exposure by Coastal Region",
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
            "Atlantic Basin Regions (Natural Earth admin-1)",
        ],
    ),
}


def build_collections(api: Api, force: bool = False, force_pinned: bool = False) -> str:
    """Two themed collections. Collection.name is UNIQUE -> reuse on re-runs;
    membership top-up is idempotent.

    The DESCRIPTION is refreshed on reuse, not only written at creation. It used
    to be a create-time argument, which meant an existing instance kept whatever
    wording it was seeded with - and Restless Planet's original wording promised
    earthquakes and eruptions to the STAC surface, which exposes only a
    collection's raster members. A correction that never reaches the instances
    carrying the mistake is not a correction.
    """
    print("\n[collections] Restless Planet + Human World")
    existing = {c["name"]: c for c in api.list_collections()}
    titles = api.datasets_by_title()
    ids = []
    for cname, (desc, wanted) in COLLECTIONS.items():
        current = existing.get(cname)
        if current is None:
            coll_id = api.create_collection(cname, desc)
        else:
            coll_id = current["id"]
            # Compared before writing, the way every other migration in this
            # script is: an unconditional PATCH would bump updated_at on every
            # seed and reorder any listing sorted by it.
            if current.get("description") != desc:
                try:
                    api.update_collection(coll_id, description=desc)
                    print(f"  updated description: {cname}")
                except httpx.HTTPStatusError as e:
                    print(
                        f"  ! could not update {cname!r} description: {e}",
                        file=sys.stderr,
                    )
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
#
# Beyond license + keywords, each entry may carry the provenance fields the
# catalog, the DCAT/ISO exports and the metadata-quality score all read:
#
#   source_organization  who published it. Left UNSET on the three
#                        analysis-derived datasets - they are computed products
#                        of this instance, no outside body published them, and
#                        their provenance panel already names the operation
#                        chain that did. Naming NOAA there would credit an
#                        organisation for a number GeoLens calculated.
#   source_url           the human-facing landing page, not the download URL:
#                        it is what a catalog visitor should follow to the
#                        authoritative source.
#   update_frequency     an ISO 19115 MD_MaintenanceFrequencyCode, and NOT free
#                        text - a CHECK constraint (chk_records_update_frequency)
#                        rejects anything outside continual / daily / weekly /
#                        monthly / quarterly / biannually / annually / asNeeded /
#                        irregular / notPlanned / unknown. Omitted wherever the
#                        honest answer is not one of those.
#   data_vintage_start   temporal coverage, ISO dates, and set ONLY where the
#   data_vintage_end     source states one. A guessed vintage is worse than an
#                        absent one: it is indistinguishable from a real one.
#                        The HURDAT2 datasets carry a START and no END for that
#                        reason. 1950 is a floor this script imposes itself
#                        (min_year), so it is true of whatever release is
#                        loaded. The end is NOT knowable here: a plain seed
#                        reuses the existing datasets by title and never
#                        downloads, so an instance seeded before the 2025 bump
#                        still holds 2024 data while this pass runs. Stamping
#                        2025 would advertise a season the data does not have
#                        until --refresh-hurdat2 has actually run.
#   theme_category       ISO 19115 MD_TopicCategoryCode values, which drive the
#                        theme facet and the DCAT theme export.
SHOWCASE_METADATA: dict[str, dict] = {
    "World Countries (Natural Earth 1:50m)": {
        "license": "Natural Earth (public domain)",
        "keywords": ["countries", "boundaries", "admin-0", "natural earth"],
        "source_organization": "Natural Earth",
        "source_url": "https://www.naturalearthdata.com/",
        "update_frequency": "asNeeded",
        "theme_category": ["boundaries"],
    },
    "World Rivers & Lake Centerlines (Natural Earth 1:50m)": {
        "license": "Natural Earth (public domain)",
        "keywords": ["rivers", "hydrology", "water", "water bodies", "natural earth"],
        "source_organization": "Natural Earth",
        "source_url": "https://www.naturalearthdata.com/",
        "update_frequency": "asNeeded",
        "theme_category": ["inlandWaters"],
    },
    "World Lakes & Reservoirs (Natural Earth 1:50m)": {
        "license": "Natural Earth (public domain)",
        "keywords": ["lakes", "hydrology", "water", "water bodies", "reservoirs"],
        "source_organization": "Natural Earth",
        "source_url": "https://www.naturalearthdata.com/",
        "update_frequency": "asNeeded",
        "theme_category": ["inlandWaters"],
    },
    "World Major Cities (500k+)": {
        "license": "Natural Earth (public domain)",
        "keywords": ["cities", "populated places", "urban", "natural earth"],
        "source_organization": "Natural Earth",
        "source_url": "https://www.naturalearthdata.com/",
        "update_frequency": "asNeeded",
        "theme_category": ["location", "society"],
    },
    "Manhattan Building Heights": {
        "license": "NYC Open Data (public domain)",
        "keywords": ["buildings", "3d", "heights", "manhattan", "nyc"],
        "source_organization": "NYC Open Data",
        "source_url": (
            "https://data.cityofnewyork.us/Housing-Development/"
            "Building-Footprints/5zhs-2jue"
        ),
        "theme_category": ["structure"],
    },
    # PINNED: this title derives the table name data.nyc_subway_lines_mta, which
    # is referenced from outside this repo. Metadata only - never retitle.
    "NYC Subway Lines (MTA)": {
        "license": "MTA open data (data.ny.gov)",
        "keywords": ["subway", "transit", "mta", "nyc", "rail"],
        "source_organization": "MTA via NY State Open Data",
        "source_url": "https://data.ny.gov/Transportation/MTA-Subway-Lines/s692-irgq",
        "theme_category": ["transportation"],
    },
    # PINNED by dataset id from outside this repo. Metadata only.
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
        "source_organization": "MTA via NY State Open Data",
        "source_url": (
            "https://data.ny.gov/Transportation/MTA-Subway-Stations/39hk-dx4f"
        ),
        "theme_category": ["transportation"],
    },
    "New York Median Household Income by County": {
        "license": "US Census Bureau, ACS 2017-21 (public domain)",
        "keywords": ["census", "income", "demographics", "acs", "new york"],
        "source_organization": "USDA Economic Research Service",
        "source_url": (
            "https://www.ers.usda.gov/data-products/"
            "atlas-of-rural-and-small-town-america/"
        ),
        # The ACS five-year estimates ship on an annual cadence, and the
        # 2017-21 window is the one this extract states.
        "update_frequency": "annually",
        "data_vintage_start": "2017-01-01",
        "data_vintage_end": "2021-12-31",
        "theme_category": ["society", "economy"],
    },
    QUAKES_TITLE: {
        "license": "USGS Earthquake Hazards Program (US public domain)",
        "keywords": ["earthquakes", "seismic", "usgs", "hazards", "magnitude"],
        "source_organization": "USGS",
        "source_url": "https://earthquake.usgs.gov/earthquakes/map/",
        "theme_category": ["geoscientificInformation"],
        # Everything above is true of this dataset whatever it currently holds.
        # Everything in `gated` describes a LIVE SERVICE, and is written only
        # when the dataset is observably reading from one. "continual" is the
        # honest maintenance code for a service that re-publishes as events
        # land, and it is a lie about a static upload. No vintage either way:
        # the window is a rolling 30 days, so any date is wrong the next day.
        "requires_origin": "service",
        "gated": {
            "update_frequency": "continual",
            "summary": QUAKE_SUMMARIES[QUAKES_TITLE],
        },
    },
    QUAKES_HEAT_TITLE: {
        "license": "USGS Earthquake Hazards Program (US public domain)",
        "keywords": ["earthquakes", "seismic", "usgs", "density", "heatmap"],
        "source_organization": "USGS",
        "source_url": "https://earthquake.usgs.gov/earthquakes/map/",
        "theme_category": ["geoscientificInformation"],
        # Gated for the same reason as the circles dataset, and this one needs
        # it more: its title never changes, so the rename-after-conversion gate
        # that protects the circles dataset does not cover it at all.
        # fix(#614): the old summary read as an internal rendering workaround;
        # describe it as the map's density layer instead. Now also corrected to
        # M2.5+, which is what the live service actually serves.
        "requires_origin": "service",
        "gated": {
            "update_frequency": "continual",
            "summary": QUAKE_SUMMARIES[QUAKES_HEAT_TITLE],
        },
    },
    "Tectonic Plate Boundaries (PB2002)": {
        "license": "Peter Bird (2003), PB2002 - free for research, please cite",
        "keywords": ["plate tectonics", "geology", "boundaries", "pb2002"],
        "source_organization": "Peter Bird (PB2002), via Nordpil",
        "source_url": "https://github.com/fraxen/tectonicplates",
        # A 2003 publication with no successor planned - which is what
        # notPlanned means, and is more useful than leaving it unknown.
        "update_frequency": "notPlanned",
        "theme_category": ["geoscientificInformation"],
    },
    "Significant Volcanic Eruptions (NCEI, 4360 BC-present)": {
        "license": "NOAA NCEI (US public domain)",
        "keywords": ["volcanoes", "eruptions", "hazards", "geology", "ncei"],
        "source_organization": "NOAA NCEI",
        "source_url": (
            "https://www.ngdc.noaa.gov/hazel/view/hazards/volcano/event-search"
        ),
        # No vintage: coverage starts in 4360 BC and the date columns cannot
        # hold a BCE year.
        "theme_category": ["geoscientificInformation"],
    },
    HURDAT2_TRACKS_TITLE: {
        "license": "NOAA NHC HURDAT2 (US public domain)",
        "keywords": [
            "hurricanes",
            "tropical cyclones",
            "noaa",
            "hurdat2",
            "storms",
        ],
        "source_organization": "NOAA National Hurricane Center",
        "source_url": "https://www.nhc.noaa.gov/data/#hurdat",
        # NHC cuts one best-track revision per year, after the season closes.
        "update_frequency": "annually",
        "data_vintage_start": "1950-01-01",
        "theme_category": ["climatologyMeteorologyAtmosphere"],
    },
    HURDAT2_LEGS_TITLE: {
        "license": "NOAA NHC HURDAT2 (US public domain)",
        "keywords": [
            "hurricanes",
            "tropical cyclones",
            "noaa",
            "hurdat2",
            "major hurricane",
        ],
        "source_organization": "NOAA National Hurricane Center",
        "source_url": "https://www.nhc.noaa.gov/data/#hurdat",
        "update_frequency": "annually",
        "data_vintage_start": "1950-01-01",
        "theme_category": ["climatologyMeteorologyAtmosphere"],
    },
    "Atlantic Basin Regions (Natural Earth admin-1)": {
        "license": "Natural Earth (public domain)",
        "keywords": [
            "admin-1",
            "boundaries",
            "coastal",
            "atlantic",
            "caribbean",
            "natural earth",
        ],
        "source_organization": "Natural Earth",
        "source_url": "https://www.naturalearthdata.com/",
        "update_frequency": "asNeeded",
        "theme_category": ["boundaries"],
    },
    # The three derived datasets. Summaries are written by _get_or_analyze at
    # materialize time (only the enrich pass's license + keywords are left);
    # lineage_summary is deliberately untouched here - the analysis API wrote
    # the real one, and it is the sentence the provenance panel shows.
    #
    # source_organization is deliberately UNSET on all three: no outside body
    # published them, GeoLens computed them, and the provenance panel already
    # names the operation chain. The vintage IS set, because it is a real
    # property of the inputs rather than a guess - these cover exactly the
    # HURDAT2 seasons the corridors were buffered from.
    "Major Hurricane Corridors (100 km buffer)": {
        "license": "Derived in GeoLens from NOAA NHC HURDAT2 (US public domain)",
        "keywords": ["hurricanes", "buffer", "analysis", "derived", "corridor"],
        "data_vintage_start": "1950-01-01",
        "theme_category": ["climatologyMeteorologyAtmosphere"],
    },
    "Coastal Regions Inside a Major Hurricane Corridor": {
        "license": (
            "Derived in GeoLens from NOAA NHC HURDAT2 and Natural Earth "
            "(both public domain)"
        ),
        "keywords": ["hurricanes", "intersect", "analysis", "derived", "exposure"],
        "data_vintage_start": "1950-01-01",
        "theme_category": ["climatologyMeteorologyAtmosphere", "boundaries"],
    },
    "Hurricane Exposure by Coastal Region": {
        "license": (
            "Derived in GeoLens from NOAA NHC HURDAT2 and Natural Earth "
            "(both public domain)"
        ),
        "keywords": [
            "hurricanes",
            "exposure",
            "dissolve",
            "analysis",
            "derived",
            "coastal",
        ],
        "data_vintage_start": "1950-01-01",
        "theme_category": ["climatologyMeteorologyAtmosphere", "boundaries"],
    },
    "Meteorite Landings (Meteoritical Society)": {
        "license": "NASA open data (public domain)",
        "keywords": ["meteorites", "impacts", "nasa", "meteoritical society"],
        "source_organization": "NASA / The Meteoritical Society",
        "source_url": "https://www.lpi.usra.edu/meteor/metbull.php",
        "theme_category": ["geoscientificInformation"],
    },
    "Matterhorn Climbing Routes": {
        "license": "(C) OpenStreetMap contributors (ODbL)",
        "keywords": ["climbing", "alpinism", "routes", "osm", "matterhorn"],
        "source_organization": "OpenStreetMap contributors",
        "source_url": "https://www.openstreetmap.org/",
        "theme_category": ["location"],
    },
    "Matterhorn Peaks": {
        "license": "(C) OpenStreetMap contributors (ODbL)",
        "keywords": ["peaks", "summits", "mountains", "osm", "matterhorn"],
        "source_organization": "OpenStreetMap contributors",
        "source_url": "https://www.openstreetmap.org/",
        "theme_category": ["location"],
    },
    "ETOPO 2022 Global Relief (60 arc-second)": {
        "license": "US public domain (NOAA NCEI)",
        "keywords": ["bathymetry", "relief", "etopo", "global", "elevation"],
        "source_organization": "NOAA NCEI",
        "source_url": ("https://www.ncei.noaa.gov/products/etopo-global-relief-model"),
        # No vintage: ETOPO 2022 is a compilation of many source surveys, so
        # the release year is not the coverage the date fields would claim.
        "theme_category": ["elevation", "oceans"],
    },
    # PINNED by dataset id from outside this repo. Metadata only.
    "swissALTI3D Matterhorn DEM (2m mosaic)": {
        "license": "swisstopo OGD",
        "keywords": ["terrain", "dem", "elevation", "swisstopo", "matterhorn"],
        "source_organization": "swisstopo",
        "source_url": ("https://www.swisstopo.admin.ch/en/height-model-swissalti3d"),
        "data_vintage_start": "2024-01-01",
        "data_vintage_end": "2024-12-31",
        "theme_category": ["elevation"],
    },
}

# Datasets the seeder creates one-per-item, so their titles carry a suffix and
# cannot be dict keys: the ~62 swissALTI3D DEM tiles and every imported
# Sentinel-2 scene. Matched by title PREFIX, and only after an exact-title
# lookup misses.
SHOWCASE_METADATA_BY_PREFIX: dict[str, dict] = {
    "swissALTI3D 2m ": {
        "license": "swisstopo OGD",
        "keywords": ["terrain", "dem", "elevation", "swisstopo", "matterhorn"],
        "source_organization": "swisstopo",
        "source_url": ("https://www.swisstopo.admin.ch/en/height-model-swissalti3d"),
        "data_vintage_start": "2024-01-01",
        "data_vintage_end": "2024-12-31",
        "theme_category": ["elevation"],
    },
    "Sentinel-2 TCI ": {
        "license": "Copernicus Sentinel data (ESA), free and open",
        "keywords": ["sentinel-2", "true-color", "imagery", "esa", "copernicus"],
        "source_organization": "ESA Copernicus via Element84 Earth Search",
        "source_url": "https://registry.opendata.aws/sentinel-2-l2a-cogs/",
        # Sentinel-2 revisits every few days and new scenes land continuously.
        # No vintage: the STAC import already stamped each scene with its own
        # acquisition datetime, which is more precise than anything set here.
        "update_frequency": "continual",
        "theme_category": ["imageryBaseMapsEarthCover"],
    },
}


# The DatasetMeta fields the enrich pass forwards verbatim when a spec carries
# them. `keywords` is NOT here - keywords hang off the catalog record and go
# through their own endpoint - and neither is `summary`, which is handled
# separately because most specs deliberately leave the ingest-time one alone.
_ENRICH_PATCH_FIELDS = (
    "license",
    "source_organization",
    "source_url",
    "update_frequency",
    "data_vintage_start",
    "data_vintage_end",
    "theme_category",
)


def _metadata_spec(title: str) -> dict | None:
    """The metadata spec for a dataset title, exact match before prefix match."""
    spec = SHOWCASE_METADATA.get(title)
    if spec is not None:
        return spec
    for prefix, prefix_spec in SHOWCASE_METADATA_BY_PREFIX.items():
        if title.startswith(prefix):
            return prefix_spec
    return None


def enrich_showcase_metadata(api: "Api") -> None:
    """Backfill the catalog metadata the ingest flow does not set.

    License and keywords (fix(#614)), plus the provenance fields that make a
    dataset legible in the catalog and exportable through DCAT/ISO:
    source_organization, source_url, update_frequency, the data vintage and the
    ISO theme categories. See SHOWCASE_METADATA for what each one means and why
    several are deliberately absent on some datasets.

    Idempotent: the PATCH is a plain overwrite of fields this file owns and
    keywords are added only when absent, so re-running never duplicates. Only
    datasets that actually exist are touched, so this composes with --only. Each
    dataset is isolated the same way the builders are - one flaky PATCH must not
    skip the rest - and the whole pass is best-effort: it never fails the seed.

    Safe on the three externally pinned datasets: a metadata PATCH does not
    touch a title, a table name or an id, which are the only things an outside
    reference depends on.

    Iterates every OWNED dataset rather than a title->newest-id map: titles are
    NOT unique (a --force reseed leaves same-titled predecessors, see
    datasets_by_title), and enriching only the newest would leave the older
    public duplicates still "proprietary"/keyword-less - the exact pollution
    this fixes. Every matching copy this account owns gets patched, and only
    those: a same-titled dataset belonging to someone else is not this
    seeder's to relicense (list_own_datasets).
    """
    for ds in api.list_own_datasets():
        spec = _metadata_spec(ds["title"])
        if not spec:
            continue
        title, dataset_id = ds["title"], ds["id"]
        try:
            fields = {k: spec[k] for k in _ENRICH_PATCH_FIELDS if k in spec}
            if spec.get("summary"):
                fields["summary"] = spec["summary"]
            # Claims that are only true once the data really came from a given
            # origin are written only when the dataset OBSERVABLY has it. This
            # pass runs whether or not the builder that was supposed to make it
            # true succeeded, so "the seeder tried" is not evidence. The list
            # response already carries origin, so this costs no extra request.
            gated = spec.get("gated")
            if gated:
                origin = ds.get("origin")
                if origin == spec.get("requires_origin"):
                    fields.update(gated)
                else:
                    print(
                        f"  (holding origin-dependent metadata for {title!r}: "
                        f"origin is {origin!r}, not "
                        f"{spec.get('requires_origin')!r})"
                    )
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


# --- post-builder styling pass --------------------------------------------------
# Everything below runs AFTER the builders, over the maps that exist, for the
# reason apply_globe_projection documents: a builder skips a map it already
# found, so anything set only at creation time reaches a fresh instance and
# never an existing one - which is every instance that matters, the live demo
# included.

# Maps whose NOTES and DESCRIPTION assert that the quakes read from a live
# service. Both texts run through a pass that executes whether or not the
# conversion succeeded, so they are held back until the datasets observably
# read from one. The legend title, folder groups, pitch alignment and the
# popup repair are unaffected: none of them claims anything about liveness,
# and the popup has its own column-level gate.
MAP_TEXT_REQUIRES_LIVE_QUAKES = frozenset({"Restless Earth"})


def _quakes_are_live(api: "Api") -> bool:
    """Observed evidence that BOTH quake datasets read from the USGS service.

    Reads origin off each dataset rather than inferring it from "the builder
    ran" or "the rename happened". Both inferences have been wrong: the
    builder is isolated so a failure is invisible downstream, and the rename
    is itself gated on the conversion, which makes it a proxy rather than
    evidence.

    Both, because the wording this gates covers both. The Restless Earth notes
    say the earthquakes are read live, and the map draws them twice - graduated
    circles from one dataset, the heat surface from the other. They convert in
    sequence, so the second can fail after the first succeeded, and checking
    only the circles would publish "read live" over a heat layer still holding
    the old M4.5 upload.

    False on any error: the claim being gated should only be published on
    positive proof.
    """
    try:
        by_title = api.datasets_by_title()
        for title in (QUAKES_TITLE, QUAKES_HEAT_TITLE):
            dataset_id = by_title.get(title)
            if dataset_id is None:
                return False
            if api.dataset_origin(dataset_id) != "service":
                return False
        return True
    except (httpx.HTTPStatusError, httpx.TimeoutException):
        return False


# Map-level legend title + notes. The legend title names what the swatches
# measure; the note says what the map is and where the numbers came from.
MAP_LEGEND_AND_NOTES: dict[str, tuple[str, str]] = {
    "Restless Earth": (
        "Earthquake magnitude",
        "Earthquakes are read live from the USGS M2.5+ service and cover a "
        "rolling 30-day window; they refresh on demand rather than on a "
        "schedule. Eruptions are NOAA NCEI significant events since 4360 BC, "
        "filtered on the map to VEI 4+ or 100+ deaths. Plate boundaries are "
        "PB2002 (Bird 2003); relief is ETOPO 2022.",
    ),
    "Manhattan - A Century of Skyline": (
        "Construction era",
        "Buildings are extruded to their surveyed roof height (NYC Open Data, "
        "feet converted to metres) and coloured by construction year. Subway "
        "routes use official MTA colours, which the source feed does not "
        "carry. Stations fade in above zoom 12.5.",
    ),
    "The Matterhorn in 3D": (
        "Elevation",
        "Terrain is a VRT mosaic of swissALTI3D 2 m lidar tiles (swisstopo "
        "OGD) with a hillshade lit from the northwest and a hypsometric tint. "
        "Routes and peaks are OpenStreetMap, clipped to the mosaic footprint "
        "so no line leaves the terrain mesh.",
    ),
    HURRICANE_MAP: (
        "Saffir-Simpson category",
        # No season named here on purpose: this note is written on every seed,
        # including on an instance whose tracks have not been refreshed to the
        # newest HURDAT2 release yet, and the map would then claim a season it
        # does not contain.
        "Every Atlantic storm since 1950 that reached Category 3, drawn as "
        "six-hourly segments coloured by its intensity at that leg. Arrows "
        "mark direction of motion on Category 5 legs only. Source: NOAA NHC "
        "HURDAT2 best-track data.",
    ),
    "Everything That Fell From the Sky": (
        "Recovery type",
        "Every meteorite recovery with coordinates, about 32,000 of them. "
        "Above 5,000 features the viewer switches to server-side cluster "
        "tiles, which is what the clustering here demonstrates. Source: NASA "
        "open data / The Meteoritical Society.",
    ),
    "New York From Orbit - Sentinel-2, by Reference": (
        "Sentinel-2 true colour",
        "Recent low-cloud Sentinel-2 scenes streamed by reference from the "
        "AWS Earth Search archive. No imagery was downloaded to build this "
        "map; the tile server reads the cloud-optimized GeoTIFFs from S3 at "
        "view time. ESA Copernicus via Element84.",
    ),
    EXPOSURE_MAP: (
        "Distinct major storms since 1950",
        "A computed result, not a rendering. The Category 3+ legs of every "
        "Atlantic storm since 1950 were buffered by 100 km, intersected with "
        "admin-1 regions, then dissolved per region, so the fill grades by how "
        "many distinct major storms reached each coast. Each derived dataset's "
        "provenance panel replays the step that made it.",
    ),
}

# Layer display_name -> (folder group id, folder group name). Grouping is
# expressed by layers SHARING a folderGroupId, so the id is the real key and the
# name is what the stack shows. Only the two maps with enough layers to be worth
# folding are listed; a map absent here keeps a flat stack.
MAP_FOLDER_GROUPS: dict[str, dict[str, tuple[str, str]]] = {
    "Restless Earth": {
        "Earthquakes (last 30 days, by magnitude)": ("re-hazards", "Hazards"),
        "Major eruptions (VEI 4+ or 100+ deaths)": ("re-hazards", "Hazards"),
        "Quake intensity (heatmap)": ("re-hazards", "Hazards"),
        "Colliding boundaries (solid)": ("re-context", "Context"),
        "Spreading & sliding boundaries (dashed)": ("re-context", "Context"),
        "Major cities (by population)": ("re-context", "Context"),
        "Global relief (ETOPO 2022)": ("re-context", "Context"),
    },
    "The Matterhorn in 3D": {
        "swissALTI3D relief": ("mh-terrain", "Terrain"),
        "Climbing routes (OSM)": ("mh-routes", "Routes & Peaks"),
        "Route casing": ("mh-routes", "Routes & Peaks"),
        "Peaks": ("mh-routes", "Routes & Peaks"),
    },
}

# Circle layers that read better flat ON the globe than billboarded toward the
# camera. Both of these maps are globe-projected (GLOBE_PROJECTION_MAPS), which
# is the whole reason: a pitch-aligned circle lies on the sphere's surface.
MAP_PITCH_ALIGNED_CIRCLES: dict[str, tuple[str, ...]] = {
    "Restless Earth": ("Earthquakes (last 30 days, by magnitude)",),
    "Everything That Fell From the Sky": ("Meteorites (amber = seen falling)",),
}

# Stored layer settings that went WRONG when the quakes moved to the live
# service, keyed by map and layer display name. This is a repair table, not a
# style preference: an instance seeded before the conversion has a popup listing
# depth_km and time_utc, columns the service does not have and no refresh will
# restore, so the popup renders blank rows on the live demo. build_restless_earth
# writes the correct values on a NEW map and then returns early on an existing
# one, which is exactly the case this covers.
#
# Values come from the shared constants, so the builder and this repair cannot
# disagree about what "correct" is.
MAP_LAYER_STYLE_FIXES: dict[str, dict[str, dict]] = {
    "Restless Earth": {
        "Earthquakes (last 30 days, by magnitude)": {
            # Gated on the columns actually being there. The conversion runs in
            # a builder, the builder is isolated so one failure cannot kill a
            # seed, and this pass runs afterwards regardless - so a transient
            # failure mid-conversion would otherwise leave an upload-origin
            # dataset carrying a popup that names service columns it does not
            # have. That is worse than the stale popup it replaced: the old one
            # showed real values, the new one would show blank rows. Applying
            # nothing is the correct outcome until the conversion succeeds.
            "requires_columns": ("depth_num", "event_time_utc_date_fmt"),
            "fields": {"popup_config": QUAKE_POPUP_CONFIG},
        },
        "Quake intensity (heatmap)": {
            # Deliberately NOT gated: this reads `mag`, which both the old
            # upload and the service carry, and a 2.5 floor over M4.5+ data is
            # simply inert rather than wrong.
            "paint": {"heatmap-weight": QUAKE_HEATMAP_WEIGHT},
        },
    },
}

# The writable half of a layer response - what POST /maps/{id}/layers accepts.
# `id` and every dataset_*/is_*/tile_version field on the response is read-only.
_LAYER_WRITABLE_FIELDS = (
    "dataset_id",
    "display_name",
    "filter",
    "label_config",
    "layer_type",
    "layout",
    "opacity",
    "paint",
    "popup_config",
    "show_in_legend",
    "sort_order",
    "style_config",
    "visible",
)


def _restyle_layer(
    api: "Api", map_id: str, layer: dict, paint=None, builder=None, fields=None
) -> None:
    """Apply a style delta to an EXISTING layer by re-creating it.

    Delete-and-re-add rather than PATCH, deliberately: the layer-diff path has a
    known style-clobbering hazard where touching one key nulls out style_config,
    and a full POST either lands whole or fails whole. The body is the layer's
    own state read back from the server, so nothing is invented and nothing is
    dropped - only the keys in the delta differ.

    There is a window between the DELETE and the POST, and the caller swallows
    exceptions so one bad map cannot fail a seed. Without the restore below,
    a timeout in that window would silently cost a showcase map one of its
    layers and the seed would still report success. So a failed replacement
    puts the ORIGINAL body back and re-raises: worst case the styling delta
    does not land, which is what the caller's warning already means.
    """
    original = {k: layer[k] for k in _LAYER_WRITABLE_FIELDS if layer.get(k) is not None}
    body = dict(original)
    if fields:
        # Whole-value replacement, not a merge: these are settings like
        # popup_config whose old contents are the thing being corrected.
        body.update(fields)
    if paint:
        body["paint"] = {**(body.get("paint") or {}), **paint}
    if builder:
        style_config = dict(body.get("style_config") or {})
        style_config["builder"] = {**(style_config.get("builder") or {}), **builder}
        body["style_config"] = style_config
    # The DELETE is ambiguous on failure, not merely failed: a lost response or
    # a timeout can follow a deletion the server already committed. Raising here
    # without checking would leave the layer gone with no attempt to put it
    # back, and the caller only logs. So re-read the map and let what is
    # actually true decide - still present means nothing was lost and the delta
    # simply does not apply, absent means the delete landed and the re-add below
    # is now the recovery path rather than an optimisation.
    try:
        api.delete_layer(map_id, layer["id"])
    except (httpx.HTTPStatusError, httpx.TimeoutException):
        try:
            survived = any(
                x.get("id") == layer["id"]
                for x in (api.get_map(map_id).get("layers") or [])
            )
        except (httpx.HTTPStatusError, httpx.TimeoutException):
            raise
        if survived:
            raise
    display = layer.get("display_name")
    try:
        api.add_layer(map_id, body)
    except Exception:
        # The POST is ambiguous exactly like the DELETE above: a lost response
        # can follow a layer the server already created. Layer creation is not
        # idempotent, so restoring blindly would leave the map with BOTH the
        # replacement and a copy - and a duplicate survives every later pass,
        # which restyles both, so it never resolves itself.
        try:
            committed = any(
                x.get("display_name") == display
                for x in (api.get_map(map_id).get("layers") or [])
            )
        except (httpx.HTTPStatusError, httpx.TimeoutException):
            # Cannot tell. Restore, because a map missing a layer is a visible
            # hole while a duplicate merely draws twice, and only one of those
            # is recoverable by an operator who can see it.
            committed = False
        if committed:
            print(
                f"  ! restyle POST reported failure but {display!r} is present; "
                "leaving it rather than adding a duplicate",
                file=sys.stderr,
            )
            raise
        try:
            api.add_layer(map_id, original)
            print(
                f"  ! restyle failed; restored the original layer {display!r}",
                file=sys.stderr,
            )
        except (httpx.HTTPStatusError, httpx.TimeoutException):
            print(
                f"  !! restyle failed AND the layer {display!r} could not be restored",
                file=sys.stderr,
            )
        raise


def _basin_context_layer_body(regions_ds: str) -> dict:
    """The Atlantic basin regions as a hatched CONTEXT layer.

    The exposure map grades the regions a major storm actually reached, and
    without this layer there is no way to see what was offered to the intersect
    and did NOT survive it. The hatch is what keeps the two readable at once:
    it says "considered, not exposed" without competing with a graded fill for
    the same visual channel, which a second flat colour would.

    sort_order 2 puts it at the BOTTOM of the three layers - the viewer draws
    lower sort_order on top. fill-color rides alongside fill-pattern to tint the
    hatch; the builder treats those as mutually exclusive but the API does not,
    and paint's colour is what the tint resolver reads first.
    """
    return {
        "dataset_id": regions_ds,
        "sort_order": 2,
        "opacity": 1.0,
        "display_name": "Atlantic basin regions (context)",
        "show_in_legend": False,
        "paint": {
            "fill-pattern": "geolens-fill-hatch",
            "fill-color": "#64748b",
            "fill-opacity": 0.22,
            "fill-outline-color": "#94a3b8",
        },
        "popup_config": {"enabled": False},
        "style_config": {"builder": {}},
    }


def _ensure_basin_context_layer(api: "Api", map_id: str, layers: list) -> bool:
    """Add the hatched basin-regions context layer if the map has none."""
    regions_ds = api.datasets_by_title().get(
        "Atlantic Basin Regions (Natural Earth admin-1)"
    )
    if not regions_ds:
        return False
    if any(x.get("dataset_id") == regions_ds for x in layers):
        return False
    api.add_layer(map_id, _basin_context_layer_body(regions_ds))
    print(f"  + hatched basin-regions context layer on {EXPOSURE_MAP}")
    return True


def _layer_style_delta(
    layer: dict, groups: dict, pitch_aligned: tuple, style_fixes: dict
) -> tuple[dict, dict, dict, list]:
    """What needs to change on one layer, and why.

    Every branch compares against the layer's CURRENT value first, so a layer
    already carrying the right settings produces an empty delta and is never
    rewritten. That is what makes the whole styling pass free to re-run: with
    no comparison here it would delete and re-add every listed layer on every
    seed. Returns (paint, builder, fields, reasons); an empty `reasons` means
    do nothing.
    """
    display = layer.get("display_name")
    builder_now = ((layer.get("style_config") or {}).get("builder")) or {}
    paint_now = layer.get("paint") or {}
    paint_delta: dict = {}
    builder_delta: dict = {}
    field_delta: dict = {}
    reasons: list[str] = []

    group = groups.get(display)
    if group and builder_now.get("folder_group_id") != group[0]:
        builder_delta = {
            "folder_group_id": group[0],
            "folder_group_name": group[1],
            "folder_group_expanded": True,
        }
        reasons.append("group")
    if display in pitch_aligned and paint_now.get("circle-pitch-alignment") != "map":
        paint_delta["circle-pitch-alignment"] = "map"
        reasons.append("pitch")

    # Repair a stored style that predates the service conversion, but only when
    # the dataset can actually support it. The layer response carries its
    # dataset's column_info, so this costs no extra request; an empty or absent
    # list fails the check and skips, which is the safe direction - never write
    # a style naming columns that cannot be confirmed to exist.
    fix = style_fixes.get(display, {})
    required = fix.get("requires_columns")
    if required:
        have = {
            c.get("name")
            for c in (layer.get("dataset_column_info") or [])
            if isinstance(c, dict)
        }
        if not set(required) <= have:
            fix = {}
    for key, value in (fix.get("paint") or {}).items():
        if paint_now.get(key) != value:
            paint_delta[key] = value
            reasons.append(f"paint.{key}")
    for key, value in (fix.get("fields") or {}).items():
        if layer.get(key) != value:
            field_delta[key] = value
            reasons.append(key)
    return paint_delta, builder_delta, field_delta, reasons


def apply_showcase_styling(api: "Api") -> None:
    """Legend titles, notes, folder groups, pitch-aligned circles and the
    exposure map's context layer - applied to whatever showcase maps exist.

    Idempotent throughout: every write is preceded by a read of the current
    value and skipped when it already matches, so a re-run costs GETs and
    changes nothing. Best-effort per map, like the other post-builder passes -
    a flaky PUT must not fail a seed whose maps and data are already built.

    Reads look for the SNAKE_CASE builder keys. The server canonicalizes
    style_config.builder on save, so folder_group_id is what comes back
    regardless of which spelling was written.
    """
    maps = api.list_maps()
    # Resolved once, and only if a map that needs it actually exists.
    live_quakes: bool | None = None
    for name, map_id in sorted(maps.items()):
        # Every table that can carry work for a map has to be in this guard, or
        # that work silently never runs. MAP_LAYER_STYLE_FIXES reaches Restless
        # Earth today only because the same map happens to appear in two other
        # tables, which is luck rather than design: a fix added for a map listed
        # nowhere else would never have applied.
        if not any(
            name in table
            for table in (
                MAP_LEGEND_AND_NOTES,
                MAP_FOLDER_GROUPS,
                MAP_DESCRIPTIONS,
                MAP_LAYER_STYLE_FIXES,
                MAP_PITCH_ALIGNED_CIRCLES,
            )
        ):
            continue
        try:
            current = api.get_map(map_id)
            # Prose that asserts a live service waits for proof of one. The
            # legend title is not prose and makes no such claim, so it is never
            # held back.
            text_ok = True
            if name in MAP_TEXT_REQUIRES_LIVE_QUAKES:
                if live_quakes is None:
                    live_quakes = _quakes_are_live(api)
                text_ok = live_quakes

            delta = {}
            legend_spec = MAP_LEGEND_AND_NOTES.get(name)
            if legend_spec:
                legend_title, notes = legend_spec
                if current.get("legend_title") != legend_title:
                    delta["legend_title"] = legend_title
                if text_ok and current.get("notes") != notes:
                    delta["notes"] = notes
            # The description too, and for the same reason the notes are here:
            # it is written once at map creation, so a builder that skips an
            # existing map can never correct text that has gone false.
            description = MAP_DESCRIPTIONS.get(name)
            if (
                text_ok
                and description is not None
                and current.get("description") != description
            ):
                delta["description"] = description
            if not text_ok:
                print(
                    f"  (holding the live-service wording on {name!r}: the quake "
                    "datasets do not read from the service yet)"
                )
            if delta:
                api.set_view(map_id, **delta)
                print(f"  {'/'.join(sorted(delta))}: {name}")

            layers = current.get("layers") or []
            if name == EXPOSURE_MAP and _ensure_basin_context_layer(
                api, map_id, layers
            ):
                layers = (api.get_map(map_id) or {}).get("layers") or []

            groups = MAP_FOLDER_GROUPS.get(name, {})
            pitch_aligned = MAP_PITCH_ALIGNED_CIRCLES.get(name, ())
            style_fixes = MAP_LAYER_STYLE_FIXES.get(name, {})
            for layer in layers:
                paint_delta, builder_delta, field_delta, reasons = _layer_style_delta(
                    layer, groups, pitch_aligned, style_fixes
                )
                if reasons:
                    _restyle_layer(
                        api,
                        map_id,
                        layer,
                        paint=paint_delta,
                        builder=builder_delta,
                        fields=field_delta,
                    )
                    print(
                        f"  {'+'.join(reasons)}: {name} / {layer.get('display_name')}"
                    )
        except (httpx.HTTPStatusError, httpx.TimeoutException) as e:
            print(f"  WARNING: could not style {name!r}: {e}", file=sys.stderr)


def apply_globe_projection(api: "Api") -> None:
    """Put the global showcase maps on the globe projection (GLOBE_PROJECTION_MAPS).

    Runs over the maps that EXIST rather than inside each builder, because a
    builder skips a map it already found - so setting the projection at
    creation time would reach a fresh instance and never an existing one.

    Idempotent, and careful about what it writes: basemap_config is NOT merged
    server-side. PUT dumps the whole submodel, so a bare {"projection": ...}
    body silently resets every other basemap setting to its default. The stored
    config is read first and sent back with one key changed, and a map already
    on the globe is left alone entirely.

    Best-effort like enrich_showcase_metadata: a flaky PUT must not fail a seed
    whose maps and data are already built.
    """
    maps = api.list_maps()
    for name in GLOBE_PROJECTION_MAPS:
        map_id = maps.get(name)
        if not map_id:
            continue
        try:
            config = dict(api.get_map(map_id).get("basemap_config") or {})
            if config.get("projection") == "globe":
                print(f"  [ok] already on the globe: {name}")
                continue
            config["projection"] = "globe"
            api.set_view(map_id, basemap_config=config)
            print(f"  globe projection: {name}")
        except (httpx.HTTPStatusError, httpx.TimeoutException) as e:
            print(
                f"  WARNING: could not set globe projection on {name!r}: {e}",
                file=sys.stderr,
            )


def run_maintenance_mode(api: Api, args) -> int | None:
    """Run whichever terminal maintenance flag was passed, if any.

    Returns an exit code when one ran, or None to fall through to a normal
    seed. Each of these is a MODE rather than a step: it does its one job
    against an already-seeded instance and exits, so none of them compose with
    each other or with --only.
    """
    if args.refresh_quakes:
        return refresh_quakes(api)
    if args.refresh_hurdat2:
        return refresh_hurdat2(api)
    if args.prune_userdata:
        return prune_userdata(api, execute=args.execute)
    return None


def _builder_outcome_line(bname: str, result: str | None) -> str | None:
    """What main() prints for a builder that produced no NEW map, or None.

    None means "this result is a map id, record it as built". Split out of
    main() so the wording is testable and so the pinned case cannot drift back
    to the generic line, which tells the operator to do the one thing that
    would break the examples: "use --force to recreate" is exactly what --force
    declines to do to a pinned map (fix(#1607 review r2)).

    A falsy result keeps the generic line it has always had - a builder that
    returned nothing built nothing.
    """
    if result == "(pinned)":
        return (
            f"  {bname}: kept as-is - externally pinned (PINNED_MAP_NAMES), so "
            "--force left its id and share links alone; --force-pinned builds "
            "a fresh row beside it"
        )
    if not result or result == "(skipped)":
        return f"  {bname}: already exists, skipped (use --force to recreate)"
    return None


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
            "hurricane-exposure",
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
        help="re-create showcase maps/datasets even if they already exist "
        "(the externally pinned maps are kept - see --force-pinned)",
    )
    ap.add_argument(
        "--force-pinned",
        action="store_true",
        help="with --force, stop keeping the externally pinned maps "
        "(PINNED_MAP_NAMES). What that costs is NOT the same for all four. For "
        "'New York From Orbit' (Sentinel-2) it deletes the existing row(s) and "
        "their share links first and then recreates, so the externally "
        "referenced UUID is destroyed. For the other three the builder creates "
        "a fresh row beside the existing one, which keeps its UUID and share "
        "links until you delete it by hand. Either way, move the "
        "geolens-examples references (ci/fixtures.json, index.html) onto the "
        "new ids",
    )
    ap.add_argument(
        "--prune",
        action="store_true",
        help="first delete the retired first-generation showcase maps/datasets",
    )
    ap.add_argument(
        "--refresh-quakes",
        action="store_true",
        help="re-pull both earthquake datasets from their USGS service binding, "
        "then exit (the demo's weekly cron - nothing refreshes on its own)",
    )
    ap.add_argument(
        "--refresh-hurdat2",
        action="store_true",
        help="re-fetch HURDAT2 into both track datasets and rebuild the derived "
        "exposure chain, then exit (run after NHC publishes a new season)",
    )
    ap.add_argument(
        "--prune-userdata",
        action="store_true",
        help="report visitor-uploaded maps/datasets a cleanup would delete, then "
        "exit. DRY RUN unless --execute is also passed",
    )
    ap.add_argument(
        "--execute",
        action="store_true",
        help="with --prune-userdata, actually perform the deletions",
    )
    args = ap.parse_args()
    if not args.password:
        ap.error("--password or GEOLENS_ADMIN_PASSWORD is required")
    if args.execute and not args.prune_userdata:
        # --execute is a modifier, not a mode. Silently ignoring a stray one
        # would be fine today and a trap the moment anything else grows a
        # dry-run pair.
        ap.error("--execute is only meaningful with --prune-userdata")
    if args.force_pinned and not args.force:
        # Same shape as --execute: a modifier, not a mode. On its own it reads
        # like "force the pinned maps" and would do nothing whatsoever.
        ap.error("--force-pinned is only meaningful with --force")

    print(f"Logging in to {args.base_url} as {args.username}...")
    api = Api.login(args.base_url, args.username, args.password)

    maintenance = run_maintenance_mode(api, args)
    if maintenance is not None:
        return maintenance

    if args.prune:
        prune(api)

    fns = {
        "catalog": build_catalog,
        "restless": lambda a, force=False, force_pinned=False: build_restless_earth(
            a, force=force, with_oceans=not args.no_oceans, force_pinned=force_pinned
        ),
        "manhattan": build_manhattan,
        "hurricanes": build_hurricanes,
        "hurricane-exposure": build_hurricane_exposure,
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
            ("hurricane-exposure", fns["hurricane-exposure"]),
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
            # Every builder takes the same (api, force, force_pinned) so the
            # pinned-map rule cannot be forgotten by a builder added later; the
            # two with no map of their own ignore force_pinned (fix(#1607)).
            result = fn(api, force=args.force, force_pinned=args.force_pinned)
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
        outcome = _builder_outcome_line(bname, result)
        if outcome is None:
            built[bname] = result
        else:
            print(outcome)

    # Backfill license + keywords on whatever showcase datasets now exist (the
    # ingest flow leaves them "proprietary" with no keywords). Best-effort and
    # self-isolating - see enrich_showcase_metadata - so it never fails the seed.
    print("\nEnriching catalog metadata (license + keywords)...")
    enrich_showcase_metadata(api)

    # Rename before the passes below, not only inside build_hurricanes. Both
    # passes look the map up by its CURRENT name, and the builder that renames
    # it does not run under --only or after a builder failure - so without this
    # the map would keep its legacy name and silently miss its legend, notes
    # and globe projection. Guarded, so running it twice does nothing.
    _rename_map_if_needed(api, HURRICANE_MAP, HURRICANE_MAP_LEGACY)

    # Same shape and the same reason: applied to whatever showcase maps exist,
    # so an instance seeded before this landed gets the globe too.
    print("\nApplying the globe projection to the global showcase maps...")
    apply_globe_projection(api)

    print("\nApplying showcase styling (legends, groups, context layer)...")
    apply_showcase_styling(api)

    # The scenes are imported by reference, so a refresh is what proves it:
    # skipped when --no-sentinel2 meant none were built, and when --only built
    # something else entirely.
    if not args.no_sentinel2 and args.only in (None, "sentinel2"):
        refresh_sentinel2_scenes(api)

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
