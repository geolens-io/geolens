---
quick_id: 260515-rdn
type: quick-task-context
status: ready-for-planning
gathered: 2026-05-15
---

# Quick Task 260515-rdn: Remove redundant per-row Opacity slider — Context

**Gathered:** 2026-05-15
**Status:** Ready for planning

<domain>
## Task Boundary

The Map Builder layer-list (sidebar, `frontend/src/components/builder/StackRow.tsx`) ships a 60×6 px Opacity slider on every layer row. The same opacity value is also editable in the LayerEditorPanel flyout (`frontend/src/components/builder/LayerEditorPanel.tsx`) Visibility section, which is full-width and always-expanded once a layer is selected.

Both sliders call the same handler (`onOpacityChange(layer.id, value)`) and bind to the same `layer.opacity` field. The row slider was sketched in BSR sketch 002 (winning A-strict variant); the panel slider was sketched in BSR sketch 003 (winning Variant A). The two sketches were authored independently and both shipped — the redundancy was never explicitly resolved.

**Goal:** Remove the per-row Opacity slider. The LayerEditorPanel's Visibility-section slider becomes the single canonical opacity control. Row freed of a fiddly micro-control that the user reports feels unresponsive.

**Out of scope:**
- Any change to the LayerEditorPanel opacity slider behavior (it stays exactly as is).
- Reworking other row controls (eye toggle, kebab, drag handle, type icon, name).
- Group-level opacity behavior, basemap opacity propagation.
- Tests beyond removing/updating tests that assert the row slider exists.

</domain>

<decisions>
## Implementation Decisions

### What to do with the redundancy
- **Decision:** Remove the row slider entirely. (User: "Remove row slider")
- **Rationale:** Single source of truth, decluttered row, eliminates user confusion about whether the row slider works. LayerEditorPanel opens on a single row click, so opacity is one click away (was: click row OR drag tiny slider).

### What to do with the freed 60px column
- **Decision:** Claude's discretion. Options:
  1. Collapse the grid column entirely (row becomes denser horizontally).
  2. Reserve the column for a future affordance (display-only opacity badge, locked icon, etc.) and leave it empty for now.
  3. Re-allocate to the `name` column (`1fr` already absorbs leftover; collapsing is cleanest).
- **Recommendation for planner:** Collapse the column. The grid template is `16px 14px 22px 22px 1fr 60px 22px` → becomes `16px 14px 22px 22px 1fr 22px`. Name gets to use more space when truncated. No empty visual gap.

### Sketch findings update
- **Decision:** Update `.claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md` so the row anatomy spec no longer claims a row slider exists. This file is consumed by future agents — leaving the old spec causes drift.
- **Scope:** Remove the `[opacity]` token from the row anatomy diagram, remove the `60px` column from the grid template CSS, remove the `<input class="opacity">` from the HTML examples, remove the rejection bullet about "Numeric opacity inputs on the row" (no longer relevant), add a note that opacity moved entirely into the LayerEditorPanel Visibility section.

### Tests
- **Decision:** Tests in `frontend/src/components/builder/__tests__/StackRow.test.tsx` (and any sibling tests) that assert the row slider's presence or behavior must be removed or updated. The LayerEditorPanel opacity tests (`__tests__/LayerEditorPanel.test.tsx`) stay as-is — they cover the canonical control now.

### Translations
- **Decision (REVISED 2026-05-15 after research):** **DO NOT** remove the `stackRow.opacitySlider` i18n key. Research (`260515-rdn-RESEARCH.md` §3) confirmed the key has 4 active consumers: StackRow.tsx (this task removes it), BasemapGroupRow.tsx, FolderGroupRow.tsx, and BasemapGroupEditorScene.tsx — the latter three are OUT-OF-SCOPE per the "group-level opacity behavior" exclusion above. Removing the key would break aria-labels on three other live sliders. **Keep the key in all four locale files unchanged.** Keep `layerEditor.visibility.opacity` (the panel-side label) too.

### Claude's Discretion
- Whether to also check for any storybook fixtures, demo seed scripts, or e2e selectors that reference the row slider (likely yes — should grep before touching code).
- Whether the `onOpacityChange` prop on `StackRow` props can also be removed (likely yes — nothing else on the row uses it after slider removal).

</decisions>

<specifics>
## Specific Ideas

- File: `frontend/src/components/builder/StackRow.tsx` — remove the Slider element block (~lines 305-325 per current grep), remove `60px` from the `grid-cols-[…]` template (line 178), remove `onOpacityChange` from the `StackRowProps` interface (line 34), remove the prop from any `StackRow` instantiation site.
- File: `frontend/src/components/builder/__tests__/StackRow.test.tsx` — remove tests asserting opacity slider behavior.
- File: `frontend/src/i18n/locales/{en,de,es,fr}/builder.json` — remove `stackRow.opacitySlider` key.
- File: `.claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md` — strip row-slider language per decisions above.
- File: `e2e/builder-v1-5.spec.ts` (if it asserts the row slider) — update.
- Verify nothing else in `frontend/src/` instantiates `StackRow` with a now-defunct `onOpacityChange` prop.
- Confirm `BasemapGroupRow.tsx`, `FolderGroupRow.tsx` — if they have row sliders too (group-level opacity), the user explicitly said only the per-row sliders are redundant; a group-level slider is a separate UX question and should not be touched in this task without confirmation.

</specifics>

<canonical_refs>
## Canonical References

- BSR sketch 002 (`.claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md`) — original row-anatomy spec, including the now-removed `[opacity]` slot.
- BSR sketch 003 (`.claude/skills/sketch-findings-geolens/references/layer-editor-flyout.md`) — Visibility section spec, the surviving canonical opacity control.
- Memory: `milestone_v1008_map_builder_sidebar_redesign` (in MEMORY.md project memory section) — v1008 BSR shipped 2026-05-14 with both controls, no decision recorded about the duplication.

</canonical_refs>
