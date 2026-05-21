---
quick_id: 260515-cej
slug: docker-rebuild-builder-smoke
date: 2026-05-15
type: smoke-check
---

# Docker Rebuild + Map Builder Smoke Check

## Objective
1. Complete rebuild of all Docker containers (no cache, fresh images, healthy state).
2. Comprehensive Playwright-driven smoke check of the Map Builder.
3. Catalog every design gap, console error, broken/regressed functionality.
4. Deliver `FINDINGS.md` with severity-tagged findings + repro notes.

## Scope — Map Builder surfaces under test
- Builder entry points: `/maps/new`, `/maps/:id`, "Open in builder" from catalog/record detail
- Unified layer stack (v1008/v1009): drag-orderable, basemap row, DEM-as-raster-layer
- Catalog drawer → add layer → stack DnD (cross-context DndContext lift, v1009)
- LayerEditorPanel flyout (380px) — open, edit style, close
- Group rows, group-children wash, group expand/collapse
- Multi-select + BulkActionBar (Promise.allSettled delete/rollback)
- Empty state (catalog-first), freshLayerId entry animation, insertion-line bloom
- Recoverable error banners
- Scene transition scroll/focus preservation
- Settings (⚙) affordance per row
- Basemap switching
- Save / autosave / share entry points (light touch)

## Quality gates
- Console: zero errors expected from app code (third-party/maplibre debug ok). Warnings noted.
- Network: zero non-2xx from `/api/*` during happy-path actions. 304/abort acceptable.
- Visual: surface design-system token regressions, layout breakage, contrast gaps, missing affordances.
- Functional: any user action that produces no visible/data effect = bug.

## Out of scope (light-touch only)
- Deep i18n key audit
- Multi-user / permissions matrix
- Mobile / responsive breakpoints (note if obvious break)
- Backend correctness of saved-map persistence (note crashes only)

## Deliverable
- `FINDINGS.md` — severity-tagged (BLOCKER / MAJOR / MINOR / POLISH) findings with repro
- `SUMMARY.md` — quick-task close-out
