# Research: Demo Environment Data & Maps

**Researched:** 2026-04-08
**Domain:** Demo content strategy — themed datasets, maps, automation posture
**Confidence:** HIGH on sources & licensing; HIGH on platform API surface; MEDIUM on map visual-impact predictions

---

## User Constraints (from CONTEXT.md)

### Locked Decisions
- **Strategy doc only.** Output is a single PROPOSAL.md — no code changes.
- **2-3 themed collections**, not one monolithic story, not a random sampler. Showcase the Collections feature.
- **Geopolitics in scope** but sourced and neutral. ACLED, UCDP, UN, Natural Earth disputed, OCHA, World Bank acceptable sources. No editorial framing. Must be safe for any customer, any region.
- **Static snapshots only.** Download-once public datasets. No API keys. No runtime outbound internet. Snapshot date stored as metadata.
- Sources in play: Natural Earth, GADM, OSM thematic extracts, Our World in Data, USGS, NASA Earthdata COGs, OCHA HDX, World Bank, SEDAC.

### Claude's Discretion
- Specific dataset selection within each theme.
- Sample map compositions (layers, styling, widgets, filters).
- Automation posture: ingest, collections, and sample-map auto-creation tradeoffs.
- Structure of the PROPOSAL document.

### Deferred Ideas (OUT OF SCOPE)
- Implementation of new seeder scripts, docker-compose wiring, auto-map creation (future phase).

---

## Summary

- **Pick three themes, not one.** Recommend: (1) **Planet Earth: Physical Systems** — safe, visually striking, exercises raster/VRT; (2) **Global Development & People** — UN/World Bank indicators, exercises tables + choropleths; (3) **Borders, Boundaries & Contested Space** — the "geopolitics" theme done safely via Natural Earth's public-domain disputed layer and UCDP CC-BY event data. Every theme intentionally touches a different record type so the demo showcases breadth.
- **ACLED is a landmine — do not ship it.** `[VERIFIED: acleddata.com/eula]` The ACLED EULA restricts governmental, quasi-governmental, and commercial use without a paid license, and explicitly prohibits training AI systems on ACLED data. GeoLens has an AI chat feature and targets government buyers. Use **UCDP GED** instead — same subject matter, CC-BY 4.0, no commercial or AI restrictions.
- **The maps API is fully automatable, but don't automate map creation.** `[VERIFIED: backend/app/maps/schemas.py, router.py]` `POST /api/maps/` creates an empty map, `PUT /api/maps/{id}` accepts a full `layers` list with MapLibre paint/layout/filter/labels/style_config, plus center/zoom/pitch/bearing/basemap/widgets. A seeder could build every sample map from JSON. **Recommendation:** automate dataset ingest + collection assignment, but hand-curate 2-3 signature maps per theme, then export them as versioned JSON fixtures. Rationale: reproducibility wins for data, but the map is the first impression — automation drift (e.g., a style_config schema change in a future version) can silently break the demo's "wow" moment. Fixtures let humans validate once and re-seed deterministically.
- **Total disk budget: ~1.2-1.5 GB bundled, ~3 GB after PostGIS ingest.** Natural Earth 10m (~400 MB zipped), one coarse GEBCO bathymetry COG downsampled to ~200 MB, Natural Earth shaded relief raster (~100 MB), ~30 Our World in Data / World Bank CSVs as table records (~20 MB), UCDP GED annual CSV (~50 MB), UNHCR refugee populations CSV (~10 MB). Leaves headroom for the existing Natural Earth baseline without bloating the demo image.
- **Every theme must produce at least one "60-second story" map.** A sales demo doesn't give a prospect time to explore — they need one compelling screen per theme that tells a visible story without interaction, plus 1-2 deeper maps for when the conversation gets interesting. Map design recommendations below are optimized for that 60-second read.

---

## Candidate Themes

Six themes considered. Top three recommended for the final demo.

| Theme | Visual | Record Types Exercised | 60-sec Story | License Risk | Pick? |
|---|---|---|---|---|---|
| **Planet Earth: Physical Systems** | HIGH — bathymetry, topography, rivers | vector + **raster COG** + **VRT** | "Mountains, oceans, rivers at a glance" | None | **YES** |
| **Global Development & People** | MEDIUM — choropleths | vector + **table** + semantic search | "Where people live, what they earn, how long they live" | None (WB/OWID are CC-BY) | **YES** |
| **Borders, Boundaries & Contested Space** | HIGH — disputed polygons + event dots | vector + table | "Where the lines are still being drawn" | LOW with curated sources | **YES** |
| Climate & Disaster | HIGH — wildfire, hurricane, COG | vector + raster + table | "The planet is moving" | NONE | backup |
| Energy & Infrastructure | MEDIUM — power plants, cables | vector + table | "How the world is wired" | Low (WRI CC-BY) | backup |
| Culture & History | MEDIUM — UNESCO, languages, treaties | vector + table | "A map of human civilization" | Low | deprioritize — thin on raster |

**Why these three:**
- Together they cover every record type the platform supports: vector (all three), raster COG (Theme 1), VRT mosaic (Theme 1), table records (Themes 2 & 3), and non-trivial semantic-search surface area (Theme 2 has rich tabular metadata that makes pgvector actually work; Themes 1 & 3 are lighter on text so they stress-test the filter/facet side).
- They present three different cognitive modes: physical world, social/statistical world, political world. A prospect can self-select the story that resonates with their org.
- None of them require live API access, API keys, or data that changes monthly — all are annually-refreshed-or-slower.

---

## Recommended Themes (Deep Dive)

### Theme 1: Planet Earth — Physical Systems

**Collection name:** "Planet Earth (2025 Snapshot)"
**Narrative:** "This is the stage on which everything else happens — land, water, elevation, ice."
**Primary value:** Exercises raster COG and VRT — the only theme that can demonstrate Titiler tile serving and the VRT mosaic lifecycle on realistic data without requiring multi-gigabyte downloads.

#### Datasets

| Dataset | Source | Format | Size | Record Type | License | Why |
|---|---|---|---|---|---|---|
| Natural Earth 1:10m coastline, land, ocean, rivers, lakes, glaciated areas, reefs, playas, minor islands | naciscdn.org | Shapefile | ~50 MB | vector | Public Domain `[VERIFIED: naturalearthdata.com/about]` | Foundation reference. Already in baseline — reuse, don't re-download. |
| Natural Earth 1:50m shaded relief (raster) | naciscdn.org/naturalearth/50m/raster | GeoTIFF | ~100 MB → convert to COG | raster_dataset | Public Domain | Exercises raster pipeline. Convert once at seeder-build time with `gdal_translate -of COG`. |
| GEBCO 2025 Grid (bathymetry) — coarse subset | gebco.net `[VERIFIED: gebco.net]` | GeoTIFF | Full grid ~6 GB; downsampled to 15 arc-min ~200 MB → COG | raster_dataset | Public Domain | Ocean depth. Download-once, convert to COG at build time. |
| Natural Earth 1:10m shaded relief tiles (2-3 bands: hypsometric, bathymetry, shaded relief) | naciscdn.org/naturalearth/10m/raster | GeoTIFF | ~300 MB total | vrt_dataset (mosaic of 2-3 sources) | Public Domain | **This is the VRT story.** Combine bathymetry + hypsometric + shaded relief into one VRT mosaic so the demo has a working VRT dataset to show off. |
| HydroSHEDS rivers (global, v1.1) | hydrosheds.org | Shapefile | ~40 MB | vector | ODbL + HydroSHEDS Technical Documentation license (CC-BY-compatible) `[ASSUMED]` — verify before shipping | Better river detail than Natural Earth. Optional. |

**Skip:** SRTM full-res (too big), Copernicus DEM (login required), OSM global extracts (too big, OSM world PBF is ~80 GB).

#### Sample Maps

**Map 1.1 — "Earth as Seen from Space"** (signature 60-second map)
- **Story:** One screen. You see the planet. Mountains, oceans, ice, rivers. Nothing else.
- **Basemap:** None — solid dark ocean background
- **Layers, top → bottom:** Rivers (thin white lines, width-by-scalerank) → Lakes (light blue fill) → Glaciated areas (white fill, 60% opacity) → Coastline (none, implied by land) → VRT mosaic (bathymetry + hypsometric + shaded relief) → Ocean fill
- **View:** center `[0, 15]` zoom 1.8 bearing 0 pitch 0
- **Widgets:** measurement, scale
- **Visual impact:** HIGH — this should look like a NASA Blue Marble still

**Map 1.2 — "Global Bathymetry"** (raster COG showcase)
- **Story:** The ocean floor. Trenches, ridges, continental shelves, revealed.
- **Basemap:** Light ("positron")
- **Layers:** GEBCO bathymetry COG (single band, viridis-reversed colormap via Titiler `?colormap_name=viridis_r`) → Coastline → Country borders (thin, dark)
- **Widgets:** measurement, elevation popup

**Map 1.3 — "Where the Ice Is"** (simple, focused story)
- **Story:** Every glacier, every ice shelf, on one map.
- **Basemap:** Dark
- **Layers:** Glaciated areas → Antarctic ice shelves polygons → Ice shelves lines → Coastline
- **Styling:** Graduated fill by area (small glaciers pale, ice sheets bright cyan)
- **Widgets:** measurement

---

### Theme 2: Global Development & People

**Collection name:** "How the World Lives (2024)"
**Narrative:** "Seven billion people, 200 countries, indicators that actually mean something — population, income, life expectancy, education."
**Primary value:** Exercises **table records** (the v12.0 record type), semantic search (rich tabular metadata), joins between tables and the ADM0 polygon for choropleth maps via the AI map builder, and facets by source/topic.

#### Datasets

| Dataset | Source | Format | Size | Record Type | License | Why |
|---|---|---|---|---|---|---|
| World Bank WDI — population, GDP per capita (PPP), life expectancy, internet penetration, urban share, under-5 mortality | databank.worldbank.org | CSV (one per indicator) | ~2-5 MB each | **table** | CC-BY 4.0 `[ASSUMED — World Bank Open Data terms are CC-BY 4.0 for most indicators; verify per-indicator]` | Seven classic development indicators. Each becomes a `record_type=table` dataset. |
| Our World in Data — human development index, GINI, democracy index (V-Dem), child mortality, educational attainment | ourworldindata.org | CSV | ~1-3 MB each | **table** | CC-BY 4.0 `[VERIFIED: ourworldindata.org]` — most OWID charts explicitly ship with CC-BY download buttons | Richer narrative data. OWID tables are opinionated (single value per country-year) — easy to join. |
| GADM Level 0 (countries) | gadm.org | GeoPackage | ~100 MB | vector | Academic / free for non-commercial `[VERIFIED — GADM license is NOT a true open license]` | **SKIP GADM.** License is not commercial-friendly. Use Natural Earth admin_0_countries from the baseline instead. |
| SEDAC Gridded Population of the World (GPWv4) — coarse | sedac.ciesin.columbia.edu | GeoTIFF | ~100 MB at 1° → COG | raster_dataset | CC-BY 4.0 | "Where people actually live" as a raster. Nice counterpoint to the country-level choropleths. |

**Explicit skip:**
- **GADM** — license is not a permissive open license (prohibits redistribution without permission for some uses). The baseline Natural Earth `ne_10m_admin_0_countries` is adequate.
- **OSM global extracts** — too large and not necessary for any map in this collection.
- **Our World in Data grapher JSON snapshots** — use CSV exports, not grapher URLs, to keep the seeder deterministic.

#### Sample Maps

**Map 2.1 — "Population at a Glance"** (signature 60-second map)
- **Story:** Where the people are. Big dots where there are lots of them.
- **Basemap:** Light
- **Layers:** Countries outline (thin gray) → Populated places (proportional symbol by `POP_MAX`, 4→40 px, colored by `ADM0NAME` via categorical)
- **Built from the AI prompt:** "Show me where people live, sized by population"

**Map 2.2 — "GDP per Capita (PPP, 2023)"** (choropleth story + table join demo)
- **Story:** Global income distribution on a choropleth, legibly.
- **Basemap:** Light
- **Layers:** Countries, joined on `ADM0_A3` to the World Bank GDP-per-capita table, choropleth fill with 7-bucket quantile ramp (Brewer YlGnBu)
- **Build path:** This is the map that showcases the **table → spatial join** workflow. If the platform does not currently support declarative "join this table to this polygon and color by column," this map has to be built by materializing a derived view. Flag this as an **Open Question** — see below.
- **Widgets:** feature popup showing indicator value

**Map 2.3 — "Life Expectancy & Income"** (two-variable story)
- **Story:** Rich countries live longer, but the relationship isn't linear — and here are the outliers.
- **Basemap:** Light
- **Layers:** Countries outline → Countries choropleth by life expectancy (sequential ramp) → Country labels where GDP/capita > $30k and life expectancy < 75 (labels reveal the outliers)
- **Widgets:** layer legend, popup

---

### Theme 3: Borders, Boundaries & Contested Space

**Collection name:** "Lines on the Map (2024 Snapshot)"
**Narrative:** "Every line on a world map was drawn by someone. Some are settled, some are not. This is what the authoritative sources say about the disputed ones."
**Primary value:** This is the "geopolitics" theme done safely. No editorial framing; every layer's description cites source and snapshot date. The value is showing that GeoLens can catalog contested information neutrally and let the user pick the view.

#### Datasets

| Dataset | Source | Format | Size | Record Type | License | Why |
|---|---|---|---|---|---|---|
| Natural Earth `ne_10m_admin_0_disputed_areas` | naciscdn.org | Shapefile | <1 MB | vector | Public Domain `[VERIFIED: naturalearthdata.com]` | The polygons for every disputed area NE tracks (Kashmir, Western Sahara, N. Cyprus, Elemi Triangle, etc). Draws de-facto lines by Natural Earth's published policy `[VERIFIED: naturalearthdata.com/about/disputed-boundaries-policy]`. |
| Natural Earth `ne_10m_admin_0_boundary_lines_disputed_areas` | naciscdn.org | Shapefile | <1 MB | vector | Public Domain | The *lines* of disputed boundaries (different from the areas). |
| Natural Earth `ne_10m_admin_0_breakaway_disputed_areas` | naciscdn.org | Shapefile | <1 MB | vector | Public Domain | Breakaway regions with de-facto control (e.g., Transnistria, Somaliland). |
| Natural Earth country-specific boundary overrides (`ne_10m_admin_0_countries_arg`, `_chn`, `_ind`, `_isr`, `_pak`, `_rus`, `_tur`, `_ukr`, `_usa`) | naciscdn.org | Shapefile | ~10 MB total | vector | Public Domain | Multiple parallel views of the same contested regions, from each source's "official" stance. The demo story: "the same territory, nine different official maps." This is *the* feature that makes this collection unique. All 9 are already in the `seed-natural-earth.py` manifest — just needs to be enabled. |
| UCDP Georeferenced Event Dataset (GED) v25.1 — 2015-2024 subset | ucdp.uu.se `[VERIFIED: ucdp.uu.se/downloads]` | CSV with lat/lon columns | ~30 MB | vector (point) | CC-BY 4.0 `[VERIFIED]` | Fatal events of organized violence. Safe alternative to ACLED (see safety analysis below). Ingest as a point layer, filter by year. Cite UCDP version and snapshot date prominently. |
| UNHCR Refugee Population Statistics — end-year 2023 | unhcr.org/refugee-statistics/download `[VERIFIED]` | CSV | ~10 MB | **table** | CC-BY 4.0 `[VERIFIED: unhcr.org]` | Country-to-country refugee flows. Becomes a table record and powers a flow/choropleth map. |
| UN membership / treaty accession status (e.g., NATO, EU, BRICS, ASEAN) | Wikipedia source tables or World Factbook | CSV (hand-curated) | <100 KB | table | Public Domain / CC-BY-SA (Wikipedia — cite) `[ASSUMED]` — World Factbook is US Gov PD; Wikipedia CC-BY-SA | Who belongs to which club. One of the most-requested demo questions from enterprise prospects. |
| Natural Earth `ne_10m_admin_0_antarctic_claims` | naciscdn.org | Shapefile | <1 MB | vector | Public Domain | The seven Antarctic claim sectors. Visually clean, obviously neutral, great "did you know" moment. |

**Explicit skip:**
- **ACLED** — see Safety Analysis below.
- **Marine Regions EEZ** — CC-BY 4.0 but updates are opinionated on disputed maritime boundaries, same sensitivity surface as land borders, complicated attribution. Not worth it for a starter demo.
- **CEPII BACI / trade flows** — too tabular, weak on visual story in 60 seconds.

#### Sample Maps

**Map 3.1 — "The World's Disputed Places"** (signature 60-second map)
- **Story:** Every place on Earth where the lines are still being argued over. Labeled by Natural Earth's published name for the dispute.
- **Basemap:** Light ("positron")
- **Layers:** Countries (pale fill, thin outline) → Disputed areas (orange fill, 50% opacity) → Breakaway disputed areas (yellow fill) → Disputed boundary lines (orange dashed) → Antarctic claims (pale blue, labeled) → Label layer on disputed areas (name from `NOTE_BRK` or `NAME`)
- **Widgets:** feature popup showing dispute note, layer legend

**Map 3.2 — "One Territory, Multiple Official Maps"** (THE conversation-starter)
- **Story:** Zoom into Kashmir. Toggle layers. Watch the border change.
- **Basemap:** Light
- **Layers:** `ne_10m_admin_0_countries_chn` (China view) + `ne_10m_admin_0_countries_ind` (India view) + `ne_10m_admin_0_countries_pak` (Pakistan view), all initially invisible except one, each rendered as outline-only with a distinct color (teal, saffron, green). User toggles layer visibility to see the three parallel "official" views.
- **View:** Kashmir region, `center=[76, 34] zoom=6`
- **Widgets:** layer toggle panel (built-in via the layer list)
- **Why this map matters:** it's the single most memorable thing in the entire demo. A prospect who sees this will remember GeoLens.

**Map 3.3 — "Conflict Events 2024 (UCDP GED)"** (point density story)
- **Story:** A year of fatal events of organized violence, as recorded by UCDP, aggregated by location.
- **Basemap:** Dark
- **Layers:** Countries outline (white thin) → UCDP GED points filtered to `year=2024` (small red circles, opacity 0.4), clustered at low zoom, unclustered at high zoom
- **Widgets:** popup showing event description, source, date; year filter slider
- **Attribution:** footer MUST cite "UCDP GED v25.1, released 2025-06, CC-BY 4.0"

**Map 3.4 — "Refugees by Country of Origin (2023)"** (table-joined choropleth)
- **Story:** Where the world's refugees are coming from.
- **Layers:** Countries joined on ISO3 to the UNHCR origin table → choropleth by log(refugees_out)
- **Attribution:** "UNHCR Refugee Data Finder, end-2023 snapshot"

---

## Geopolitics Safety Analysis

The CONTEXT locked decision is "embrace carefully — must be safe for any prospect, any region." That imposes two tests on every candidate:
1. **License test:** Is the data redistributable with attribution, and is it compatible with commercial and governmental customer use (including AI-assisted features)?
2. **Editorial test:** Does the source have a published, defensible policy for handling contested claims, so GeoLens can say "we show what the source says, take it up with them"?

| Angle | License Safe? | Editorial Safe? | Recommendation |
|---|---|---|---|
| **Disputed borders & de facto control** (Natural Earth) | YES — Public Domain `[VERIFIED]` | YES — NE has a published disputed-boundaries policy since 2009 `[VERIFIED]` | **SHIP.** This is the safest geopolitical content on the internet. |
| **UCDP GED conflict events** | YES — CC-BY 4.0, no AI restriction `[VERIFIED]` | YES — academic, peer-reviewed, public codebook | **SHIP.** Always cite version and snapshot date in the layer description. |
| **ACLED conflict events** | **NO** — governmental and commercial use require paid license; AI training prohibited `[VERIFIED: acleddata.com/eula]` | Yes (academically rigorous) | **DO NOT SHIP.** GeoLens (a) targets government buyers, (b) has AI chat, (c) is commercial/open-core. All three are EULA violations. Use UCDP instead. |
| **Trade & sanctions** (World Bank, UN Comtrade) | YES — CC-BY | YES | Backup. Low visual impact vs. borders story. |
| **Migration & displacement** (UNHCR, IDMC) | YES — CC-BY `[VERIFIED for UNHCR]` | YES | **SHIP** — already in Theme 3. IDMC is a nice-to-have. |
| **Elections / governance** (V-Dem, Freedom House) | V-Dem CC-BY `[ASSUMED]`; Freedom House unclear terms | MEDIUM — ratings are interpretive and politically charged in some regions | **Use V-Dem only if license verified, and label as "Source: V-Dem Institute v14, 2024"**. Skip Freedom House. |
| **Treaties & memberships** (UN, NATO, EU, BRICS) | Public record | YES — membership is non-controversial fact | Light ship — hand-curated CSV. |
| **Maritime boundaries & EEZ** (Flanders Marine Institute) | CC-BY 4.0 | MIXED — EEZ disputes exist (e.g., South China Sea) | **Defer.** Not worth the complication for v1 demo. |

**Hard no-go list for this demo:** ACLED, Freedom House (license uncertain), any single-country partisan source, any dataset whose description uses words like "aggression," "occupation," or "terrorism" in layer metadata (cite source verbatim only).

**Language discipline in layer descriptions:** Every geopolitics-adjacent layer must follow the pattern:

> "Source: {Source Name} v{version}, released {date}. {Source}'s published policy on contested regions: {URL}. Contents shown per {Source}'s editorial stance, not GeoLens."

---

## Automation Posture

### What the API can do

Verified from `backend/app/maps/` and `backend/app/collections/`:

**Maps:** `[VERIFIED: backend/app/maps/schemas.py, router.py]`
- `POST /api/maps/` — create empty map (name, description only). Returns map UUID.
- `PUT /api/maps/{id}` — **full update** — accepts the entire map in one call: `name, description, center_lng, center_lat, zoom, bearing, pitch, basemap_style, show_basemap_labels, visibility, layers[], widgets[]`. Each `MapLayerInput` includes `dataset_id, sort_order, visible, opacity, paint (MapLibre paint dict), layout (MapLibre layout dict), display_name, filter (MapLibre filter expression), label_config, style_config (categorical/graduated), layer_type, show_in_legend`.
- `POST /api/maps/{id}/share/` — mint share token for public link.

**Conclusion: creating a complete map via API is a two-call operation.** `POST /api/maps/ {name}` → `PUT /api/maps/{id} {full body}`.

**Collections:** `[VERIFIED: backend/app/collections/schemas.py, seed-natural-earth.py lines 623-733]`
- `POST /api/catalog/collections/` — create collection (name, description). Returns 201 with UUID; 409 on duplicate name (already handled idempotently in `seed-natural-earth.py`).
- `POST /api/catalog/collections/{id}/datasets` — add batch of dataset IDs (max 100).

**Ingest (vector + raster + table):** `[VERIFIED: backend/app/ingest/router.py]`
- Single `/upload` → `/preview/{job_id}` → `/commit/{job_id}` pipeline handles **all three record types**. Raster files are auto-detected (magic bytes) and routed to COG processing. Tables (CSV without geometry) become `record_type=table`. VRT mosaics use a separate `/vrt/create` endpoint.

### Recommended posture

| Concern | Automate? | Reason |
|---|---|---|
| **Dataset ingest (vector)** | **YES** | Already working in `seed-natural-earth.py`. Pattern is proven. Extend to handle multi-source. |
| **Raster COG ingest** | **YES** | Same pipeline. Just needs `gdal_translate -of COG` at seeder build time before upload. |
| **VRT mosaic creation** | **YES** | `/vrt/create` is a single call with source dataset IDs. |
| **Table record ingest (CSV)** | **YES** | Same upload pipeline. |
| **Collection creation + assignment** | **YES** | Already done in `seed-natural-earth.py` — lift the pattern. |
| **Sample map creation** | **PARTIAL — fixtures, not code** | Hand-curate 2-3 maps per theme once, then export each via `GET /api/maps/{id}` to a JSON fixture committed to the repo. Seeder reads fixture and runs `PUT /api/maps/{id}`. |
| **Share tokens for sample maps** | NO | Let the operator mint if they want a guest link. Keeps the demo secure by default. |

### Why fixtures, not generated-from-code maps

A map has ~30 style knobs per layer. Hand-coding them in Python is (a) verbose, (b) fragile against future schema changes (e.g., a new required field in `MapLayerInput`), and (c) divergent from what humans actually build in the UI. If the planner picks "generate maps from Python," the generation code becomes a second dialect of the map schema that has to be kept in sync.

**Fixtures solve this:**
1. Human builds a signature map in the UI.
2. `curl GET /api/maps/{id}` → save to `scripts/fixtures/demo-maps/theme-1-earth-from-space.json`.
3. Commit JSON to repo.
4. Seeder reads JSON, rewrites `layers[].dataset_id` to match newly-ingested dataset UUIDs (via a name-lookup map), and `PUT /api/maps/{id}`.

**The one hard part:** dataset UUIDs are regenerated on every seed, so layers[].dataset_id in fixtures must be resolved by name at seed time. This is easy — seeder already has a `source_filename → dataset_id` map from the idempotency check (see `fetch_existing_datasets` in `seed-natural-earth.py:257-295`). Extend that to cover CSV/raster stems.

### Pseudocode sketch of `seed-thematic-demo.py`

```python
# Reuses primitives from seed-natural-earth.py — do NOT rewrite
from seed_natural_earth import (
    fetch_existing_datasets, ingest_dataset, create_or_get_collection
)

THEMES = [
    {"name": "Planet Earth (2025 Snapshot)", "datasets": [...], "maps": [...]},
    {"name": "How the World Lives (2024)",   "datasets": [...], "maps": [...]},
    {"name": "Lines on the Map (2024 Snapshot)", "datasets": [...], "maps": [...]},
]

async def seed_theme(theme, client, base_url, api_key):
    # 1. Ingest all datasets (idempotent — skips if source_filename exists)
    name_to_id = {}
    for ds in theme["datasets"]:
        data = await download_or_load_cache(...)
        # raster, vrt, vector, table all take the same path; API auto-detects
        result = await ingest_dataset(client, base_url, api_key, ds["stem"], data, ...)
        name_to_id[ds["stem"]] = result["dataset_id"]

    # 2. Create collection + attach datasets
    coll_id = await create_or_get_collection(client, base_url, {...},
                                              theme["name"], theme["description"])
    await client.post(f"{base_url}/api/catalog/collections/{coll_id}/datasets",
                      json={"dataset_ids": list(name_to_id.values())})

    # 3. Hydrate signature maps from JSON fixtures
    for map_fixture_path in theme["maps"]:
        fixture = json.load(open(map_fixture_path))
        # Rewrite layer dataset_ids from stems
        for layer in fixture["layers"]:
            stem = layer.pop("_stem")  # fixtures use _stem, not dataset_id
            layer["dataset_id"] = name_to_id[stem]
        # Two-step: create shell, then PUT full body
        shell = await client.post(f"{base_url}/api/maps/",
                                   json={"name": fixture["name"],
                                         "description": fixture["description"]})
        map_id = shell.json()["id"]
        await client.put(f"{base_url}/api/maps/{map_id}", json=fixture)

async def main():
    existing = await fetch_existing_datasets(...)
    for theme in THEMES:
        await seed_theme(theme, ...)
```

**Cache-on-build posture:** All downloads happen during seeder container build (via a `Dockerfile` `RUN` step), NOT at container run. Container ships with datasets baked into `/seed-data/`. This satisfies the "no outbound internet at demo run-time" constraint from CONTEXT.md. Build-time license terms still apply — the Dockerfile is what actually downloads the data, and the build log is the redistribution record.

---

## Pitfalls

- **Disk bloat.** Natural Earth 10m raster is ~300 MB, GEBCO bathymetry even at 15 arc-min is ~200 MB after COG conversion, Natural Earth vector baseline is ~400 MB. Cap total bundled data at ~1.5 GB; downsample bathymetry more aggressively if needed. `gdal_translate -of COG -co COMPRESS=DEFLATE -co PREDICTOR=3 -co OVERVIEWS=IGNORE_EXISTING` for float rasters, `-co COMPRESS=ZSTD` for byte rasters.
- **ACLED trap.** Already flagged. Reviewers will suggest ACLED — write the rejection rationale into the proposal so it doesn't come up twice.
- **GADM license trap.** GADM is NOT true open data for commercial use. Use Natural Earth ADM0 instead, always. Do not let a contributor PR add GADM to the manifest without a license review.
- **CSV encoding + column name collisions.** World Bank and OWID CSVs have column names like `"Country Name"` (with spaces, sometimes unicode). The ingest pipeline's slugifier should handle this but test with a real file first. See `ENCODING_OVERRIDE_STEMS` pattern in `seed-natural-earth.py:384` for how the current code handles encoding landmines.
- **World-scale rendering gotchas.** Natural Earth populated places with `scalerank < 3` is only ~250 points and looks sparse at world zoom; `scalerank < 5` is ~2500 and legible. HydroSHEDS river order > 4 at world zoom is unusable density — pre-filter in the seed by `ORD_STRA >= 5` or the map will look like spaghetti.
- **Raster + basemap label conflict.** COG raster layers with default styling often wash out basemap labels. Set layer opacity to 0.85 and pick `basemap_style=positron-no-labels` (if it exists in admin basemap presets) or use a `labels_on_top` layer.
- **Semantic search noise at small N.** pgvector embedding-based search gets more interesting with more rich-metadata records. With only ~30 non-Natural-Earth datasets, semantic search will be "barely works" quality. Ensure each table record has a paragraph-long, keyword-rich description in its metadata so embeddings have something to chew on.
- **"Looks dated" risk.** Demo with 2024 data shown in 2028 is a credibility killer. Mitigation: (a) prefer datasets that update annually not monthly; (b) include snapshot date in every layer's title/description; (c) document a 12-month refresh cadence as a follow-on task, with the seeder's manifest as the single source of truth.
- **Map fixture drift.** If the `MapLayerInput` schema gains a required field, all fixtures break. Mitigation: add a JSON schema version field to fixtures; have the seeder validate against the current `MapLayerInput` on load; fail loud, not silent.
- **Share-token pollution.** Don't auto-mint share tokens during seed. Reset-demo has to know to clean them up, and stale public share URLs are a security risk.
- **OWID CSV format variance.** Different OWID datasets have different column schemas (some are country-year pairs, some are country-year-category triples). Don't assume a uniform shape — pre-normalize during seeder build, not at ingest time.
- **World Bank indicator codes vs human names.** WDI indicator codes like `NY.GDP.PCAP.PP.CD` are unusable in a UI. Make the dataset title human-readable ("GDP per capita, PPP (current international $)") and keep the code in metadata.

---

## Platform API Reference (for the planner)

| Operation | Endpoint | Body |
|---|---|---|
| Ingest vector/raster/table | `POST /api/ingest/upload` + `POST /api/ingest/preview/{id}` + `POST /api/ingest/commit/{id}` | File + commit body (title, visibility, srid_override) |
| Create VRT mosaic | `POST /api/ingest/vrt/create` | list of source dataset IDs |
| Tag record (post-ingest) | `POST /api/records/{record_id}/keywords/` | `{keyword, keyword_type}` |
| Create collection | `POST /api/catalog/collections/` | `{name, description}` |
| Add datasets to collection | `POST /api/catalog/collections/{id}/datasets` | `{dataset_ids: [...]}` |
| Create map shell | `POST /api/maps/` | `{name, description}` |
| Populate map | `PUT /api/maps/{id}` | full map body incl. `layers[]` with MapLibre paint/layout/filter/labels/style_config |
| Export map for fixture | `GET /api/maps/{id}` | returns full `MapResponse` — strip id/timestamps/created_by, store to JSON |

---

## Project Constraints (from CLAUDE.md)

- No AI/bot attribution in commit messages.
- Prefer simple readable code over clever abstractions.
- Follow existing project conventions (for this task: Python async + httpx, same pattern as `seed-natural-earth.py`).
- Be direct and concise (applies to proposal prose — avoid marketing language in the PROPOSAL.md).

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|---|---|---|
| A1 | World Bank WDI is CC-BY 4.0 for all indicators (some API terms apply) | Theme 2 | LOW — plan to verify per-indicator before shipping |
| A2 | HydroSHEDS license is compatible with commercial redistribution | Theme 1 | LOW — it's an "optional" layer; drop if verification fails |
| A3 | V-Dem is CC-BY | Geopolitics safety | MEDIUM — skip V-Dem entirely if not verified |
| A4 | Wikipedia-sourced treaty membership tables can be attributed under CC-BY-SA | Theme 3 | LOW — alternative is US CIA World Factbook (public domain) |
| A5 | Natural Earth shaded relief rasters redistribute cleanly (inherit PD from the NE project) | Theme 1 | LOW — NE's public domain declaration is explicit and broad |
| A6 | Bundled seeder image of ~1.5 GB is acceptable for docker-compose demo | Pitfalls | MEDIUM — if target is "fits in GitHub Actions cache," may need to drop GEBCO |
| A7 | The platform's AI map builder can join a table record to an ADM0 polygon by ISO3 code and produce a choropleth | Theme 2 Map 2.2 | **HIGH — this is the signature map for Theme 2.** If the platform can't do table joins in the map builder today, either (a) defer Map 2.2 to a later phase, (b) pre-materialize a view that contains the join, or (c) use a pre-joined GeoJSON. Planner must verify before committing to this map. |
| A8 | MapLibre `paint` / `layout` / `filter` / `style_config` schemas are stable enough that fixtures committed today will still load in 6-12 months without migration | Automation Posture | MEDIUM — enforce fixture version stamps and validation in seeder |

---

## Open Questions for the Planner

1. **Table → spatial join capability.** Can the current map builder produce a choropleth from a `record_type=table` CSV joined to a polygon dataset on a key column (e.g., ISO3)? If not, Theme 2 Map 2.2 ("GDP per Capita") either becomes a pre-materialized GeoJSON or gets downgraded. The answer determines whether Theme 2 has a signature map or not. See `backend/app/maps/service.py` and the AI map builder tool-calling code.
2. **VRT mosaic + COG dataset count.** Does the demo need exactly one VRT to "exercise" the feature, or should we ship 2-3 to exercise the VRT lifecycle (add source, remove source, replace source)? The proposal currently recommends one; verify that's enough to be a meaningful demo.
3. **Share link posture in the demo.** Should any sample maps ship with pre-minted share tokens (for a one-click "look at this!" from docs/README), or should operators mint their own? Share tokens are a security surface — recommend default-off, but confirm.
4. **`reset-demo.sh` scope.** When an operator wants to re-seed, does the reset script drop **only** the demo's datasets/collections/maps, or **everything**? The thematic seeder has to be idempotent in the face of partial resets. Review `scripts/reset-demo.sh` (not read in this research).
5. **i18n / translation of layer titles and descriptions.** The v6.x milestones added i18n. Do layer titles/descriptions get translated for the demo, or ship English-only? If translated, pre-populate the translation table at seed time or rely on the platform's runtime LLM fallback.
6. **AI chat seeding.** Should the demo include a set of suggested prompts on the AI chat panel ("Show me where people live", "What countries have disputed borders?") so a prospect can immediately see AI map building work? This is a separate feature surface from map fixtures but adds huge demo punch. Not resolved in this research.
7. **Export STAC 1.1 for raster datasets.** v10.0 shipped STAC export. Does the demo need to demonstrate this? If yes, the raster layers in Theme 1 should include rich STAC-compatible metadata in their ingest commit body.
8. **Refresh cadence ownership.** Who owns annual refresh of the snapshots, and what's the gate that detects "demo data is too old"? Not implementation, but a planning concern — flag for the planner to define.

---

## Sources

### Primary (HIGH confidence)
- Natural Earth licensing & disputed boundaries policy — `[VERIFIED: naturalearthdata.com/about, naturalearthdata.com/about/disputed-boundaries-policy]`
- Natural Earth baseline seed script — `/Users/ishiland/Code/geolens/scripts/seed-natural-earth.py`
- Natural Earth downstream demo seeder — `/Users/ishiland/Code/geolens/scripts/seed-demo.sh`
- GeoLens Maps API — `/Users/ishiland/Code/geolens/backend/app/maps/schemas.py`, `/Users/ishiland/Code/geolens/backend/app/maps/router.py`
- GeoLens Collections API — `/Users/ishiland/Code/geolens/backend/app/collections/schemas.py`
- GeoLens Ingest API — `/Users/ishiland/Code/geolens/backend/app/ingest/router.py` (vector + raster + VRT paths verified)
- UCDP Dataset Download Center — https://ucdp.uu.se/downloads/ (CC-BY 4.0 verified)
- UNHCR Refugee Statistics — https://www.unhcr.org/refugee-statistics/download (CC-BY 4.0 verified)
- ACLED EULA (basis for the hard-no ship decision) — https://acleddata.com/eula, https://acleddata.com/contentusage
- GEBCO Gridded Bathymetry — https://www.gebco.net/data-products/gridded-bathymetry-data (public domain verified)
- .planning/PROJECT.md (record types, current baseline capabilities)
- .planning/STATE.md (current milestone, v12.0 record-first architecture confirmed)

### Secondary (MEDIUM confidence)
- Our World in Data CC-BY download terms (general statement; per-chart verification recommended for any specific dataset included)
- World Bank WDI terms (CC-BY is the general stance for Open Data indicators; legal text per indicator)
- NASA Earthdata COG program description — https://www.earthdata.nasa.gov/engage/cloud-optimized-geotiffs

### Tertiary (LOW — flagged in Assumptions)
- HydroSHEDS license details
- V-Dem license details
- Wikipedia treaty-membership tables as demo source (CC-BY-SA attribution mechanics)

---

## Metadata

**Confidence breakdown:**
- Source/license viability: HIGH — key claims (ACLED restrictive, UCDP/UNHCR CC-BY, Natural Earth PD, GEBCO PD) are verified against primary sources.
- Platform API surface: HIGH — verified by reading `schemas.py` and `router.py` directly.
- Theme selection: MEDIUM — based on platform capability fit, not on customer testing. Recommend validating the three-theme pick against any real sales-motion input before committing.
- Map visual impact predictions: MEDIUM — hand-curated maps are creative choices; the six maps flagged as "signature 60-second" should be built in a throwaway branch first and validated by a human before fixture export.
- Disk budget estimate: MEDIUM — rough sums, not bench-tested.

**Research date:** 2026-04-08
**Valid until:** 2026-10-08 (6 months — licensing stability high, but annual refresh of UCDP GED / UNHCR / World Bank will nudge this to need re-verification)
