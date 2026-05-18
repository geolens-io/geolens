---
phase: 1051
plan: 07
type: execute
wave: 7
depends_on: ["1051-06"]
files_modified:
  - frontend/src/components/builder/SettingsEditorScene.tsx
  - frontend/src/stores/map-widget-store.ts
  - frontend/src/components/builder/__tests__/SettingsEditorScene.widgets.test.tsx
  - frontend/src/i18n/locales/en/builder.json
  - frontend/src/i18n/locales/de/builder.json
  - frontend/src/i18n/locales/es/builder.json
  - frontend/src/i18n/locales/fr/builder.json
autonomous: false
requirements: [UX-04]
tags: [builder, ux, settings, widgets-toggles, i18n]

must_haves:
  truths:
    - "Map Settings → Widgets section contains one on/off Switch per widget (no duplicate on-map widget controls inside Settings)"
    - "Each toggle label clearly reads 'Enable [widget name]' when off and 'Disable [widget name]' when on (or unambiguous equivalent per UI-SPEC §UX-04)"
    - "Toggling a widget OFF removes it from on-map render (the WidgetHost no longer renders that widget)"
    - "Toggling a widget ON restores the on-map render"
    - "On-map controls for enabled widgets remain functional (no regression to live interaction — clicking coord readout, dragging scale)"
    - "New i18n keys translated en/de/es/fr maintaining parity"
  artifacts:
    - path: "frontend/src/components/builder/SettingsEditorScene.tsx"
      provides: "Widgets section uses clear 'Enable/Disable [name]' label pattern; any duplicate widget control elsewhere in Settings removed"
      contains: "settings.enableWidget"
    - path: "frontend/src/components/builder/__tests__/SettingsEditorScene.widgets.test.tsx"
      provides: "Regression test asserting toggle off → activeWidgetIds.delete + WidgetHost render gate; toggle on → restore"
      contains: "activeWidgetIds"
  key_links:
    - from: "SettingsEditorScene.tsx Switch component"
      to: "frontend/src/stores/map-widget-store.ts (activeWidgetIds Set)"
      via: "onCheckedChange={() => onToggleWidget(widget.id)} → store mutation"
      pattern: "onToggleWidget"
    - from: "frontend/src/stores/map-widget-store.ts"
      to: "frontend/src/components/map-widgets/WidgetHost.tsx (render gate)"
      via: "WidgetHost reads activeWidgetIds and gates render"
      pattern: "activeWidgetIds.has"
---

<objective>
Fix UX-04: Map Settings → Widgets section converts from "duplicate on-map widget controls" to enable/disable availability toggles. Per PATTERNS.md Plan 07: the existing implementation in `SettingsEditorScene.tsx:146-201` ALREADY uses a shadcn `<Switch />`. UX-04 is mostly a label-clarity + duplicate-controls audit, NOT a full UI rebuild. The Switch already wires to `onToggleWidget(widget.id)` which mutates `activeWidgetIds: Set<string>` in `frontend/src/stores/map-widget-store.ts`. The `WidgetHost` reads this set to gate on-map widget rendering.

Per UI-SPEC §UX-04: ensure label clarity (`Enable [name]` / `Disable [name]`); add `settings.widgetsAvailabilityNote` descriptive line ("Controls whether each widget appears on the map."); audit Settings + Map Settings drawer for any duplicate widget control (e.g., another widget on/off control rendered elsewhere) and remove the duplicate.

Purpose: Disambiguate the Settings purpose (toggle availability vs duplicate live control); cleaner mental model.
Output: Label refinement + 3 new i18n keys × 4 locales = 12 new entries; duplicate-control audit + removal if any; regression test for off→on round-trip.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/1051-map-builder-polish-bug-sweep/1051-CONTEXT.md
@.planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md
@.planning/phases/1051-map-builder-polish-bug-sweep/1051-UI-SPEC.md

<interfaces>
<!-- From PATTERNS.md — existing Settings widget toggle implementation. -->

From frontend/src/components/builder/SettingsEditorScene.tsx (around lines 146-201 — Widgets Collapsible):
- Uses shadcn Switch wired to onToggleWidget(widget.id)
- Label currently: `t('settings.toggleWidget', { defaultValue: '{{action}} {{name}} widget', action, name: widgetLabel })`
- Section header: `t('settings.widgetsLabel', { defaultValue: 'WIDGETS' })`
- Enabled-count micro: `t('settings.widgetsEnabledCount', { count: activeWidgetIds.size })`

From frontend/src/components/map-widgets/registry.ts: widget registry (id, labelKey, icon)
From frontend/src/stores/map-widget-store.ts: `activeWidgetIds: Set<string>` + `toggleWidget(id)` action
From frontend/src/components/map-widgets/WidgetHost.tsx: render-gates on `activeWidgetIds.has(id)`

Required i18n keys (per UI-SPEC):
- `settings.enableWidget` → "Enable {{name}}"
- `settings.disableWidget` → "Disable {{name}}"
- `settings.widgetsAvailabilityNote` → "Controls whether each widget appears on the map."

Add to all 4 locales (en/de/es/fr).
</interfaces>
</context>

<tasks>

<task type="checkpoint:orchestrator">
  <name>Task 1: Playwright MCP audit (label clarity + duplicate control hunt)</name>
  <files>(no files modified)</files>
  <read_first>
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md (Plan 07 — Existing Switch implementation)
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-UI-SPEC.md (UX-04)
  </read_first>
  <action>
    Orchestrator drives Playwright MCP. Steps: (1) Open a map. (2) Open Map Settings (gear icon → Settings scene). (3) Expand the Widgets section. (4) Capture each widget row: icon, label, current Switch state (checked/unchecked). (5) Read the aria-label currently used for each Switch. (6) Confirm current label uses `t('settings.toggleWidget', ...)` shape. (7) Audit: scan elsewhere in the Settings scene (and any other surfaces — Map Builder right panel, BuilderRail, etc.) for any duplicate "enable widget" or duplicate widget control. Document any duplicate found. (8) Confirm: toggling a widget off in Settings actually removes it from the on-map render (sanity check the wiring is already correct before refining labels). Add incidental issues to scratch list for EMRG-01.
  </action>
  <verify>
    <automated>Playwright MCP captures current Settings → Widgets UI + audit results (duplicate widget controls inventory).</automated>
  </verify>
  <acceptance_criteria>
    - Current label pattern captured
    - Duplicate widget controls (if any) inventoried with file + line citation
    - Wiring sanity check confirmed (or filed as a separate BUG if broken)
  </acceptance_criteria>
  <done>Pre-fix state + duplicate audit complete.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Refine labels + add i18n keys + remove duplicate controls (if any)</name>
  <files>frontend/src/components/builder/SettingsEditorScene.tsx, frontend/src/i18n/locales/en/builder.json, frontend/src/i18n/locales/de/builder.json, frontend/src/i18n/locales/es/builder.json, frontend/src/i18n/locales/fr/builder.json, frontend/src/components/builder/__tests__/SettingsEditorScene.widgets.test.tsx</files>
  <read_first>
    - frontend/src/components/builder/SettingsEditorScene.tsx (widgets section lines 146-201)
    - frontend/src/i18n/locales/{en,de,es,fr}/builder.json (settings.* keys; confirm 770-key parity baseline)
    - frontend/src/components/builder/__tests__/SettingsEditorScene.test.tsx if it exists (otherwise SettingsEditorScene smoke pattern)
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md (Plan 07 — UI-SPEC label table)
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-UI-SPEC.md (UX-04 row visual contract)
  </read_first>
  <behavior>
    - Test 1: When widget is OFF, Switch aria-label reads "Enable {widget name}" (from settings.enableWidget)
    - Test 2: When widget is ON, Switch aria-label reads "Disable {widget name}" (from settings.disableWidget)
    - Test 3: Toggling Switch calls onToggleWidget(widget.id) once with the correct id
    - Test 4: The descriptive line `settings.widgetsAvailabilityNote` is rendered in the Widgets section
    - Test 5: No two Switch elements exist within the Settings scene for the same widget id (duplicate-controls check)
  </behavior>
  <action>
    Edit `frontend/src/components/builder/SettingsEditorScene.tsx` (around lines 146-201): (a) Update the Switch aria-label to use the new conditional keys: `aria-label={isEnabled ? t('settings.disableWidget', { defaultValue: 'Disable {{name}}', name: widgetLabel }) : t('settings.enableWidget', { defaultValue: 'Enable {{name}}', name: widgetLabel })}`. (b) Add a descriptive note paragraph inside the CollapsibleContent (above the widget list): `<p className="px-4 pt-2 pb-1 text-[11px] text-muted-foreground">{t('settings.widgetsAvailabilityNote', { defaultValue: 'Controls whether each widget appears on the map.' })}</p>`. (c) If the Task 1 audit found any duplicate widget control surface in the Settings scene, remove the duplicate (keep only the Switch row). Document the removal in the commit body. (d) Align row gap to `gap-2` per UI-SPEC (verify current — likely already gap-2; do not change if already correct).
    
    Update i18n: add three keys to each of `frontend/src/i18n/locales/{en,de,es,fr}/builder.json` under the `settings` namespace:
    - `settings.enableWidget` (en: "Enable {{name}}"; de/es/fr: reasonable translation OR keep English defaultValue)
    - `settings.disableWidget` (en: "Disable {{name}}")
    - `settings.widgetsAvailabilityNote` (en: "Controls whether each widget appears on the map.")
    Maintain parity: each locale has the same key set under `settings.*`.
    
    Create or extend `frontend/src/components/builder/__tests__/SettingsEditorScene.widgets.test.tsx` with the 5 behavior tests above. Use the existing test harness pattern (renderHook or render + i18n provider).
  </action>
  <verify>
    <automated>cd frontend && npx vitest run src/components/builder/__tests__/SettingsEditorScene.widgets.test.tsx && cd frontend && npx tsc --noEmit</automated>
  </verify>
  <acceptance_criteria>
    - `grep -c 'settings\\.enableWidget\\|settings\\.disableWidget\\|settings\\.widgetsAvailabilityNote' frontend/src/i18n/locales/en/builder.json` returns ≥3
    - Same for de/es/fr (parity)
    - `grep -n 'settings.enableWidget\\|settings.disableWidget' frontend/src/components/builder/SettingsEditorScene.tsx` returns ≥2 matches (used in aria-label)
    - If duplicate widget controls existed, they are removed (cite their pre-state in commit body)
    - Vitest tests pass
    - `cd frontend && npx tsc --noEmit` returns 0 errors
  </acceptance_criteria>
  <done>Labels refined; descriptive note added; duplicates removed; i18n parity preserved.</done>
</task>

<task type="checkpoint:orchestrator">
  <name>Task 3: Playwright MCP post-fix re-verify + atomic commit</name>
  <files>(no files modified beyond commit)</files>
  <read_first>
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-UI-SPEC.md
  </read_first>
  <action>
    Orchestrator drives Playwright MCP. Steps: (1) Reload page. (2) Open Map Settings → Widgets. (3) Read each Switch aria-label — confirm "Enable [name]" / "Disable [name]" copy. (4) Read the new descriptive note in the section. (5) Toggle a widget (e.g., scale or coord readout) OFF — confirm it disappears from the on-map render. (6) Toggle it back ON — confirm it reappears. (7) Spot-check: clicking the coord readout pill on the map (when enabled) still has its native click-to-cycle behavior (no regression to on-map live interaction). (8) Switch the language to de/es/fr via the i18n switcher (if accessible) and confirm the translations render correctly (or no untranslated `settings.enableWidget` raw key surfaces). After MCP verify passes, create atomic commit with subject: `refactor(builder): Map Settings Widgets section now enables/disables widget availability (UX-04)`. Stage SettingsEditorScene.tsx + test file + the 4 locale files.
  </action>
  <verify>
    <automated>git log --oneline -1 && git show --stat HEAD</automated>
  </verify>
  <acceptance_criteria>
    - Playwright MCP confirms toggle off → widget disappears; on → reappears
    - Labels read clearly as Enable/Disable [name]
    - On-map interaction unaffected
    - Commit exists with subject `refactor(builder): Map Settings Widgets section now enables/disables widget availability (UX-04)`
    - `git diff HEAD~1 HEAD --stat` shows only the 7 in-scope files modified
  </acceptance_criteria>
  <done>UX-04 fix verified live + committed atomically.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| client-only state | Widget enable/disable is client-side zustand state; no API surface |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-1051-07 | (n/a) | widget toggle state | accept | No security surface; pure client state |
</threat_model>

<verification>
- Playwright MCP confirms toggle round-trip
- Vitest covers label, callback, no-duplicate
- `npx tsc --noEmit` returns 0 errors
- i18n parity preserved across en/de/es/fr
</verification>

<success_criteria>
- Map Settings → Widgets section contains one on/off toggle per widget (no duplicate controls)
- Toggles are labeled clearly (Enable/Disable [name]) and translated en/de/es/fr
- Toggling off removes the widget from the on-map render; on restores
- On-map live interaction unaffected
- Vitest regression confirms toggle round-trip
- Atomic commit on main with subject `refactor(builder): Map Settings Widgets section now enables/disables widget availability (UX-04)`
</success_criteria>

<output>
Create `.planning/phases/1051-map-builder-polish-bug-sweep/1051-07-SUMMARY.md` with: label diff, duplicate-controls inventory (if any), i18n key additions, files modified, test result, MCP screenshots.
</output>
