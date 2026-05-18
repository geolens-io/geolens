---
phase: 1052
plan: 02
subsystem: builder
tags: [builder, dead-code-removal, basemap-sublayer, i18n, path-a-remove, emrg-fn-01]
dependency_graph:
  requires: [EMRG-FN-01-surface-deleted]
  provides: [EMRG-FN-01-i18n-cleaned]
  affects: []
tech_stack:
  added: []
  patterns: []
key_files:
  modified:
    - frontend/src/i18n/locales/en/builder.json
    - frontend/src/i18n/locales/de/builder.json
    - frontend/src/i18n/locales/es/builder.json
    - frontend/src/i18n/locales/fr/builder.json
decisions:
  - "No aria-label variants (strokeWidthLabel, casingWidthLabel) existed in any locale — confirmed by grep before removal"
  - "5 keys removed (not 7) — aria-label variants were never added to any locale file"
metrics:
  duration: "~8 minutes"
  completed: "2026-05-18T17:36:00Z"
  tasks_completed: 3
  files_changed: 4
---

# Phase 1052 Plan 02: EMRG-FN-01 Path A REMOVE — Orphan basemapSublayer i18n Keys

**One-liner:** Removed 5 orphan basemapSublayer i18n keys (strokeLabel, strokeColor, strokeWidth, casingColor, casingWidth) from all 4 locales after Plan 01 deleted their only consumers; parity 7/7 keys preserved; i18n check 2/2.

## What Shipped

Removed the 5 basemapSublayer keys that became orphans when Plan 01 deleted the STROKE section + zoom range inputs from `BasemapSublayerEditorScene.tsx`. All 4 locale files (en/de/es/fr) were edited identically — parity preserved at 7 surviving keys per locale.

### Per-Locale Key Count (Before / After)

| Locale | Before | After | Removed |
|--------|--------|-------|---------|
| en     | 12     | 7     | 5       |
| de     | 12     | 7     | 5       |
| es     | 12     | 7     | 5       |
| fr     | 12     | 7     | 5       |

### Exact Keys Removed (same in all 4 locales)

| Key | en value | de value | es value | fr value |
|-----|----------|----------|----------|----------|
| `basemapSublayer.casingColor` | "Casing color" | "Außenrahmenfarbe" | "Color de carcasa" | "Couleur de bordure externe" |
| `basemapSublayer.casingWidth` | "Casing width" | "Außenrahmenbreite" | "Ancho de carcasa" | "Largeur de bordure externe" |
| `basemapSublayer.strokeColor` | "Stroke color" | "Konturfarbe" | "Color de trazo" | "Couleur de contour" |
| `basemapSublayer.strokeLabel` | "STROKE" | "KONTUR" | "TRAZO" | "CONTOUR" |
| `basemapSublayer.strokeWidth` | "Stroke width" | "Konturbreite" | "Ancho de trazo" | "Largeur de contour" |

### Keys Preserved (live consumers)

| Key | Purpose |
|-----|---------|
| `basemapSublayer.breadcrumbLabel` | Back-nav label in BasemapSublayerEditorScene header |
| `basemapSublayer.footerBack` | Footer back button text |
| `basemapSublayer.resetConfirmAction` | Reset confirm dialog action button |
| `basemapSublayer.resetConfirmCancel` | Reset confirm dialog cancel button |
| `basemapSublayer.resetConfirmMessage` | Reset confirm dialog message body |
| `basemapSublayer.resetHint` | Reset section hint text |
| `basemapSublayer.resetLabel` | Reset section heading |

### Shared keys NOT touched

`layerEditor.visibility.minZoom`, `layerEditor.visibility.maxZoom`, `layerEditor.visibility.opacity` — used by regular layer editor for non-basemap layers; not in basemapSublayer namespace.

## Verification

- `git grep` for `basemapSublayer.strokeLabel|strokeColor|strokeWidth|casingColor|casingWidth` in `frontend/src/`: 0 hits (exit 1 — no matches)
- `python3 -c "import json; json.load(open('frontend/src/i18n/locales/{LOCALE}/builder.json'))"`: PARSE OK for all 4 locales
- `npm run test:i18n`: **2/2 PASS** (vitest 2/2, no untranslated keys, no key-count drift)
- `npx tsc --noEmit`: **0 errors**
- Per-locale parity: en == de == es == fr (same 7 keys post-removal)

### i18n parity check output

```
PASS src/i18n/resources.test.ts
  Test Files  1 passed (1)
        Tests  2 passed (2)
```

## Commit

| Hash | Subject | Files |
|------|---------|-------|
| `3e48d331` | `chore(1052): EMRG-FN-01 Path A REMOVE — orphan basemapSublayer i18n keys` | 4 locale files, +4/-24 |

## Deviations from Plan

### Deviation 1 — aria-label variants not present (scope reduction)

**Plan assumed:** `strokeWidthLabel` and `casingWidthLabel` might exist as aria-label variants per locale, making the potential removal set 7 keys.

**Actual:** grep confirmed neither variant existed in any of the 4 locale files before this plan ran. The JSX in Plan 01 used `t('basemapSublayer.strokeWidthLabel', { defaultValue: 'Stroke width' })` — the `defaultValue` fallback was in use, meaning the keys were never added to the locale JSON files. Removal set is exactly 5 keys per locale.

**Assessment:** Expected and benign — plan's "conditional removal set" language anticipated this case. Rule 1/2/3 do not apply. No correctness impact.

## Threat Surface Scan

No new endpoints, auth paths, file access patterns, or schema changes. Pure client-side dead-string removal.

## Self-Check: PASSED

- [x] `frontend/src/i18n/locales/en/builder.json` — 12 → 7 keys, parses cleanly
- [x] `frontend/src/i18n/locales/de/builder.json` — 12 → 7 keys, parses cleanly
- [x] `frontend/src/i18n/locales/es/builder.json` — 12 → 7 keys, parses cleanly
- [x] `frontend/src/i18n/locales/fr/builder.json` — 12 → 7 keys, parses cleanly
- [x] Commit `3e48d331` exists on main (4 files, +4/-24)
- [x] i18n parity check: 2/2 PASS
- [x] TypeScript: 0 errors
- [x] git grep for target keys: 0 hits
