# Requirements: v1010 Builder Performance & Code Quality

**Defined:** 2026-05-16
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.

**Milestone goal:** Improve Map Builder performance under load (large saved maps, bulk-ops, MapLibre repaint, bundle weight) and lock in code-quality wins via an audit-first sweep — while clearing three carried-forward builder follow-ups.

## v1010 Requirements

Requirements for this milestone. Each maps to a roadmap phase.

### Performance (PERF)

- [ ] **PERF-01**: User can open a saved map with 50+ layers and see first paint complete inside a measured budget. Baseline captured at audit time; target documented in phase notes; verified by an automated perf check or Playwright timing assertion.
- [ ] **PERF-02**: User can hover/click rows in the unified stack on a 50+ layer map without per-row jank. Target: input latency under 16ms on a representative dev laptop; verified by profiling notes + smoke pass.
- [ ] **PERF-03**: User-triggered bulk visibility/opacity/group/ungroup/delete on N selected layers batches requests (Promise.allSettled or batched endpoint) with rollback + progress affordances. No regression in the existing v1009 multi-select bulk-ops surface.
- [ ] **PERF-04**: User-typed paint property updates (color pick, opacity slider, expression edits) coalesce into one MapLibre repaint per animation frame via debounce / requestAnimationFrame. Verified by perf profile + unit-level rAF coalescing test.
- [ ] **PERF-05**: Builder route entry chunk shrinks via lazy-load of LayerEditorPanel, AddDataModal, and the Settings scene. Before/after chunk sizes documented in phase notes; no regression in first-paint to first-interactive on `/maps/:id`.
- [ ] **PERF-06**: All perf changes ship with measured before/after metrics in PHASE notes; no measurable regression in builder smoke runtime, vitest builder suite runtime, or cold first build.

### Code Quality (CODE)

- [ ] **CODE-01**: `BUILDER-CODE-AUDIT.md` documents structured findings (duplication, file-size offenders, dead code, complexity hotspots) classified P0/P1/P2 across `frontend/src/components/builder/`, `frontend/src/hooks/use-builder-*`, and `frontend/src/lib/builder-*` (and any adjacent `basemap-utils.ts` / `fill-adapter.ts` style helpers used by builder).
- [ ] **CODE-02**: All P0 audit findings are remediated and committed with regression tests where applicable.
- [ ] **CODE-03**: All P1 audit findings are remediated OR explicitly deferred-with-rationale in the audit doc; no silent skips.
- [ ] **CODE-04**: No new dead code remains in audited directories; audit re-verification step in closeout confirms removal.
- [ ] **CODE-05**: File-size offenders either drop below a milestone-defined LOC threshold OR are explicitly accepted with rationale (e.g., generated SDK code, fixture data).
- [ ] **CODE-06**: No behavior regressions from code-quality refactors: vitest builder suite green, builder smoke green, typecheck clean, public component contracts preserved.

### Carried-forward Followups (FOLLOWUP)

- [ ] **FOLLOWUP-01**: Invalid `popup_config` no longer silently blocks PUT round-trip. User sees a visible, actionable error toast/banner. Backend rejection path surfaces a structured error the frontend can render. Vitest covers the failure surface; e2e covers the success-path round-trip on the once-blocked test map.
- [ ] **FOLLOWUP-02**: Add Data modal audit completes. Findings surfaced in audit doc, P0 fixes shipped inline or as targeted plans, deferred items documented with rationale. Alignment with v1008 unified-stack model verified (no leftover six-section assumptions).
- [ ] **FOLLOWUP-03**: SourcesTab `it.todo` backlog (8 items at `.planning/backlog/SourcesTab-test-todos.md`) resolved — items either ship as live tests OR migrate to documented backlog with rationale; net `it.todo` count drops to zero on the closeout.

### Closeout (CLOSE)

- [ ] **CLOSE-01**: Smoke gate green at milestone close — typecheck clean, vitest builder suite (no regressions vs pre-milestone count), builder smoke (Playwright) green, i18n parity green, frontend coverage thresholds met.
- [ ] **CLOSE-02**: `CHANGELOG.md` `[Unreleased]` section populated with v1010 user-visible changes (perf wins quantified, follow-up bug fixes, audit deliverable).

## Future Requirements

Deferred to a future milestone. Tracked but not in this roadmap.

### Mobile / Responsive

- Mobile builder polish (drill-down Sheet under 800px), touch-target verification, mobile-first AddData, mobile bulk-ops affordances.

### AI Authoring

- AI-assisted authoring: prompt-to-layer, AI-driven map title/description, AI-driven legend authoring, smarter `ai-style` suggestions.

### Render Modes

- Extruded polygons (beyond `paint._height_column` initial drop), animated lines, heatmap polish, dot-density, additional 3D building modes.

### Widgets

- Custom legend authoring, scale-bar customization beyond v1009.1 `1:N`, configurable north-arrow / compass, fullscreen control polish, mini-map widget.

### History / Undo

- History panel UX iteration, named snapshots, branch undo, recoverable corrupted-state flows.

## Out of Scope

Explicitly excluded for v1010. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| New design tokens / visual vocabulary | Milestone reuses `sketch-findings-geolens` per v1009 constraint |
| Backend schema changes | Perf must work over existing routes; bulk-op batching may add ONE additive endpoint if essential, documented as exception |
| New AI / chat capability work | Deferred to a dedicated AI milestone |
| Cross-repo (`getgeolens.com`) work | Owned by sibling repo's `.planning/` |
| Mobile-first builder | Deferred (see Future Requirements) |
| New render modes (extruded poly, animated line, etc.) | Deferred (see Future Requirements) |
| New widgets (custom legend, north arrow) | Deferred (see Future Requirements) |
| History panel UX changes | Deferred (see Future Requirements) |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| PERF-01 | Phase 1047 | Pending |
| PERF-02 | Phase 1047 | Pending |
| PERF-03 | Phase 1047 | Pending |
| PERF-04 | Phase 1047 | Pending |
| PERF-05 | Phase 1047 | Pending |
| PERF-06 | Phase 1047 | Pending |
| CODE-01 | Phase 1046 | Pending |
| CODE-02 | Phase 1047 | Pending |
| CODE-03 | Phase 1047 | Pending |
| CODE-04 | Phase 1047 | Pending |
| CODE-05 | Phase 1047 | Pending |
| CODE-06 | Phase 1047 | Pending |
| FOLLOWUP-01 | Phase 1048 | Pending |
| FOLLOWUP-02 | Phase 1048 | Pending |
| FOLLOWUP-03 | Phase 1048 | Pending |
| CLOSE-01 | Phase 1048 | Pending |
| CLOSE-02 | Phase 1048 | Pending |

**Coverage:**
- v1010 requirements: 17 total
- Mapped to phases: 17
- Unmapped: 0

---
*Requirements defined: 2026-05-16*
*Last updated: 2026-05-16 after roadmap creation*
