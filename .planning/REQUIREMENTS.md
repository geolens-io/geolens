# Requirements: v1011 Map Builder Polish & Bug Sweep

**Defined:** 2026-05-17
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Milestone Goal:** Close 11 user-reported Map Builder polish/bug items via Playwright MCP inspect-verify-fix loop on live `localhost:8080` stack; surface and triage emergent issues found in flight.

**Shape:** Hygiene milestone, single phase (1051), sequential plans, single CTRL-01 close gate per `feedback_hygiene_milestone_pattern.md`. Mirrors v1009.1 Phase 1045 and v1010.2 Phase 1050.

**Execution path:** `/gsd-autonomous` with Playwright MCP orchestrator-scoped verification against live stack.

## v1011 Requirements

Each item is a discrete deliverable. All requirements verified via Playwright MCP on `http://localhost:8080` against a real stack before close.

### Broken Affordances (BUG)

- [x] **BUG-01**: User can toggle a regular (non-basemap, non-sublayer) layer's visibility on/off and the map reflects the change immediately. Repro before fix: `http://localhost:8080/maps/c868cc3a-a3a0-4714-b559-67b3f2b478e2` — Layer 1 visibility toggle is a no-op. Closes the source report. — ✅ SHIPPED 2026-05-17 (commit `8c6de63`) — adapter.addLayers contract fix + defense-in-depth syncVisibility.
- [x] **BUG-02**: User can delete a layer from the stack and the layer is removed from both the sidebar list AND the map render. Currently no-op. — ✅ SHIPPED 2026-05-18 (commit `eeeb8be8`) — handleRemove optimistic state update + rollback pattern lifted from handleBulkDelete.
- [x] **BUG-03**: User can click "Rename group" on a basemap or group row and the text input receives focus automatically (autofocus on the rename input). Currently focus is not applied — users must click into the input manually.

### UX Clarifications (UX)

- [x] **UX-01**: Layer-group expand caret meets touch-target size (≥24×24 px hit area; visible glyph ≥16 px or follows existing icon-size convention from `frontend/src/lib/icons` if larger). Current caret is too small to comfortably tap, especially on tablet.
- [ ] **UX-02**: Sublayer rows replace the per-row opacity slider with config-state indicators (badge/icon for: has labels, has filters, has data-driven styling, any other high-impact config). Opacity edits remain available through the LayerEditorPanel flyout. Indicators reflect live config state (mount-time + react to edits).
- [ ] **UX-03**: Basemap row is draggable in the layer order — user can position basemap at top of stack (for 3D maps showing elevation rendered above basemap context) OR bottom (default 2D map). Drag preserves the basemap-as-group semantics (basemap sublayers move with parent). Saved-map JSON encodes the basemap position.
- [ ] **UX-04**: Map Settings → Widgets section converts from duplicate on-map widget controls to enable/disable availability toggles (each widget has an on/off toggle that governs whether the widget renders on the map at all). On-map controls remain for live interaction with enabled widgets. Settings UI labels clearly state "Enable/disable widget" so the purpose is unambiguous.

### Small-Screen Responsive Layout (RESPONSIVE)

- [ ] **RESP-01**: At narrow viewport widths (≤1024 px viewport, exact breakpoint identified in flight via Playwright MCP), the collapsed right sidebar does NOT visually overlap or obscure the MapLibre zoom in/out controls. Either reflow the zoom controls, push them in from the edge, or constrain the sidebar collapse footprint.
- [ ] **RESP-02**: At narrow viewport widths, the lat/long/zoom coordinate readout pill does NOT overlap the map-widget container. Reflow, reposition, or z-order one above the other with clear non-overlap.
- [ ] **RESP-03**: At narrow viewport widths, the basemap selector flyout renders exactly ONE "X" close button (not two stacked). Audit other right-sidebar-opened elements (LayerEditorPanel flyout, settings drawer, etc.) for the same duplicate-close bug and fix any other occurrences found.

### Investigation-Then-Decision (INVESTIGATE)

- [ ] **INV-01**: DETAIL LEVEL toggle disposition resolved. Plan opens with a Playwright MCP + codebase-grep investigation step to identify the toggle's intended purpose (consumer, prop wiring, state). Findings surface mid-flight; orchestrator either (a) removes the toggle + its plumbing if no consumer exists or intent is unrecoverable, or (b) fixes the toggle if the consumer can be reconstructed. Disposition recorded in commit message + close-gate notes.

### Emergent Findings (EMERGENT)

- [ ] **EMRG-01**: Any additional Map Builder issues surfaced during Playwright MCP inspection of the 11 above are documented in `.planning/phases/1051-*/FINDINGS.md` with per-finding triage: severity, scope, fix-now-vs-defer decision, and rationale. Fix-now items become inline commits in the relevant plan; defer items become tech-debt entries in PROJECT.md Out-of-Scope or new pending todos in `.planning/todos/pending/` with the v1011 source citation.

### Close Gate (CTRL)

- [ ] **CTRL-01**: Single batched close gate runs at end of phase: `typecheck`, `vitest`, `e2e:smoke:builder`, and Playwright MCP re-verify of all 11 fixed items against fresh `docker compose up` stack. CHANGELOG `[Unreleased]` populated with v1011 fix notes (one bullet per BUG/UX/RESP/INV requirement). Per `feedback_review_findings_inline.md`: any code-review findings surfaced during gate get fixed inline before close, not deferred to v1011.1.

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| New Map Builder features beyond the 11 polish items | v1011 is a hygiene/polish round, not feature work — defer renderer expansion, AI capability, time-series, collaboration to dedicated milestones |
| Backend/API changes outside what's required to fix the 11 items | If a fix turns out to need a backend change (e.g., persisting basemap position), scope the minimum API surface; do not bundle broader backend refactors |
| Refactoring `MapBuilderPage`, builder hooks, or layer-adapters except where directly required to fix an item | Avoid the v1010-style code-quality audit pattern; this milestone is symptom-fix not structural cleanup |
| Mobile-phone optimization (<800 px portrait) | v1011 small-screen targets tablet and narrow desktop, not phone-portrait — already noted as separate scope per PROJECT.md |
| New i18n keys beyond what fixes/conversions strictly require | Translations added only for new visible strings introduced by INV-01 disposition or UX-04 widget toggles |
| New saved-map schema fields beyond what UX-03 (draggable basemap) requires | If basemap-position needs a single new field, add it minimally; do not introduce migration scaffolding for unrelated future state |

## Traceability

All 13 v1011 requirements mapped to Phase 1051 by gsd-roadmapper.

| Requirement | Phase | Status |
|-------------|-------|--------|
| BUG-01 | Phase 1051 | Complete (commit `8c6de63`) |
| BUG-02 | Phase 1051 | Complete (commit `eeeb8be8`) |
| BUG-03 | Phase 1051 | Complete (commit `80bddc14`) |
| UX-01 | Phase 1051 | Complete (commit `278e8933`) |
| UX-02 | Phase 1051 | Pending |
| UX-03 | Phase 1051 | Pending |
| UX-04 | Phase 1051 | Pending |
| RESP-01 | Phase 1051 | Pending |
| RESP-02 | Phase 1051 | Pending |
| RESP-03 | Phase 1051 | Pending |
| INV-01 | Phase 1051 | Pending |
| EMRG-01 | Phase 1051 | Pending |
| CTRL-01 | Phase 1051 | Pending |

**Coverage:**
- v1011 requirements: 13 total
- Mapped to phases: 13 (Phase 1051)
- Unmapped: 0 ✓

---
*Requirements defined: 2026-05-17*
*Last updated: 2026-05-18 — BUG-02 complete (Plan 1051-02, commit `eeeb8be8`)*
