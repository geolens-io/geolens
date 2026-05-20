# Phase 1057: Service URL Reliability - Context

**Gathered:** 2026-05-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Backend fixes to the Service URL ingest path so a user can import data from a WFS, ArcGIS, or OGC API Features endpoint with:

1. Successful commit for polygon-heavy WFS layers declaring abstract OGC geometry types (`MultiSurface`, `MultiCurve`, `CompoundSurface`, `CompoundCurve`, `GeometryCollection`) — **P0**.
2. End-to-end probe completion within ≤5s for fast services where an adapter succeeds quickly — **P1**.
3. Automatic CRS detection for OGC API Features sources declaring URI- or URN-form CRS references; no manual EPSG override needed for the four covered forms — **P2**.
4. VEC classification fallback in the Service URL layer-select list when probe response lacks `geometry_type`; RAS requires an explicit raster signal — **P2**.

**In scope:** WFS abstract-type column declaration, probe orchestrator + enrichment behavior, OGC API CRS URI/URN parsing, probe-response `kind` classification field, frontend wire-up for the above (Override-field auto-hide + `layer.kind` consumption).

**Not in scope (deferred to other phases or out of milestone):** retry path for previously-failed imports; new adapter types (WMS/WMTS/TMS); backend-side CRS reprojection beyond URI parsing; multi-layer GPKG handling (Phase 1058); basemap sublayer styling (Phase 1059); CHANGELOG / tag work (Phase 1060).

</domain>

<decisions>
## Implementation Decisions

### WFS-04 — Abstract OGC Geometry Type (P0)

- **D-01:** **Strategy (c) — generic `geometry(Geometry, 4326)` column on the service-ingest path.** Pass `-nlt CONVERT_TO_LINEAR` or drop subtype declaration entirely at `backend/app/processing/ingest/ogr.py:567-583` so PostGIS declares a constraint-free `geometry` column for WFS / ArcGIS / OGC API service ingests. Works for every abstract type AND mixed-type GeometryCollections without a per-type lookup table. **File ingest path is unaffected** — local files report concrete types accurately; the change is service-path only.
- **D-02:** **PostGIS column-level type discipline is replaced by `metadata.geometry_type`** (the existing `get_geometry_type` at `backend/app/processing/ingest/metadata.py:165`, which computes the concrete type via `GeometryType(geom) FROM data.<t> LIMIT 1`). `Dataset.geometry_type` continues to drive record_type classification, icons, and downstream UX (`backend/app/modules/catalog/datasets/domain/service_create.py:196`). No other call site depends on the PostGIS column-level constraint.
- **D-03:** Repro to lock the fix: `ahocevar.com/geoserver/wfs` → Countries of the World → Import succeeds end-to-end (vector tiles render, bounds-clip UPDATE completes without `asyncpg.exceptions.InvalidParameterValueError`). Add a regression test fixture with a synthetic WFS response declaring `MultiSurfacePropertyType`.

### PROBE-05 — Probe Latency ≤5s (P1)

- **D-04:** **Real root cause: per-layer ogrinfo enrichment, not orchestration.** The probe orchestrator at `backend/app/modules/catalog/sources/probe.py:95-161` already short-circuits per-probe — each `if result is not None: return` exits immediately. The measured ~60s is spent in `enrich_ogcapi_layers` (`adapters/ogcapi.py:162-239`) and its WFS sibling: a per-layer `ogrinfo -json -so OAPIF:{url} {layer_name}` subprocess gated by `asyncio.Semaphore(5)` with a 30s `wait_for`. Seventeen pygeoapi collections × ~3-4s each = ~60s wall clock. **REQUIREMENTS.md WFS-04 text says "short-circuit try_all_probes()" — that is misdiagnosed.** Planner must treat enrichment as the bottleneck.
- **D-05:** **Strategy (i) — drop ogrinfo enrichment from the probe phase; lazy-enrich the single layer the user selects.** The probe returns `geometry_type=null` and `feature_count=null` for all layers. When the user clicks a layer in the layer-select list, the preview path (which already calls `ogrinfo`) supplies the concrete geometry type for that one layer. This makes the ≤5s target trivially achievable and removes a per-collection cost that scales linearly with service size.
- **D-06:** Probe response must still carry enough signal for CLASS-07 to classify VEC vs RAS without `geometry_type` (see D-09).

### CRS-06 — URI/URN-form CRS Parsing (P2)

- **D-07:** **Cover four URI/URN forms; anything unrecognized falls through to today's behavior** (CRS=null + frontend Override field shown). Helper lives backend-side in the OGC API adapter at `adapters/ogcapi.py` and is exercised at the probe response layer-build step (`ogcapi.py:144-152`, currently `crs: None`):
  - `http(s)://www.opengis.net/def/crs/OGC/1.3/CRS84` → 4326
  - `http(s)://www.opengis.net/def/crs/EPSG/0/{N}` → {N}
  - `urn:ogc:def:crs:EPSG::{N}` → {N}
  - `urn:ogc:def:crs:OGC:1.3:CRS84` → 4326
- **D-08:** **Frontend Override-field auto-hide when probe carries non-null CRS.** Override stays visible (today's behavior) when CRS is null, so users with unrecognized URIs still have an escape hatch. No regression for users importing sources with bare `EPSG:N` or recognized URIs.

### CLASS-07 — VEC/RAS Classification Fallback (P2)

- **D-09:** **Backend-classified `kind: 'vector' | 'raster'` field added to the probe-response `Layer` / `ProbeLayer` schema** at `backend/app/modules/catalog/sources/schemas.py`. Classification logic — a layer is `raster` IFF any of:
  - `geometry_type` (lowercased) contains `'raster'`, OR
  - adapter is STAC (current `stac.py` adapter), OR
  - layer has `coverage_format`, `bands`, or `mediaType: image/*`.
  Everything else (including `geometry_type: null` after D-05) → `vector`. Durable across other callers (frontend can stop re-deriving; future ingest UI surfaces inherit the same rule).
- **D-10:** **Frontend `ServiceUrlForm.tsx:197` consumes `layer.kind` instead of re-deriving** the `isVector = geometry_type && !contains('raster')` rule. One-line read, mirror schema in `frontend/src/types/api.ts`.

### Scope Guardrails Locked

- **D-11:** No retry path or remediation for previously-failed imports (existing `MultiSurface` failures, OGC API failures from manual-override gaps). User re-runs the import after deploy. Migrating data is out of scope.
- **D-12:** No new adapter types (WMS/WMTS/TMS) — explicitly excluded by REQUIREMENTS.md "Out of Scope".
- **D-13:** No backend-side CRS reprojection beyond URI/URN parsing — REQUIREMENTS.md "Out of Scope".

### Plan Split Anticipated (Planner Refines)

- **D-14:** Anticipated three plans, ordered by priority:
  1. **Plan A — WFS-04** (backend ingest + regression test against a `MultiSurface` fixture)
  2. **Plan B — PROBE-05 + CLASS-07 paired** (both touch the probe-response shape; drop enrichment from probe phase, add `kind` field, wire frontend `ServiceUrlForm.tsx:197` to read `layer.kind`)
  3. **Plan C — CRS-06** (URI/URN→EPSG helper, OGC API adapter wire-up, frontend Override-field auto-hide)
  Inline review fixes folded into the originating plan per `feedback_review_findings_inline.md`. Researcher / planner free to merge, split, or reorder once they map the wave dependencies.

### Claude's Discretion

- Choice of test fixture format (synthetic WFS XML payload vs. recorded VCR-style HTTP cassette vs. live integration test against `ahocevar.com`) for the WFS-04 regression test — researcher decides.
- Exact location of the URI/URN→EPSG helper (inline in `ogcapi.py` vs. shared utility module under `backend/app/modules/catalog/sources/`) — planner decides based on whether the helper has future re-use (e.g., WFS `urn:ogc:def:crs:EPSG::N` declarations also benefit from URN parsing).
- Whether to add structured-log probe-duration telemetry now (for regression detection) or defer — planner decides; trivial if added, not required for acceptance.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Source of Truth

- `.planning/quick/260519-smoke-v1012/SMOKE-v1012-REPORT.md` — **REQUIRED.** All four requirements (WFS-04, PROBE-05, CRS-06, CLASS-07) trace to Findings 4-7 in this report. Includes exact repro URLs, backend log evidence for the ~60s probe (Finding 5), and the design-reference observation about Service URL preview parity.
- `.planning/REQUIREMENTS.md` — v1013 requirement IDs, P0/P1/P2 priorities, Out of Scope table.
- `.planning/ROADMAP.md` §"Phase 1057" — phase goal, depends-on, success criteria (4 items).
- `.planning/STATE.md` §"v1013 Source: Post-v1012 Live Smoke" — finding→REQ-ID→phase mapping table.

### Established Workflow Patterns (apply during execution + close)

- Memory file `feedback_review_findings_inline.md` — Inline code-review fixes go into the originating plan, no v1013.1. (Referenced explicitly by CTRL-01 in REQUIREMENTS.md.)

### Probe + Ingest Code (touched by this phase)

- `backend/app/modules/catalog/sources/probe.py:95-161` — `detect_service_type` orchestrator (already short-circuits per-probe; do not re-architect).
- `backend/app/modules/catalog/sources/adapters/ogcapi.py:120-159` — OGC API probe response build (CRS=null today; CRS-06 fix point).
- `backend/app/modules/catalog/sources/adapters/ogcapi.py:162-239` — `enrich_ogcapi_layers` (PROBE-05 bottleneck; D-05 drops this from probe phase).
- `backend/app/modules/catalog/sources/adapters/wfs.py:200-217` — WFS sibling enrichment (same shape; same D-05 treatment).
- `backend/app/modules/catalog/sources/schemas.py` — `ProbeResponse` / `Layer` schemas (CLASS-07 adds `kind` field).
- `backend/app/processing/ingest/ogr.py:520-611` (`run_ogr2ogr_service`) — WFS-04 fix surface; the `-nlt PROMOTE_TO_MULTI` flag at line 575 is the change point.
- `backend/app/processing/ingest/metadata.py:934-984` (`clip_to_mercator_bounds`) — WFS-04 failure site (UPDATE asyncpg type mismatch). After D-01, this UPDATE succeeds because the column has no subtype constraint.
- `backend/app/processing/ingest/metadata.py:165` (`get_geometry_type`) — derives concrete type from first feature; replaces the PostGIS column-level discipline lost by D-01.
- `backend/app/processing/ingest/tasks_vector.py:114-180` — geometry_type plumbing (no change expected; verify D-01 doesn't break downstream consumers).

### Frontend Wire-up Surfaces

- `frontend/src/components/import/ServiceUrlForm.tsx:197` — CLASS-07 frontend change point (read `layer.kind` instead of re-deriving).
- `frontend/src/types/api.ts` — mirror `kind` field added to `ProbeLayer` schema.
- CRS Override field (search `crsOverride` / `srid_override` in `frontend/src/components/import/`) — D-08 auto-hide when probe CRS is non-null.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- **`get_geometry_type` at `metadata.py:165`** — already derives concrete PostGIS type from first feature. This is the replacement for the column-level type constraint that D-01 drops. No new code needed — just verify it runs after ogr2ogr completes on the service-ingest path.
- **`detect_service_type` per-probe short-circuit (`probe.py:95-161`)** — already correct; do not re-architect.
- **`ProbeResponse` / `Layer` Pydantic schemas (`sources/schemas.py`)** — additive `kind` field is a backward-compat change for existing consumers (Pydantic v2 with field default).

### Established Patterns

- **`ogr2ogr` flag conventions at `ogr.py:520-611`** — `PROMOTE_TO_MULTI`, `GEOMETRY_NAME=_geolens_geom`, `SPATIAL_INDEX=NONE`. Locked decisions (e.g., PRECISION=NO) noted inline; do not change without review. D-01 changes only the `-nlt` flag for the service path.
- **`async with semaphore + asyncio.wait_for + asyncio.gather`** in enrichment paths. D-05 drops the enrichment call entirely, not the pattern.
- **Pydantic schema field-default for additive evolution** — when adding `kind: Literal['vector', 'raster']`, supply a default of `'vector'` so existing consumers don't break (and document the null→vector implication of D-09).
- **No-migration backward compat** — the `MapBasemapConfig.sublayer_overrides` jsonb pattern from v1011 (BUG-04) shows the project prefers additive schema changes without migrations. For Phase 1057 this means: no PostGIS column ALTERs, no Alembic revision; the change is at column-creation time for new ingests only.

### Integration Points

- **Probe → preview → commit pipeline.** Probe builds the layer list (now without enrichment per D-05); user clicks a layer; preview path runs ogrinfo on that one layer; commit path runs `run_ogr2ogr_service` (with the new `-nlt` flag per D-01). No new integration boundaries; the existing flow already supports per-layer enrichment at preview time.
- **CLASS-07's `kind` field is consumed both today (`ServiceUrlForm.tsx:197`) and in future ingest UIs** — the backend classification is the durable contract; frontend changes are minimal mirrors. Other call sites (BulkReviewList, `isRasterPreview` at `frontend/src/components/import/utils.ts:5`) classify on `previewData` not probe response, so they are unaffected.

### Restart vs Rebuild

- v1057 changes are Python-only (no migrations). Stack-restart pattern applies: `docker compose restart api worker frontend` after backend edits; `npm run dev` HMR for frontend edits. No `down -v && up -d --build` needed unless a Python dependency is added.

</code_context>

<specifics>
## Specific Ideas

- **Test against the same endpoints used in the v1012 smoke** so that the live MCP re-verify at the Phase 1060 close gate exercises the same surfaces:
  - WFS-04 → `https://ahocevar.com/geoserver/wfs` → `topp:countries` (Countries of the World)
  - PROBE-05 → `https://demo.pygeoapi.io/master` (17 collections; pre-fix ~63s, target ≤5s)
  - CRS-06 → `https://demo.pygeoapi.io/master` → `lakes` (Large Lakes, CRS84 URI form)
  - CLASS-07 → `https://demo.pygeoapi.io/master` → any collection without `geometry_type` (also Natural Earth Points via the GeoServer WFS layer-select)
- **The Service URL Reupload preview pane is the gold standard for surfacing chosen-layer + schema-diff + schema-change warning** (per smoke report addendum). Phase 1057 does not change Reupload — but the same observation informs Phase 1058 (GPKG-02 design reference).

</specifics>

<deferred>
## Deferred Ideas

- **Migrating / retrying previously-failed WFS imports** that left empty PostGIS tables. Out of v1013 scope; user re-runs import after deploy.
- **Probe-duration structured-log telemetry / metric.** Trivial to add inline; planner's discretion (D-14 Claude's Discretion #3). Defer to v1014+ if not folded into Plan B.
- **WMS / WMTS / TMS adapter support.** Explicitly out of milestone scope (REQUIREMENTS.md "Out of Scope").
- **Backend-side CRS reprojection beyond URI parsing.** Explicitly out of milestone scope.
- **Per-layer ogrinfo enrichment as a background task with eventual UI update** (alternative to D-05). Defer — D-05 (lazy-on-select) is simpler and achieves the ≤5s target.
- **Pre-emptive raster signal expansion** (e.g., `coverage_format` taxonomy) for sources beyond STAC. Defer until a real source surfaces — current D-09 rule covers the known cases.

### Reviewed Todos (not folded)

- **Recreate public repo before launch** (`.planning/todos/pending/2026-05-05-recreate-public-repo-before-launch.md`) — reviewed via `gsd-sdk query todo.match-phase 1057` (0 matches against this phase). Listed in STATE.md as outside v1013 scope. Not folded.

</deferred>

---

*Phase: 1057-Service URL Reliability*
*Context gathered: 2026-05-19*
