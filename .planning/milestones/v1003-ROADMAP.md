# Milestone v1003: Builder v1 Hardening

**Status:** Shipped 2026-05-12
**Audit:** passed / GO
**Phases:** 1014-1018
**Plans:** 5 / 5 complete
**Requirements:** 24 / 24 complete

## Overview

v1003 hardened the v1002 Map Builder layer sidebar and Add Dataset redesign through durable browser, accessibility, save/reload, and viewer compatibility coverage. The milestone intentionally shipped no schema changes, no new renderers, and no new catalog/import capabilities.

## Requirements

- Browser baseline and responsive shell: BQA-01..05 complete.
- Duplicate rendering and renderAs behavior: DUP-01..05 complete.
- Basemap and terrain integration: MAPCTL-01..05 complete.
- Add Dataset modal state hardening: ADDH-01..05 complete.
- Saved-map round trip and closeout: ROUND-01..04 complete.

Full requirement archive: `.planning/milestones/v1003-REQUIREMENTS.md`.

## Phases

### Phase 1014: browser-baseline-and-responsive-shell

**Goal:** Establish the real-browser baseline for the redesigned builder shell and close responsive/accessibility regressions.

**Requirements:** BQA-01, BQA-02, BQA-03, BQA-04, BQA-05

**Completed:**

- Builder smoke covered the redesigned sidebar and Add Dataset modal on desktop/tablet surfaces.
- Playwright MCP verified the live builder Map Stack, Add Dataset, basemap states, and tablet layout with no unexpected console errors or warnings.
- Persisted wide sidebar preferences are capped on narrower viewports while preserving the stored desktop preference.
- Scoped builder accessibility, focused Vitest, lint, and build gates passed.

**Evidence:** `.planning/phases/1014-browser-baseline-and-responsive-shell/1014-VERIFICATION.md`

### Phase 1015: duplicate-rendering-and-renderas-hardening

**Goal:** Prove duplicate renderings and v1 renderAs behavior from both sidebar and modal entry points.

**Requirements:** DUP-01, DUP-02, DUP-03, DUP-04, DUP-05

**Completed:**

- Layer-row overflow duplicate rendering creates a sibling layer with shared dataset identity and independent style fields.
- Add Dataset `another rendering` produces the same sibling-layer result.
- Dataset-rendering headers show accurate counts and each row remains independently configurable.
- RenderAs patches stay within existing writable fields and never write `is_3d`.
- Unsupported v1-punted renderers remain absent from the UI.

**Evidence:** `.planning/phases/1015-duplicate-rendering-and-renderas-hardening/1015-VERIFICATION.md`

### Phase 1016: basemap-and-terrain-integration-hardening

**Goal:** Prove basemap and terrain controls remain map-level writes and survive MapLibre style reload/save flows.

**Requirements:** MAPCTL-01, MAPCTL-02, MAPCTL-03, MAPCTL-04, MAPCTL-05

**Completed:**

- Basemap swap/reset writes only `basemap_style`, `show_basemap_labels`, and supported `basemap_config` keys.
- Sidebar and Add Dataset basemap states stay synchronized after swap.
- Terrain enabled/exaggeration/source changes write only `terrain_config`.
- Raster-dem `Use as terrain` sets `terrain_config.source_dataset_id` without mutating the layer row.
- Save/reload preserves basemap and terrain choices.

**Evidence:** `.planning/phases/1016-basemap-and-terrain-integration-hardening/1016-VERIFICATION.md`

### Phase 1017: add-dataset-modal-state-hardening

**Goal:** Prove Add Dataset modal state transitions, filters, row expansion, import routing, and keyboard behavior.

**Requirements:** ADDH-01, ADDH-02, ADDH-03, ADDH-04, ADDH-05

**Completed:**

- Modal tabs remain All, Vector, Raster, and Basemap; DEM remains represented under Raster when available.
- Filter chips use only current API-supported search parameters.
- Data rows transition among Add to map, added, and another rendering states without a page reload.
- Expanded rows keep preview, metadata, and primary actions keyboard reachable.
- The footer routes to the existing ImportPage as `Import data...`; no import logic was reimplemented.

**Evidence:** `.planning/phases/1017-add-dataset-modal-state-hardening/1017-VERIFICATION.md`

### Phase 1018: saved-map-roundtrip-and-closeout

**Goal:** Prove saved-map/public-viewer compatibility and close v1003 with exact verification evidence.

**Requirements:** ROUND-01, ROUND-02, ROUND-03, ROUND-04

**Completed:**

- Existing saved maps load/save without adding, removing, or renaming persisted fields.
- Duplicate renderings, basemap config, terrain config, and zoom-range layout settings round-trip through builder save/reload unchanged.
- Public/shared viewer behavior remains compatible with builder-authored basemap and terrain settings.
- Closeout records verification commands, Playwright MCP observations, and residual unrelated gaps.

**Evidence:** `.planning/phases/1018-saved-map-roundtrip-and-closeout/1018-VERIFICATION.md`, `.planning/milestones/v1003-MILESTONE-AUDIT.md`

## Verification

- `npx playwright test e2e/builder.spec.ts --project=chromium -g "round-trips layer zoom range"` — 2 passed.
- `cd frontend && npm run test -- use-builder-save PublicMapViewerPage PublicViewerPage --run` — 36 tests passed.
- `npm run e2e:smoke:builder` — 26 passed.
- `cd frontend && npm run lint` — passed.
- `cd frontend && npm run build` — passed with the pre-existing large `map-vendor` chunk-size warning.
- Playwright MCP final inspection of the authenticated map builder reported 0 console warnings and 0 console errors.

Earlier v1003 phases also passed their focused Playwright, Vitest, lint, and browser smoke gates; see each phase verification document for the exact command list.

## Known Caveats

- Backend pytest, SDK/OpenAPI drift checks, CLI tests, and packaging/release gates were not rerun; v1003 was scoped to frontend builder hardening.
- Browser DEM terrain provisioning remains covered by deterministic component/unit tests rather than a seeded DEM E2E fixture.
- Production build still emits the pre-existing `map-vendor` chunk-size warning.

## Outcome

v1003 is complete. The builder sidebar and Add Dataset redesign now has browser-proven behavior across the high-risk v1 flows while preserving the existing persisted schema and renderer capabilities.
