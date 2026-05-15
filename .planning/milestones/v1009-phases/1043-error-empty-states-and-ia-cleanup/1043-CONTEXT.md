---
phase: 1043
phase_name: error-empty-states-and-ia-cleanup
status: ready_for_planning
generated: auto (workflow.skip_discuss=true)
date: 2026-05-14
---

# Phase 1043: error-empty-states-and-ia-cleanup — Context

**Gathered:** 2026-05-14
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

Close the Phase 1039 audit's error/empty-state and information-architecture findings — every async failure recoverable with localized copy + retry, every section's empty state intentionally designed, section ordering consistent across vector/raster/DEM/basemap layer types, and scene transitions preserving scroll + focus.

**Requirements:** POL-16, POL-17, POL-18

**Success Criteria:**
1. Any builder async failure (column fetch, preview, save) shows localized error message + retry affordance — no silent fall-through to the error boundary.
2. Filter section (no conditions), Labels section (labels off), Source section (no indexed columns), and LayerEditorPanel for basemap-group with zero customization — all show intentional empty-state copy + iconography.
3. LayerEditorPanel section ordering is consistent across vector / raster / DEM / basemap-group.
4. Scene transitions (default → basemap-group → basemap-sublayer + back) preserve scroll position and keyboard focus.

**Depends on:** Phase 1042 (polish — must be merged for consistent state vocab to extend into error/empty UI).

**Audit findings to consume from `BUILDER-UX-AUDIT.md`:** AUD-09 (autoFocus on Cancel — already applied), AUD-11, AUD-14, AUD-18, AUD-20, AUD-22 (error/empty/IA findings explicitly deferred from Phase 1042 to here).

**Carry-overs from Phase 1042 UI review:** SettingsEditorScene `eyebrowClassName` migration; missing i18n keys (`basemapGroup.toggleExpand`, `basemapSublayer.*`); `hover:bg-accent` → `hover:bg-[var(--surface-2)]` on 7 builder call sites (kebab triggers, expand buttons, LEP close/pin) — token sweep falls in this IA cleanup phase.

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion (`workflow.skip_discuss=true`).

### Hard Constraints (v1009)
- No saved-map shape changes
- No public viewer / shared / embed surface changes
- Sketch-findings tokens only
- No new backend endpoints
- TanStack Query refetch + onError patterns for error recovery

### Scope Discipline
Phase 1044 owns i18n locale fill (de/es/fr) + Playwright UAT + a11y verification + smoke. This phase ships English-only error/empty copy; non-en locales will be filled in Phase 1044.

</decisions>

<code_context>
## Existing Code Insights

Will be gathered during pattern mapping. Surfaces in scope:
- `frontend/src/components/builder/LayerEditorPanel.tsx` — section ordering across layer kinds
- `frontend/src/components/builder/{BasemapGroupEditorScene,BasemapSublayerEditorScene,DEMEditorScene,SettingsEditorScene}.tsx` — scene transitions
- Filter section + Labels section + Source section (likely sub-components in LayerEditorPanel or separate files)
- `frontend/src/components/builder/hooks/use-builder-layers.ts` — error states
- `frontend/src/i18n/locales/en/builder.json` — error/empty copy
- TanStack Query usage points (`isError`, `error`, `refetch`)

</code_context>

<specifics>
## Specific Ideas

### Error recovery pattern
- Inline error banner with retry button per failed query
- Use TanStack Query `isError`/`error` + `refetch()` (already wired)
- Localized copy: `errors.failedToLoad{Section}` + `errors.retry`

### Empty states
- Filter empty: "No filter conditions yet" + "Add condition" CTA
- Labels off: "Labels disabled" + "Enable labels" CTA
- Source no indexed columns: "No queryable columns" + link to ingestion docs
- Basemap-group LEP zero customization: "Default basemap settings" + reset/customize CTAs

### Section ordering
- Define canonical order: Style → Filter → Labels → Source → Advanced (or similar)
- Apply consistently across vector/raster/DEM/basemap-group; sections can hide if N/A but ordering is fixed

### Scene transition state preservation
- useRef for scroll position before navigating away
- Restore scroll on remount via useEffect
- Track focus via document.activeElement, restore via element.focus()

### Token sweep (carry-over from 1042)
- Search/replace `hover:bg-accent` → `hover:bg-[var(--surface-2)]` on the 7 sites the auditor flagged
- Migrate SettingsEditorScene 3 inline eyebrows to imported `eyebrowClassName`

</specifics>

<deferred>
## Deferred Ideas

- i18n locale fill (de/es/fr) — Phase 1044
- Playwright UAT — Phase 1044
- New backend error response shapes — out of scope
- Empty-state illustrations beyond iconography — out of scope

</deferred>
