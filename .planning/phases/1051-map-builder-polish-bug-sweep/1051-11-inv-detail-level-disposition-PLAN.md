---
phase: 1051
plan: 11
type: execute
wave: 11
depends_on: ["1051-10"]
files_modified:
  - frontend/src/components/builder/BasemapSublayerEditorScene.tsx
  - frontend/src/pages/MapBuilderPage.tsx
  - frontend/src/i18n/locales/en/builder.json
  - frontend/src/i18n/locales/de/builder.json
  - frontend/src/i18n/locales/es/builder.json
  - frontend/src/i18n/locales/fr/builder.json
autonomous: false
requirements: [INV-01]
tags: [builder, investigation, detail-level, dead-code-removal]

must_haves:
  truths:
    - "DETAIL LEVEL disposition resolved: REMOVE (default per critical_planning_directive #6) — the toggle is confirmed dead wiring per PATTERNS.md finding #1: MapBuilderPage.tsx:801-810 passes hardcoded activeDetailLevel='default' + onDetailLevelChange={() => { /* TODO(Phase 1038) */ }}"
    - "Disposition (REMOVE) is recorded in the commit body AND in the CHANGELOG bullet drafted for Plan 13"
    - "After removal: `git grep -in 'detail.level\\|detaillevel\\|DETAIL LEVEL' frontend/src/` returns 0 matches"
    - "All orphan i18n keys (`basemapSublayer.detailLevel*`) removed from all 4 locales — parity preserved"
    - "FIX disposition path NOT taken (no consumer can be reconstructed without 3-5 days of MapLibre style-mutation work — out of v1011 scope per REQUIREMENTS.md Out-of-Scope row 1)"
  artifacts:
    - path: "frontend/src/components/builder/BasemapSublayerEditorScene.tsx"
      provides: "DETAIL LEVEL <section> (lines 90-132) removed; activeDetailLevel/isCustomized/onDetailLevelChange props removed from the component interface; DETAIL_LEVELS const removed"
      contains: "BasemapSublayerEditorScene"
    - path: "frontend/src/pages/MapBuilderPage.tsx"
      provides: "Lines 801-810 call site no longer passes the now-removed detail-level props"
      contains: "BasemapSublayerEditorScene"
  key_links:
    - from: "BasemapSublayerEditorScene.tsx props interface"
      to: "MapBuilderPage.tsx call site (line ~801-810)"
      via: "Removed props must be cleanly removed at both ends — no orphan TODO comments left behind"
      pattern: "BasemapSublayerEditorScene"
---

<objective>
Fix INV-01: DETAIL LEVEL toggle disposition resolved.

Per critical_planning_directive #6 + PATTERNS.md finding #1: the DETAIL LEVEL toggle in `BasemapSublayerEditorScene.tsx:90-132` is confirmed DEAD WIRING. The call site at `MapBuilderPage.tsx:801-810` passes `activeDetailLevel="default"` (hardcoded) and `onDetailLevelChange={() => { /* TODO(Phase 1038): markDirty() once sublayer styling is persisted */ }}`. The wider scene has the same TODO on `onStrokeColorChange`, `onStrokeWidthChange`, `onCasingColorChange`, `onCasingWidthChange`, and `onZoomChange` — all no-op stubs.

**Default disposition: REMOVE.** Per ROADMAP Plan 11 task 4 and REQUIREMENTS.md Out-of-Scope row 1 (no new feature work), the FIX path requires 3-5 days of MapLibre style-mutation implementation, which is out of v1011 scope. The REMOVE path is the clean choice for this hygiene milestone. FIX disposition is documented as a future backlog candidate (referenced in CHANGELOG bullet via Plan 13).

Scope of removal:
- The DETAIL LEVEL `<section>` JSX (BasemapSublayerEditorScene.tsx:90-132)
- The `DETAIL_LEVELS` const array (search the file for `const DETAIL_LEVELS = [`)
- The `activeDetailLevel`, `isCustomized`, `onDetailLevelChange` props from the component's TypeScript interface
- The corresponding props at the call site (MapBuilderPage.tsx:801-810)
- Any orphan i18n keys under `basemapSublayer.detailLevel*` and `basemapSublayer.customizedHint` in all 4 locale files

Note: this plan ONLY removes DETAIL LEVEL. The OTHER no-op callbacks (`onStrokeColorChange`, etc.) are NOT removed in this plan — they belong to a separate "Phase 1038 TODO" cleanup scope that has not been explicitly authorized. Surface them as an EMRG-01 finding for the orchestrator to triage in Plan 12.

Purpose: Dead UI affordance with no real behavior → confusing/misleading to users; per `feedback_no_security_by_obscurity.md` ethos, dead UI is technical debt that should not ship to production.
Output: DETAIL LEVEL UI + props + i18n keys removed; full grep returns 0 hits; CHANGELOG bullet drafted; FIX path documented as future backlog.
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

<interfaces>
<!-- From PATTERNS.md — confirmed dead wiring evidence. -->

From frontend/src/components/builder/BasemapSublayerEditorScene.tsx (lines 90-132 — DETAIL LEVEL section to REMOVE):
```tsx
<section className="border-b">
  <div className="px-4 py-2">
    <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground mb-2">
      {t('basemapSublayer.detailLevelLabel', { defaultValue: 'DETAIL LEVEL' })}
    </p>
    <div role="radiogroup" className="flex flex-wrap gap-1.5">
      {DETAIL_LEVELS.map((pill) => { ... })}
    </div>
    {activeDetailLevel !== 'default' && isCustomized && (
      <p className="text-[12px] text-muted-foreground italic mt-2">
        {t('basemapSublayer.customizedHint', { sublayer: sublayerName, defaultValue: '{{sublayer}} is currently customized' })}
      </p>
    )}
  </div>
</section>
```

From frontend/src/pages/MapBuilderPage.tsx (lines 801-810 — call site with no-op TODO):
```tsx
<BasemapSublayerEditorScene
  sublayerId={sublayer.id}
  sublayerName={sublayer.name}
  activeDetailLevel="default"
  isCustomized={false}
  ...
  onDetailLevelChange={() => { /* TODO(Phase 1038): markDirty() once sublayer styling is persisted */ }}
  ...
/>
```

Grep targets (initial inventory in Task 1):
```bash
git grep -in 'detail.level\|detaillevel\|DETAIL LEVEL\|DETAIL_LEVELS\|activeDetailLevel\|onDetailLevelChange\|isCustomized\|customizedHint' frontend/src/
```
</interfaces>
</context>

<tasks>

<task type="checkpoint:orchestrator">
  <name>Task 1: Playwright MCP screenshot + grep enumeration</name>
  <files>(no files modified)</files>
  <read_first>
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md (Plan 11 — confirmed DEAD WIRING)
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-CONTEXT.md (INV-01 disposition flow)
  </read_first>
  <action>
    Orchestrator drives Playwright MCP. Steps: (1) Open a map. (2) Click a basemap sublayer to open BasemapSublayerEditorScene. (3) Screenshot the DETAIL LEVEL section (the radiogroup pills). (4) Click each detail level pill — confirm NO observable map change (validating dead wiring claim live). (5) Document observed pre-removal state. THEN run, in a shell: `cd /Users/ishiland/Code/geolens && git grep -in 'detail.level\|detaillevel\|DETAIL LEVEL\|DETAIL_LEVELS\|activeDetailLevel\|onDetailLevelChange\|isCustomized\|customizedHint' frontend/src/ | sort -u`. Save the full grep output. Add incidental issues to scratch list for EMRG-01 (e.g., the sibling no-op callbacks `onStrokeColorChange` etc. → flag as separate EMRG finding).
  </action>
  <verify>
    <automated>Playwright MCP screenshot + shell grep output capture (full enumeration of all references).</automated>
  </verify>
  <acceptance_criteria>
    - Pre-removal screenshot of DETAIL LEVEL section captured
    - Click-on-pill produces no observable map change (validates dead wiring)
    - Full grep enumeration of detail-level references recorded (file:line for each)
    - Sibling no-op callbacks (onStrokeColorChange etc.) flagged for EMRG-01 (NOT in scope for this plan)
  </acceptance_criteria>
  <done>Pre-removal state + grep inventory recorded; REMOVE disposition confirmed.</done>
</task>

<task type="auto">
  <name>Task 2: Remove DETAIL LEVEL section + props + i18n keys</name>
  <files>frontend/src/components/builder/BasemapSublayerEditorScene.tsx, frontend/src/pages/MapBuilderPage.tsx, frontend/src/i18n/locales/en/builder.json, frontend/src/i18n/locales/de/builder.json, frontend/src/i18n/locales/es/builder.json, frontend/src/i18n/locales/fr/builder.json</files>
  <read_first>
    - frontend/src/components/builder/BasemapSublayerEditorScene.tsx (full file — esp DETAIL_LEVELS const, the <section> at lines 90-132, props interface)
    - frontend/src/pages/MapBuilderPage.tsx (lines ~801-810 call site)
    - frontend/src/i18n/locales/en/builder.json (search for `detailLevel`, `customizedHint`)
    - frontend/src/i18n/locales/de/builder.json (same)
    - frontend/src/i18n/locales/es/builder.json (same)
    - frontend/src/i18n/locales/fr/builder.json (same)
    - Task 1 grep output (full inventory)
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md (Plan 11 — REMOVE shape)
  </read_first>
  <action>
    Remove DETAIL LEVEL wiring across all touch points:
    
    (a) `frontend/src/components/builder/BasemapSublayerEditorScene.tsx`:
    - Delete the `DETAIL_LEVELS` constant array (search the file for `const DETAIL_LEVELS = [` and remove the whole declaration)
    - Delete the `<section>` JSX block at lines 90-132 (the DETAIL LEVEL UI)
    - Remove `activeDetailLevel`, `isCustomized`, `onDetailLevelChange` from the props interface (TypeScript type)
    - Remove `activeDetailLevel`, `isCustomized`, `onDetailLevelChange` from the function signature destructure
    - Verify no other reference to these props remains in the file
    
    (b) `frontend/src/pages/MapBuilderPage.tsx` (around lines 801-810):
    - Remove the `activeDetailLevel="default"`, `isCustomized={false}`, `onDetailLevelChange={() => { /* TODO(Phase 1038): ... */ }}` props from the `<BasemapSublayerEditorScene ... />` call
    - Leave the OTHER no-op TODO props (onStrokeColorChange, etc.) UNTOUCHED — they are out of this plan's scope and tracked separately via EMRG-01
    
    (c) i18n locales (all 4): remove these keys (and any sibling keys solely referenced by the removed UI):
    - `basemapSublayer.detailLevelLabel`
    - `basemapSublayer.customizedHint`
    - Any per-detail-level pill labelKey (find via the Task 1 grep — search the DETAIL_LEVELS const for `labelKey` strings)
    - Maintain parity across en/de/es/fr (each locale loses the same key set)
    
    (d) Run the grep again post-removal — should return 0 hits in frontend/src/ for: `detail.level`, `detaillevel`, `DETAIL LEVEL`, `DETAIL_LEVELS`, `activeDetailLevel`, `onDetailLevelChange`, `customizedHint` (NOTE: `isCustomized` may legitimately exist in other contexts — verify the post-removal grep is for the DETAIL LEVEL `isCustomized` specifically, not a coincidental other use).
    
    (e) Add a CHANGELOG bullet draft as a comment near the removal site (or in this task's SUMMARY): "REMOVE — DETAIL LEVEL was dead wiring (Phase 1038 TODO never implemented); track FIX as future milestone if user value justifies."
    
    Do NOT touch the sibling onStrokeColorChange/onCasingColorChange/etc. no-ops. Those belong to a separate triage.
  </action>
  <verify>
    <automated>cd frontend && npx tsc --noEmit && git grep -in 'detail.level\|detaillevel\|DETAIL LEVEL\|DETAIL_LEVELS\|activeDetailLevel\|onDetailLevelChange\|customizedHint' frontend/src/ | head -20</automated>
  </verify>
  <acceptance_criteria>
    - `git grep -in 'detail.level\|detaillevel\|DETAIL LEVEL\|DETAIL_LEVELS\|activeDetailLevel\|onDetailLevelChange\|customizedHint' frontend/src/` returns 0 matches
    - `cd frontend && npx tsc --noEmit` returns 0 errors
    - Each of the 4 locale files loses the same key set under `basemapSublayer.detailLevel*` and `basemapSublayer.customizedHint` (parity preserved)
    - Sibling no-op callbacks (onStrokeColorChange etc.) are UNTOUCHED (diff shows no change to those lines)
    - CHANGELOG bullet draft recorded for Plan 13 use
  </acceptance_criteria>
  <done>DETAIL LEVEL wiring + UI + i18n removed cleanly; grep returns 0; type check passes.</done>
</task>

<task type="checkpoint:orchestrator">
  <name>Task 3: Playwright MCP post-removal re-verify + atomic commit</name>
  <files>(no files modified beyond commit)</files>
  <read_first>
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md
  </read_first>
  <action>
    Orchestrator drives Playwright MCP. Steps: (1) Reload page. (2) Open the same basemap sublayer used in Task 1. (3) Confirm the DETAIL LEVEL section is GONE — no radiogroup, no "DETAIL LEVEL" label, no customized hint paragraph. (4) Confirm the BasemapSublayerEditorScene still renders cleanly (other sections like stroke color / opacity still display, even though their handlers remain no-op — those are out of scope). (5) Spot-check: i18n switcher (if available) — switch to de/es/fr and confirm no untranslated keys surface (any `basemapSublayer.detailLevel*` orphans would appear as raw keys). After MCP verify passes, create atomic commit with subject: `refactor(builder): DETAIL LEVEL removed (no consumer; Phase 1038 TODO never implemented) (INV-01)`. Commit body must include: (a) the REMOVE rationale, (b) cited evidence (file:line of the original TODO at MapBuilderPage.tsx:810), (c) the CHANGELOG bullet draft. Stage only the 6 in-scope files.
  </action>
  <verify>
    <automated>git log --oneline -1 && git show --stat HEAD</automated>
  </verify>
  <acceptance_criteria>
    - Playwright MCP confirms DETAIL LEVEL is gone from the BasemapSublayerEditorScene
    - i18n shows no orphan key surfaces in any locale
    - Commit exists with subject `refactor(builder): DETAIL LEVEL removed (no consumer; Phase 1038 TODO never implemented) (INV-01)`
    - Commit body includes disposition rationale + cited evidence + CHANGELOG bullet draft
    - `git diff HEAD~1 HEAD --stat` shows the 6 in-scope files only
  </acceptance_criteria>
  <done>INV-01 disposition (REMOVE) verified live + committed atomically.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| client-only UI removal | Deletes a dead-wired UI section; no API change; no user data affected |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-1051-11 | (n/a) | dead-code removal | accept | Removed code had no live consumer; no security surface change |
</threat_model>

<verification>
- Playwright MCP confirms DETAIL LEVEL gone from UI
- `git grep` for all DETAIL LEVEL identifiers returns 0
- `npx tsc --noEmit` returns 0 errors
- i18n parity preserved at en/de/es/fr (4 keys removed × 4 locales = 16 entries removed)
</verification>

<success_criteria>
- INV-01 disposition is REMOVE; recorded in commit body
- No `DETAIL LEVEL` references remain in `frontend/src/` (grep returns 0)
- No orphan i18n keys remain
- CHANGELOG bullet text drafted for Plan 13 consumption
- Atomic commit on main with subject `refactor(builder): DETAIL LEVEL removed (no consumer; Phase 1038 TODO never implemented) (INV-01)`
</success_criteria>

<output>
Create `.planning/phases/1051-map-builder-polish-bug-sweep/1051-11-SUMMARY.md` with: full grep inventory (pre + post removal), disposition rationale (REMOVE), files modified, MCP screenshots before/after, CHANGELOG bullet draft, mention of the EMRG-01 followup (sibling no-op callbacks onStrokeColorChange etc. flagged for Plan 12 triage).
</output>
