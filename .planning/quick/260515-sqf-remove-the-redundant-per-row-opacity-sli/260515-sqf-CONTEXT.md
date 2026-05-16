---
quick_id: 260515-sqf
type: quick-task-context
status: ready-for-planning
gathered: 2026-05-15
predecessor: 260515-rdn
---

# Quick Task 260515-sqf: Remove FolderGroupRow per-row Opacity slider — Context

**Gathered:** 2026-05-15
**Status:** Ready for planning
**Predecessor:** 260515-rdn (StackRow row slider removal — same pattern, same outcome)

<domain>
## Task Boundary

`frontend/src/components/builder/FolderGroupRow.tsx` renders a 60×6 px Opacity slider on every folder-group row (lines 282-296). Clicking the row body invokes `onSelectGroup(layer.id)` → `onSelectLayer(layer.id)` → opens the LayerEditorPanel default content for that layer. The LayerEditorPanel's Visibility section contains an identical "Opacity" slider that calls the same `onOpacityChange` handler and writes to the same `layer.opacity` field.

This is structurally identical to the StackRow redundancy resolved in 260515-rdn. The user has explicitly directed this removal as a follow-up:

> "/gsd-quick FolderGroupRow row slider removal"
> "Mirrors 260515-rdn exactly. Low-risk, ~−25 LOC. Removes folder-group row slider; opacity stays in LayerEditorPanel Visibility section."

**Goal:** Remove the per-row Opacity slider from FolderGroupRow. The LayerEditorPanel Visibility-section slider (already canonical for non-group layers post-260515-rdn) becomes the canonical control for folder groups too.

**Out of scope:**
- Any change to the LayerEditorPanel opacity slider behavior.
- BasemapGroupRow row slider (separate investigation, see 260515-zzz follow-up — has additional persistence concerns).
- BasemapGroupEditorScene's master-opacity or per-sublayer sliders.
- Other FolderGroupRow controls (eye, kebab, drag handle, type icon, name, expand caret).

</domain>

<decisions>
## Implementation Decisions

### What to do with the redundancy
- **Decision:** Remove the FolderGroupRow row slider entirely. (User: "Mirrors 260515-rdn exactly")
- **Rationale:** Single source of truth, decluttered row, consistency with StackRow pattern shipped in 260515-rdn.

### What to do with the freed 60px column
- **Decision:** Collapse the column. Same approach as 260515-rdn StackRow change. The grid template `'16px_14px_22px_22px_1fr_60px_22px'` (or similar — research must confirm) becomes `'16px_14px_22px_22px_1fr_22px'`.

### i18n key — DO NOT delete
- **Decision (preempted from 260515-rdn precedent):** The `stackRow.opacitySlider` i18n key is shared by 3 sibling sliders (BasemapGroupRow, BasemapGroupEditorScene/SublayerRow, and **was** previously also FolderGroupRow). After this task, only 2 consumers remain (BasemapGroupRow and BasemapGroupEditorScene/SublayerRow). The key MUST stay. **DO NOT touch any locale file.**

### Tests
- **Decision:** Tests in `frontend/src/components/builder/__tests__/FolderGroupRow.test.tsx` that assert the row slider's presence or behavior must be removed or updated. The LayerEditorPanel opacity tests stay as-is.

### onOpacityChange prop on FolderGroupRow
- **Decision:** Remove the `onOpacityChange` prop from `FolderGroupRowProps` interface AND from any callsite that passes it. The TS safety net will surface every callsite — same approach that worked in 260515-rdn.

### onOpacityChange flow upstream
- **Decision (Claude's discretion):** The `handlers.onOpacityChange` callback chain in MapBuilderPage / use-builder-layers.ts STAYS — it's still load-bearing for LayerEditorPanel + BasemapGroupRow + BasemapGroupEditorScene. Only the *forwarding into FolderGroupRow* stops.

### Sketch findings update
- **Decision (Claude's discretion):** Check whether `.claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md` (already updated in 260515-rdn) needs further amendment for folder groups specifically. The 260515-rdn update covered the canonical row anatomy and noted group rows retain their slider — the group-row HTML example was intentionally left unchanged. Now that folder groups also lose their slider, the doc should be revisited: at minimum, the "group rows retain opacity slider" caveat in the forward note (260515-rdn line 34-41) needs to be narrowed to "*basemap* group rows" only.

</decisions>

<specifics>
## Specific Ideas

- File: `frontend/src/components/builder/FolderGroupRow.tsx` — remove the Slider element (lines 282-296), grid template, prop, destructure, opacity local, import.
- File: `frontend/src/components/builder/__tests__/FolderGroupRow.test.tsx` — drop slider assertions.
- File: `frontend/src/components/builder/UnifiedStackPanel.tsx` line 910 — drop `onOpacityChange={onOpacityChange}` from the FolderGroupRowWrapper instantiation. May also need to drop the prop from the wrapper interface (analogous to SortableStackRow's `onOpacityChange` removal in 260515-rdn).
- File: `.claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md` — narrow the 260515-rdn forward note to "basemap group rows retain their slider; folder group rows do not".

Verification commands (mirrors 260515-rdn):
- `cd frontend && pnpm typecheck` (must pass — TS surfaces missed callsites)
- `cd frontend && pnpm vitest run src/components/builder/__tests__/FolderGroupRow.test.tsx`
- `cd frontend && pnpm vitest run src/components/builder/__tests__` (all green)
- `grep -n "onOpacityChange" frontend/src/components/builder/FolderGroupRow.tsx` returns 0
- `grep -n '"opacitySlider"' frontend/src/i18n/locales/{en,de,es,fr}/builder.json` returns 4 (locales untouched)
- `grep -rn "stackRow\\.opacitySlider" frontend/src/components/builder/` returns 2 (was 3 after 260515-rdn: BasemapGroupRow + BasemapGroupEditorScene)
- Manual Playwright smoke at http://localhost:8080/maps/dfbe4fd8-… — folder-group row (if present) has no slider; LayerEditorPanel Visibility-section opacity remains functional.

</specifics>

<canonical_refs>
## Canonical References

- Predecessor task: `.planning/quick/260515-rdn-remove-the-redundant-per-row-opacity-sli/` — same pattern, same files, same gates. Read for established workflow.
- BSR sketch 002 (`.claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md`) — already updated in 260515-rdn; needs further narrowing.
- `frontend/src/components/builder/FolderGroupRow.tsx` lines 282-296 — the slider being removed.

</canonical_refs>
