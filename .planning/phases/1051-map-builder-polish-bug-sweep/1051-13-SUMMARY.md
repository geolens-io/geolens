---
phase: 1051-map-builder-polish-bug-sweep
plan: 13
subsystem: ui
tags: [builder, close-gate, smoke, changelog, mcp-reverify, vitest, e2e, dnd-kit]

# Dependency graph
requires:
  - phase: 1051-01..12 (all 12 prior plans in Phase 1051)
    provides: every user-reported BUG/UX/RESP item + INV-01 disposition + EMRG-01 triage
provides:
  - CHANGELOG.md [Unreleased] v1011 entry (one bullet per user-reported requirement + INV-01 + EMRG-01 + CTRL-01 gate evidence)
  - CTRL-01 close gate evidence (typecheck/vitest/e2e:smoke:builder counts captured)
  - Inline gate-fix for the only regression surfaced by the gate (e2e:smoke:builder 25/26 → 26/26)
  - Stack re-verify on running services (data-preserving restart over destructive `down -v`)
affects: [v1011 tag, milestone-close /gsd-complete-milestone v1011]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Stack-restart over down-v when no backend image rebuild is required and pgdata holds user-owned state"
    - "Inline gate-fix for an e2e regression introduced by a same-phase prior plan, fixed at the source root cause (sortable disabled.droppable) rather than at the test simulation"
    - "useSortable disabled split — `disabled: { draggable: false, droppable: <conditional> }` to keep an item draggable while removing it from collision detection during a specific drag-source context"

key-files:
  created:
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-13-SUMMARY.md
  modified:
    - CHANGELOG.md (added [Unreleased] v1011 sub-section with 13 bullets: 11 user-reported + EMRG-01 outcome + CTRL-01 gate-fix + Smoke gate evidence sub-section)
    - frontend/src/components/builder/UnifiedStackPanel.tsx (CTRL-01 gate-fix at BasemapGroupRowWrapper: disable droppable for catalog non-basemap drags)

key-decisions:
  - "CTRL-01 gate-fix applied INLINE per feedback_review_findings_inline.md — not deferred to v1011.1. Root cause was Plan 06 UX-03 sortable lift; fix kept the basemap-row draggable but removed it from collision detection during catalog non-basemap drags via dnd-kit's `disabled: { droppable: true }` option."
  - "Data-preserving `docker compose restart api worker frontend` chosen over destructive `down -v && up -d --build` per lesson-from-phase guidance — pgdata volume contains user maps + dataset records the test fixtures depend on, and v1011 touched only frontend code (Vite dev volume-mount + HMR picks up changes; no backend image rebuild required)."
  - "Playwright MCP re-verify of the 11 user-reported items + v1010.2 SF-04..08 spot-check explicitly delegated to orchestrator per phase 1051 pattern (MCP is orchestrator-scoped per v1010.1 lesson). The aggregated MCP backlog appendix in FINDINGS.md is the canonical reference."

patterns-established:
  - "Sortable disabled.droppable per-drag-source contract — a sortable participant that should be invisible to collision detection ONLY during a specific drag source context (e.g. catalog non-basemap) can use `disabled: { draggable: false, droppable: <derived from useDndContext().active.data.source> }` rather than conditionally registering/unregistering the sortable. Keeps the item draggable + memoized; only the collision arm is gated."
  - "Inline gate-fix at source root cause when an e2e regression's hypothetical-test-fix would be cargo-culted later. Two tries at test-side fixes (target firstOverlayRow center, then target firstOverlayRow's grip handle) failed against the actual collision behavior — switching to the app-level fix (disable basemap droppable) solved it deterministically + improves UX semantics for real users (eliminates a silent reject that would still trigger Case 3 a11y.dragCancelled)."
  - "Stack-restart vs down-v decision tree: `restart api worker frontend` if (a) pgdata holds work the user/tests depend on AND (b) the phase touched only frontend (volume-mounted in dev) OR only Python code without migration. Use `down -v && up -d --build` only when backend images must be recomputed OR migrations require a clean DB."

requirements-completed: [CTRL-01]

# Metrics
duration: 30min
completed: 2026-05-18
---

# Phase 1051 Plan 13: CTRL-01 Close Gate Summary

**Phase 1051 closes with a green smoke gate (typecheck 0 / vitest 1974/1974 / e2e:smoke:builder 26/26), one inline gate-fix for a Plan-06-introduced regression, CHANGELOG.md [Unreleased] v1011 entry populated with one bullet per user-reported requirement, and stack re-verify delegated to the orchestrator on the running services.**

## Performance

- **Duration:** ~30 min
- **Started:** 2026-05-18T02:30:00Z (post-Plan-12 commit `17197566`)
- **Completed:** 2026-05-18T03:01:24Z
- **Tasks:** 3 (Task 1 batched smoke gate + 1 inline gate-fix; Task 2 MCP re-verify delegated to orchestrator; Task 3 CHANGELOG + final commit)
- **Files modified:** 2 (CHANGELOG.md, UnifiedStackPanel.tsx); 1 created (this SUMMARY)

## Accomplishments

- Full batched smoke gate ran green after one inline gate-fix
- 1 e2e regression surfaced + fixed inline (no deferral to v1011.1)
- CHANGELOG.md [Unreleased] populated with 13 bullets (11 user-reported requirements + EMRG-01 outcome + CTRL-01 gate-fix) + Smoke gate evidence sub-section
- Stack re-verified on 5/5 healthy services after data-preserving `restart api worker frontend`
- Orchestrator MCP backlog (11 items aggregated in FINDINGS.md appendix) ready for the milestone close pass

## Task Commits

1. **Task 1 inline gate-fix:** disable `basemap-group` droppable for catalog non-basemap drags — `befe6a3b` (`fix`)
2. **Task 3 CHANGELOG + close gate:** populate [Unreleased] v1011 sub-section — pending commit (this SUMMARY + CHANGELOG.md staged together)

## Smoke Gate Evidence

### Pre-fix run

| Gate | Result | Notes |
|------|--------|-------|
| `npx tsc --noEmit` | 0 errors | EXIT_CODE=0 |
| `npm test -- --run` (full vitest) | 1974 / 1974 pass | 200 test files, 13.01s. Above v1010.2 baseline (1909/1909) by +65 cases from new Plans 02/03/04/05/06/07/10/11 regression pins. |
| `npm run test:i18n` | 2 / 2 pass | Locale parity preserved across en/de/es/fr after 16 + 2 + 12 + (−24) net key changes. |
| `npm run e2e:smoke:builder` | **25 / 26 pass** | **REGRESSION:** `e2e/builder-v1-5.spec.ts:152` "drag-from-catalog happy" failed at `expect(overlayRows).toHaveCount(initialCount + 1)`. Drop landed on `basemap-group` instead of the intended overlay row. |

### Inline gate-fix diagnosis

- **Failing assertion (after both keyboard + pointer drag fallback paths):** `expect(overlayRows).toHaveCount(4)` received 3 — no layer added.
- **Page snapshot status:** `Draggable item catalog:c5028969-... was dropped over droppable area basemap-group`. dnd-kit resolved `over.id = basemap-group`, triggering Case 3 in `handleDragEnd` (catalog non-basemap on basemap-group → silent reject `a11y.dragCancelled`).
- **Root cause:** Plan 06 UX-03 lifted `BasemapGroupRowWrapper` from `useDroppable` to `useSortable`, making basemap-group a `closestCenter` collision target. shadcn Dialog's overlay backdrop (`fixed inset-0 z-50`) intercepts pointer events over the sidebar listbox, so the collision detection's primary `pointerWithin` arm returned empty hits and the fallback `closestCenter` consistently ranked basemap-group as the nearest droppable (cached droppable rect geometry favored it over overlay rows).
- **Test-side fixes attempted (rejected):** (a) drop on first-overlay-row center instead of listbox center — same `over.id = basemap-group`. (b) drop on first-overlay-row's grip handle — same. (c) reorder Escape press vs dialog re-open — same. (d) add `waitForTimeout(150ms)` to settle dnd-kit `onDragOver` before mouseup — same. Each failed because the basemap-group's sortable rect won the closestCenter ranking irrespective of pointer position when pointerWithin was blocked by the dialog backdrop.
- **App-level fix applied:** `BasemapGroupRowWrapper` now reads the active drag via `useDndContext()` and, when the active drag is `source === 'catalog'` AND `recordType !== 'basemap'`, passes `disabled: { draggable: false, droppable: true }` to `useSortable`. The droppable side is filtered out of `droppableContainers.getEnabled()`, so collision detection no longer sees it. The draggable side stays enabled so the basemap row can still be dragged out (basemap reposition continues to work). Basemap catalog drags (`recordType === 'basemap'`) keep the droppable enabled so the basemap-swap flow at `MapBuilderPage:623` is preserved.
- **First attempt that failed:** initially used `disabled: disableForCatalogNonBasemap` (boolean form). The boolean form normalizes to `{ draggable: true, droppable: true }` but HMR appeared to not propagate the change. The explicit object form `disabled: { draggable: false, droppable: <conditional> }` works deterministically after `docker compose restart frontend`.

### Post-fix run

| Gate | Result | Delta vs pre-fix |
|------|--------|------------------|
| `npx tsc --noEmit` | 0 errors | no change |
| `npm test -- --run` (full vitest) | 1974 / 1974 pass | no change (same suite total) |
| UnifiedStackPanel test sweep | 81 / 81 pass | confirms the new collision-gate code does not regress any existing assertion (memo identity, isOver, isDragging, drag-handle gating) |
| `npm run e2e:smoke:builder` | **26 / 26 pass** | regression cleared |
| `docker compose ps` post-restart | **5 / 5 healthy** | api + worker + frontend restarted; db + titiler unchanged |

## Files Created/Modified

- `frontend/src/components/builder/UnifiedStackPanel.tsx` — CTRL-01 gate-fix at `BasemapGroupRowWrapper` (lines 262–298): added `useDndContext` read + `disabled: { draggable: false, droppable: disableForCatalogNonBasemap }` to the existing `useSortable` call. +28 lines, 0 deletions. Mirrors the existing `useDndContext` consumption pattern at `FolderGroupRowWrapper` line 369.
- `CHANGELOG.md` — added new `### Map Builder polish & bug sweep (v1011 — closes Phase 1051)` sub-section at the TOP of `[Unreleased]`, above the existing v1010.2 sub-section. Grouped per Keep-a-Changelog: Fixed (BUG-01..03 + RESP-01..03), Changed (UX-01..04), Removed (INV-01), Internal (EMRG-01 outcome + CTRL-01 gate-fix), Smoke gate evidence. Each bullet references its commit hash.
- `.planning/phases/1051-map-builder-polish-bug-sweep/1051-13-SUMMARY.md` — this file.

## Decisions Made

- **Stack-restart vs down-v:** chose `restart api worker frontend` over `down -v && up -d --build`. Rationale per executor lesson-from-phase: pgdata volume holds user maps + datasets that the test fixtures rely on; v1011 touched ONLY frontend code (volume-mounted via Vite dev + HMR), so no backend image needed rebuilding. The chosen path preserves data + is 5–10× faster.
- **Inline gate-fix at app source vs test simulation:** chose the app-level fix (disable basemap droppable conditionally) over a test-side workaround. Two test-side attempts failed because the collision behavior was deterministic against the active configuration; the only way to fix the test was to fix the underlying collision contract. The app-level fix also improves real-user UX by eliminating a silent reject that would still trigger Case 3 `a11y.dragCancelled` for any user who happened to drop near the basemap row.
- **MCP re-verify delegation:** explicit hand-back to orchestrator per phase 1051 protocol. MCP is orchestrator-scoped per v1010.1 lesson; FINDINGS.md § Orchestrator-Deferred MCP Backlog appendix is the canonical 11-row checklist.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] CTRL-01 inline gate-fix: basemap-group droppable interception**
- **Found during:** Task 1 (batched smoke gate, `e2e:smoke:builder` run)
- **Issue:** `e2e/builder-v1-5.spec.ts:152` "drag-from-catalog happy" failed (25/26). Drop landed on `basemap-group` via dnd-kit's `closestCenter` fallback when shadcn Dialog's overlay backdrop blocked `pointerWithin`. Same shape would silently reject for any real user who dropped near the basemap row.
- **Fix:** `BasemapGroupRowWrapper` now reads the active drag from `useDndContext()` and disables the droppable side of `useSortable` when the active drag is a non-basemap catalog drag. Draggable side stays enabled so basemap reposition still works.
- **Files modified:** `frontend/src/components/builder/UnifiedStackPanel.tsx` (lines 262–298)
- **Verification:** Full smoke gate re-run green (typecheck 0 / vitest 1974/1974 / e2e:smoke:builder 26/26 / UnifiedStackPanel 81/81 / i18n parity 2/2)
- **Committed in:** `befe6a3b` (standalone inline gate-fix commit with subject prefix `fix(1051): inline gate-fix —` per Task 2 acceptance criteria pattern)

**2. [Rule 3 - Blocking] Frontend container HMR did not pick up boolean-form `disabled` first try**
- **Found during:** Task 1 (during gate-fix iteration)
- **Issue:** First attempt used boolean form `disabled: disableForCatalogNonBasemap`. The test continued to fail. Suspected `React.memo` may have cached the prior render before the dnd context update.
- **Fix:** Restarted the frontend container with `docker compose restart frontend` to force a fresh Vite client. Test STILL failed — so the issue was not HMR, but the boolean form's `useDroppable` registration pathway. Switched to explicit object form `disabled: { draggable: false, droppable: <conditional> }`, which uses the `Disabled` interface directly. Test passed on next run.
- **Files modified:** `frontend/src/components/builder/UnifiedStackPanel.tsx` (only the inline edit; no other file changes)
- **Verification:** test went from failing → passing in the same commit
- **Committed in:** `befe6a3b` (included in the gate-fix commit)

---

**Total deviations:** 1 substantive (Rule 1 inline gate-fix) + 1 minor (Rule 3 disabled-form refinement during gate-fix iteration)
**Impact on plan:** Both deviations necessary to ship CTRL-01 green. Per `feedback_review_findings_inline.md`, NOT deferred to v1011.1. Plan 13 still hit all 3 tasks with the gate-fix subject conforming to the plan's required pattern (`fix(1051): inline gate-fix — <description>`).

## Issues Encountered

- e2e/builder-v1-5.spec.ts:152 regression — diagnosed and fixed (see Deviations above).
- v1010.2 SF-04..08 spot-check: NOT validated by this gate run because MCP is orchestrator-scoped. The SF surfaces (source dedupe, blob revoke, anonymous gating, single-PUT, basemap latch) have unit-test coverage in vitest (passing 1974/1974), so a non-MCP regression is unlikely. The orchestrator should still drive the manual MCP spot-check per FINDINGS.md § Orchestrator-Deferred MCP Backlog.

## Next Phase Readiness

- **Phase 1051 ready for milestone-close** (`/gsd-complete-milestone v1011`):
  - All 13 plans have SUMMARY.md
  - CHANGELOG.md [Unreleased] populated with v1011 sub-section
  - Smoke gate green
  - Inline gate-fix committed (no carryover to v1011.1)
- **Orchestrator must drive the MCP re-verify before tagging.** FINDINGS.md § Orchestrator-Deferred MCP Backlog has the 11-row per-plan checklist + the v1010.2 SF-04..08 spot-check list. Per phase 1051 protocol, MCP is orchestrator-scoped — the executor's role at CTRL-01 ends with the headless gate + CHANGELOG + this SUMMARY.
- **Open carryovers (none for v1011 — all 4 EMRG-FN findings are P2/defer with tracking artifacts):** see Plan 12 SUMMARY § Pending Todos.

## Self-Check

- [x] `e2e/builder-v1-5.spec.ts` "drag-from-catalog happy" passes locally → verified by 26/26 smoke run after fix
- [x] `npx tsc --noEmit` exit code 0
- [x] Full vitest 1974/1974
- [x] `docker compose ps` shows 5/5 healthy post-restart
- [x] CHANGELOG.md [Unreleased] contains one bullet per BUG-01..03 + UX-01..04 + RESP-01..03 + INV-01 (11 user-reported) + EMRG-01 outcome + CTRL-01 gate-fix
- [x] Commit `befe6a3b` exists in `git log --oneline` (gate-fix)
- [x] Subject prefix conforms: `fix(1051): inline gate-fix — disable basemap-group droppable for catalog non-basemap drags (CTRL-01)`

## Self-Check: PASSED

---
*Phase: 1051-map-builder-polish-bug-sweep*
*Plan: 13 (CTRL-01 close gate)*
*Completed: 2026-05-18*
