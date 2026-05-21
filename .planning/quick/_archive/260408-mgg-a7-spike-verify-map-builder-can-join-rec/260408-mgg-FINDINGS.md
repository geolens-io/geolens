---
quick_id: 260408-mgg
type: spike
date: 2026-04-08
status: complete
verdict: unsupported
related: 260408-lnq
---

# A7 Spike Findings — Table→Polygon Join

## Verdict

The map builder cannot join a table record to a polygon and render a choropleth today: the tile-serving pipeline requires a `geom_4326` column (`tiles/service.py:75-76`) that does not exist on non-spatial CSV tables, the `MapLayer` schema has a single `dataset_id` with no join-key fields, and the frontend layer adapter system has no join primitive whatsoever. Every path to a choropleth requires that geometry already be present in the table before it is registered as a dataset.

---

## Q1: Join Primitive in Map Builder?

**Answer: None exists — not even a stub.**

The `MapLayer` ORM model (`backend/app/maps/models.py:82-119`) holds exactly one `dataset_id` (line 98) and no second dataset reference, no join-key columns, and no join configuration. The `MapLayerInput` Pydantic schema (`backend/app/maps/schemas.py:14-49`) mirrors this: `dataset_id`, `paint`, `layout`, `filter`, `style_config`, `label_config` — nothing about a second dataset or a column join.

On the frontend, `SyncLayerInput` in `frontend/src/components/builder/map-sync.ts:19-33` defines the normalized layer descriptor that feeds the MapLibre renderer; it contains `dataset_id`, `dataset_table_name`, `paint`, `layout`, `filter`, and `style_config`. No `join_dataset_id`, `join_key`, or equivalent field.

The `LayerAdapter` interface (`frontend/src/components/builder/layer-adapters/types.ts:26-32`) defines `addLayers`, `syncPaint`, `syncVisibility`, and `getLayerIds` — four methods, none of which accept a second data source.

Grep for "join", "choropleth", "foreign_key" in the builder component tree returns no map-builder results; the only `DatasetRelationship` model (`backend/app/datasets/models.py:417-450`) records metadata relationships between catalog records but has no effect on tile rendering. It is read-only provenance data.

---

## Q2: Table Record Render Path Today

**Answer: The layer is added to the DB without error, a token is issued, but the tile query crashes with a PostgreSQL column-not-found error — the user sees a blank layer silently.**

Step-by-step trace:

1. User clicks "Add" in `DatasetSearchPanel` (`frontend/src/components/builder/DatasetSearchPanel.tsx:119`). The panel does not filter by `record_type` — it passes all results including `table` records. The toggle group only offers "All / Vector / Raster" (lines 63-72), so `table` records are reachable via "All".

2. `handleAddDataset` in `use-builder-layers.ts:204-218` calls the `addLayer` mutation with just `{ dataset_id, sort_order }`.

3. The backend `add_layer` service (`backend/app/maps/service.py:592-641`) looks up `record_type` from the DB. For a `table` record, `record_type` is not `raster_dataset` or `vrt_dataset`, so `resolved_layer_type` becomes `"vector_geolens"` (line 588). `geometry_type` is `None` (no spatial column). `generate_default_style(None)` returns a fill-style (lines 43-82), so the layer is stored with fill paint. No error, no guard.

4. `MapLayerResponse.dataset_record_type` is populated as `"table"` and sent to the frontend.

5. `getLayerCapabilities` (`frontend/src/lib/layer-capabilities.ts:22-63`) receives `layer_type="vector_geolens"` and `dataset_geometry_type=null`. It falls to the else branch, resolves `mapLayerType="fill"` and `iconVariant="polygon"`. The layer appears in the sidebar with a polygon icon and style/filter/label tabs — all enabled.

6. `syncLayersToMap` (`frontend/src/components/builder/map-sync.ts:115-269`) calls `resolveAdapterType(null, style_config)` → `"fill"`, then issues a `map.addSource(sourceId, { type: 'vector', tiles: [...] })`. The tile URL resolves to `/tiles/data.<table_name>/{z}/{x}/{y}.pbf`.

7. The tile endpoint (`backend/app/tiles/router.py:538-759`) is hit. The in-memory cache miss triggers `get_tile` (`backend/app/tiles/service.py:83-114`), which builds and executes:
   ```sql
   WHERE t.geom_4326 && bounds.geom_4326
     AND ST_Intersects(t.geom_4326, bounds.geom_4326)
   ```
   The table has no `geom_4326` column. PostgreSQL raises `column "geom_4326" does not exist`. The exception handler at `tiles/router.py:713-725` catches it and returns HTTP 503 "Tile service unavailable".

8. MapLibre silently swallows the 503 for each tile request. The user sees a blank layer with a polygon-fill icon and no error message.

No existing styling support (data-driven color, classify) helps here because those features operate on MVT attribute data that never arrives.

> **Secondary finding (out of scope for A7 but worth logging):** The blank-layer-no-error behavior when adding a `table` record to a map is a UX bug independent of the join question. Either `DatasetSearchPanel` should filter out `record_type=table` when adding to a map, or `add_layer` should reject table records with a 422. Candidate for a future quick task.

---

## Q3: Join Alternatives

### (a) Layer-level join at render

**Feasibility: None — not stubbed.**

There is no second `dataset_id` on `MapLayer`, no join-key fields, no tile-time SQL join in `_build_tile_query` (`backend/app/tiles/service.py:37-80`), and no adapter hook for a join. Implementing this would require schema migrations, a new tile query path, RBAC checks on both datasets, and new UI primitives in the builder. This is a non-trivial feature, not a configuration.

### (b) View-based join

**Feasibility: Practical, with caveats. This is the viable platform path.**

The `register_existing_table` endpoint (`backend/app/ingest/service.py:232-321`) accepts any name that exists in `information_schema.tables WHERE table_schema = 'data'` — which includes both BASE TABLEs and VIEWs (the existence check at line 256-258 does not filter by `table_type`). It will detect a `geom` column, call `add_4326_column`, grant reader access, extract metadata, and register the view as a `vector_dataset` record. The tile pipeline (`tiles/service.py:74`) queries `data.<table_name>` with no distinction between tables and views.

Concretely: a developer creates a materialized view in the `data` schema that joins the CSV table to the countries polygon table on ISO3 code, includes a `geom` column from the polygon, then calls the register endpoint. The view lands in the catalog as a normal `vector_dataset` (polygon), renders as a choropleth with `style_config` data-driven fill, and supports all builder features including AI styling.

Caveats:
- The `discover_unregistered_tables` query (`ingest/service.py:36-65`) filters `table_type = 'BASE TABLE'`, so the view will **not** surface in the admin "unregistered tables" panel — it must be registered manually via the API.
- `add_4326_column` issues `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` which fails on a VIEW (views cannot have columns added). The view must already expose a `geom_4326` column (i.e., the view definition must include `ST_Transform(geom, 4326) AS geom_4326`). If only `geom` is present, the registration will error. The workaround is to include both `geom` and `geom_4326` in the view SELECT explicitly, OR use a materialized view (which accepts `ALTER`).

### (c) Pre-materialized join at ingest

**Feasibility: Clean and zero-code-change. This is the cheapest path for the demo.**

The ingest pipeline's `_finalize_ingest` (`backend/app/ingest/tasks.py:52-215`) calls `ensure_geom_column`, `clip_to_mercator_bounds`, `add_4326_column`, and `extract_metadata` after the ogr2ogr step. The seam is **before** ingest: if the CSV is pre-joined offline into a GeoJSON (using Python/pandas/geopandas or GDAL's `-sql` flag joining two ogr2ogr sources), the result ingests as a normal `vector_dataset` with geometry. No code changes required. For the demo seeder, this means writing one Python helper that reads a CSV and the countries GeoJSON, merges on ISO3, and emits a choropleth-ready GeoJSON per indicator. This is pure data-pipeline work, and fits cleanly inside the thematic seeder scope already planned for the implementation phase.

---

## Q4: AI Map Builder Handling

**Answer: The AI has no special handling for table records.** It will describe the layer in the system prompt with `geometry: None` and attempt to use `set_data_driven_style`, which returns a technically valid action but against a layer whose tiles never render.

Detailed trace:

`build_chat_system_prompt` (`backend/app/ai/chat_service.py:236-353`) lists each layer's `geometry_type`. For a table record this is `None`, which renders as the string "None" in the prompt. The system prompt says:
```
- fill-color for Polygon/MultiPolygon
- line-color for LineString/MultiLineString
- circle-color for Point/MultiPoint
```
None matches, but the LLM will likely pick `circle-color` as the default fallback (since `_get_color_property(None)` at line 179-188 returns `"circle-color"`).

If the user asks "show me GDP per capita by country" with a table layer in context, the AI will call `set_data_driven_style` with `layer_id=<table_layer>`, `column="gdp_per_capita"`, `mode="graduated"`. `_build_graduated_style` calls `get_column_stats` against the DB table — which succeeds because the column exists. It builds a valid-looking `step` expression with `circle-color`. This is returned as an action and applied to the layer's paint. The map still renders no tiles (503 from tile endpoint). The AI explains it applied the style; the user sees nothing.

There is no guard in `_execute_chat_tool`, `_build_data_driven_style`, or `_validate_actions` that detects `geometry_type=None` or `record_type=table` and refuses the action.

---

## Q5: Recommended Demo Fallback

**Pre-join CSVs offline into GeoJSON choropleths during seeder build.** (Option C)

This is the cheapest option because it requires zero application code changes. The seeder script reads each indicator CSV (GDP per capita, life expectancy, population density), joins to the Natural Earth ADM0 GeoJSON on ISO3, and writes one GeoJSON per indicator with both the indicator value column and the country polygon geometry. These are ingested as normal `vector_dataset` records with `MULTIPOLYGON` geometry. The map builder renders them as fill layers, the AI can produce data-driven choropleth styles on demand, and the full legend/filter/label stack works. The demo story is preserved: "here is a GDP per capita choropleth" — it just happens to have been assembled offline rather than at query time.

The proportional-symbol fallback (using `populated_places`) loses the "by country" framing and is less compelling for a development indicators theme. The "store indicators as columns on countries dataset" approach creates a wide table that is awkward to manage as separate records and pollutes the countries dataset with unrelated fields.

Option B (materialized view) is a credible second choice if the implementation phase wants to demonstrate the "register existing PostGIS table" feature on a non-trivial example, but it is operationally messier (the view lives outside Alembic migrations) and offers no user-visible benefit over Option C for the demo.

---

## Impact on 260408-lnq Proposal

| Map | Original Scope | Verdict | New Scope |
|-----|----------------|---------|-----------|
| 2.2 — GDP per Capita choropleth | CSV table record styled as polygon fill via join | **REWORK** | Seeder pre-joins GDP CSV → ADM0 polygons → single GeoJSON indicator dataset. Ingest as normal `vector_dataset`. |
| 3.4 — Refugees by Country choropleth | UNHCR CSV table record styled as polygon fill via join | **REWORK** | Seeder pre-joins UNHCR CSV → ADM0 polygons → single GeoJSON indicator dataset. Ingest as normal `vector_dataset`. |
| Theme 2 signature 60-second story ("A world map of populated places, dot-sized by population, produced from an AI prompt") | Depended on `populated_places` + optional AI join | **UNCHANGED** | `populated_places` is already spatial — no join needed. Story ships as scoped. |

**Theme 2 still ships.** No maps drop. Two maps need seeder-side data pre-joining instead of layer-time joining. Net scope impact on the implementation phase: +0.5 to +1 day for a reusable `indicator-to-choropleth` helper in the seeder.

---

## Recommendation for Implementation Phase

The implementation phase as scoped in `260408-lnq-PROPOSAL.md` can proceed **with one seeder-shape adjustment** and no platform feature work. Instead of ingesting World Bank / OWID / UNHCR CSVs as `record_type=table` and relying on a join capability that does not exist, the thematic seeder should include a small helper (e.g., `scripts/demo/csv_to_choropleth.py`) that takes an indicator CSV, an ADM0 GeoJSON, and a join key (ISO3) and emits a choropleth-ready GeoJSON. Each indicator becomes its own `vector_dataset` with MULTIPOLYGON geometry and one numeric attribute column — exactly the input the existing data-driven style system expects.

The phase plan sequence from the proposal (A7 spike → static data bundle → thematic seeder → collection auto-assignment → map fixtures → docker-compose wiring) remains valid. The A7 spike step is now **complete** and should be removed from the sequence; the "static data bundle + download scripts" plan should absorb the `csv_to_choropleth.py` helper; everything downstream is unchanged.

**A true layer-time join capability** (Option A from Q3) is a distinct platform feature that would enable dynamic dashboards, joined attribute filters, and AI-suggested joins across datasets. It is worth considering as a future milestone in its own right, but it is **not a prerequisite for the demo** and should not be conflated with the demo implementation work.

---

## Follow-Up Items for the Proposal

1. **Update `260408-lnq-PROPOSAL.md`** — Map 2.2 and 3.4 descriptions should note "ingested as pre-joined GeoJSON indicator dataset" so the implementation phase inherits the correct spec.
2. **Open Question #1 (A7) in the proposal** — status changes from CRITICAL/UNVERIFIED to RESOLVED/UNSUPPORTED with fallback C selected.
3. **New candidate quick task** — the blank-layer-no-error UX bug from Q2 (adding a table record to a map silently fails). Not blocking A7 resolution; can be a separate quick task if the demo implementation phase hits it during development.
