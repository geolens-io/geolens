# Phase 1107 Summary: Playwright Deep QA Sweep

**Status:** Complete
**Requirements closed:** QA-01, QA-02, QA-03, QA-04

## Evidence

- Baseline screenshot: `evidence/adk-map-initial.png`
- Layer/options snapshots: `evidence/adk-layers-snapshot.md`, `evidence/adk-46er-editor-panel.md`
- API capture: `evidence/adk-map-full.json`, `evidence/adk-map-summary.json`
- Initial console capture: `evidence/adk-map-initial-console.log` showed 0 warnings/errors before the manual unauthenticated probe.

## Findings

| ID | Severity | Finding | Disposition |
|----|----------|---------|-------------|
| QA-1107-01 | High | DEM layer saved as `style_config.builder.render_mode=hillshade`; frontend normalization did not promote it, so the editor opened DEM as Image. | Fixed in Phase 1108. |
| QA-1107-02 | High | 46er peak `label_config` used MapLibre keys (`text-field`, `text-size`) instead of GeoLens keys (`column`, `fontSize`), so labels did not render. | Fixed in Phase 1108. |
| QA-1107-03 | Medium | True hillshade made the screenshot too gray after the metadata fix. | Tuned in Phase 1109. |
| QA-1107-04 | Low | Forced reload during automated QA can produce transient `ERR_ABORTED` requestfailed events for OpenFreeMap style requests; these did not surface as browser console warnings/errors. | Documented as non-blocking QA-script noise. |

## Passing Surfaces

- All 8 data layer rows opened.
- Basemap row opened.
- All layer options menus opened and exposed source/action content.
- Visibility toggles flipped off/on for all data layers and restored to visible.
- Style/Filter/Popup tabs opened for representative vector layers.
