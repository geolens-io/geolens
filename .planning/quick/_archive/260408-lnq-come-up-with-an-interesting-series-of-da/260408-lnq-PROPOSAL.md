---
title: "Demo Environment Data & Maps — Strategy Proposal"
quick_id: 260408-lnq
date: 2026-04-08
status: proposal
decision_required_from: project owner
---

# Demo Environment Data & Maps — Strategy Proposal

A decision document for whether and when to ship themed demo content (three collections, six signature maps) to replace the current reference-layer-only demo.

**Reference files:**
- [260408-lnq-CONTEXT.md](./260408-lnq-CONTEXT.md) — locked decisions this proposal honors
- [260408-lnq-RESEARCH.md](./260408-lnq-RESEARCH.md) — source material: full dataset tables, API verifications, safety analysis. Read this for the evidence; read this proposal for the decisions.

---

## TL;DR

- **Three themed collections recommended:** Planet Earth — Physical Systems (raster/VRT story), Global Development & People (table records + semantic search story), and Borders, Boundaries & Contested Space (geopolitics done safely).
- **Automation posture:** Automate dataset ingest (vector, raster COG, VRT, table CSV) and collection assignment using existing `seed-natural-earth.py` primitives. Hand-curate six signature maps in the GeoLens UI, then export as JSON fixtures committed to the repo; the seeder re-seeds deterministically from fixtures.
- **ACLED is out; UCDP is in:** ACLED's EULA conflicts with governmental, commercial, and AI-training use — all three apply to GeoLens. UCDP GED v25.1 covers the same subject matter (organized violence events), is CC-BY 4.0 with no AI restriction, and is the drop-in replacement.
- **A7 RESOLVED (2026-04-08, quick task 260408-mgg):** Table→polygon join is NOT supported in the map builder — the tile pipeline requires a `geom_4326` column that does not exist on CSV tables. Fallback **Option C** selected: the seeder pre-joins each indicator CSV to ADM0 polygons offline and emits a choropleth-ready GeoJSON. Zero platform code changes. Theme 2 ships at full scope. See `../260408-mgg-a7-spike-verify-map-builder-can-join-rec/260408-mgg-FINDINGS.md`.
- **Recommended next step:** Schedule a medium-complexity implementation phase of approximately 5 plans (A7 spike removed from Plan 1). Ready for `/gsd-discuss-phase`.

---

## Current State

The current demo entry point, `scripts/seed-demo.sh`, calls `scripts/seed-natural-earth.py` to ingest approximately 20 Natural Earth `ne_10m_*` reference layers: coastlines, country boundaries, populated places, rivers, lakes, and ocean. There are no sample maps. There are no collections. There is no narrative.

The platform works correctly — data ingests cleanly, vector tiles render, search returns results. But a prospective user opening the demo sees a flat catalog of technical reference layers. Nothing explains what GeoLens is for. Nothing demonstrates raster COG tile serving via Titiler, VRT mosaics, table records (the v12.0 record type), semantic search via pgvector, the Collections feature, AI-assisted map building, or share links. The AI map builder has data to work with, but the data is so sparse that any map it builds is just another country-outlines view.

The opportunity: three themed collections built around a narrative — one per cognitive mode (physical world, social-statistical world, political world) — can demonstrate every platform capability in a context a prospect immediately understands. The Collections feature exists to present "playlists" of related datasets; using it for the demo exercises and showcases the feature simultaneously. A sales demo built on themed collections gives a rep three distinct 60-second stories to choose from depending on who is in the room.

---

## Recommended Themes

The demo will contain exactly three themed collections. Alternatives considered (Climate & Disaster, Energy & Infrastructure, Culture & History) are competent backup choices but do not exercise the full record-type surface area as cleanly — see RESEARCH.md §Candidate Themes for the comparison table.

### Theme 1: Planet Earth — Physical Systems

**Elevator pitch:** The stage on which everything else happens. Land, water, elevation, ice — all layers, one screen.

**Collection name:** "Planet Earth (2025 Snapshot)"

**Why this theme:** It is the only theme that exercises both raster COG tile serving (Titiler) and VRT mosaics on realistic, visually compelling data without requiring data that raises license or editorial concerns. The visual impact is immediate — bathymetry and shaded relief together produce a Blue Marble effect that reads in two seconds. It also reuses the existing Natural Earth baseline, so the incremental ingest is modest.

**Record types exercised:** vector + raster COG + VRT mosaic

**Signature 60-second story:** One screen showing the planet with mountains, ocean depth, glaciers, and rivers — nothing else, no interaction required.

---

### Theme 2: Global Development & People

**Elevator pitch:** Seven billion people, 200 countries. Population, income, life expectancy — where the world is and where it's heading.

**Collection name:** "How the World Lives (2024)"

**Why this theme:** It exercises table records (the v12.0 `record_type=table` architecture) on substantive data that enterprise prospects immediately recognize — World Bank and Our World in Data indicators are near-universal references. The rich textual metadata in these tables (indicator names, country names, year ranges) gives the pgvector semantic search something meaningful to work with. It is the only theme where a prospect can see the AI map builder produce a data-driven map from a natural-language prompt ("show me where people live").

**Record types exercised:** vector + table records + raster COG + semantic search surface

**Signature 60-second story:** A world map of populated places, dot-sized by population, produced from an AI prompt — no configuration required.

---

### Theme 3: Borders, Boundaries & Contested Space

**Elevator pitch:** Every line on a world map was drawn by someone. Some are settled, some are not. Here is what the authoritative sources say.

**Collection name:** "Lines on the Map (2024 Snapshot)"

**Why this theme:** This is the geopolitics theme, done carefully. The value proposition is unique: GeoLens can hold contested information neutrally — multiple parallel "official" views of the same territory, side by side — and let the user choose the lens. No other catalog tool on the market demonstrates this. The "One Territory, Multiple Official Maps" map (Map 3.2) is, alone, worth the implementation cost because it is the single most memorable screen in any enterprise demo.

**Record types exercised:** vector + table records

**Signature 60-second story:** A world map with every disputed area highlighted, labeled from the Natural Earth disputed-boundaries dataset, no editorial framing.

---

## Datasets per Theme

### Theme 1: Planet Earth — Physical Systems

| Dataset | Source | Format | Approx Size | Record Type | License | Why |
|---|---|---|---|---|---|---|
| Natural Earth 1:10m coastline, land, ocean, rivers, lakes, glaciated areas, reefs, playas, minor islands | naciscdn.org | Shapefile | ~50 MB | vector | Public Domain (VERIFIED) | Foundation reference; already in baseline — reuse, no re-download |
| Natural Earth 1:50m shaded relief raster | naciscdn.org/naturalearth/50m/raster | GeoTIFF → COG | ~100 MB | raster_dataset | Public Domain (VERIFIED) | Exercises raster pipeline; convert once at seeder-build time with `gdal_translate -of COG` |
| GEBCO 2025 Grid — coarse subset (15 arc-min) | gebco.net | GeoTIFF → COG | ~200 MB post-downsample | raster_dataset | Public Domain (VERIFIED) | Ocean depth; the bathymetry that makes Map 1.1 look like a NASA still |
| Natural Earth 1:10m shaded relief tiles (hypsometric + bathymetry + shaded relief bands, 2-3 sources) | naciscdn.org/naturalearth/10m/raster | GeoTIFF → VRT mosaic | ~300 MB total | vrt_dataset | Public Domain (VERIFIED) | The VRT story: mosaic of three raster sources into one queryable dataset |
| HydroSHEDS rivers (global, v1.1) | hydrosheds.org | Shapefile | ~40 MB | vector | ODbL + HydroSHEDS license (ASSUMED — verify before shipping) | Finer river detail than Natural Earth; optional, drop if license verification fails |

**Skips, with rationale:**
- **SRTM full-resolution** — too large (multiple GB) for the bundle budget; GEBCO at 15 arc-min is sufficient for demo purposes.
- **Copernicus DEM** — requires login; violates the "no outbound internet / no credentials at seed time" constraint.
- **OSM global extract** — ~80 GB PBF; incompatible with bundle budget and too broad for any specific narrative.

### Theme 2: Global Development & People

| Dataset | Source | Format | Approx Size | Record Type | License | Why |
|---|---|---|---|---|---|---|
| World Bank WDI — population, GDP per capita PPP, life expectancy, internet penetration, urban share, under-5 mortality (one CSV per indicator) | databank.worldbank.org | CSV | ~2-5 MB each | table | CC-BY 4.0 (ASSUMED — World Bank Open Data general terms; verify per-indicator) | Six classic development indicators; rich, trusted, recognized by any enterprise prospect |
| Our World in Data — Human Development Index, GINI, V-Dem democracy index, educational attainment | ourworldindata.org | CSV | ~1-3 MB each | table | CC-BY 4.0 (VERIFIED — OWID download buttons include CC-BY statement) | Richer narrative frame; single country-year value per row, easy to join |
| SEDAC Gridded Population of the World v4 (GPWv4) — coarse resolution | sedac.ciesin.columbia.edu | GeoTIFF → COG | ~100 MB at 1-degree | raster_dataset | CC-BY 4.0 (VERIFIED) | "Where people actually live" as a raster; counterpoint to country-level choropleths |

**Skips, with rationale:**
- **GADM Level 0** — license is not a true open license and restricts some commercial redistribution. Use Natural Earth `ne_10m_admin_0_countries` from the baseline instead.
- **OSM global extracts** — not needed; Natural Earth country polygons are adequate for any join.
- **Our World in Data grapher JSON snapshots** — use CSV exports for determinism; grapher URLs change.

### Theme 3: Borders, Boundaries & Contested Space

| Dataset | Source | Format | Approx Size | Record Type | License | Why |
|---|---|---|---|---|---|---|
| Natural Earth `ne_10m_admin_0_disputed_areas` | naciscdn.org | Shapefile | <1 MB | vector | Public Domain (VERIFIED) | Every disputed area NE tracks; the core polygon layer for Map 3.1 |
| Natural Earth `ne_10m_admin_0_boundary_lines_disputed_areas` | naciscdn.org | Shapefile | <1 MB | vector | Public Domain (VERIFIED) | Disputed boundary lines (distinct from area polygons); adds line geometry for styling |
| Natural Earth `ne_10m_admin_0_breakaway_disputed_areas` | naciscdn.org | Shapefile | <1 MB | vector | Public Domain (VERIFIED) | De-facto control regions (Transnistria, Somaliland, etc.); adds nuance to Map 3.1 |
| Natural Earth country-specific boundary overrides (`ne_10m_admin_0_countries_arg`, `_chn`, `_ind`, `_isr`, `_pak`, `_rus`, `_tur`, `_ukr`, `_usa`) | naciscdn.org | Shapefile | ~10 MB total | vector | Public Domain (VERIFIED) | Nine parallel "official" views of contested regions — the raw material for Map 3.2. Already in the `seed-natural-earth.py` manifest; needs only to be enabled. |
| UCDP Georeferenced Event Dataset (GED) v25.1 — 2015-2024 subset | ucdp.uu.se/downloads | CSV with lat/lon | ~30 MB | vector (point) | CC-BY 4.0 (VERIFIED) | Fatal events of organized violence; the ACLED-free alternative. Cite version and snapshot date in every layer description. |
| UNHCR Refugee Population Statistics — end-year 2023 | unhcr.org/refugee-statistics/download | CSV | ~10 MB | vector after pre-join | CC-BY 4.0 (VERIFIED) | Country-to-country refugee flows; pre-joined to ADM0 polygons by seeder helper (A7/Option C) before ingest; powers Map 3.4 |
| UN/NATO/EU/BRICS treaty membership (hand-curated from CIA World Factbook) | CIA World Factbook | CSV | <100 KB | table | Public Domain (US Gov) | Who belongs to which club; one of the most-requested demo questions from enterprise prospects |
| Natural Earth `ne_10m_admin_0_antarctic_claims` | naciscdn.org | Shapefile | <1 MB | vector | Public Domain (VERIFIED) | Seven Antarctic claim sectors; visually clean, obviously neutral, strong "did you know" moment |

**Skips, with rationale:**
- **ACLED** — see Geopolitics Safety Notes below. Hard no.
- **Marine Regions EEZ (Flanders Marine Institute)** — CC-BY 4.0 but updates are opinionated on disputed maritime boundaries (South China Sea), adding a second editorial sensitivity surface. Defer to a future phase after the baseline ships.
- **Freedom House** — license terms unclear; governance ratings are politically charged in some regions and cannot be attributed to a neutral source policy with the confidence that NE and UCDP can.
- **CEPII BACI trade flows** — too tabular, weak on visual story in 60 seconds; no spatial geometry.

---

## Signature Maps

Nine maps across the three themes, chosen to tell a 60-second story on first load and reward exploration afterward. A7 is resolved (see 260408-mgg): Maps 2.2, 2.3, and 3.4 ship via seeder pre-join instead of a runtime table→polygon join. Map 1.3 remains "add if time permits."

| # | Theme | Name | 60-sec story | A7-dependent? | Ship list |
|---|---|---|---|---|---|
| 1.1 | Planet Earth | Earth as Seen from Space | The planet in one screen: bathymetry, topography, ice, rivers | No | **ship** |
| 1.2 | Planet Earth | Global Bathymetry | The ocean floor revealed via GEBCO COG | No | **ship** |
| 2.1 | Development & People | Population at a Glance | Dot-sized populated places, built from an AI prompt | No | **ship** |
| 3.1 | Borders | The World's Disputed Places | Every disputed area NE tracks, in one map | No | **ship** |
| 3.2 | Borders | One Territory, Multiple Official Maps | Kashmir, three official views, toggled by layer | No | **ship** (the conversation starter) |
| 3.3 | Borders | Conflict Events 2024 (UCDP GED) | A year of fatal events, point density on a dark basemap | No | **ship** |
| 1.3 | Planet Earth | Where the Ice Is | Every glacier and ice shelf on one map | No | add if time permits |
| 2.2 | Development & People | GDP per Capita PPP 2023 | Country choropleth from seeder-prejoined GDP+ADM0 GeoJSON | Resolved via seeder pre-join (A7/Option C) | ship |
| 2.3 | Development & People | Life Expectancy & Income (outliers) | Rich-country outliers labeled on a two-variable choropleth | Resolved via seeder pre-join (A7/Option C) | ship (if time) |
| 3.4 | Borders | Refugees by Country of Origin 2023 | Country choropleth from seeder-prejoined UNHCR+ADM0 GeoJSON | Resolved via seeder pre-join (A7/Option C) | ship |

### Map Detail: Ship List

#### Map 1.1 — Earth as Seen from Space

- **Story:** One screen. You see the planet. Mountains, oceans, ice, rivers. Nothing else.
- **Basemap:** None — solid dark ocean background
- **Layers (top to bottom):** Rivers (thin white, width by scalerank) → Lakes (light blue fill) → Glaciated areas (white, 60% opacity) → VRT mosaic (bathymetry + hypsometric + shaded relief) → Ocean fill
- **View:** center `[0, 15]`, zoom 1.8, bearing 0, pitch 0
- **Widgets:** measurement, scale bar

#### Map 1.2 — Global Bathymetry

- **Story:** The ocean floor — trenches, ridges, continental shelves, revealed.
- **Basemap:** Light (positron)
- **Layers (top to bottom):** Coastline → Country borders (thin, dark) → GEBCO bathymetry COG (viridis-reversed colormap via Titiler `?colormap_name=viridis_r`)
- **View:** world extent
- **Widgets:** measurement, elevation popup

#### Map 2.1 — Population at a Glance

- **Story:** Where the people are. Big dots where there are lots of them.
- **Basemap:** Light
- **Layers (top to bottom):** Country outlines (thin gray) → Populated places (proportional symbol by `POP_MAX`, 4–40 px radius, colored categorically by region)
- **View:** world extent, zoom 1.5
- **Widgets:** feature popup with population value
- **Build path:** This map should be built from the AI prompt "Show me where people live, sized by population" and exported as-is — demonstrates the AI map builder in the fixture.

#### Map 3.1 — The World's Disputed Places

- **Story:** Every place on Earth where the lines are still being argued over, labeled.
- **Basemap:** Light (positron)
- **Layers (top to bottom):** Country outlines (pale fill, thin border) → Antarctic claims (pale blue fill, labeled) → Breakaway disputed areas (yellow fill, 50% opacity) → Disputed areas (orange fill, 50% opacity) → Disputed boundary lines (orange dashed) → Label layer on disputed areas (`NOTE_BRK` or `NAME`)
- **View:** world extent
- **Widgets:** feature popup (dispute note), layer legend

#### Map 3.2 — One Territory, Multiple Official Maps

- **Story:** Zoom into Kashmir. Toggle layers. Watch the border change. Three countries, three official maps, one territory.
- **Basemap:** Light
- **Layers (top to bottom):** `ne_10m_admin_0_countries_pak` (Pakistan view, green outline, initially hidden) → `ne_10m_admin_0_countries_ind` (India view, saffron outline, initially hidden) → `ne_10m_admin_0_countries_chn` (China view, teal outline, visible by default)
- **View:** center `[76, 34]`, zoom 6
- **Widgets:** layer toggle panel (built-in layer list)
- **Why this map matters:** It is the single most memorable screen in the demo. A prospect who sees one territory shift across three official views will remember GeoLens. The layer toggle panel does all the work — no custom code required.

#### Map 3.3 — Conflict Events 2024 (UCDP GED)

- **Story:** A year of fatal events of organized violence, as recorded by UCDP, aggregated by location.
- **Basemap:** Dark
- **Layers (top to bottom):** Country outlines (white, thin) → UCDP GED points filtered to `year=2024` (small red circles, 0.4 opacity), clustered at low zoom, unclustered at zoom > 5
- **View:** world extent
- **Widgets:** popup showing event description, date, source; year filter slider
- **Attribution required:** Layer description must read: "Source: UCDP GED v25.1, released 2025. Uppsala Conflict Data Program's published codebook and terms: https://ucdp.uu.se/downloads. Contents shown per UCDP's editorial stance, not GeoLens."

---

## Geopolitics Safety Notes

Every geopolitics-adjacent dataset in Theme 3 must pass two tests before it ships:

1. **License test:** Is the data redistributable with attribution, compatible with commercial use, governmental customer use, and AI-training use? GeoLens is all three.
2. **Editorial test:** Does the source have a published, defensible policy for handling contested claims — so GeoLens can say "we show what the source says; disputes with the framing go to them"?

### The ACLED Decision

ACLED does not pass the license test. The ACLED EULA (verified at `acleddata.com/eula` and `acleddata.com/contentusage`) imposes three independent restrictions that conflict with GeoLens:

1. **Governmental and quasi-governmental use** requires a paid license. GeoLens's primary buyer segment is government agencies and departments.
2. **Commercial use** requires a paid license. GeoLens is a commercial product (open-core with paid enterprise tiers).
3. **Training AI systems** on ACLED data is explicitly prohibited. GeoLens has an AI chat feature backed by an LLM.

All three apply simultaneously. There is no "free for open-source" exception. Any use of ACLED in the demo would require a commercial license that covers governmental and AI training use — which is not the ACLED standard tier.

**Substitution: UCDP GED v25.1.** The Uppsala Conflict Data Program's Georeferenced Event Dataset covers the same subject matter — fatal events of organized violence — with fine-grained latitude/longitude and year. License is CC-BY 4.0 with no AI training restriction. The data is peer-reviewed by the Uppsala University Department of Peace and Conflict Research and includes a public codebook. UCDP GED is the correct choice for any open-core commercial platform targeting government buyers.

If a reviewer suggests adding ACLED "just for the demo" or "under a fair use interpretation," the answer is no. The rationale above is the standing rejection.

### Natural Earth Disputed-Borders Policy

Natural Earth has maintained a published disputed-boundaries policy since 2009 (`naturalearthdata.com/about/disputed-boundaries-policy`). The policy documents how NE resolves conflicting claims for every disputed feature. GeoLens renders what Natural Earth says — disputes with Natural Earth's framing are disputes with Natural Earth, not GeoLens. This is the editorial shield that makes Theme 3 safe to show to any customer, regardless of region.

### Language Discipline for Layer Descriptions

Every layer in Theme 3 whose content touches territorial claims, conflict, or displacement must use this description pattern verbatim (fill in the blanks for each layer):

> "Source: {Source Name} v{version}, released {date}. {Source}'s published policy on contested regions: {URL}. Contents shown per {Source}'s editorial stance, not GeoLens."

No layer description in Theme 3 may use the words "aggression," "occupation," "invasion," or "terrorism" except as verbatim quotes from the source document itself.

### Hard No-Go List

- **ACLED** — three-EULA-conflict (see above)
- **Freedom House** — license terms unclear; governance ratings are politically charged in some regions
- **Any single-country partisan source** — must be neutral, multi-national, or academic
- **Marine Regions EEZ** — deferred; maritime dispute sensitivity adds a second surface not worth tackling in the first demo version

---

## Data Sources Catalog

Every source referenced in the dataset tables above, consolidated for license audit.

| Source | Provider | License | URL | Used in Themes | Verification |
|---|---|---|---|---|---|
| Natural Earth 1:10m and 1:50m datasets | Natural Earth (NACIS CDN) | Public Domain | naturalearthdata.com/about | 1, 2, 3 | VERIFIED |
| Natural Earth disputed-boundaries policy | Natural Earth | Public Domain | naturalearthdata.com/about/disputed-boundaries-policy | 3 | VERIFIED |
| GEBCO 2025 Gridded Bathymetry | GEBCO (NERC/BODC) | Public Domain | gebco.net/data-products/gridded-bathymetry-data | 1 | VERIFIED |
| SEDAC GPWv4 population grid | CIESIN/Columbia University | CC-BY 4.0 | sedac.ciesin.columbia.edu | 2 | VERIFIED |
| World Bank WDI indicators | World Bank Open Data | CC-BY 4.0 (general) | databank.worldbank.org | 2 | ASSUMED — verify per-indicator |
| Our World in Data CSVs | Our World in Data | CC-BY 4.0 | ourworldindata.org | 2 | VERIFIED (per-chart download button) |
| UCDP GED v25.1 | Uppsala University (UCDP) | CC-BY 4.0 | ucdp.uu.se/downloads | 3 | VERIFIED |
| UNHCR Refugee Population Statistics | UNHCR | CC-BY 4.0 | unhcr.org/refugee-statistics/download | 3 | VERIFIED |
| CIA World Factbook (treaty memberships) | US Gov / CIA | Public Domain | cia.gov/the-world-factbook | 3 | ASSUMED — US federal government works are PD by statute |
| HydroSHEDS rivers v1.1 | WWF / USGS | ODbL + HydroSHEDS terms | hydrosheds.org | 1 (optional) | ASSUMED — verify commercial compatibility before shipping |

Full source analysis, API surface verification, and per-indicator license notes are in [260408-lnq-RESEARCH.md](./260408-lnq-RESEARCH.md) §Sources.

---

## Automation Recommendation

**Recommendation:** Automate dataset ingest, raster/VRT processing, and collection assignment. Hand-curate signature maps as JSON fixtures committed to the repo; the seeder hydrates them deterministically at seed time.

### What to Automate

- **Vector ingest** — proven pattern from `seed-natural-earth.py`. Extend to handle the new shapefiles and CSVs without rewriting the upload/preview/commit pipeline.
- **Raster COG ingest** — same three-step ingest pipeline (magic bytes auto-detect raster). Run `gdal_translate -of COG -co COMPRESS=DEFLATE -co PREDICTOR=3` at seeder container build time, not at seed time.
- **VRT mosaic creation** — one API call: `POST /api/ingest/vrt/create` with a list of source dataset IDs after their individual ingest completes.
- **Table CSV ingest** — same pipeline as vector. CSVs without geometry auto-route to `record_type=table`. Pre-normalize column names at build time (World Bank indicator codes → human-readable titles).
- **Collection creation and dataset assignment** — already done in `seed-natural-earth.py` (`create_or_get_collection`, 409-idempotent). Lift the pattern, extend for three themed collections.

All of these primitives exist in `seed-natural-earth.py` today. The new `seed-thematic-demo.py` extends them; it does not replace them.

### What Not to Automate: Maps

Maps have approximately 30 style knobs per layer (paint, layout, filter, label_config, style_config, opacity, sort_order). Hand-coding these in Python is verbose, fragile against schema changes, and produces maps that diverge from what a human would build in the UI.

**The fixture approach:**
1. Human builds a signature map in the GeoLens UI.
2. Export: `GET /api/maps/{id}` → strip id/timestamps/created_by → save to `scripts/fixtures/demo-maps/theme-1-earth-from-space.json`.
3. Commit JSON to the repo.
4. At seed time, the seeder reads the fixture, rewrites each `layer.dataset_id` by looking up the source filename stem in the `fetch_existing_datasets` name-to-id map (pattern already in `seed-natural-earth.py:257-295`), and `PUT /api/maps/{id}`.

The key invariant: dataset UUIDs change on every fresh seed, but source filenames are stable. The fixture uses a `_stem` field (e.g., `"gebco_2025_15arcmin"`) instead of a UUID; the seeder resolves stems to IDs at runtime.

### Tradeoffs Considered

| Approach | Verdict | Reason |
|---|---|---|
| Fully automated (generate maps from Python code) | Rejected | Verbose, fragile against `MapLayerInput` schema changes, diverges from human-built maps; any schema update silently breaks the demo |
| Fully manual (operator builds maps by hand after seed) | Rejected | Not reproducible; defeats the demo's determinism goal; slow for re-seeding |
| Fixture-based (recommended) | Accepted | Human-validated once, seeder applies deterministically; resolves UUID instability with name lookup; easy to update (rebuild map in UI, re-export) |

### Cache-on-Build Posture

All downloads happen during seeder container build (`Dockerfile RUN` step), not at demo run time. The container ships with datasets in `/seed-data/`. This satisfies the CONTEXT.md constraint: no outbound internet at demo run time. Total bundled size: approximately 1.2–1.5 GB. Total PostGIS footprint after ingest: approximately 3 GB. GEBCO at 15 arc-min (~200 MB COG) is the single largest contributor — downsample to 30 arc-min if the bundle budget needs to contract.

**Share tokens:** Not automated. Operators mint their own via the admin UI. Default-off keeps the demo secure; pre-minted tokens have no cleanup mechanism in `reset-demo.sh`.

---

## Open Questions & Dependencies

1. ~~**A7 — Table→polygon join in the map builder. CRITICAL.**~~ **RESOLVED 2026-04-08 (quick task 260408-mgg).** Verdict: UNSUPPORTED. The tile pipeline requires a `geom_4326` column (`backend/app/tiles/service.py:75-76`) that does not exist on CSV tables; `MapLayer` has no join primitive (`backend/app/maps/models.py:82-119`); adding a table record to a map produces a silent blank layer. **Selected fallback: Option C** (pre-materialized join at seeder build time). The seeder runs a small `csv_to_choropleth.py` helper that joins each indicator CSV to `ne_10m_admin_0_countries` on ISO3 and emits a choropleth-ready GeoJSON. Zero platform code changes. Maps 2.2, 2.3, and 3.4 all ship at full scope. Full findings: `../260408-mgg-a7-spike-verify-map-builder-can-join-rec/260408-mgg-FINDINGS.md`.

2. **VRT mosaic count.** One VRT mosaic (Natural Earth 10m raster bands) is sufficient to demonstrate the feature. The implementation phase should ship exactly one and not add more unless there is a specific gap. Resolution: confirmed — ship one.

3. **Share link posture.** Sample maps should not ship with pre-minted share tokens. Default-off. Operators opt in via the admin UI. Resolution: confirmed — no automation of share token minting.

4. **`reset-demo.sh` scope.** The new thematic seeder must be idempotent against a partial reset. Review `scripts/reset-demo.sh` as the first act of Plan 1 of the implementation phase — confirm whether it drops only demo-owned datasets/collections/maps, or everything. The seeder's collection and dataset names must be stable and prefixed (e.g., `[demo] Planet Earth`) so the reset script can target them by name.

5. **i18n of layer titles and descriptions.** Ship English-only for the baseline demo. Translation is deferred — rely on the platform's runtime fallback for non-English users.

6. **AI chat seeded prompts.** Seeding suggested prompts on the AI chat panel ("Show me where people live", "What countries have disputed borders?") would increase demo punch significantly. This is out of scope for the first implementation phase — schedule as a stretch goal or a follow-on quick task.

7. **STAC 1.1 metadata for raster datasets.** The platform's STAC export feature (shipped in v10.0) is worth demonstrating. Include rich STAC-compatible metadata in the ingest commit body for the GEBCO and GPWv4 raster datasets so the STAC export endpoint returns meaningful results for Theme 1.

8. **Refresh cadence ownership.** Demo data with a 2024 timestamp shown in 2028 is a credibility problem. Define in the implementation phase: (a) target annual refresh, (b) gate on a "snapshot date > 365 days old" check in CI, (c) assign ownership to whoever owns the demo environment.

---

## Suggested Next Steps

**Recommendation:** Schedule this as a medium-complexity implementation phase, roughly the scope of v12.3 Map Builder Excellence (approximately 5 plans, 3-4 waves). A7 is resolved — the implementation phase can proceed without any uncertainty on Theme 2 map scope.

### Rough Phase Shape

| Plan | Name | Scope | Prerequisite |
|---|---|---|---|
| 1 | Foundation + `csv_to_choropleth.py` helper | Scaffold `seed-thematic-demo.py` extending existing primitives; write the `csv_to_choropleth.py` helper (the A7/Option C seam); review `reset-demo.sh` scope for prefix-safe teardown | None |
| 2 | Theme 1 — Planet Earth | Ingest NE shaded relief COG, GEBCO bathymetry COG, build VRT mosaic; collection assignment; build + export fixtures for Maps 1.1 and 1.2 | Plan 1 |
| 3 | Theme 2 — Development & People | Ingest World Bank + OWID + SEDAC datasets; pre-join GDP/life-expectancy indicators via the helper → choropleth GeoJSONs; build + export fixtures for Maps 2.1, 2.2, 2.3 | Plan 1 |
| 4 | Theme 3 — Borders & Contested Space | Enable nine NE country-specific shapefiles; ingest UCDP GED + UNHCR (pre-joined via helper for Map 3.4) + treaty CSV; build + export fixtures for Maps 3.1, 3.2, 3.3, 3.4 | Plan 1 |
| 5 | Wiring + Verification | Dockerfile build-time caching; `seed-demo.sh` integration; `reset-demo.sh` scope updates; STAC metadata on raster ingest bodies; README update; human-verified walkthrough of all three collections | Plans 2, 3, 4 |

**Sequencing note:** Plan 1 is a gate — the `csv_to_choropleth.py` helper it produces is consumed by Plans 3 and 4. Plans 2, 3, and 4 are independent of each other once Plan 1 is complete and can run in parallel waves if the team has capacity.

**Deciding at the bottom of this document:**

- **Yes, schedule it** → run `/gsd-discuss-phase` with this proposal as the starting context. The five-plan outline above is the starting skeleton. A7 is resolved — no gates.
- **No, defer it** → add a note to STATE.md's Pending Todos: "Demo themed collections (3 themes, 9 maps) — proposal at 260408-lnq-PROPOSAL.md; A7 resolved; ready to plan when capacity permits."

---

*Proposal compiled 2026-04-08 from RESEARCH.md and CONTEXT.md. Source material: `260408-lnq-RESEARCH.md`.*
