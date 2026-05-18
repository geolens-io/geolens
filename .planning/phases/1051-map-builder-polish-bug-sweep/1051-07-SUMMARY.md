---
phase: 1051-map-builder-polish-bug-sweep
plan: 07
subsystem: ui
tags: [builder, ux, settings, widgets, a11y, i18n, label-clarity]

requires:
  - phase: 1008-map-builder-sidebar-redesign
    provides: SettingsEditorScene + WIDGETS Collapsible + shadcn Switch row scaffolding
  - phase: 1010-builder-performance-code-quality
    provides: stable settings.* i18n namespace + 4-locale parity invariant (770-key baseline)

provides:
  - State-specific Switch aria-label ("Enable {{name}}" / "Disable {{name}}") replacing the composite "{{action}} {{name}} widget" pattern
  - Availability-clarifying descriptive note ("Controls whether each widget appears on the map.") above the widget rows
  - 3 new i18n keys × 4 locales: settings.enableWidget, settings.disableWidget, settings.widgetsAvailabilityNote (12 entries total)
  - Regression suite SettingsEditorScene.widgets.test.tsx (5 tests) covering the new label pattern, callback dispatch, note rendering, and no-duplicate-Switch invariant
  - Documented audit outcome: NO duplicate widget control surfaces exist; MapToolbar's Measure/Legend buttons are live-interaction tools (not availability toggles)

affects: [builder, settings-scene, screen-readers, i18n-en-de-es-fr]

tech-stack:
  added: []
  patterns:
    - "State-specific aria-label keys (Enable/Disable {name}) replacing composite {action} {name} template — better screen-reader semantics + simpler per-locale grammar handling"
    - "Section-level descriptive note paragraph (text-[11px] text-muted-foreground) above grouped form rows — disambiguates section purpose without enlarging row chrome"
    - "Reuse of existing onToggleWidget → activeWidgets Set mutation pipeline (no store API change)"

key-files:
  created:
    - frontend/src/components/builder/__tests__/SettingsEditorScene.widgets.test.tsx
  modified:
    - frontend/src/components/builder/SettingsEditorScene.tsx (Switch aria-label switched to settings.enableWidget/disableWidget; availability-note paragraph added inside CollapsibleContent above the widget rows)
    - frontend/src/components/builder/__tests__/SettingsEditorScene.test.tsx (existing tests 5+6 updated to assert the new "Enable {name}" / "Disable {name}" labels — Rule 1 regression fix from the deliberate label change)
    - frontend/src/i18n/locales/en/builder.json (3 new settings.* keys)
    - frontend/src/i18n/locales/de/builder.json (parity — German translations: "{name} aktivieren" / "{name} deaktivieren" / "Steuert, ob jedes Widget auf der Karte erscheint.")
    - frontend/src/i18n/locales/es/builder.json (parity — Spanish translations: "Activar {name}" / "Desactivar {name}" / "Controla si cada widget aparece en el mapa.")
    - frontend/src/i18n/locales/fr/builder.json (parity — French translations: "Activer {name}" / "Désactiver {name}" / "Détermine si chaque widget apparaît sur la carte.")

key-decisions:
  - "MapToolbar's Measure/Legend toggle buttons are NOT a duplicate of the Settings availability switch — they remain as the on-map live-interaction surface (per the plan's success criterion: 'On-map controls for enabled widgets remain functional'). The Settings Switch is the single source of truth for activeWidgets membership; MapToolbar consumes that state and provides ergonomic top-of-canvas access for the active tool. No duplicate to remove."
  - "Keep the existing settings.toggleWidget composite key in all 4 locales — currently unused after this change, but retained to avoid an unrelated i18n removal in a polish plan. Future cleanup is tracked as deferred."
  - "Availability note placed inside CollapsibleContent (not below the section header) so it stays visually grouped with the rows and only renders when the section is expanded — avoids cluttering the collapsed-section eyebrow."
  - "State-specific aria-label keys (Enable/Disable {name}) over the composite {action} {name} pattern because (a) screen readers announce them as a single phrase without an interpolated 'verb noun widget' construction, (b) per-locale word-order grammar (e.g., German 'Widget X deaktivieren' vs English 'Disable X widget') can be expressed naturally in each locale, (c) the word 'widget' is implementation jargon — the readable label is the widget's display name."

patterns-established:
  - "Pattern A (state-specific i18n keys for binary actions): prefer two keys (enableX / disableX) with {{name}} interpolation over a composite {action} {{name}} template. Each locale can word-order naturally. Applies to any future toggle row with availability semantics."
  - "Pattern B (section-purpose note): for grouped form sections whose name alone is ambiguous (WIDGETS could mean 'on-map controls' vs 'availability'), place a text-[11px] text-muted-foreground note inside the CollapsibleContent body above the rows. 11px to stay subordinate to the 12px row labels."
  - "Pattern C (duplicate-controls audit before refactor): when a plan says 'remove duplicate controls,' inventory all consumers of the same store action (here: useWidgetStore.toggle). The audit found exactly one Settings consumer (single source of truth) and one MapToolbar consumer (live interaction). They are functionally distinct, not duplicates."

deferred:
  - "settings.toggleWidget key now unused in code. Removing it is out of scope for this polish plan; leave for a future i18n-cleanup sweep."

metrics:
  duration: "~25 minutes (sequential agent)"
  tasks_completed: "2 of 3 (Task 1 + Task 3 are checkpoint:orchestrator — Playwright MCP verification deferred to orchestrator per lesson_from_phase: 'Live MCP is orchestrator-scoped')"
  completed_date: "2026-05-18"
  files_created: 1
  files_modified: 6
  commits: 1
  lines_added: 221
  lines_removed: 31
  test_files_touched: 2
  vitest_tests_added: 5
  vitest_total_after: 15  # 5 new + 10 existing in the two settings scene test files
  i18n_keys_added: 12  # 3 keys × 4 locales
  i18n_parity: "4/4 (en/de/es/fr each have settings.enableWidget + settings.disableWidget + settings.widgetsAvailabilityNote)"
  typecheck: "0 errors"
  duplicate_widget_controls_removed: 0  # audit found none

---

# Phase 1051 Plan 07: UX-04 Map Settings Widgets Section Now Toggles Availability Summary

One-liner: Settings → Widgets Switch labels now read "Enable {name}" / "Disable {name}" with an availability note clarifying that the section controls whether widgets appear on the map (distinct from MapToolbar's live-interaction Measure/Legend buttons).

## What Changed

### `SettingsEditorScene.tsx` (lines 166-203, Widgets CollapsibleContent body)

**Before:** The Switch used a composite `settings.toggleWidget` key — `t('settings.toggleWidget', { action: isEnabled ? 'Disable' : 'Enable', name: widgetLabel })` → "Enable measurement widget" / "Disable legend widget". The Widgets section had no descriptive note explaining what it controls.

**After:**
1. The Switch reads two state-specific i18n keys: `settings.enableWidget` when off ("Enable {{name}}") and `settings.disableWidget` when on ("Disable {{name}}"). The composite `toggleWidget` key is no longer referenced from the SettingsEditorScene (kept in locale files for future cleanup).
2. A descriptive note paragraph renders inside `CollapsibleContent` above the widget rows: `<p className="px-4 pt-2 pb-1 text-[11px] text-muted-foreground">Controls whether each widget appears on the map.</p>`. Subordinate 11px size + muted color keeps it lower-priority than the 12px row labels.
3. The widget rows themselves are unchanged (`h-9 items-center gap-2 px-4` per UI-SPEC §UX-04 lock).

### i18n (en/de/es/fr × 3 keys = 12 entries)

| Key | en | de | es | fr |
|---|---|---|---|---|
| `settings.enableWidget` | "Enable {{name}}" | "{{name}} aktivieren" | "Activar {{name}}" | "Activer {{name}}" |
| `settings.disableWidget` | "Disable {{name}}" | "{{name}} deaktivieren" | "Desactivar {{name}}" | "Désactiver {{name}}" |
| `settings.widgetsAvailabilityNote` | "Controls whether each widget appears on the map." | "Steuert, ob jedes Widget auf der Karte erscheint." | "Controla si cada widget aparece en el mapa." | "Détermine si chaque widget apparaît sur la carte." |

`node frontend/scripts/check-i18n-changed-namespaces.mjs` returns: "Changed namespaces exist across all locale directories: builder.json" — parity preserved.

### Tests

**New file** `SettingsEditorScene.widgets.test.tsx` (5 tests, all pass):
1. Switch aria-label is "Enable {name}" when widget is OFF
2. Switch aria-label is "Disable {name}" when widget is ON
3. Clicking Switch calls `onToggleWidget(widget.id)` once with the correct id
4. The availability-note paragraph renders inside the section
5. No-duplicate invariant: exactly one Switch per widget id and all aria-labels are unique

**Updated file** `SettingsEditorScene.test.tsx` (tests 5 + 6): The assertion strings "Enable measurement widget" / "Disable legend widget" → "Enable measurement" / "Disable legend" to track the deliberate label change (Rule 1 — fix the regression caused by my own change).

## Duplicate-Controls Audit (per plan acceptance criterion)

Grepped all `useWidgetStore` and `toggle` consumers in `frontend/src/`:

| Surface | Consumer | Role | Disposition |
|---|---|---|---|
| `SettingsEditorScene.tsx:188` (via `onToggleWidget` prop) | `MapBuilderPage.tsx:225` → `useWidgetStore.toggle` | Availability toggle (which widgets can appear at all) | KEEP — single source of truth, this plan's focus |
| `MapToolbar.tsx:26,66,110` | `useWidgetStore.toggle` | Live interaction (top-of-canvas Measure tool + Legend toggle for already-available widgets) | KEEP — distinct semantic role per plan success criterion 5 |
| `WidgetPanel.tsx:32` | `useWidgetStore.close` (close button on floating panel) | Dismissal of the rendered widget panel | KEEP — orthogonal to availability |
| `BuilderMap.tsx:353-357` | `useWidgetStore.subscribe` on `activeWidgets.has('measurement')` | Side-effect handler registration (MapLibre measurement listeners) | KEEP — read-only consumer |
| `MeasurementWidget.tsx:202` | `useWidgetStore.close('measurement')` on internal "done" action | Self-dismissal | KEEP — orthogonal |

**Conclusion:** 0 duplicate availability toggles. The Settings Switch is the single source of truth; MapToolbar buttons are live-interaction tools that consume the same store but represent a different user-facing concept. No removal was performed — none was required.

## Deviations from Plan

### Rule 1 (Bug — caused by my deliberate change)

**1. [Rule 1 - Bug] Updated SettingsEditorScene.test.tsx tests 5+6 to track the new label pattern**
- **Found during:** Task 2 verification — first vitest run.
- **Issue:** Existing tests 5 + 6 asserted the OLD composite labels ("Enable measurement widget", "Disable legend widget"). My intentional label change broke them.
- **Fix:** Updated both assertions to the new "Enable measurement" / "Disable legend" pattern (matches the new `settings.enableWidget`/`disableWidget` keys).
- **Files modified:** `frontend/src/components/builder/__tests__/SettingsEditorScene.test.tsx`
- **Commit:** 57d88d01 (same atomic commit as the rest of the plan)

### Task 1 + Task 3 — Playwright MCP verification deferred

Both checkpoint tasks (Task 1 pre-fix audit, Task 3 post-fix re-verify) require live Playwright MCP, which is orchestrator-scoped per the lesson_from_phase note ("Live MCP is orchestrator-scoped — defer MCP verify in SUMMARY but ship the fix"). The implementation, regression tests, typecheck, and i18n parity are all green and committed. The orchestrator owes the MCP round-trip: open Map Settings → Widgets, confirm the new "Enable {name}" / "Disable {name}" labels render, read the availability note paragraph, toggle a widget OFF → confirm removal from on-map render, toggle ON → confirm restoration, switch language to de/es/fr to confirm translations render.

## Verification

- `cd frontend && npx vitest run src/components/builder/__tests__/SettingsEditorScene.widgets.test.tsx src/components/builder/__tests__/SettingsEditorScene.test.tsx` → 15 passed (5 new + 10 existing)
- `cd frontend && npx tsc --noEmit` → 0 errors
- `node frontend/scripts/check-i18n-changed-namespaces.mjs` → "Changed namespaces exist across all locale directories: builder.json" (parity OK)
- `grep -c 'enableWidget' frontend/src/i18n/locales/{en,de,es,fr}/builder.json` → 1, 1, 1, 1 (per-locale)
- `grep -c 'disableWidget' frontend/src/i18n/locales/{en,de,es,fr}/builder.json` → 1, 1, 1, 1
- `grep -c 'widgetsAvailabilityNote' frontend/src/i18n/locales/{en,de,es,fr}/builder.json` → 1, 1, 1, 1
- `grep -n 'settings.enableWidget\|settings.disableWidget' frontend/src/components/builder/SettingsEditorScene.tsx` → 2 hits (lines 186 + 187 — used in conditional aria-label)

## Self-Check: PASSED

- FOUND: `frontend/src/components/builder/__tests__/SettingsEditorScene.widgets.test.tsx`
- FOUND: `frontend/src/components/builder/SettingsEditorScene.tsx` (modified)
- FOUND: `frontend/src/components/builder/__tests__/SettingsEditorScene.test.tsx` (modified)
- FOUND: 4 × `frontend/src/i18n/locales/{en,de,es,fr}/builder.json` (modified)
- FOUND commit: 57d88d01 — `refactor(builder): Map Settings Widgets section now enables/disables widget availability (UX-04)`
