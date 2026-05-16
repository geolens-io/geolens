---
title: Audit Add Data modal against unified-stack sidebar redesign
date: 2026-05-13
priority: medium
context: spawned from /gsd-explore map builder sidebar redesign
resolves_phase: 1048
---

# Audit Add Data modal against unified-stack sidebar redesign

The map builder sidebar is being redesigned around a single unified stack
where basemap is a group and DEM is a raster layer with a render mode
(see `.planning/notes/map-builder-sidebar-redesign-direction.md`).

The user said the existing Add Data modal "kind of works" but should be
revisited to make sure it aligns with the new vision. **Don't redesign
the modal yet — audit it first.**

## What to inspect

- `frontend/src/components/builder/DatasetSearchPanel.tsx` (likely the
  current modal/panel)
- Phase 1012 commit `b5905850 feat(1012): redesign add dataset modal` — last redesign

## Questions the audit should answer

1. **Does it support adding non-vector layers?** Once DEMs are first-class
   raster layers in the stack (not buried in a "Relief" section), the
   modal needs to make raster discovery as easy as vector.
2. **Does it support adding URL-based layers** (XYZ, WMS, COG) or only
   catalog datasets? Catalog-only is fine for v1 but should be a conscious
   decision.
3. **What happens after add?** Does the new layer land at a sensible
   z-position in the unified stack? Does the LayerEditorPanel flyout open
   automatically so the user can immediately style it?
4. **Catalog parity with `/collections`** — does the modal duplicate
   the search UX from the standalone catalog page, or share components?
   Sharing reduces drift.
5. **Empty-state and zero-result UX** — adequate, or needs work?

## Out of scope for this todo

- Redesigning the modal layout
- Drag-from-modal-into-stack (deferred — sidebar redesign should ship
  without it first)
- Multi-select / bulk add

## Trigger

Pick up once the sidebar redesign phase has been planned (`/gsd-discuss-phase`
output exists). The audit findings should feed the phase plan, not block
exploration.
