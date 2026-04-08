---
phase: 218-demo-themed-collections
plan: "01"
subsystem: demo-seeder
tags: [demo, seeder, python, csv, geojson, fixtures, parallel-execution]
dependency_graph:
  requires: []
  provides:
    - scripts/demo/lib/csv_to_choropleth.py — _value stable contract for choropleth pre-join
    - scripts/demo/lib/fixture_schema.py — strip_for_fixture / resolve_fixture round-trip
    - scripts/demo/lib/apply_fixture.py — async fixture apply helper
    - scripts/demo/lib/subset_ucdp.py — UCDP GED CSV year-range subsetter
    - scripts/demo/themes/theme{1,2,3}.py — per-plan DATASETS stubs (Plans 02/03/04 own one each)
    - scripts/demo/seed-thematic-demo.py — frozen orchestrator with 8 ingest helpers
  affects:
    - Plans 218-02, 218-03, 218-04 — each writes exactly one theme module (zero file overlap)
    - Plan 218-05 — Dockerfile build uses subset_ucdp.py; orchestrator frozen here
tech_stack:
  added: []
  patterns:
    - importlib.util.spec_from_file_location to import hyphen-named seed-natural-earth.py without modifying it
    - sys.path.insert(0, scripts/demo/) + from themes import theme1 for per-theme module dispatch
    - Dual-context import fallback in apply_fixture.py (project root vs orchestrator sys.path)
    - ogr2ogr shell-out for shapefile-to-GeoJSON conversion (no geopandas)
key_files:
  created:
    - scripts/demo/__init__.py
    - scripts/demo/lib/__init__.py
    - scripts/demo/lib/csv_to_choropleth.py
    - scripts/demo/lib/fixture_schema.py
    - scripts/demo/lib/apply_fixture.py
    - scripts/demo/lib/subset_ucdp.py
    - scripts/demo/lib/test_csv_to_choropleth.py
    - scripts/demo/themes/__init__.py
    - scripts/demo/themes/theme1.py
    - scripts/demo/themes/theme2.py
    - scripts/demo/themes/theme3.py
    - scripts/demo/seed-thematic-demo.py
    - scripts/demo/fixtures/maps/.gitkeep
  modified: []
decisions:
  - "apply_fixture.py uses dual-context import fallback: tries `from scripts.demo.lib.fixture_schema` first (project root context), falls back to `from fixture_schema` (orchestrator sys.path context). This avoids modifying sys.path in the test entry point."
  - "ingest_vector_ne_cdn (raises NotImplementedError) kept alongside ingest_vector_ne_cdn_with_cache to make the API asymmetry explicit — downstream plans always use the _with_cache variant."
  - "STRIP_TOP_LEVEL and STRIP_LAYER are frozensets (not sets) to signal immutability."
metrics:
  duration_minutes: 15
  completed_date: "2026-04-08"
  tasks_completed: 2
  tasks_total: 2
  files_created: 13
  files_modified: 0
---

# Phase 218 Plan 01: Foundation — lib helpers, fixture schema, frozen orchestrator, per-theme stubs Summary

One-liner: Stdlib-only csv_to_choropleth pre-join helper with stable `_value` contract, fixture round-trip schema, async apply_fixture, and a frozen orchestrator with three empty per-theme DATASETS modules that let Plans 02/03/04 run in parallel with zero file overlap.

## What Was Built

### lib helpers (`scripts/demo/lib/`)

**csv_to_choropleth.py** — Pure stdlib + ogr2ogr CLI join. The `_value` field is a stable contract: every downstream fixture that references a choropleth GeoJSON can rely on `properties._value` being present and numeric. The module docstring contains the secondary-bug warning: do NOT substitute table-record ingestion — `record_type=table` datasets produce silent blank layers (tile endpoint 503, per 260408-mgg-FINDINGS.md).

**fixture_schema.py** — Round-trip transform between live map API responses and portable fixture JSON:
- `strip_for_fixture(map_response, stem_lookup, *, theme, snapshot_date)` — strips server-generated fields, replaces `dataset_id` with `_stem` + `_ext`, prepends `_meta` block
- `resolve_fixture(fixture, existing)` — reverses the transform, swaps `_stem + _ext` → live UUID, strips `_meta`
- `STRIP_TOP_LEVEL` and `STRIP_LAYER` are frozensets matching the schema verified in 218-RESEARCH.md Q2

**apply_fixture.py** — Async helper that reads a fixture from disk, calls `resolve_fixture`, POSTs `/api/maps/` to create the map, then PUTs `/api/maps/{id}` with the full resolved body. Uses `X-Api-Key` header (case-sensitive). Raises `RuntimeError` with status code + first 500 chars of body on HTTP error.

**subset_ucdp.py** — CLI: `python3 subset_ucdp.py <input_csv> <output_csv> <year_min> <year_max>`. Reads a UCDP GED CSV, writes only rows where `year` is in `[year_min, year_max]` inclusive.

**test_csv_to_choropleth.py** — 5 pytest unit tests using inline fixtures (no external test data):
1. Basic join: 3 matched + 1 unmatched ISO3 + 1 null value → 3 output features, unmatched logged
2. Duplicate ISO3: last value wins, WARNING emitted
3. World Bank 4-line metadata header: skipped correctly, real data rows parsed
4. Year filter: only 2021 rows returned when `year_filter="2021"`
5. Zero matches: `join_and_write` returns exit code 1

### Per-theme module stubs (`scripts/demo/themes/`)

Each file is tiny and owned exclusively by one downstream plan. The constants are locked here — Plans 02/03/04 ONLY populate the `DATASETS` list:

| File | THEME_NAME | THEME_IDX | Owner |
|------|-----------|-----------|-------|
| theme1.py | "Planet Earth (2025 Snapshot)" | 0 | Plan 218-02 |
| theme2.py | "How the World Lives (2024)" | 1 | Plan 218-03 |
| theme3.py | "Lines on the Map (2024 Snapshot)" | 2 | Plan 218-04 |

### Frozen orchestrator (`scripts/demo/seed-thematic-demo.py`)

The orchestrator owns ALL infrastructure. The 8 frozen helpers (Plans 02/03/04 must NOT modify this file):

| Helper | Purpose |
|--------|---------|
| `ingest_vector_ne_cdn_with_cache` | Download NE shapefile from NACIS CDN via download_or_load_cache |
| `ingest_vector_local_with_summary` | 3-step ingest of local GeoJSON/CSV + PATCH description with summary |
| `ingest_raster_local` | 3-step ingest of local COG with 600s poll timeout |
| `create_vrt_mosaic` | POST /api/ingest/vrt/create + poll |
| `ingest_theme` | Dispatch loop over a theme module's DATASETS list |
| `assign_collection` | create_or_get_collection + bulk-assign succeeded/skipped IDs |
| `apply_theme_fixtures` | Loop fixtures/maps/*.json filtered by _meta.theme |
| `main_async` | Top-level async: fetch existing, ingest themes, VRT (Theme 1 only), assign collections, apply fixtures |

**Import wiring:** `importlib.util.spec_from_file_location("seed_natural_earth", _ne_path)` loads `seed-natural-earth.py` by file path (bypassing the hyphen). The primitives are bound as module-level names so the orchestrator reads identically to a normal import.

**Per-theme dispatch:** `sys.path.insert(0, str(Path(__file__).parent))` then `from themes import theme1, theme2, theme3`. Plans 02/03/04 edit the theme file directly (Python list assignment in the file body) — they do NOT import from the orchestrator.

## Downstream Plan Contract

Plans 02/03/04 each own exactly one file and must NOT touch anything else in `scripts/demo/`:

```
Plan 218-02 owns: scripts/demo/themes/theme1.py + their own fixture JSON files
Plan 218-03 owns: scripts/demo/themes/theme2.py + their own fixture JSON files
Plan 218-04 owns: scripts/demo/themes/theme3.py + their own fixture JSON files
```

To add a dataset, a downstream plan appends an entry to `DATASETS` in its theme module:
```python
DATASETS: list[dict[str, Any]] = [
    {
        "stem": "ne_10m_land",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "physical",
        "local_path": None,
        "summary": "Natural Earth land polygons...",
        "snapshot_date": "2024-01-01",
        "license": "Public Domain",
    },
]
```

The ingest helpers available from the frozen orchestrator:
- `ingest_vector_ne_cdn_with_cache` — for `type=vector, source=ne_cdn` entries
- `ingest_vector_local_with_summary` — for `type=vector, source=local` entries (pre-joined GeoJSON)
- `ingest_raster_local` — for `type=raster, source=local` entries (COG .tif)

## Stable `_value` Contract

Every choropleth GeoJSON produced by `csv_to_choropleth.py` will have:
```json
{
  "properties": {
    "ISO_A3": "USA",
    "_value": 67523.4,
    "_value_col": "gdp_per_capita_ppp_2023"
  }
}
```

Fixture JSON layer paint blocks for choropleth layers should use `["get", "_value"]` as the data expression. This is documented in the csv_to_choropleth module docstring.

## Fixture JSON Schema

Fixture files live in `scripts/demo/fixtures/maps/`. Shape produced by `strip_for_fixture`:
```json
{
  "_meta": {
    "name": "GDP per Capita (PPP, 2023)",
    "description": "...",
    "theme": "How the World Lives (2024)",
    "snapshot_date": "2023-12-31",
    "exported_at": "2026-04-08T..."
  },
  "name": "GDP per Capita (PPP, 2023)",
  "visibility": "public",
  "layers": [
    {
      "_stem": "gdp_per_capita_ppp_2023",
      "_ext": ".geojson",
      "sort_order": 0,
      "visible": true,
      "opacity": 1.0,
      "paint": {...},
      "layout": {},
      "layer_type": "vector_geolens",
      "show_in_legend": true
    }
  ]
}
```

The `apply_fixture` function routes `_stem + _ext` (e.g. `gdp_per_capita_ppp_2023.geojson`) through `fetch_existing_datasets`'s `{source_filename: dataset_id}` dict to resolve UUIDs at apply time.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Dual-context import in apply_fixture.py**
- **Found during:** Task 2 (dry-run verification)
- **Issue:** `apply_fixture.py` imported `from scripts.demo.lib.fixture_schema` assuming project root on `sys.path`. When the orchestrator adds `scripts/demo/` to `sys.path` and imports `lib.apply_fixture`, Python resolved `scripts.demo.lib` as a new module path — failing with `ModuleNotFoundError: No module named 'scripts'`.
- **Fix:** Added try/except import fallback: try `from scripts.demo.lib.fixture_schema` first; on `ModuleNotFoundError` fall back to `from fixture_schema` (the lib/ directory is then on sys.path).
- **Files modified:** `scripts/demo/lib/apply_fixture.py`
- **Commit:** 7abe043d

## Known Stubs

None — this plan produces only foundation infrastructure. No data is ingested; no maps are created. All theme DATASETS lists are intentionally empty (Plans 02/03/04 fill them).

## Self-Check: PASSED

Files created:
- FOUND: scripts/demo/__init__.py
- FOUND: scripts/demo/lib/__init__.py
- FOUND: scripts/demo/lib/csv_to_choropleth.py
- FOUND: scripts/demo/lib/fixture_schema.py
- FOUND: scripts/demo/lib/apply_fixture.py
- FOUND: scripts/demo/lib/subset_ucdp.py
- FOUND: scripts/demo/lib/test_csv_to_choropleth.py
- FOUND: scripts/demo/themes/__init__.py
- FOUND: scripts/demo/themes/theme1.py
- FOUND: scripts/demo/themes/theme2.py
- FOUND: scripts/demo/themes/theme3.py
- FOUND: scripts/demo/seed-thematic-demo.py
- FOUND: scripts/demo/fixtures/maps/.gitkeep

Commits verified:
- 7dfe53a5: feat(218-01): lib helpers — csv_to_choropleth, fixture_schema, apply_fixture, subset_ucdp + unit tests
- 7abe043d: feat(218-01): per-theme module stubs + frozen orchestrator with all ingest helpers
