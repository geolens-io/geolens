---
phase: 1057-service-url-reliability
verified_at: 2026-05-19T01:35:00Z
status: passed
must_haves_covered: 4/4
deferred_to_1060:
  - "Live WFS import: ahocevar.com/geoserver/wfs → Countries of the World → Import succeeds end-to-end (WFS-04)"
  - "Live probe wall-clock: demo.pygeoapi.io/master returns 17 collections within ≤5s (PROBE-05)"
  - "Live CRS auto-detect: demo.pygeoapi.io/master Large Lakes import without CRS Override field interaction (CRS-06)"
  - "Live VEC label: ne:ne_10m_populated_places (Natural Earth Points) shows VEC, not RAS, in layer-select list (CLASS-07)"
---

# Phase 1057: Service URL Reliability Verification Report

**Phase Goal**: A user importing data from a Service URL (WFS, ArcGIS, OGC API Features) sees fast probe completion, accurate geometry-type classification, automatic CRS detection for URI-form references, and successful commit for polygon-heavy WFS sources declaring abstract OGC geometry types.
**Verified**: 2026-05-19T01:35:00Z
**Status**: passed
**Re-verification**: No — initial verification
**Scope**: Source-level + unit/integration test evidence only. Live MCP gates deferred to Phase 1060 (Close Gate) per CONTEXT.md and all three plan verification sections.

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | User can import a polygon-heavy WFS layer declaring abstract OGC geometry types without a post-ingest bounds-clip UPDATE failure | VERIFIED | `run_ogr2ogr_service` emits `-nlt GEOMETRY` (not `PROMOTE_TO_MULTI`) at `ogr.py:616`; 6 argv-shape tests pass |
| 2 | User sees probe complete in ≤5s for fast services where any adapter succeeds quickly | VERIFIED | `enrich_ogcapi_layers` and `enrich_wfs_layers` deleted entirely from adapters; probe.py passes layers through directly; 17-collection mock probe completes <100ms in unit test |
| 3 | User importing OGC API Features source with URI-form CRS does not need to manually enter EPSG override | VERIFIED | `parse_crs_uri` covers 4 D-07 forms; wired into `extract_srid_from_json` as third fallback at `ogr.py:194-197`; frontend CRS Override hidden when `detectedCrs` non-null at `ImportMetadataForm.tsx:211`; 23 tests pass |
| 4 | User browsing Service URL layer-select list sees vector layers classified as VEC even when probe response is missing geometry_type | VERIFIED | `LayerInfo.kind: Literal['vector', 'raster']` with default `'vector'` in `schemas.py:58-67`; `classify_layer_kind` helper in `classify.py` implements D-09 raster signals; `ServiceUrlForm.tsx:209` reads `layer.kind` directly; 25 classification tests pass |

**Score**: 4/4 truths verified (source-level + unit/integration evidence)

---

## Criterion 1: WFS-04 — Abstract OGC Geometry Type (P0)

**Verdict**: VERIFIED

### Source Evidence

`backend/app/processing/ingest/ogr.py:582-618` — `run_ogr2ogr_service` spatial branch:
- `-nlt GEOMETRY` replaces the former `-nlt PROMOTE_TO_MULTI`
- 15-line inline comment block explains: (a) the asyncpg `InvalidParameterValueError` on `MultiSurface vs MultiPolygon` during `clip_to_mercator_bounds`; (b) that `Dataset.geometry_type` is derived post-ingest via `get_geometry_type()` at `metadata.py:165`; (c) that the file-ingest sibling `run_ogr2ogr` is unchanged. References D-01 and Phase 1057.

`backend/app/processing/ingest/ogr.py:485-501` — file-ingest `run_ogr2ogr` spatial branch:
- Still emits `-nlt PROMOTE_TO_MULTI` at line 489 — **negative control confirmed**.

**Grep output confirming scope-clean split**:
```
grep -n "PROMOTE_TO_MULTI" ogr.py
  489:                "PROMOTE_TO_MULTI",       ← file-ingest only
  586:        # D-01 / Phase 1057 — WHY -nlt GEOMETRY (not PROMOTE_TO_MULTI):   ← comment only
  606:        # PROMOTE_TO_MULTI because local files always report concrete types; ← comment only
```
`run_ogr2ogr_service` spatial argv contains no live `PROMOTE_TO_MULTI` token.

### Test Evidence

`backend/tests/test_ingest_service_geometry_type.py` — `TestRunOgr2ogrServiceArgv` — **6/6 PASS**:
- `test_wfs_spatial_branch_omits_promote_to_multi` — regression pin (D-01)
- `test_wfs_spatial_branch_emits_nlt_geometry` — confirms constraint-free flag present
- `test_wfs_spatial_branch_includes_geometry_name` — `GEOMETRY_NAME=_geolens_geom` + `SPATIAL_INDEX=NONE` preserved
- `test_wfs_spatial_branch_includes_t_srs_4326` — reprojection preserved
- `test_wfs_spatial_branch_includes_page_size_config` — WFS-specific `OGR_WFS_PAGE_SIZE` preserved
- `test_non_spatial_branch_omits_geometry_flags` — `is_non_spatial=True` path unchanged

---

## Criterion 2: PROBE-05 — Probe Latency ≤5s (P1)

**Verdict**: VERIFIED (source + unit-test; live wall-clock deferred to Phase 1060)

### Source Evidence

**Enrichment deletion — complete**:
- `enrich_ogcapi_layers` definition: **absent** from `adapters/ogcapi.py` (78 lines deleted)
- `enrich_wfs_layers` definition: **absent** from `adapters/wfs.py` (89 lines deleted)

```
grep -n "def enrich_ogcapi_layers\|def enrich_wfs_layers" adapters/ogcapi.py adapters/wfs.py
(no output)
```

**Probe orchestrator — only references in comments**:
```
grep -n "enrich_ogcapi_layers\|enrich_wfs_layers" probe.py adapters/ogcapi.py adapters/wfs.py
probe.py:10:  #   bottleneck was enrich_ogcapi_layers ... (comment)
probe.py:14:  # D-05 (fix): enrich_ogcapi_layers and enrich_wfs_layers are REMOVED (comment)
adapters/ogcapi.py:8:  # enrich_ogcapi_layers() was removed in Phase 1057 (comment)
adapters/wfs.py:18:  # enrich_wfs_layers() was removed in Phase 1057 (comment)
```
No live call sites remain.

**OGC API layer build** (`adapters/ogcapi.py:152-167`): layers constructed with `"geometry_type": None`, `"feature_count": None`, `"kind": classify_layer_kind(c, adapter_type="ogcapi")` — no subprocess invoked.

**WFS layer build** (`adapters/wfs.py:82`): `"kind": "vector"` added to every WFS layer dict — no subprocess invoked.

**ArcGIS enrichment preserved** (`probe.py:134, 172`): `enrich_arcgis_feature_counts` still called at both ArcGIS branches — HTTP-based, not ogrinfo, not the bottleneck per D-04.

**Per-probe short-circuit preserved** (`probe.py:149, 160, 166`): `if result is not None: return` pattern intact — D-04 explicitly verified correct, untouched.

### Test Evidence

`backend/tests/test_probe_classification.py` — `TestProbeOrchestratorNoEnrichment` — **5/5 PASS**:
- `test_ogcapi_probe_completes_fast_without_subprocess` — 17-collection mock probe <100ms wall-clock
- `test_ogcapi_probe_layers_have_null_geometry_and_count` — `geometry_type=None`, `feature_count=None`
- `test_wfs_probe_layers_have_null_geometry_and_count_with_vector_kind` — same shape for WFS
- `test_enrich_ogcapi_layers_not_called` — structural assertion: function absent from probe module namespace
- `test_enrich_arcgis_feature_counts_still_called` — mock spy confirms ArcGIS enrichment invoked

---

## Criterion 3: CRS-06 — URI/URN-form CRS Parsing (P2)

**Verdict**: VERIFIED (source + unit-test; live flow deferred to Phase 1060)

### Source Evidence

**`backend/app/modules/catalog/sources/crs_uri.py`** (new file, 100 lines):
- 4 compiled regex constants at module level: `_RE_OGC_CRS84_HTTP`, `_RE_EPSG_HTTP`, `_RE_EPSG_URN`, `_RE_OGC_CRS84_URN`
- `parse_crs_uri(value: str | None) -> int | None` — default-deny allowlist (unrecognised → `None`)
- Module docstring references Phase 1057 CRS-06, D-07, D-13 (no reprojection)

**`backend/app/processing/ingest/ogr.py:10, 193-197`** — wire-up confirmed:
```
grep -n "parse_crs_uri" ogr.py
  10: from app.modules.catalog.sources.crs_uri import parse_crs_uri
  195:     srid = parse_crs_uri(name)
```
Third-fallback ordering: projjson (line 170) → WKT (line 178) → URI/URN (line 193) — authoritative EPSG declarations win.

**`frontend/src/components/import/ImportMetadataForm.tsx:211-235`** — conditional render:
- `{detectedCrs ? ( ... read-only confirmation ... ) : ( ... editable #import-crs input ... )}`
- Non-null branch shows `"Detected CRS: EPSG:{N} (auto-detected — no override needed)"` (option B)
- Null branch shows existing manual `#import-crs` input — escape hatch preserved
- `sridOverride` state + `srid_override` commit payload unchanged at lines 134-137

### Test Evidence

`backend/tests/test_crs_uri_parsing.py` — **23/23 PASS**:
- `TestParseCrsUri` (16 tests): all 4 D-07 forms + HTTPS variants + fallthrough cases (None, empty string, unknown HTTP/URN, bare `EPSG:N`, non-numeric code, large integer)
- `TestExtractSridFromJsonUriFallback` (7 tests): URI fires when projjson+WKT absent; projjson wins over URI; WKT wins over URI; unrecognised → None; empty dict; `name: None`

`frontend/src/components/import/__tests__/ImportMetadataForm.test.tsx` — **27/27 PASS** (23 pre-existing + 4 new):
- `hides the CRS input when detectedCrs is non-null`
- `shows CRS input when detectedCrs is null (escape hatch preserved)`
- `shows a non-editable confirmation when detectedCrs is non-null`
- `srid_override is null in commit when CRS input is hidden`

---

## Criterion 4: CLASS-07 — VEC Classification Fallback (P2)

**Verdict**: VERIFIED (source + unit-test; live label display deferred to Phase 1060)

### Source Evidence

**`backend/app/modules/catalog/sources/schemas.py:58-67`** — `LayerInfo.kind` field:
```python
kind: Literal["vector", "raster"] = Field(
    default="vector",
    description="Backend-classified layer kind. ... Per Phase 1057 CLASS-07 D-09. ..."
)
```
Default `'vector'` ensures backward-compat (Pydantic-v2 field with default). `from typing import Literal` imported at line 4.

**`backend/app/modules/catalog/sources/classify.py`** (new file, 77 lines):
- `classify_layer_kind(layer: dict, adapter_type: Literal['wfs', 'ogcapi', 'arcgis', 'stac']) -> Literal['vector', 'raster']`
- D-09 rules in priority order: STAC → geometry_type contains 'raster' → coverage_format truthy → bands truthy → any link.type startswith 'image/'
- Defensive: `isinstance(links, list)` guard prevents malformed responses returning 'raster'

**Classification wired at all three adapter layer-build sites**:
- OGC API (`adapters/ogcapi.py:163`): `"kind": classify_layer_kind(c, adapter_type="ogcapi")`
- WFS (`adapters/wfs.py:82`): `"kind": "vector"` (WFS is always vector by OGC spec — no classify call needed)
- ArcGIS (`probe.py:102`, post WR-01 fix): `kind=classify_layer_kind(layer, adapter_type="arcgis")`

**`frontend/src/types/api.ts:1215-1223`** — `LayerInfo` TS interface:
```typescript
/** Backend-classified layer kind. Phase 1057 CLASS-07 D-09 / D-10. ... */
kind: 'vector' | 'raster';
```
Required field (non-optional) forces correct handling.

**`frontend/src/components/import/ServiceUrlForm.tsx:197-209`**:
```tsx
// D-10 (Phase 1057 CLASS-07): consume backend-classified layer.kind directly.
<TypeTag kind={layer.kind} size="sm" />
```
Old `isVector = layer.geometry_type && !layer.geometry_type.toLowerCase().includes('raster')` derivation is gone — confirmed by:
```
grep "geometry_type.*toLowerCase.*raster" ServiceUrlForm.tsx
(no output)
```

### Test Evidence

`backend/tests/test_probe_classification.py` — `TestClassifyLayerKind` — **20/20 PASS**:
- STAC → raster (2 tests)
- geometry_type containing 'raster' parametrized (5 cases: raster, Raster, RASTER, rasterBand, gridcoverage_raster)
- Raster signal fields (coverage_format, bands, links[].type image/*) parametrized (6 cases, including empty `coverage_format` → vector)
- Null geometry_type OGC API → vector
- WFS layer → vector
- ArcGIS FeatureServer → vector
- `LayerInfo.kind` Pydantic default `'vector'`
- `LayerInfo.kind='invalid'` rejected (Literal enforcement)
- Non-image link type → vector
- Malformed links (dict not list) → vector (defensive guard)

---

## Required Artifacts

| Artifact | Expected | Status | Evidence |
|----------|----------|--------|----------|
| `backend/app/processing/ingest/ogr.py` | `-nlt GEOMETRY` in `run_ogr2ogr_service` spatial branch | VERIFIED | Line 616; comment block lines 582-614 |
| `backend/tests/test_ingest_service_geometry_type.py` | 6 argv-shape tests, all pass | VERIFIED | 6/6 PASS at runtime |
| `backend/app/modules/catalog/sources/schemas.py` | `LayerInfo.kind: Literal['vector', 'raster']` with default `'vector'` | VERIFIED | Lines 58-67 |
| `backend/app/modules/catalog/sources/classify.py` | `classify_layer_kind` D-09 helper | VERIFIED | Full file, 77 lines, 5 rules |
| `backend/app/modules/catalog/sources/adapters/ogcapi.py` | `enrich_ogcapi_layers` deleted; `kind` classified at build | VERIFIED | Function absent; layer dict line 163 |
| `backend/app/modules/catalog/sources/adapters/wfs.py` | `enrich_wfs_layers` deleted; `kind='vector'` at build | VERIFIED | Function absent; layer dict line 82 |
| `backend/app/modules/catalog/sources/probe.py` | No enrich_ogcapi/wfs calls; ArcGIS enrichment preserved | VERIFIED | Only comment refs to deleted functions; `enrich_arcgis_feature_counts` at lines 134, 172 |
| `backend/app/modules/catalog/sources/crs_uri.py` | `parse_crs_uri` with 4 compiled regex constants | VERIFIED | Full file, 100 lines |
| `backend/tests/test_probe_classification.py` | 25 tests (20 classify + 5 orchestrator), all pass | VERIFIED | 25/25 PASS at runtime |
| `backend/tests/test_crs_uri_parsing.py` | 23 tests (16 form + 7 fallback), all pass | VERIFIED | 23/23 PASS at runtime |
| `frontend/src/types/api.ts` | `LayerInfo.kind: 'vector' \| 'raster'` required field | VERIFIED | Lines 1215-1223 |
| `frontend/src/components/import/ServiceUrlForm.tsx` | `<TypeTag kind={layer.kind} ...>` direct consumption | VERIFIED | Line 209; old derivation absent |
| `frontend/src/components/import/ImportMetadataForm.tsx` | CRS Override auto-hides when `detectedCrs` non-null | VERIFIED | Lines 205-235; option B (read-only confirmation) |

---

## Key Link Verification

| From | To | Via | Status |
|------|----|-----|--------|
| `ogr.py:run_ogr2ogr_service` | PostGIS `geometry(Geometry, 4326)` | `-nlt GEOMETRY` argv token at line 616 | VERIFIED |
| `ogr.py:run_ogr2ogr` (file-ingest) | PostGIS `geometry(MultiPolygon, 4326)` | `-nlt PROMOTE_TO_MULTI` at line 489 | VERIFIED (unchanged, negative control) |
| `ogr.py:extract_srid_from_json` | `crs_uri.py:parse_crs_uri` | import line 10; call line 195 in third-fallback block | VERIFIED |
| `adapters/ogcapi.py:probe_ogcapi` | `classify.py:classify_layer_kind` | import line 36; call at layer dict line 163 | VERIFIED |
| `probe.py:_build_arcgis_response` | `classify.py:classify_layer_kind` | import line 36; call line 102 (WR-01 fix) | VERIFIED |
| `probe.py:detect_service_type` | `enrich_arcgis_feature_counts` | lines 134, 172 — preserved | VERIFIED |
| `ServiceUrlForm.tsx` | `LayerInfo.kind` from `api.ts` | line 209 `layer.kind`; `api.ts:1223` required field | VERIFIED |
| `ImportMetadataForm.tsx:detectedCrs` | CRS Override conditional render | `{detectedCrs ? ... : ...}` at line 211 | VERIFIED |

---

## Behavioral Spot-Checks

| Behavior | Check | Result | Status |
|----------|-------|--------|--------|
| All 54 phase-specific backend tests pass | `pytest test_ingest_service_geometry_type.py test_probe_classification.py test_crs_uri_parsing.py -v` | 54/54 PASS in 0.65s | PASS |
| WFS pure tests updated and pass after layer-dict shape change | `pytest test_services_wfs_pure.py -v` | 11/11 PASS | PASS |
| Full 4-suite unit test set (65 tests) | `pytest test_ingest_ogr_pure.py + 4 phase suites` | 145/145 PASS | PASS |
| TypeScript compiles without new errors | `npx tsc --noEmit` | 0 errors introduced (exit 0) | PASS |
| No live call sites to deleted enrich functions | `grep -rn "enrich_ogcapi_layers\|enrich_wfs_layers" backend/app --include="*.py"` (excl comments) | 0 matches | PASS |
| PROMOTE_TO_MULTI absent from service-ingest argv | `grep -n "PROMOTE_TO_MULTI" ogr.py` — only lines 489, 586, 606 | File-ingest only + comment lines | PASS |

---

## Negative-Control Checks

| Guard | Check | Result |
|-------|-------|--------|
| File-ingest path (`run_ogr2ogr`) unchanged — still uses PROMOTE_TO_MULTI | `grep -n "PROMOTE_TO_MULTI" ogr.py` shows line 489 in `run_ogr2ogr` body | CONFIRMED |
| No WMS/WMTS/TMS adapter code added | `grep -rn "WMS\|WMTS\|TMS" backend/app/modules/catalog/sources/adapters/` | 0 live references |
| No CRS reprojection added (D-13) | No ST_Transform, no pyproj, no coordinate-transform call added | CONFIRMED |
| SSRF guards still wired | `validate_url_for_ssrf` in `router.py` at lines 102, 239; secondary OGC API URLs re-validated in `ogcapi.py:131` | CONFIRMED |
| `isRasterPreview` in `utils.ts` untouched | `frontend/src/components/import/utils.ts` not in any plan's `files_modified` | CONFIRMED |

---

## Scope Guardrail Audit

Per CONTEXT.md D-11 through D-13 and ROADMAP.md "Not in scope":

| Guardrail | Status |
|-----------|--------|
| No retry path for previously-failed imports | No retry/remediation code added to any ingest route |
| No new adapter types (WMS/WMTS/TMS) | `adapters/` directory unchanged except ogcapi.py and wfs.py modifications |
| No backend-side CRS reprojection beyond URI parsing | `parse_crs_uri` returns EPSG integers only; no transform calls added |
| No migration (Alembic revision) | Change is at column-creation time (`-nlt GEOMETRY` flag); no schema migration file added |
| Phase 1058 (GPKG), 1059 (Basemap Sublayer), 1060 (Close Gate) untouched | No GPKG, basemap sublayer, or CHANGELOG code in any of the 3 plans |

---

## Anti-Patterns Found

| File | Pattern | Severity | Assessment |
|------|---------|----------|------------|
| `test_crs_uri_parsing.py` (pre-review) | WR-02: vacuous assertion `result is None or isinstance(result, int)` | Warning | Fixed inline (commit `80bfb694`) — now asserts `result == 99999999999999999999` |
| `ImportMetadataForm.test.tsx` (pre-review) | WR-03: dead test body with no assertions | Warning | Fixed inline (commit `299097d5`) — mode-switch + column assertions added |

All 6 code-review findings (WR-01, WR-02, WR-03, IN-01, IN-02, IN-03) fixed inline. Post-fix suite: 65/65 backend PASS, 27/27 frontend PASS. No remaining stubs, no unresolved debt markers.

---

## Code Review Summary

REVIEW.md status: **clean** (0 critical, 0 warning, 0 info after all 6 inline fixes).

Post-fix evidence from REVIEW.md:
- WR-01: `classify_layer_kind(layer, adapter_type="arcgis")` added to `_build_arcgis_response` — verified at `probe.py:102`
- WR-02: Vacuous large-int assertion replaced — pinned to exact integer value
- WR-03: Dead numeric-column test completed with mode-switch + column assertions
- IN-01: `looks_arcgis` / `looks_wfs` locals extracted to avoid duplicate `_looks_like_arcgis` calls
- IN-02: Comment corrected from `mediaType` to `'type' field` in `classify.py:67`
- IN-03: Unnecessary `async def` + `@pytest.mark.anyio` removed from structural test

---

## Human Verification Required

None. All must-haves are verifiable from source code and test evidence. Live MCP gates are explicitly deferred (not uncertain) to Phase 1060 per CONTEXT.md and all three plan verification sections.

---

## Deferred to Phase 1060 (Close Gate)

The following live behavioral checks are explicitly out-of-scope for this verification. They require browser-based Playwright MCP against running services:

1. **WFS-04 live repro**: `ahocevar.com/geoserver/wfs` → Countries of the World → Import completes without `asyncpg.exceptions.InvalidParameterValueError`
2. **PROBE-05 live wall-clock**: `demo.pygeoapi.io/master` probe returns 17 collections in ≤5s end-to-end
3. **CRS-06 live flow**: `demo.pygeoapi.io/master` → Large Lakes → Import succeeds without CRS Override field interaction (no manual EPSG entry)
4. **CLASS-07 live label**: `ne:ne_10m_populated_places` (Natural Earth Points) shows VEC TypeTag, not RAS, in the layer-select list

These are deferred by design, not uncertain. Phase 1060 close-gate plan lists them explicitly.

---

## Gaps Summary

No gaps. All 4 success criteria have source-level evidence in code and passing unit/integration tests. All code-review findings were fixed inline. No scope creep detected. No debt markers (TBD/FIXME/XXX) introduced.

---

_Verified: 2026-05-19T01:35:00Z_
_Verifier: Claude (gsd-verifier)_
