# Requirements: GeoLens v1025 Mapbuilder Polishing

**Defined:** 2026-05-25
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.

## v1025 Requirements

### Playwright QA

- [x] **QA-01**: Operator can run a Playwright MCP sweep against `http://localhost:8080/maps/8dd6a129-8eb0-4ba9-b421-716c83b160dd` that opens every data layer and basemap row without unhandled UI errors.
- [x] **QA-02**: Operator can verify every layer options menu opens and exposes source metadata plus safe layer actions without trapping focus or breaking row interaction.
- [x] **QA-03**: Operator can verify representative editor tabs and controls for point, line, polygon, raster, DEM, and basemap layers.
- [x] **QA-04**: Browser console warnings/errors, failed requests, screenshot evidence, and visual/cartographic findings are captured in phase artifacts with dispositions.

### Layer Option Fixes

- [x] **LAYER-01**: DEM layers whose saved style config declares hillshade open in the builder as Hillshade, not Image, and retain that render mode through API normalization.
- [x] **LAYER-02**: ADK marketing composition uses GeoLens `label_config` keys so 46er peak labels render in the builder/viewer and remain editable.
- [x] **LAYER-03**: The ADK composition script writes canonical render/style metadata for DEM hillshade, aerial raster, Blue Line outline, and peak labels so reruns reproduce the polished map.
- [x] **LAYER-04**: The existing target map is updated in the running catalog with the same canonical layer metadata without duplicating datasets or maps.

### Marketing Cartography

- [x] **CARTO-01**: Target map styling makes terrain, aerial, hillshade, hydrography, trails, Blue Line, land classification, waterbodies, and 46er peaks legible at the screenshot view.
- [x] **CARTO-02**: Peak labels are readable without overwhelming the terrain and are gated to an appropriate zoom range.
- [x] **CARTO-03**: Legend and builder/sidebar presentation demonstrate GeoLens functionality without hiding key map content.
- [x] **CARTO-04**: Suggestions for future cartographic improvements are documented separately from fixes completed in this milestone.

### Verification

- [x] **VERIFY-01**: Fresh Playwright MCP load of the target map after fixes has zero unexpected console errors/warnings.
- [x] **VERIFY-02**: Playwright MCP verifies the fixed DEM hillshade editor state, peak label rendering, layer options menus, and visibility toggles after reload.
- [x] **VERIFY-03**: Frontend unit tests cover the style-config normalization regression that hid render-mode-only and legacy nested render modes.
- [x] **VERIFY-04**: Phase summaries include the final screenshot target, changed files, commands run, and any accepted external/noise limitations.

### Builder Hygiene Closeout

- [x] **HYGIENE-01**: Frontend lint exits with zero errors and zero warnings after fixing discovered mapbuilder a11y/rules findings.
- [x] **HYGIENE-02**: A post-lint Playwright MCP smoke confirms the target map still loads with expected stack rows and zero console warnings/errors.

## Future Requirements

### Builder UX Follow-ups

- **UX-FU-01**: Consider a non-destructive "presentation mode" for builder screenshots that keeps layer/tool affordances visible while temporarily reducing chrome density.
- **UX-FU-02**: Consider exposing companion label configuration for point mode directly instead of requiring labels to be inferred from saved metadata.

### CI Infrastructure

- **CI-01-v1025**: Live-verify `pytest-parallel-isolation` on real GitHub Actions infrastructure after geolens-io billing is resolved. This rolling external blocker remains outside the mapbuilder polishing invariant.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Rebuilding the whole map-builder information architecture | v1025 is a targeted QA/polish/fix milestone for one existing marketing map. |
| Adding new external datasets | The target map already has the required ADK source stack; this milestone fixes presentation and builder behavior. |
| Replacing OpenFreeMap Positron | Only fix GeoLens handling or document basemap-provider limitations if fresh Playwright evidence requires it. |
| Deleting/duplicating target datasets during QA | QA should exercise destructive menu affordances only up to safe confirmation boundaries unless a fix explicitly requires data changes. |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| QA-01 | Phase 1107 | Complete |
| QA-02 | Phase 1107 | Complete |
| QA-03 | Phase 1107 | Complete |
| QA-04 | Phase 1107 | Complete |
| LAYER-01 | Phase 1108 | Complete |
| LAYER-02 | Phase 1108 | Complete |
| LAYER-03 | Phase 1108 | Complete |
| LAYER-04 | Phase 1108 | Complete |
| CARTO-01 | Phase 1109 | Complete |
| CARTO-02 | Phase 1109 | Complete |
| CARTO-03 | Phase 1109 | Complete |
| CARTO-04 | Phase 1109 | Complete |
| VERIFY-01 | Phase 1110 | Complete |
| VERIFY-02 | Phase 1110 | Complete |
| VERIFY-03 | Phase 1110 | Complete |
| VERIFY-04 | Phase 1110 | Complete |
| HYGIENE-01 | Phase 1111 | Complete |
| HYGIENE-02 | Phase 1111 | Complete |

**Coverage:**
- v1025 requirements: 18 total, 18 complete
- Mapped to phases: 18
- Unmapped: 0

---
*Requirements defined: 2026-05-25*
*Last updated: 2026-05-25 after v1025 builder lint closeout*
