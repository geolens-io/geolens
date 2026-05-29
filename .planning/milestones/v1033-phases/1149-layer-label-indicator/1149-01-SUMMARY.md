---
phase: "1149"
plan: "01"
subsystem: "builder"
tags: ["label-indicator", "ux", "a11y", "i18n", "tdd"]
dependency_graph:
  requires: []
  provides: ["label-indicator-in-stack-row"]
  affects: ["frontend/src/components/builder/StackRow.tsx"]
tech_stack:
  added: []
  patterns: ["derived-indicator (mirrors map-sync gate)", "shrink-0 glyph in flex name cell"]
key_files:
  created:
    - frontend/src/components/builder/__tests__/StackRow.test.tsx (label indicator describe block appended)
  modified:
    - frontend/src/components/builder/StackRow.tsx
    - frontend/src/i18n/locales/en/builder.json
    - frontend/src/i18n/locales/de/builder.json
    - frontend/src/i18n/locales/es/builder.json
    - frontend/src/i18n/locales/fr/builder.json
decisions:
  - "Predicate: !!label_config?.column && renderMode !== 'heatmap' && renderMode !== 'symbol' — exact mirror of map-sync.ts:795"
  - "Placement: inside name cell as flex sibling to truncated name span, using shrink-0"
  - "Visual: Type lucide icon (already used in SublayerConfigIndicators), text-muted-foreground, h-3.5 w-3.5 badge"
  - "A11y: title attribute + sr-only span both carrying interpolated i18n string"
metrics:
  duration: "~10 minutes"
  completed: "2026-05-28"
  tasks_completed: 2
  files_changed: 6
---

# Phase 1149 Plan 01: Layer Label Indicator Summary

**One-liner:** `Type` glyph badge inside StackRow name cell, gated on `label_config.column` with heatmap/symbol suppression, mirroring map-sync.ts:795.

## Tasks Completed

### Task 1: Add label indicator to StackRow + i18n keys (TDD RED → GREEN)

**RED commit:** `deaf1933` — 4 failing RTL tests in new `describe('label indicator')` block:
- `labeled-layer-shows-indicator`
- `unlabeled-layer-hides-indicator`
- `heatmap-suppression`
- `symbol-suppression`

**GREEN commit:** `c3b032d7` — implementation:
- Added `Type` to lucide-react import in `StackRow.tsx`
- Derived `hasLabels` boolean from `label_config?.column` + render_mode gate (before return)
- Wrapped non-editing name content in `div.min-w-0.flex.items-center.gap-1` (preserves truncation via `min-w-0` + `truncate` on name span; `block` removed since flex handles block behavior)
- Rendered `shrink-0` indicator span with `data-testid="label-indicator"`, `title` + `sr-only` using `t('stackRow.labelsIndicator', { column })`
- Added `stackRow.labelsIndicator` as last key in `stackRow` object in all four locale files

**Files changed:**
- `frontend/src/components/builder/StackRow.tsx` — +14 lines (import, hasLabels derivation, indicator JSX)
- `frontend/src/components/builder/__tests__/StackRow.test.tsx` — +54 lines (4 new test cases)
- `frontend/src/i18n/locales/en/builder.json` — +1 key
- `frontend/src/i18n/locales/de/builder.json` — +1 key
- `frontend/src/i18n/locales/es/builder.json` — +1 key
- `frontend/src/i18n/locales/fr/builder.json` — +1 key

### Task 2: Verify i18n parity + full test suite green

All verification commands run and captured below.

## Verification Outputs (Real)

### 1. StackRow unit tests (vitest)

```
Tests  31 passed (31)
Start at  21:03:11
Duration  1.34s
```

All 31 tests pass: 27 pre-existing + 4 new label indicator tests.
New tests:
- ✓ label indicator > labeled-layer-shows-indicator: shows data-testid="label-indicator" with sr-only text when label_config.column is set
- ✓ label indicator > unlabeled-layer-hides-indicator: shows no data-testid="label-indicator" when label_config is null
- ✓ label indicator > heatmap-suppression: shows no indicator when label_config.column is set but render_mode is heatmap
- ✓ label indicator > symbol-suppression: shows no indicator when label_config.column is set but render_mode is symbol

### 2. i18n parity test

```
npm run test:i18n
Tests  2 passed (2)
```

Exit 0. All four locale builder.json files have structural parity including the new key.

### 3. Broader builder test suite

```
npx vitest run StackRow.test.tsx SublayerConfigIndicators.test.tsx UnifiedStackPanel.test.tsx
Test Files  3 passed (3)
Tests  73 passed (73)
```

Zero regressions.

### 4. TypeScript typecheck

```
npm run typecheck
(exit 0, no output)
```

No type errors.

### 5. grep spot-check

```
grep -c "labelsIndicator" en/builder.json de/builder.json es/builder.json fr/builder.json
en: 1
de: 1
es: 1
fr: 1
```

Each locale file contains exactly one occurrence.

## Deviations from Plan

None — plan executed exactly as written.

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced. `label_config.column` is already visible in the label editor UI; displaying it in a `title` attribute is T-1149-01 (accepted per threat model).

## Self-Check: PASSED

- StackRow.tsx: FOUND
- StackRow.test.tsx: FOUND
- en/builder.json: FOUND
- commit deaf1933 (RED): FOUND
- commit c3b032d7 (GREEN): FOUND
