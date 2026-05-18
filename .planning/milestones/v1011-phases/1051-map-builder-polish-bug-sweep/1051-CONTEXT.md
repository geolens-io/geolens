# Phase 1051: map-builder-polish-bug-sweep - Context

**Gathered:** 2026-05-17
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

Close 11 user-reported Map Builder polish/bug items (BUG-01..03, UX-01..04, RESP-01..03) via Playwright MCP inspect-verify-fix loop on live `localhost:8080` stack; triage emergent issues found in flight (EMRG-01); resolve INV-01 DETAIL LEVEL disposition; gate close with batched typecheck/vitest/e2e:smoke:builder/MCP re-verify (CTRL-01).

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — discuss phase was skipped per user setting. Use ROADMAP phase goal, success criteria, REQUIREMENTS.md traceability, and codebase conventions to guide decisions.

Specific guidance already embedded in ROADMAP Plans 01-13:
- Playwright MCP is orchestrator-scoped (live `localhost:8080` stack)
- Repro URL `http://localhost:8080/maps/c868cc3a-a3a0-4714-b559-67b3f2b478e2` for BUG-01
- INV-01 disposition (REMOVE vs FIX) decided in flight based on consumer trace
- Per `feedback_review_findings_inline.md`: code-review findings fixed inline at CTRL-01, not deferred
- Per `feedback_hygiene_milestone_pattern.md` shape: single phase, sequential plans, single CTRL-01 close gate
- Per v1010.2 SF-04..08 learnings: spot-check dedupe/blob revoke/anonymous-gate/single-PUT/basemap-latch surfaces during MCP re-verify

</decisions>

<code_context>
## Existing Code Insights

Codebase context will be gathered during plan-phase research (gsd-pattern-mapper + gsd-phase-researcher).

Known relevant surfaces from v1010 + v1010.2 close (per MEMORY.md):
- `frontend/src/components/builder/UnifiedStackPanel.tsx` — unified layer stack
- `frontend/src/components/builder/StackRow.tsx` — row rendering (visibility toggle, delete)
- `frontend/src/components/builder/BasemapGroupRow.tsx` — basemap-as-group sublayer rendering
- `frontend/src/components/builder/LayerEditorPanel.tsx` — flyout panel
- `frontend/src/components/builder/hooks/use-builder-layers.ts` — layer state hooks
- `frontend/src/components/builder/map-sync.ts` — MapLibre dispatch (`getSourceIdForLayer` helper at line 374)
- `frontend/src/components/builder/BuilderMap.tsx` — MapLibre container + NavigationControl
- `frontend/src/pages/MapBuilderPage.tsx` — page-level responsive layout
- `frontend/src/components/map/MapCoordReadout.tsx` — coord readout pill

</code_context>

<specifics>
## Specific Ideas

13 plans pre-defined in ROADMAP section for phase 1051. Each plan has its own goal, touches list, tasks, and success criteria. See ROADMAP.md `### Phase 1051` section for the authoritative plan definitions.

Plans:
1. BUG-01: layer visibility toggle is a no-op
2. BUG-02: delete-layer is a no-op
3. BUG-03: rename-group autofocus
4. UX-01: group-expand caret touch target
5. UX-02: sublayer config-state indicators (replace per-row opacity slider)
6. UX-03: draggable basemap row + saved-map persistence
7. UX-04: Map Settings → Widgets enable/disable toggles
8. RESP-01: sidebar/zoom-controls collision
9. RESP-02: coord-readout/map-widget overlap
10. RESP-03: duplicate close-button audit + fix
11. INV-01: DETAIL LEVEL toggle disposition
12. EMRG-01: emergent findings triage (FINDINGS.md)
13. CTRL-01: smoke gate + CHANGELOG + MCP re-verify

</specifics>

<deferred>
## Deferred Ideas

None — discuss phase skipped. Any new emergent decisions or scope adjustments will be triaged via Plan 12 EMRG-01.

</deferred>
