---
milestone: v1009
milestone_name: Map Builder v1.5 (Polish)
audited: 2026-05-15
status: passed
scores:
  requirements: 25/25
  phases: 6/6
  integration: 18/18 (1 BLOCKER B-01 fixed inline; W-01 doc-cleanup fixed inline)
  flows: 6/6 (Flow 6 freshLayerId entry-animation now wired post-fix)
gaps:
  requirements: []
  integration: []
  flows: []
tech_debt:
  - phase: 1041 multi-layer-selection-and-bulk-ops
    items:
      - "W-02 (Phase 1044 integration check): BulkActionBar renders role='alertdialog' inside role='toolbar' — invalid ARIA ownership. Functional but non-conformant. Future: move confirm into a Radix AlertDialog portal."
  - phase: 1044 cross-cutting-closeout
    items:
      - "W-03 (integration check): e2e/builder-v1-5.spec.ts Test 1 has documented MapLibre WebGL 'pt' console-error flake on cold start. Add 'pt' to assertConsoleClean allowlist OR set test.retries(1)."
      - "W-04 (integration check): Tests 3+4 use element.dispatchEvent('click') instead of Playwright .click() to avoid mousedown race with outside-click handler. Document the pattern in e2e helpers; consider migrating BulkActionBar to suppress outside-click during in-bar interactions."
  - phase: 1042 spacing-density-states-polish
    items:
      - "Top-level hover token sweep is partial — 15 residual hover:bg-accent occurrences remain in 10 non-builder-core files (BuilderRail, MapToolbar, ChatPanel, SharePanel, BasemapPicker, MapTitleBar, PopupConfigEditor, ColorRampPicker, IconPicker, MentionDropdown). Not in v1009 scope but worth future sweep."
deferred_to_phase_1044:
  - "Manual screen-reader (VoiceOver/NVDA) verification of drag-from-catalog + multi-select keyboard paths. Documented in 1044-A11Y-WALKTHROUGH.md as optional enhancement."
nyquist:
  status: skipped
  reason: "workflow.nyquist_validation not enabled for v1009; no VALIDATION.md files in any phase."
backlog_not_in_scope:
  - "999.6 — Tenant scoping infrastructure (Cloud prerequisite)"
  - "999.13 — Persistent connector registry"
  - "999.14 — Helm chart + AMI Packer pipeline"
  - "999.15 — SBOM + signed image distribution"
  - "999.16 — Extract geolens-schemas package"
---

# v1009 Map Builder v1.5 (Polish) — Milestone Audit

**Status: PASSED** — all 25 POL requirements satisfied; 6/6 phases verified; cross-phase integration complete; 1 BLOCKER + 1 doc-cleanup found and fixed inline during audit.

## Summary

| Metric | Result |
|---|---|
| Phases shipped | 6/6 (1039, 1040, 1041, 1042, 1043, 1044) |
| Requirements satisfied | 25/25 (POL-01..25) |
| Total plans executed | 22 across 6 phases |
| Final smoke gate | typecheck 0 errors; vitest 799/799 + 54/54 pages; i18n 2/2; e2e:smoke:builder 25/25 |
| Locales at parity | en/de/es/fr — 770 keys each, 0 missing |
| New tests added | +13 (1040) + +55 (1041) + +83 (1042) + +10 (1044 a11y) + +4 (1044 e2e) = 165 |
| Code review fixes applied inline | 31 (across 1040/1041/1042/1043/1044) |
| Integration check BLOCKERs (audit) | 1 (B-01 freshLayerId wiring) — fixed inline (commit b1d1c289) |

## Requirements Coverage

All 25 POL requirements (POL-01..25) checked `[x]` in REQUIREMENTS.md after inline doc-cleanup (W-01).

| Group | Reqs | Phase | Status |
|---|---|---|---|
| Drag from Catalog | POL-01..05 | 1040 | satisfied |
| Multi-Layer Selection + Bulk Ops | POL-06..11 | 1041 | satisfied |
| UI/UX Audit Survey + Polish | POL-12..18 | 1039/1042/1043 | satisfied |
| Builder Test Debt Closeout | POL-19..21 | 1039 | satisfied |
| Cross-Cutting Closeout | POL-22..25 | 1044 | satisfied |

## Phase Scorecards

| Phase | Plans | Tests Added | Verification | Code Review Fixes | UI Review Score |
|---|---|---|---|---|---|
| 1039 ux-audit-and-test-debt-closeout | 2 | (pre-existing test repairs) | passed (POL-12/19/20/21) | n/a | n/a |
| 1040 drag-from-catalog-into-stack | 4 | +13 | human_needed (6/6 auto) | 2C+4W+1IN → 7 commits | 20/24 |
| 1041 multi-layer-selection-and-bulk-ops | 4 | +55 | human_needed (7/7 auto) | 2C+4W+1IN → 7 commits | 20/24 |
| 1042 spacing-density-states-polish | 4 (3 parallel) | +83 | human_needed (10/10 auto) | 1C+4W → 5 commits | 18/24 |
| 1043 error-empty-states-and-ia-cleanup | 4 | parity holds | human_needed (7/7 auto) | 3C+3W+1IN → 7 commits | 18/24 (Exp 4/4) |
| 1044 cross-cutting-closeout | 4 (2 parallel) | +10 a11y + +4 e2e | **passed** | 0C+3W+2IN → 5 commits | n/a |

Per AskUserQuestion at each phase, human verification was deferred to Phase 1044 Playwright UAT for all phases that produced `human_needed`. Phase 1044 verifies the full surface via 4 e2e tests + 10 vitest a11y contracts + 1044-A11Y-WALKTHROUGH.md.

## Integration Check Findings (inline-fixed)

### BLOCKER — B-01 fixed inline (commit b1d1c289)
`freshLayerId` prop was computed in `use-builder-layers.ts:955` and accepted by `UnifiedStackPanel` (typed prop with `null` default) but never passed from `MapBuilderPage.tsx`. The new-row entry animation was silently dead in production. One-line fix: added `freshLayerId={layers.freshLayerId}` to the `<UnifiedStackPanel>` prop list in MapBuilderPage. Affects POL-14, POL-15. Test verification post-fix: tsc 0 errors; pages vitest 54/54 PASS.

### Warning — W-01 fixed inline (commit b1d1c289)
REQUIREMENTS.md had stale `[ ]` checkboxes for POL-12/19/20/21 (Phase 1039 requirements). All four are confirmed satisfied per 1039-VERIFICATION.md + summaries; checkboxes flipped to `[x]`.

### Warnings tracked as tech debt (non-blocking)
- W-02: BulkActionBar's `role="alertdialog"` inside `role="toolbar"` is invalid ARIA ownership. Functional but non-conformant. Future: move confirm into Radix AlertDialog portal.
- W-03: e2e Test 1 "pt" MapLibre WebGL flake — add to allowlist or use test.retries(1).
- W-04: e2e Tests 3+4 use dispatchEvent('click') workaround for outside-click race. Document the pattern.

## Cross-Phase Wiring Map (all verified WIRED after B-01 fix)

| Connection | Status |
|---|---|
| Phase 1040 DnD lift → Phase 1041 drag-start clears selectedIds | WIRED (handleDragStart in MapBuilderPage) |
| Phase 1041 selectedIds Set → Phase 1042 freshLayerId interaction | WIRED |
| Phase 1042 motion tokens → Phase 1043 LayerEditorPanel scroll/focus | WIRED (duration-[--motion-fast] consumes index.css :root) |
| Phase 1043 error/empty copy → Phase 1044 i18n locale fill | WIRED (770 keys parity en/de/es/fr) |
| Phase 1044 e2e/builder-v1-5.spec.ts covers Phase 1040 + 1041 features | WIRED (4 scenarios passing in smoke) |
| Phase 1042 freshLayerId hook → UnifiedStackPanel → StackRow | **WIRED post-fix** (was BLOCKER B-01) |

## E2E Flow Verification

| # | Flow | Reqs | Status |
|---|---|---|---|
| 1 | Drag dataset → stack → layer added | POL-01..05 | WIRED + e2e Test 1 |
| 2 | Multi-select → bulk delete → confirm → remove | POL-06..11 | WIRED + e2e Tests 3/4 |
| 3 | Async fetch failure → retry banner → succeed | POL-16 | WIRED (unit-tested) |
| 4 | Locale switch en/de/es/fr → all strings translated | POL-22 | WIRED (770/770 parity) |
| 5 | Keyboard-only walkthrough drag + multi-select | POL-23 | WIRED + 10 a11y vitest + walkthrough doc |
| 6 | New stack row entry animation (freshLayerId) | POL-14/15 | WIRED post-B-01 fix |

## Backlog (not in scope of v1009)

5 phases at `999.x` are explicitly tagged BACKLOG and out-of-scope for v1009:
- 999.6 Tenant scoping infrastructure (Cloud prerequisite)
- 999.13 Persistent connector registry
- 999.14 Helm chart + AMI Packer pipeline
- 999.15 SBOM + signed image distribution
- 999.16 Extract geolens-schemas package

These remain in the backlog for a future milestone.

## Recommendation: **GO** — proceed to `/gsd-complete-milestone v1009`
