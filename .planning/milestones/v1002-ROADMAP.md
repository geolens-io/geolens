# Milestone v1002: Layer Sidebar + Add Dataset Redesign

**Status:** SHIPPED 2026-05-12  
**Phases:** 1008-1013  
**Total Plans:** 6  
**Requirements:** 37/37 satisfied  
**Audit:** `tech_debt` / `COMPLETE_WITH_BROWSER_ENV_REVIEW`

## Overview

v1002 redesigned the Map Builder layer sidebar and Add Dataset modal over the existing persisted schema. The milestone intentionally shipped zero migrations, no new tables, no new renderer capabilities, and no persisted group model.

## Phases

### Phase 1008: Sidebar view-model and renderAs foundation

**Goal:** Establish the no-migration frontend model and renderAs utility so later UI work has a stable, tested contract.  
**Requirements:** ARCH-01..04, RENDER-01  
**Plans:** 1

- [x] 1008-01: Add pure `renderAs` utility and preserve existing stack view-model.

### Phase 1009: Layer row and dataset-rendering sidebar

**Goal:** Replace the current row presentation with the scoped v1 row anatomy and dataset-rendering grouping inside `data`.  
**Requirements:** STACK-01..05  
**Plans:** 1

- [x] 1009-01: Redesign row anatomy and dataset-rendering headers.

### Phase 1010: RenderAs actions and duplicate renderings

**Goal:** Wire user-facing renderAs changes and duplicate rendering actions over the existing `MapLayer` patch/diff behavior.  
**Requirements:** RENDER-02..08  
**Plans:** 1

- [x] 1010-01: Add renderAs mutation patches and duplicate-rendering action.

### Phase 1011: Basemap and terrain inline rows

**Goal:** Surface basemap and terrain as inline stack rows backed by existing map-level fields.  
**Requirements:** BASE-01..04, TERRAIN-01..02  
**Plans:** 1

- [x] 1011-01: Inline basemap swap/reset/appearance and terrain controls.

### Phase 1012: Add Dataset modal redesign

**Goal:** Rewrite the Add Dataset modal around search-first catalog browsing, supported filters, basemap swap states, and duplicate-rendering affordances.  
**Requirements:** ADD-01..08  
**Plans:** 1

- [x] 1012-01: Redesign Add Dataset modal in place.

### Phase 1013: Builder sidebar/modal QA closeout

**Goal:** Convert the milestone's schema, behavior, accessibility, and responsive guarantees into focused repeatable checks.  
**Requirements:** QA-01..06  
**Plans:** 1

- [x] 1013-01: Align Playwright specs, run focused Vitest/lint/build, and document browser-stack caveat.

## Milestone Summary

**Key Decisions:**

- Sidebar groups remain a frontend view-model over existing `Map`, `MapLayer[]`, `basemap_*`, `terrain_config`, and `widgets`.
- `Dataset` remains the data entity; dataset-rendering headers are UI grouping only.
- `Basemap` and terrain stay on map-level fields, not synthetic persisted `MapLayer` rows.
- `is_3d` remains read-only response/dataset metadata and is never written by sidebar/modal mutation paths.
- Kepler.gl remains a conceptual reference for dataset/layer separation and workflow semantics, not an implementation dependency.

**Issues Resolved:**

- Layer rows now expose renderAs, opacity, visibility-at-zoom, duplicate rendering, and terrain actions in one stack surface.
- Multiple renderings of one dataset are visually grouped without schema changes.
- Add Dataset now handles already-added datasets through `another rendering` instead of blocking multi-rendering workflows.
- Basemap and terrain controls are accessible from the sidebar while preserving existing map-level storage.

**Issues Deferred:**

- Live Playwright browser execution needs a healthy local full stack; this environment had unreachable app ports and unresponsive Docker.
- Full release gates, SDK/OpenAPI checks, and backend suites were not rerun for this frontend-only, schema-preserving milestone.
- Future renderer/capability work remains out of scope: Cluster, Hexbin, H3, Arrow, Animated path, Point 3D extrusion, timeline, recipes, cross-layer filters, blend mode, persisted basemap presets, org connector library, and exact-position modal-to-stack drag.

**Verification:**

- Focused Vitest single-worker rerun: 5 files / 61 tests passed.
- Frontend lint passed.
- Frontend production build passed with the existing large `map-vendor` chunk warning.
- Playwright spec loading passed for `e2e/builder.spec.ts` and `e2e/accessibility.spec.ts`, listing the new Add Dataset modal and modal accessibility tests.

---

For current project status, see `.planning/ROADMAP.md`.
