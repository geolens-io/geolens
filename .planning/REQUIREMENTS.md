# Requirements: GeoLens — v1013 Ingest Hardening

**Defined:** 2026-05-19
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Source of truth:** `.planning/quick/260519-smoke-v1012/SMOKE-v1012-REPORT.md` (Findings 1-7) + v1011.1 EMRG-FN-01 deferral (BSE-01).

## v1013 Requirements

Requirements for milestone v1013. Each maps to exactly one phase in `ROADMAP.md`. Public tag: **v1.4.0** (minor — Findings 1+3 add new affordances; BSE-01 is feature work).

### Service URL Reliability

- [x] **WFS-04** *(P0)*: User can import polygon-heavy WFS layers declaring abstract OGC geometry types (`MultiSurface`, `MultiCurve`, `CompoundSurface`) without the post-ingest bounds-clip UPDATE failing on PostGIS type mismatch. Fix candidates: (a) map abstract → concrete on column creation; (b) inspect first feature in probe to determine concrete subtype; (c) drop subtype constraint — use generic `GEOMETRY` column. Repro: `ahocevar.com/geoserver/wfs` → Countries of the World → Import.
- [x] **PROBE-05** *(P1)*: User sees Service URL probe completion within ≤5s for fast services. `try_all_probes()` short-circuits on first success rather than running all probe types sequentially (currently ~63s for a 1.5s adapter on `demo.pygeoapi.io/master`). Acceptance: timed probe of OGC API endpoint completes in ≤5s end-to-end.
- [ ] **CRS-06** *(P2)*: User can import OGC API Features sources declaring URI-form CRS references (e.g., `http://www.opengis.net/def/crs/OGC/1.3/CRS84`) without manually entering an EPSG override. URI → EPSG mapper covers at minimum: CRS84 → 4326, `http://www.opengis.net/def/crs/EPSG/0/{N}` → EPSG:N. Acceptance: `demo.pygeoapi.io/master` Large Lakes import succeeds without CRS Override field interaction.
- [x] **CLASS-07** *(P2)*: User sees vector layers (point/line/polygon) in the Service URL layer-select list classified as VEC even when the probe response is missing `geometry_type`. RAS classification requires an explicit raster signal. Repro: `ne:ne_10m_populated_places` (Natural Earth Points) currently labels RAS.

### Multi-Layer GPKG Handling

- [x] **GPKG-01** *(P0)*: User selecting Reupload File path with a multi-layer GPKG sees a layer-select step (mirroring Service URL flow at `ReuploadDialog.tsx:581`). The chosen layer is honored end-to-end through preview + commit; `dataset.source_layer` is the default selection when present in the new file. Fix surfaces: `ReuploadDialog.tsx` state machine + `previewMutation.mutateAsync({ datasetId, jobId, layer_name })` + `router_reupload.py:329` + `backend/app/processing/ingest/ogr.py:209` (no longer fall through to `layers[0]`).
- [ ] **GPKG-02** *(P1)*: User sees the chosen layer name + column-level schema diff (Columns Added / Columns Removed with types) + schema-change warning in the Reupload preview pane. Service URL preview is the design reference. Acceptance: preview pane displays "Layer: {name}" line + schema diff rows when columns differ.
- [x] **GPKG-03** *(P2)*: User can ingest all layers of a multi-layer GPKG as separate datasets via the Bulk Review flow — single upload, N datasets created. Mitigation candidates: (a) accept multi-commit per file in Bulk Review with "+ add another layer from this file" button; (b) add an "Ingest all layers" path that fans out to N datasets per file. Surface: `BulkReviewList.tsx:343-358`, `onCommitSingle` at line 150. **Partial**: UX implemented; T-1058C-03 backend constraint (job.status check) means only 1 layer succeeds per upload — follow-up plan needed.

### Basemap Sublayer Editor (Path B FIX)

- [ ] **BSE-01** *(Feature)*: User can edit and persist per-sublayer styling overrides for any basemap sublayer. Surfaces include stroke color, stroke width, casing color, casing width, zoom range, opacity. Overrides round-trip through save/reload and apply correctly on map render across builder + viewer + shared/embed contexts. Replaces the dead-wired surface removed in v1011.1 EMRG-FN-01 (commits `3629ec04` + `3e48d331`) with a real persistence path through `MapBasemapConfig.sublayer_overrides` jsonb-additive (or equivalent). Estimated: 3-5 day feature phase per v1011.1 disposition note.

### Hygiene

- [ ] **CLEAN-01**: The 3 v1012 smoke repro datasets deleted from the `localhost:8080` catalog at the CTRL-01 close gate:
  - `ec18b546-d86d-4375-8e1f-8564b6a75687` (reupload sandbox; v3 = 49 wildfire points)
  - `54763119-0cf4-448e-a950-81551d090267` (AGO Wildfire Response Points; 49 features)
  - `667a6c65-cdbc-4158-87f2-21a7e791ba7c` (OGC API Large Lakes; 25 features)

### Close Gate

- [ ] **CTRL-01**: Milestone close requires:
  - All smoke gates green: typecheck 0, vitest passing, e2e:smoke:builder green, i18n parity 2/2
  - Live Playwright MCP re-verify of WFS-04, PROBE-05, GPKG-01, GPKG-02, BSE-01 against `localhost:8080`
  - Code-review pass with any inline fixes applied per `feedback_review_findings_inline.md`
  - CHANGELOG `[Unreleased]` → `[1.4.0]` block populated
  - Local tag `v1013` created
  - Public tag `v1.4.0` created (minor bump from v1.3.0)

## v2 Requirements (deferred — not in v1013 scope)

Carried forward from prior milestone close notes.

### Marketplace & Distribution

- **MARKET-01**: AWS AMI Build (paused v1.7 phase 40)
- **MARKET-02**: Helm chart + AMI packer pipeline (Phase 999.14)
- **MARKET-03**: SBOM + signed image distribution (Phase 999.15)

### Multi-Tenant Cloud

- **CLOUD-01**: Tenant scoping infrastructure for multi-tenant isolation (Phase 999.6)

### Enterprise Feature Backlog

- **ENT-01**: Persistent connector registry (Phase 999.13)
- **ENT-02**: Extract geolens-schemas package (Phase 999.16)

### Public Repo

- **REPO-01**: Recreate public repo before launch (pending todo from 2026-05-05)

## Out of Scope

Explicitly excluded for v1013. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Cluster fan-out: ingest all layers from non-GPKG multi-source containers (FileGDB, KML w/ multiple folders) | GPKG-03 is GPKG-specific; non-GPKG multi-layer containers are a separate effort. Defer to v1014+. |
| Service URL adapter for new service types (WMS, WMTS, TMS) | This milestone hardens existing adapters (WFS, ArcGIS, OGC API); adding new ones is feature work. |
| WFS write/transaction support | Read-only WFS is the current contract; transactional WFS is out of scope. |
| OGC API Features write/transaction support | Same as WFS — read-only OGC API is current contract. |
| Backend-side CRS reprojection beyond URI parsing | CRS-06 is a parsing-only fix. Full reprojection infrastructure is separate. |
| Basemap sublayer styling beyond fill/stroke/casing/zoom/opacity (e.g., dash pattern, line cap, text-font for label sublayers) | BSE-01 restores the v1011.1-removed surface; additional MapLibre style properties are v2 polish. |
| New basemap providers (vector tile authoring, custom MapTiler styles) | BSE-01 is about per-sublayer override persistence on existing basemaps. New providers are out of scope. |

## Traceability

Populated by `gsd-roadmapper` after phase plan creation. All 10 v1013 requirements mapped to exactly one phase.

| Requirement | Phase | Status |
|-------------|-------|--------|
| WFS-04 | 1057 | Complete |
| PROBE-05 | 1057 | Complete |
| CRS-06 | 1057 | Pending |
| CLASS-07 | 1057 | Complete |
| GPKG-01 | 1058 | Complete |
| GPKG-02 | 1058 | Pending |
| GPKG-03 | 1058 | Partial (T-1058C-03 backend gap) |
| BSE-01 | 1059 | Pending |
| CLEAN-01 | 1060 | Pending |
| CTRL-01 | 1060 | Pending |

**Coverage:**
- v1013 requirements: 10 total
- Mapped to phases: 10 ✓
- Unmapped: 0 ✓

---
*Requirements defined: 2026-05-19*
*Last updated: 2026-05-19 — roadmap committed (4 phases 1057-1060, 10/10 reqs mapped)*
