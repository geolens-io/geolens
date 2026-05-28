---
phase: 1141-fill-pattern-editor-control
plan: "01"
subsystem: frontend/builder
tags: [fill-pattern, editor, maplibre, i18n, tdd]
dependency_graph:
  requires: []
  provides:
    - fill-pattern-images catalog + registrar (ensureFillPatternImages)
    - FillPatternPicker UI component
    - FillEditor Fill Pattern section (EDITOR-FILL-01)
  affects:
    - frontend/src/components/builder/LayerStyleEditor/FillEditor.tsx
    - frontend/src/components/builder/layer-adapters/fill-adapter.ts
tech_stack:
  added: []
  patterns:
    - procedural ImageData generation (Uint8ClampedArray, TILE x TILE)
    - idempotent map image registrar (mirrors ensureArrowImage)
    - IconPicker-style swatch grid with selection ring
    - CSS repeating-linear-gradient / radial-gradient for pattern previews
key_files:
  created:
    - frontend/src/components/builder/layer-adapters/fill-pattern-images.ts
    - frontend/src/components/builder/FillPatternPicker.tsx
    - frontend/src/components/builder/layer-adapters/__tests__/fill-pattern-images.test.ts
    - frontend/src/components/builder/__tests__/FillPatternPicker.test.tsx
  modified:
    - frontend/src/components/builder/layer-adapters/fill-adapter.ts
    - frontend/src/components/builder/LayerStyleEditor/FillEditor.tsx
    - frontend/src/components/builder/LayerStyleEditor/__tests__/FillEditor.test.tsx
    - frontend/src/components/builder/__tests__/layer-adapters.test.ts
    - frontend/src/i18n/locales/en/builder.json
    - frontend/src/i18n/locales/de/builder.json
    - frontend/src/i18n/locales/es/builder.json
    - frontend/src/i18n/locales/fr/builder.json
decisions:
  - "Built-in curated patterns only (hatch, crosshatch, diagonal, dots, grid) via procedural Uint8ClampedArray generation — no user upload, no network fetch, no sprite-serving backend"
  - "Pattern images registered NOT as SDF (full-color tiles vs. the arrow image which is SDF)"
  - "FillPatternPicker gated on isPolygon AND fillEnabled inside the fillEnabled block — consistent with fill group scope"
  - "Pattern previews use CSS repeating-linear-gradient/radial-gradient inline styles — no asset fetch required"
metrics:
  duration_seconds: 347
  completed_date: "2026-05-28"
  tasks_completed: 3
  files_changed: 10
---

# Phase 1141 Plan 01: Fill-Pattern Editor Control Summary

Built-in fill-pattern authoring control for FillEditor — curated 5-pattern sprite catalog, idempotent map registrar, IconPicker-style swatch picker, and FillEditor integration with 4-locale i18n.

## What Was Built

### Task 1: fill-pattern image catalog + idempotent registrar (GREEN: `3e71802d`)

New `fill-pattern-images.ts`:
- `FILL_PATTERN_IDS`: 5 namespaced ids (`geolens-fill-hatch`, `geolens-fill-crosshatch`, `geolens-fill-diagonal`, `geolens-fill-dots`, `geolens-fill-grid`)
- `makeFillPatternImage(id)`: procedural 16×16 Uint8ClampedArray generator per pattern id — tileable, no external assets
- `ensureFillPatternImages(map)`: mirrors `ensureArrowImage` exactly minus `sdf:true`; iterates FILL_PATTERN_IDS, skips hasImage-truthy ids, wraps in try/catch with DEV-only console.warn

`fill-adapter.ts` wired: `ensureFillPatternImages(map)` called at the top of `addLayers` and `syncPaint`. `FILL_OWNED_PAINT_PROPERTIES` unchanged (already contained `fill-pattern`).

### Task 2: FillPatternPicker component + i18n (GREEN: `c94e5b36`)

New `FillPatternPicker.tsx`:
- Props: `value: string | undefined`, `onChange: (id: string | undefined) => void`, `t`
- `grid grid-cols-5 gap-1` swatch layout mirroring IconPicker; `h-8 w-8` buttons; `border-primary ring-1 ring-primary` selection ring exactly as IconPicker
- None swatch first, then one per FILL_PATTERN_IDS; CSS inline pattern previews (no asset fetch)
- `aria-label`, `title`, `aria-pressed` on each swatch

i18n keys added to en/de/es/fr builder.json under `style`:
- `style.fillPattern`, `style.fillPatternNone`, `style.fillPatternName.{hatch,crosshatch,diagonal,dots,grid}`
- `style.pattern` (LineEditor) untouched in all locales

### Task 3: Mount FillPatternPicker in FillEditor (GREEN: `58e7b2f2`)

`FillEditor.tsx` edited:
- Import `FillPatternPicker` from `../FillPatternPicker`
- Inside the `{fillEnabled && ...}` block, after the opacity SliderRow, gated on `isPolygon`:
  `<FillPatternPicker value={paint['fill-pattern'] as string | undefined} onChange={(id) => onPaintProp('fill-pattern', id)} t={t} />`
- No change to `BaseStyleEditorProps`; reuses `paint`, `onPaintProp`, `t`, `isPolygon` already destructured

## Test Coverage

| File | Tests |
|------|-------|
| `fill-pattern-images.test.ts` | 13 (FILL_PATTERN_IDS catalog, generator correctness, ensureFillPatternImages idempotency) |
| `layer-adapters.test.ts` (extended) | +7 (addLayers/syncPaint invoke registrar; idempotency gate; regression pin no-pattern = no fill-pattern key; syncPaint set+clear path) |
| `FillPatternPicker.test.tsx` | 8 (count, active ring, onClick set/clear, aria-label resolution, section label) |
| `FillEditor.test.tsx` (extended) | +6 (renders section when isPolygon+fillEnabled; set/clear onPaintProp; not rendered when isPolygon=false or fillEnabled=false; behavior preservation) |
| `resources.test.ts` | passes (4-locale parity) |

Total: 148/148 tests pass; `tsc -b --noEmit` clean.

## Deviations from Plan

None — plan executed exactly as written.

## Commits

| Task | Commit | Message |
|------|--------|---------|
| T1 RED | `d1c353e2` | test(1141-01): add failing tests for fill-pattern-images catalog and registrar (RED) |
| T1 GREEN | `3e71802d` | feat(1141-01): add fill-pattern image catalog + registrar, wire into fill adapter (GREEN) |
| T2 RED | `5943797f` | test(1141-01): add failing tests for FillPatternPicker component (RED) |
| T2 GREEN | `c94e5b36` | feat(1141-01): add FillPatternPicker component + 4-locale i18n keys (GREEN) |
| T3 RED | `2b64c212` | test(1141-01): extend FillEditor tests with FillPatternPicker integration cases (RED) |
| T3 GREEN | `58e7b2f2` | feat(1141-01): mount FillPatternPicker in FillEditor, wired to fill-pattern paint (GREEN) |

## Known Stubs

None — all pattern generation is fully implemented; fill-pattern writes the real MapLibre property.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or schema changes introduced. All patterns are built-in (code-defined allowlist); no user-supplied image path.

## Self-Check: PASSED

- fill-pattern-images.ts: FOUND
- FillPatternPicker.tsx: FOUND
- fill-pattern-images.test.ts: FOUND
- FillPatternPicker.test.tsx: FOUND
- All 6 task commits verified in git log
- 148/148 tests pass; tsc -b --noEmit clean
