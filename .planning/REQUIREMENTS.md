# Requirements: GeoLens v1001 Map Builder UI/UX Polish Sweep

**Defined:** 2026-05-11  
**Core Value:** Users can find any dataset in the catalog in seconds - search, see it on a map, understand what it is, and get it out in the format they need.  
**Milestone Goal:** Make the Map Builder feel coherent, efficient, and trustworthy across the full create/edit/style/preview/share workflow on desktop, tablet, and mobile.  
**Research:** Skipped. This milestone refines existing GeoLens builder surfaces and should be driven by product/codebase audit, prior builder notes, and live UI verification.
**Functional reference:** Kepler.gl should guide behavior for layer workflow, filtering, interactions, map settings, and export/share semantics, but not GeoLens visual styling. Reference docs checked 2026-05-11: [Kepler user guides](https://docs.kepler.gl/docs/user-guides), [filters](https://docs.kepler.gl/docs/user-guides/e-filters), [interactions](https://docs.kepler.gl/docs/user-guides/g-interactions), [blend/rearrange layers](https://docs.kepler.gl/docs/user-guides/b-kepler-gl-workflow/add-data-to-layers/d-blend-and-rearrange-layers), and [save/export](https://docs.kepler.gl/docs/user-guides/k-save-and-export).

## v1001 Requirements

### Workflow Sweep

- [x] **FLOW-01**: Reviewer can complete a documented builder UX audit across create, add-data, edit-layer, style, preview, save, share, and public-viewer flows.
- [x] **FLOW-02**: User can create a new map, add at least one vector layer and one raster or DEM layer, and reach a useful saved state without unclear dead ends.
- [x] **FLOW-03**: User can move through common builder states - empty, loading, loaded, dirty, saved, validation error, network error, and read-only - with clear affordances and recovery paths.
- [x] **FLOW-04**: User can understand which controls affect the whole map, the selected layer, basemap appearance, relief, labels, interactions, or published output.
- [x] **FLOW-05**: Reviewer can see a prioritized finding inventory with each issue mapped to a requirement, severity, affected viewport, and recommended fix path.
- [x] **FLOW-06**: Reviewer can compare GeoLens builder behavior against Kepler.gl-style layer, filter, interaction, map-settings, and save/export workflows, with explicit notes for behavior adopted, adapted, or rejected.

### Map Stack and Inspector

- [x] **STACK-01**: User can scan the Map Stack and understand Surface, Relief, Basemap, Data, Labels, and Interactions without duplicated or competing layer-management surfaces.
- [x] **STACK-02**: User can select, hide/show, rename, reorder, duplicate-disambiguate, and remove editable layers from the stack with stable keyboard and pointer interactions.
- [x] **STACK-03**: User can open the layer inspector from desktop, tablet, and mobile layouts without losing context or access to primary layer actions.
- [x] **STACK-04**: User can distinguish selected, disabled, locked, unsupported, hidden, loading, and error states in stack rows and inspector controls.
- [x] **STACK-05**: User can edit filters, labels, popups, and layer metadata from the inspector without cramped controls, text overflow, or layout shift.
- [x] **STACK-06**: Keyboard user can navigate the stack, inspector tabs, disclosure controls, menus, and modal workflows in logical order with visible focus.

### Styling and Cartography

- [x] **STYLE-01**: User can configure simple point, line, polygon, raster, DEM hillshade, terrain, symbol, and label styling with controls grouped by visual intent.
- [x] **STYLE-02**: User can configure categorical, graduated, heatmap, zoom-expression, line-gradient, and raster adjustment styles with validation that explains invalid inputs.
- [x] **STYLE-03**: User can preview style changes in the map and in compact inspector swatches before saving, including geometry-aware swatches for point, line, and polygon layers.
- [x] **STYLE-04**: User can reset or cancel style edits without accidentally losing unrelated layer settings.
- [x] **STYLE-05**: User can see and fix unsupported style states imported from MapLibre style JSON without corrupting valid builder-managed style config.
- [x] **STYLE-06**: User can configure popup behavior and label behavior without tab gating, empty-column states, or disabled controls feeling broken.
- [x] **STYLE-07**: User can use color, opacity, size, width, blur, halo, relief, and basemap appearance controls without text clipping across supported viewports.
- [x] **STYLE-08**: Reviewer can verify that builder controls, `paint`, `style_config`, exported style JSON, imported style JSON, and public render output stay aligned.

### Preview, Save, Share, and Output

- [x] **OUTPUT-01**: User can trust the builder preview to match saved map detail, shared-token view, authenticated public view, and embed output for basemap, terrain, relief, labels, popups, and layer order.
- [x] **OUTPUT-02**: User can identify unsaved changes, save progress, save success, save failure, and retry paths without ambiguous button states.
- [x] **OUTPUT-03**: User can share or publish a polished map without hidden builder-only controls leaking into public or embedded output.
- [x] **OUTPUT-04**: User can inspect map title, description, legend, attribution, scale/navigation controls, and optional widgets without overlap or visual clutter.
- [x] **OUTPUT-05**: User can work with blank/no-basemap, light basemap, dark basemap, relief-heavy, raster-heavy, vector-heavy, and mixed maps without presentation regressions.
- [x] **OUTPUT-06**: Reviewer can identify whether server-side thumbnails are needed for builder polish, while leaving the full OPS-01 thumbnail pipeline out of this milestone unless explicitly approved.

### Responsive, Accessibility, and Copy

- [x] **A11Y-01**: User can operate the builder at desktop, tablet, and mobile widths without inaccessible controls, off-screen panels, or unreadable dense rows.
- [x] **A11Y-02**: Screen-reader and keyboard users can operate visible builder controls without focus reaching hidden/collapsed content.
- [x] **A11Y-03**: Builder dialogs, tooltips, menus, switches, icon buttons, sliders, segmented controls, and tablists have accessible names, descriptions where needed, and WCAG AA contrast.
- [x] **A11Y-04**: User-facing builder copy uses GIS/product language instead of internal implementation terms, and explains validation issues in action-oriented language.
- [x] **A11Y-05**: Builder i18n keys remain complete for en, es, fr, and de for any touched copy.
- [x] **A11Y-06**: User can use common controls with 44px touch targets on mobile and stable dimensions that do not resize the layout on hover, focus, loading, or validation.

### Durable QA Gate

- [ ] **QA-01**: Developer can run a focused builder regression suite covering the polished workflow without requiring seeded demo maps unless the test explicitly opts in.
- [ ] **QA-02**: Developer can run builder smoke tests without the known sidebar drag-handle flake or with a deterministic replacement that proves the intended behavior.
- [ ] **QA-03**: Developer can run Playwright coverage for desktop, tablet, and mobile builder paths that asserts key UI state rather than relying only on screenshots.
- [ ] **QA-04**: Developer can run accessibility checks for the builder and public saved-map outputs with documented exclusions only for MapLibre canvas internals.
- [ ] **QA-05**: Reviewer can compare before/after screenshots for genuinely visual polish decisions, with screenshot paths recorded in the phase artifact.
- [ ] **QA-06**: Developer can run focused Vitest coverage for touched builder components, hooks, and adapters, including regression tests for style/public-output alignment.

## vNext Requirements

Deferred to future releases. Tracked but not in the current roadmap.

### Builder Capabilities

- **NEXT-01**: User can create annotation layers as first-class builder objects.
- **NEXT-02**: User can configure time sliders and temporal animation for eligible datasets.
- **NEXT-03**: Multiple users can collaborate live on the same map.
- **NEXT-04**: User can generate durable server-side thumbnails for every saved map through the full OPS-01 pipeline.

### Product Expansion

- **NEXT-05**: User can use expanded AI map-authoring flows beyond existing AI-assisted map building.
- **NEXT-06**: Operator can deploy a new map-builder architecture that replaces the current MapLibre builder model wholesale.

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Wholesale Kepler.gl replacement | v1000 decided to keep GeoLens MapLibre architecture and borrow only useful stack patterns. |
| Live collaboration | Large persistence and conflict-resolution surface; not required for UI polish. |
| Annotation layers | Net-new authoring capability; defer to a dedicated capability milestone. |
| Time sliders / animation | Net-new temporal interaction model; defer until temporal requirements are scoped. |
| Full OPS-01 server-side thumbnail pipeline | Operational backend pipeline; only thumbnail-related UX discovery is in scope. |
| AI capability expansion | Existing AI flows may be polished, but new AI features need a separate AI milestone. |
| Enterprise governance changes | Publication workflow overlays and enterprise policies remain separate from builder UX polish. |
| Cloud tenant scoping | Cloud prerequisite, unrelated to builder UI/UX. |
| Helm, AMI, SBOM, and signed image distribution | Distribution milestones, unrelated to builder UI/UX. |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| FLOW-01 | Phase 1002 | Complete |
| FLOW-02 | Phase 1002 | Complete |
| FLOW-03 | Phase 1002 | Complete |
| FLOW-04 | Phase 1002 | Complete |
| FLOW-05 | Phase 1002 | Complete |
| FLOW-06 | Phase 1002 | Complete |
| STACK-01 | Phase 1003 | Complete |
| STACK-02 | Phase 1003 | Complete |
| STACK-03 | Phase 1003 | Complete |
| STACK-04 | Phase 1003 | Complete |
| STACK-05 | Phase 1003 | Complete |
| STACK-06 | Phase 1003 | Complete |
| STYLE-01 | Phase 1004 | Complete |
| STYLE-02 | Phase 1004 | Complete |
| STYLE-03 | Phase 1004 | Complete |
| STYLE-04 | Phase 1004 | Complete |
| STYLE-05 | Phase 1004 | Complete |
| STYLE-06 | Phase 1004 | Complete |
| STYLE-07 | Phase 1004 | Complete |
| STYLE-08 | Phase 1004 | Complete |
| OUTPUT-01 | Phase 1005 | Complete |
| OUTPUT-02 | Phase 1005 | Complete |
| OUTPUT-03 | Phase 1005 | Complete |
| OUTPUT-04 | Phase 1005 | Complete |
| OUTPUT-05 | Phase 1005 | Complete |
| OUTPUT-06 | Phase 1005 | Complete |
| A11Y-01 | Phase 1006 | Complete |
| A11Y-02 | Phase 1006 | Complete |
| A11Y-03 | Phase 1006 | Complete |
| A11Y-04 | Phase 1006 | Complete |
| A11Y-05 | Phase 1006 | Complete |
| A11Y-06 | Phase 1006 | Complete |
| QA-01 | Phase 1007 | Pending |
| QA-02 | Phase 1007 | Pending |
| QA-03 | Phase 1007 | Pending |
| QA-04 | Phase 1007 | Pending |
| QA-05 | Phase 1007 | Pending |
| QA-06 | Phase 1007 | Pending |

**Coverage:**
- v1001 requirements: 38 total
- Mapped to phases: 38
- Unmapped: 0

---
*Requirements defined: 2026-05-11*
*Last updated: 2026-05-11 after Phase 1006 verification*
