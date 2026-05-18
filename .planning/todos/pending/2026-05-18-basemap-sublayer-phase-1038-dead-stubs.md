---
created: 2026-05-18T22:30:00Z
title: Basemap sublayer editor — Phase 1038 dead-wired callbacks (stroke/casing/zoom)
area: frontend / map-builder
source: v1011 Phase 1051 Plan 12 (EMRG-01) — EMRG-FN-01
related:
  - v1011 Phase 1051 Plan 11 (INV-01) — DETAIL LEVEL removed via REMOVE disposition at commit 6078b82a
files:
  - frontend/src/pages/MapBuilderPage.tsx
  - frontend/src/components/builder/BasemapSublayerEditorScene.tsx
  - frontend/src/components/builder/__tests__/BasemapSublayerEditorScene.test.tsx
  - frontend/src/i18n/locales/en/builder.json
  - frontend/src/i18n/locales/de/builder.json
  - frontend/src/i18n/locales/es/builder.json
  - frontend/src/i18n/locales/fr/builder.json
---

## Problem

`BasemapSublayerEditorScene` has 5 sibling no-op callbacks at `MapBuilderPage.tsx:845-850` that all bear the identical `TODO(Phase 1038): markDirty() once sublayer styling is persisted` comment:

- `onStrokeColorChange`
- `onStrokeWidthChange`
- `onCasingColorChange`
- `onCasingWidthChange`
- `onZoomChange`

Each is wired into a live UI control in the BasemapSublayerEditorScene flyout (stroke color picker, stroke width slider, casing color picker, casing width slider, min/max zoom inputs). Each click/drag fires the callback, which then does nothing — no state mutation, no MapLibre style update, no dirty flag.

This is the same shape as the DETAIL LEVEL toggle removed in v1011 Phase 1051 Plan 11 (INV-01 → REMOVE disposition, commit `6078b82a`). Plan 11's `<action>` directive explicitly scoped INV-01 to DETAIL LEVEL only and flagged these 5 siblings for follow-up via EMRG-01 (Plan 12).

Plan 12 triaged the 5 callbacks as **EMRG-FN-01** with severity **P2** and disposition **defer** — see `.planning/phases/1051-map-builder-polish-bug-sweep/FINDINGS.md` § EMRG-FN-01.

## Solution

Two paths, decision deferred to a future planning cycle:

**Path A — REMOVE (mirror INV-01 precedent):**
1. Delete the 5 callback props from `MapBuilderPage.tsx:845-850`.
2. Delete matching props from `BasemapSublayerEditorScene` interface + signature destructure.
3. Delete the STROKE / CASING / ZOOM `<section>` JSX blocks (the entire scene becomes effectively empty after this — consider also removing `BasemapSublayerEditorFooter` and the `editorScene === 'basemap-sublayer'` branch in `MapBuilderPage.tsx:828-872`).
4. Delete matching i18n keys from `builder.json` × 4 locales.
5. Delete vitest cases referencing the removed surfaces from `BasemapSublayerEditorScene.test.tsx`.
6. Add a REMOVE-disposition regression test mirroring INV-01 Test 13.
7. Add an inline disposition comment per the pattern established in INV-01.

**Path B — FIX (implement Phase 1038):**
1. Persist `stroke_color` / `stroke_width` / `casing_color` / `casing_width` / `min_zoom` / `max_zoom` per sublayer in `MapBasemapConfig.sublayer_overrides[sublayerId]` (jsonb-additive per Phase 1051 Plan 06 pattern).
2. Wire each callback to update the corresponding field via `setBasemapConfig` (auto-marks dirty via WR-02 fix in `use-builder-layers.ts`).
3. Plumb each field through `applyBasemapConfigToMap` in `map-sync.ts:222` so MapLibre style mutations actually reflect user changes.
4. Implement the per-field MapLibre dispatch (likely 3-5 days across multiple basemap presets — sublayer style filtering varies per preset).

## Recommendation

**REMOVE (Path A) is the clean choice for a hygiene close** unless a user-facing product priority emerges that justifies the FIX work. The entire BasemapSublayerEditorScene is dead stubs after DETAIL LEVEL was removed — keeping the rest of the scene live in the UI is actively misleading to users who expect the controls to mutate the basemap.

**Estimated REMOVE effort:** 1 plan, similar shape to Plan 11 (INV-01) — ~10 min executor work + orchestrator MCP re-verify.

**Estimated FIX effort:** Phase-scoped (3-5 days, multi-plan).

## Defer Rationale

DEFER from v1011 Plan 12 (EMRG-01) per `<lesson_from_phase>`: "Default to deferring large items to follow-up phases rather than expanding scope mid-phase." 5-callback removal is the same shape as a full INV-style plan and would expand Plan 12 scope (originally a single-file FINDINGS.md authoring plan) into a code+test+i18n removal sweep. The dead wiring has shipped since v1008 — it is not a regression, it is unfinished work.

## Acceptance

When this todo is actioned:

- Either the 5 callbacks + their wired UI controls are removed (Path A) and a regression-pin test asserts they stay gone, OR
- The 5 callbacks each fire a real state mutation that round-trips through save/reload (Path B) verified via Playwright MCP.
- This file moves to `.planning/todos/done/` with frontmatter `status: closed, shipped_in: vXXXX`.
