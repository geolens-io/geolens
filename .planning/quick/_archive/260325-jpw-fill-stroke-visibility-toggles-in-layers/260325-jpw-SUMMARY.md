---
phase: quick-260325-jpw
plan: 01
subsystem: ui
tags: [react, maplibre, switch, toggle, i18n]

requires:
  - phase: quick-260325-ff5
    provides: "_outline-* custom paint prop pattern and CUSTOM_PAINT_PROPS set"
provides:
  - "Fill/stroke visibility toggles with saved-value persistence in LayerStyleEditor"
  - "4 new custom paint prop metadata keys for toggle state"
  - "10 new unit tests for toggle behavior"
affects: [builder, map-sync]

tech-stack:
  added: []
  patterns:
    - "Toggle metadata via underscore-prefixed custom paint props (_fill-disabled, _stroke-disabled, _fill-opacity-saved, _outline-width-saved)"
    - "CUSTOM_PAINT_PROPS set-based filtering replaces hardcoded destructuring for extensibility"

key-files:
  modified:
    - frontend/src/components/builder/map-sync.ts
    - frontend/src/components/builder/LayerStyleEditor.tsx
    - frontend/src/components/builder/__tests__/LayerStyleEditor.test.tsx
    - frontend/src/i18n/locales/en/builder.json
    - frontend/src/i18n/locales/fr/builder.json
    - frontend/src/i18n/locales/es/builder.json
    - frontend/src/i18n/locales/de/builder.json

key-decisions:
  - "Use CUSTOM_PAINT_PROPS set for generic filtering instead of hardcoded destructuring in syncLayersToMap fill branch"

requirements-completed: [TOGGLE-FILL, TOGGLE-STROKE, TOGGLE-I18N, TOGGLE-TESTS]

duration: 4min
completed: 2026-03-25
---

# Quick Task 260325-jpw: Fill/Stroke Visibility Toggles Summary

**Fill/stroke toggle switches in LayerStyleEditor with saved-value persistence via custom paint props, per-geometry-type behavior, and 10 new unit tests**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-25T18:16:31Z
- **Completed:** 2026-03-25T18:20:19Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments
- Polygon layers show fill + stroke toggle switches; toggling OFF saves current value and collapses controls
- Circle layers show stroke toggle only (no fill toggle); uses circle-stroke-width
- Line layers unaffected -- no toggles rendered
- CUSTOM_PAINT_PROPS expanded to 6 keys; map-sync fill branch uses set-based filtering instead of hardcoded destructuring
- i18n aria-labels (toggleFill, toggleStroke) added to all 4 locales (en, fr, es, de)
- 10 new unit tests alongside 5 existing, all 15 passing

## Task Commits

1. **Task 1: Add custom paint props and i18n keys** - `c37cc86a` (feat)
2. **Task 2 RED: Failing tests for toggle behavior** - `6980cd10` (test)
3. **Task 2 GREEN: Implement fill/stroke toggles** - `556a0575` (feat)

## Files Created/Modified
- `frontend/src/components/builder/map-sync.ts` - Expanded CUSTOM_PAINT_PROPS to 6 keys, replaced hardcoded destructuring with set-based filtering
- `frontend/src/components/builder/LayerStyleEditor.tsx` - Added Switch import, toggle state derivation, handleToggleFill/handleToggleStroke handlers, conditional rendering
- `frontend/src/components/builder/__tests__/LayerStyleEditor.test.tsx` - 10 new tests for toggle rendering, paint prop changes, and control collapse
- `frontend/src/i18n/locales/en/builder.json` - toggleFill, toggleStroke keys
- `frontend/src/i18n/locales/fr/builder.json` - toggleFill, toggleStroke keys
- `frontend/src/i18n/locales/es/builder.json` - toggleFill, toggleStroke keys
- `frontend/src/i18n/locales/de/builder.json` - toggleFill, toggleStroke keys

## Decisions Made
- Replaced hardcoded `const { '_outline-width': _ow, '_outline-color': _foc, ...fillPaint } = basePaint` destructuring with generic `CUSTOM_PAINT_PROPS.has(k)` loop for extensibility (Rule 2 auto-fix)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Generic CUSTOM_PAINT_PROPS filtering in syncLayersToMap fill branch**
- **Found during:** Task 1 (expanding CUSTOM_PAINT_PROPS)
- **Issue:** Fill branch used hardcoded destructuring for only 2 props; new 4 props would leak to MapLibre as invalid paint properties
- **Fix:** Replaced destructuring with for-of loop checking CUSTOM_PAINT_PROPS set; also replaced hardcoded expression filter check
- **Files modified:** frontend/src/components/builder/map-sync.ts
- **Verification:** TypeScript compiles cleanly, existing tests pass
- **Committed in:** c37cc86a (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 missing critical)
**Impact on plan:** Essential fix to prevent invalid MapLibre paint properties. No scope creep.

## Issues Encountered
None

## Known Stubs
None

## Next Phase Readiness
- Toggle infrastructure complete and extensible via CUSTOM_PAINT_PROPS set
- Future custom paint metadata keys only need adding to the set

---
## Self-Check: PASSED

All 7 modified files exist. All 3 commit hashes verified.

---
*Phase: quick-260325-jpw*
*Completed: 2026-03-25*
