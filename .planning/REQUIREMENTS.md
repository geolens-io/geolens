# Requirements: v1008 Map Builder Sidebar Redesign

**Defined:** 2026-05-13
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.

## Milestone Goal

Re-architect the Map Builder sidebar from six fixed sections (Surface / Relief / Basemap / Data / Labels / Interactions) into one unified, drag-orderable layer stack — with basemap-as-group, DEM-as-raster-layer, compact rows, and a side-by-side LayerEditorPanel flyout — while normalizing legacy saved maps and aligning the Add Data modal to the new model.

## Locked Context

- **Direction note:** `.planning/notes/map-builder-sidebar-redesign-direction.md`
- **Seed:** `.planning/seeds/map-builder-sidebar-redesign.md`
- **Sketch findings:** `.planning/sketches/WRAP-UP-SUMMARY.md` (skill `sketch-findings-geolens`)
- **Companion todo:** `.planning/todos/pending/audit-add-data-modal.md`
- **Reference commits:**
  - Revive: `1d3cdc9a` (LayerEditorPanel flyout), `aeac195c` (flyout z-index fix)
  - Retire: `383e1f55` (inline expansion regression), `6756149c` (six-section model), `fa5856ba` (inline basemap/terrain rows)
  - Compat fixtures: `d2c5c99c test(1000-02): lock saved map stack compatibility`

## Constraints

- Reuse the existing OKLCH design tokens in `frontend/src/index.css`; do not introduce new tokens.
- Preserve public, shared, and embed viewer fidelity — no viewer regressions.
- Do not redesign the Add Data modal in full; this milestone aligns it.
- Defer `/api/datasets/suggested` endpoint; ship hand-curated suggestions.
- Carry the existing mobile shell forward; no mobile-specific layout polish here.
- Existing renderer set (v1004–v1007) is preserved; no new renderAs modes introduced.
- Touch saved-map JSON shape only via a backward-compatible normalizer in the loader (no schema migration).

## v1008 Requirements

### Unified Stack & Row Anatomy

- [ ] **BSR-01**: User sees a single drag-orderable layer list — no Surface / Relief / Basemap / Data / Labels / Interactions sibling sections.
- [ ] **BSR-02**: User can reorder layers via the drag handle; z-order updates on the map immediately.
- [ ] **BSR-03**: Each row shows drag · visibility · type-icon · name · opacity · kebab — no inline-expanding controls and no duplicate subtitle/position-tag/type-chip clutter.
- [ ] **BSR-04**: Row kebab menu exposes rename, duplicate, delete, and grouping actions.

### Basemap Group & Folder Groups

- [ ] **BSR-05**: User sees the basemap as a collapsible group row (`⊞`) with sublayer expansion (roads / labels / buildings / boundaries / land–water).
- [ ] **BSR-06**: User can toggle basemap sublayer visibility from inside the expanded group.
- [ ] **BSR-07**: User-created folder groups use `▸`, share rename / add-layer / ungroup operations, and persist expansion state per map.

### DEM as Raster Layer

- [ ] **BSR-08**: User adds a DEM as a regular raster layer carrying a `render as: image | hillshade | terrain` property; no separate Relief or Surface section exists.
- [ ] **BSR-09**: User switches a DEM render mode without losing source binding or paint config; terrain mode wires the map-level terrain config without resurrecting a Relief section.

### Layer Editor Flyout

- [ ] **BSR-10**: Clicking a row highlights it and opens a 380px side-by-side LayerEditorPanel flyout between the sidebar (340px) and the map.
- [ ] **BSR-11**: Flyout includes Render-as pill strip, Appearance (paint), Visibility (opacity + zoom range), Filter / Labels / Source (collapsed), and Delete in footer.
- [ ] **BSR-12**: Cross-layer comparison stays available because the sidebar remains mounted while the flyout is open.
- [ ] **BSR-13**: At narrow viewports the flyout falls back to a rail or drill-down variant without loss of capability.

### Settings Affordance

- [ ] **BSR-14**: User opens a `⚙ Settings` affordance for terrain global config, map widgets, and projection.
- [ ] **BSR-15**: Settings panel removes those controls from the sidebar layer stack entirely; no permanent settings fixtures in the stack.

### Empty State & Add Data Alignment

- [ ] **BSR-16**: User on a new map sees an empty-state catalog entry experience with inline search and suggested datasets — not a generic "Add data" prompt.
- [ ] **BSR-17**: Inline empty-state search routes into the same Add Data modal as `+ Add data`, with the query pre-filled.
- [ ] **BSR-18**: Add Data modal audit findings (raster discovery, post-add z-position, flyout opens on add, catalog parity, empty/zero-result UX) are resolved; the modal aligns with the unified stack model.
- [ ] **BSR-19**: Hand-curated suggested datasets ship for v1; `/api/datasets/suggested` endpoint is explicitly deferred and tracked.

### Saved-Map Compatibility

- [ ] **BSR-20**: User opens a legacy six-section saved map and sees it rendered correctly under the unified stack.
- [ ] **BSR-21**: Saved-map loader normalizes legacy `{ surface, relief, basemap, data, labels, interactions }` shape into a flat layer array + group metadata, without schema migration.
- [ ] **BSR-22**: Public, shared, and embed viewers render normalized maps identically to the builder.
- [ ] **BSR-23**: New maps saved under the unified stack round-trip through save → reload → public/shared/embed without loss; `d2c5c99c` compat fixtures pass against the normalized loader.

### Closeout

- [ ] **BSR-24**: Sketch fidelity holds — implementation matches the `sketch-findings-geolens` skill (palette, row anatomy, group semantics, flyout layout).
- [ ] **BSR-25**: Accessibility — keyboard navigation through stack, flyout sections, and settings panel; focus management on row-select + flyout-open + flyout-close.
- [ ] **BSR-26**: i18n keys for new copy added; existing keys reused where possible; changed-namespace check passes.
- [ ] **BSR-27**: Playwright MCP UAT proves drag-reorder, basemap-group-expand, DEM render-mode switch, flyout open/close, settings panel, empty-state entry, Add Data modal pre-fill, legacy-map open, and save/reload round-trip — with zero console warnings/errors.

## Future Requirements (deferred)

- Smart `/api/datasets/suggested` backend endpoint (ranked by org-usage + recency, starter set gated by `is_first_map(user)`).
- Drag-from-catalog-into-stack.
- Multi-layer selection / bulk operations.
- Mobile-specific layout polish for sidebar + flyout.
- Full Add Data modal redesign beyond alignment.

## Out of Scope

- Map widgets configuration UI rework (settings affordance covers entry point only).
- New renderer types or renderAs modes (v1004–v1007 set preserved).
- Schema migrations beyond the saved-map loader normalizer.
- Re-architecting the catalog page or `/collections`.

## Traceability

| Requirement | Phase | Status |
|---|---|---|
| BSR-01..27 | _to be assigned by roadmapper_ | Pending |

**Coverage:**
- v1008 requirements: 27 total
- Complete: 0
- Pending: 27
- Mapped to phases: 0
- Unmapped: 27

---
*Requirements defined: 2026-05-13*
