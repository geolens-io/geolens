# Requirements Archive: v1011 Map Builder Polish & Bug Sweep

**Archived:** 2026-05-18
**Status:** SHIPPED

For current requirements, see `.planning/REQUIREMENTS.md`.

---

# Milestone v1011 Requirements — Map Builder Polish & Bug Sweep

**Milestone version:** v1011
**Milestone name:** Map Builder Polish & Bug Sweep
**Defined:** 2026-05-17
**Goal:** Close 11 user-reported Map Builder polish/bug items (5 broken affordances, 3 small-screen layout collisions, 3 UX decisions, 1 investigation-then-decision) via Playwright MCP inspect-verify-fix loop on live `localhost:8080` stack; surface and triage emergent issues found in flight.

**Shape:** Hygiene milestone, single phase (1051), sequential plans, single CTRL-01 close gate per `feedback_hygiene_milestone_pattern.md`. Mirrors v1009.1 Phase 1045, v1010.1 Phase 1049, and v1010.2 Phase 1050.

**Execution path:** `/gsd-autonomous` with Playwright MCP orchestrator-scoped verification against live stack.

---

## v1011 Requirements

Each item is a discrete deliverable. All requirements verified via Playwright MCP on `http://localhost:8080` against a real stack before close.

### Broken Affordances (BUG)

- [x] **BUG-01**: User can toggle a regular (non-basemap, non-sublayer) layer's visibility on/off and the map reflects the change immediately. Repro before fix: `http://localhost:8080/maps/c868cc3a-a3a0-4714-b559-67b3f2b478e2` — Layer 1 visibility toggle is a no-op. — ✅ SHIPPED 2026-05-17 (commit `8c6de63`). Adapter contract fix at fill/line/circle/heatmap-adapter.addLayers (honor `input.visible` at initial add) + defense-in-depth `syncVisibility` invocation at every non-sync re-add caller (`swapLayerOnMap`, raster re-add in `handleStyleConfigChange`).
- [x] **BUG-02**: User can delete a layer from the stack and the layer is removed from both the sidebar list AND the map render. — ✅ SHIPPED 2026-05-18 (commit `eeeb8be8`). `handleRemove` gains the optimistic state update + rollback pattern lifted from `handleBulkDelete`: capture `previousLayers = layersRef.current`, `setLocalLayers` optimistically, `savedLayerBaselineRef.current` sync in onSuccess, `setLocalLayers(previousLayers)` rollback on onError.
- [x] **BUG-03**: User can click "Rename group" on a basemap or group row and the text input receives focus automatically. — ✅ SHIPPED 2026-05-18 (commit `80bddc14`). Fix at TWO levels: (a) `FolderGroupRow` editing useEffect wraps `inputRef.current.focus()` + `select()` in `requestAnimationFrame` so it runs AFTER Radix `restoreFocus` fires synchronously on menu close; (b) kebab Rename `DropdownMenuItem` `onSelect` no longer calls `_e.preventDefault()`. Defense in depth — regression on either lever alone won't re-introduce the bug.

### UX Clarifications (UX)

- [x] **UX-01**: Layer-group expand caret meets touch-target size (≥24×24 px hit area; visible glyph ≥16 px). — ✅ SHIPPED 2026-05-18 (commit `278e8933`). Caret swap from `text-xs` Unicode `▸` to `flex items-center justify-center h-6 w-6 -mx-1 rounded` button with `<ChevronRight className="h-4 w-4" />` glyph. `-mx-1` negative margin extends visual hit-box 24px without altering the locked `StackRow.tsx:174` grid template.
- [x] **UX-02**: Sublayer rows replace per-row opacity slider with config-state indicators (badge/icon for: has labels, has filters, has data-driven styling). Opacity edits remain available through the LayerEditorPanel flyout. Indicators reflect live config state. — ✅ SHIPPED 2026-05-18 (commits `79b0c0c6` + `a69d00ac`). New `SublayerConfigIndicators.tsx` pure-derivation component renders 0–4 Lucide-icon badges (Labels/Filter/DataDriven/OpacityModified). Slider removed from SublayerRow; Cell 6 grid column widened 60px → 76px.
- [x] **UX-03**: Basemap row is draggable in the layer order — user can position basemap at top of stack (for 3D maps) or bottom (default 2D map). Drag preserves basemap-as-group semantics. Saved-map JSON encodes the basemap position. — ✅ SHIPPED 2026-05-18 (commit `0957cf6d`). `BasemapGroupRowWrapper` lifted `useDroppable` → `useSortable`; `MapBasemapConfig.basemap_position: 'top' | 'bottom'` jsonb-additive (zero backend migration); new `reorderBasemapAboveData(map, position, sourcePrefix)` map-sync helper wired into 3 BuilderMap call sites; `MapBuilderPage.handleDragEnd` detects basemap drag BEFORE `arrayMove` and toggles position.
- [x] **UX-04**: Map Settings → Widgets section converts from duplicate on-map widget controls to enable/disable availability toggles. — ✅ SHIPPED 2026-05-18 (commit `57d88d01`). State-specific aria-labels ("Enable {{name}}" off / "Disable {{name}}" on) replace composite template + availability note paragraph. Duplicate-controls audit found 0 actual duplicates: `SettingsEditorScene` is availability source, `MapToolbar` is live-interaction (distinct role).

### Small-Screen Responsive Layout (RESPONSIVE)

- [x] **RESP-01**: At narrow viewport widths (≤1024 px), the collapsed right sidebar does NOT visually overlap or obscure the MapLibre zoom in/out controls. — ✅ SHIPPED 2026-05-18 (commit `391459bb`). MapLibre `NavigationControl` repositioned from `position="top-right"` → `position="top-left"` in `BuilderMap.tsx:924`. Pure-positioning Strategy A: NavigationControl's right-edge anchor visually clashed with the always-rendered `BuilderRail` 44px sibling at rail-mode widths (800-1099px); anchoring left eliminates collision at every width without conditional dispatch.
- [x] **RESP-02**: At narrow viewport widths, the lat/long/zoom coordinate readout pill does NOT overlap the map-widget container. — ✅ SHIPPED 2026-05-18 (commit `c6ab4fbd` initial + commit `4f4a9917` RESP-02-FOLLOWUP). Original collision provably already-resolved in BuilderMap context by RESP-01 (NavigationControl freed top-right zone); `MapCoordReadout` docstring extension codifies cross-context `right-14` load-bearing offset (viewer NavigationControl stays `top-right`). RESP-02-FOLLOWUP boundary regression discovered live during MCP re-verify (20×16 px overlap at 800px) → fixed inline via `data-builder-canvas="true"` attribute on BuilderMap outer wrapper + scoped CSS rule `[data-builder-canvas="true"] .maplibregl-ctrl-top-left { margin-top: 32px }` in `index.css`; ViewerMap context unaffected by attribute scoping.
- [x] **RESP-03**: At narrow viewport widths, right-sidebar Sheet overlays (basemap selector flyout, LayerEditorPanel flyout, mobile-rail Sheet) render exactly ONE "X" close button. — ✅ SHIPPED 2026-05-18 (commit `0a72cb58`). Both `<SheetContent>` instances in `MapBuilderPage.tsx` (editor flyout at line 1182 + mobile-rail flyout at line 1325) gain `showCloseButton={false}` opt-out; inner panels' canonical close affordances are single source of truth (LayerEditorPanel X at lines 316-325 + BuilderRail ChevronRight at lines 125-132). 8 regression tests including a NEGATIVE-CONTROL bug-shape pin (renders Sheet WITHOUT prop, asserts 2 close buttons) — protects against shadcn default-behavior drift. BasemapPicker.tsx confirmed dead per PATTERNS.md finding #6.

### Investigation-Then-Decision (INVESTIGATE)

- [x] **INV-01**: DETAIL LEVEL toggle disposition resolved. — ✅ SHIPPED 2026-05-18 (commit `6078b82a`). Disposition: **REMOVE**. Investigation confirmed dead wiring: `MapBuilderPage.tsx:838-839,847` passed hardcoded `activeDetailLevel="default"` + `isCustomized={false}` + `onDetailLevelChange={() => { /* TODO(Phase 1038) */ }}`; no consumer ever mutated MapLibre style. FIX requires 3-5 days of MapLibre style-mutation work across basemap presets — out of v1011 scope per Out-of-Scope row 1. Removed: DETAIL_LEVELS const, DetailLevel type, 3 props from BasemapSublayerEditorScene interface + signature, entire DETAIL LEVEL `<section>` JSX, 3 props from MapBuilderPage call site, 6 i18n keys × 4 locales = 24 entries. 7 files changed (+28/-153). New Test 13 as REMOVE-disposition regression pin.

### Emergent Findings (EMERGENT)

- [x] **EMRG-01**: Any additional Map Builder issues surfaced during Playwright MCP inspection of the 11 above are documented in `.planning/phases/1051-*/FINDINGS.md` with per-finding triage. — ✅ SHIPPED 2026-05-18 (commit `60b0f536`). FINDINGS.md authored with **4 emergent findings — all P2, all defer**: EMRG-FN-01 (BasemapSublayerEditorScene Phase 1038 sibling no-op callbacks → new pending todo `2026-05-18-basemap-sublayer-phase-1038-dead-stubs.md`), EMRG-FN-02 (settings.toggleWidget orphan i18n key from Plan 07 → SUMMARY cross-reference), EMRG-FN-03 (pre-existing UnifiedStackPanel unused-eslint-disable from Phase 1041 → SUMMARY cross-reference), EMRG-FN-04 (SublayerConfigIndicators receives layer=null for basemap sublayers → SUMMARY cross-reference, dependent on EMRG-FN-01). Zero fix-now. Orchestrator MCP backlog from Plans 01-11 aggregated INSIDE FINDINGS.md as appendix table for CTRL-01 reference.

### Close Gate (CTRL)

- [x] **CTRL-01**: Single batched close gate runs at end of phase: `typecheck`, `vitest`, `e2e:smoke:builder`, and Playwright MCP re-verify of all 11 fixed items against fresh `docker compose up` stack. CHANGELOG `[Unreleased]` populated with v1011 fix notes. Per `feedback_review_findings_inline.md`: any code-review findings surfaced during gate get fixed inline before close, not deferred to v1011.1. — ✅ SHIPPED 2026-05-18. Gate-fix commit `befe6a3b` (typecheck 0 / vitest 1974/1974 / e2e:smoke:builder 26/26 after 1 inline gate-fix for Plan-06-introduced dnd-kit collision regression at `e2e/builder-v1-5.spec.ts:152` — disable basemap-group droppable for catalog non-basemap drags via `useDndContext` + `disabled: { droppable: disableForCatalogNonBasemap }`). RESP-02-FOLLOWUP boundary regression discovered + fixed inline via commit `4f4a9917`. 21 code-review findings (iter-1: 17 / iter-2: 4) all fixed inline; zero v1011.1 deferrals. Playwright MCP re-verify 11/11 PASS + v1010.2 SF-04..08 spot-check.

---

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| New Map Builder features beyond the 11 polish items | v1011 is a hygiene/polish round, not feature work — defer renderer expansion, AI capability, time-series, collaboration to dedicated milestones |
| Backend/API changes outside what's required to fix the 11 items | If a fix turns out to need a backend change (e.g., persisting basemap position), scope the minimum API surface; do not bundle broader backend refactors |
| Refactoring `MapBuilderPage`, builder hooks, or layer-adapters except where directly required to fix an item | Avoid the v1010-style code-quality audit pattern; this milestone is symptom-fix not structural cleanup |
| Mobile-phone optimization (<800 px portrait) | v1011 small-screen targets tablet and narrow desktop, not phone-portrait — already noted as separate scope per PROJECT.md |
| New i18n keys beyond what fixes/conversions strictly require | Translations added only for new visible strings introduced by INV-01 disposition or UX-04 widget toggles |
| New saved-map schema fields beyond what UX-03 (draggable basemap) requires | UX-03 ultimately needed only an optional `basemap_position` field on `MapBasemapConfig` — jsonb-additive, zero backend migration |

---

## Traceability

All 13 v1011 requirements mapped to Phase 1051 by gsd-roadmapper.

| Requirement | Phase | Status | Final Commit(s) |
|-------------|-------|--------|-----------------|
| BUG-01 | Phase 1051 | Complete | `8c6de63` |
| BUG-02 | Phase 1051 | Complete | `eeeb8be8` |
| BUG-03 | Phase 1051 | Complete | `80bddc14` |
| UX-01 | Phase 1051 | Complete | `278e8933` |
| UX-02 | Phase 1051 | Complete | `79b0c0c6` + `a69d00ac` |
| UX-03 | Phase 1051 | Complete | `0957cf6d` |
| UX-04 | Phase 1051 | Complete | `57d88d01` |
| RESP-01 | Phase 1051 | Complete | `391459bb` |
| RESP-02 | Phase 1051 | Complete | `c6ab4fbd` + `4f4a9917` (FOLLOWUP) |
| RESP-03 | Phase 1051 | Complete | `0a72cb58` |
| INV-01 | Phase 1051 | Complete (REMOVE) | `6078b82a` |
| EMRG-01 | Phase 1051 | Complete (0 fix-now / 4 defer) | `60b0f536` |
| CTRL-01 | Phase 1051 | Complete | `befe6a3b` (gate-fix) + close-gate commit |

**Coverage:**
- v1011 requirements: 13 total
- Mapped to phases: 13 (Phase 1051) ✓
- Unmapped: 0 ✓
- Complete: 13 / 13 ✓
- Deferred to v1011.1: 0 ✓

---

## Outcomes Note

**Validated as shipped:** All 13 requirements validated by live Playwright MCP on `localhost:8080` (11/11 user-reported items PASS + INV-01 grep-clean + EMRG-01 FINDINGS.md exists + CTRL-01 gate green). One in-flight boundary regression (RESP-02-FOLLOWUP at 800px) discovered + fixed inline during MCP re-verify, demonstrating the `feedback_review_findings_inline.md` "default to fixing all inline" pattern continues to pay off.

**No requirements changed shape during execution.** UX-03 (basemap position persistence) was scoped at planning time to allow either an explicit field or layer-order derivation; the final implementation chose the explicit jsonb-additive `MapBasemapConfig.basemap_position` field — both options were anticipated in the requirement's text.

**Pattern established:** v1011 reinforces v1010.2's lesson — post-implementation code review (iter-1 + iter-2) routinely catches secondary findings that the planner's `deep_work` rules don't pre-empt. Fixing them inline (21 fixes across 2 iterations) was correct; deferring would have produced a v1011.1.

---

*Requirements defined: 2026-05-17*
*Requirements shipped: 2026-05-18*
*Archived: 2026-05-18 by /gsd-complete-milestone*
