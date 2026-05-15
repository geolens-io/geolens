---
phase: 1045
phase_name: builder-smoke-polish
milestone: v1009.1
date_started: 2026-05-15
date_completed: 2026-05-15
status: complete
---

# Phase 1045 — Builder Smoke Polish — SUMMARY

Single-phase hygiene milestone closing the 17 non-B-01 findings from the 2026-05-15 Map Builder Playwright smoke check (FINDINGS.md at `.planning/quick/260515-cej-docker-rebuild-builder-smoke/`). B-01 itself shipped ahead of milestone open at commit `85738f1c`.

## Result

**18 / 18 SP requirements accounted for:** 16 PASS + 1 PARTIAL-PASS (SP-07) + 1 ESCALATE (SP-03) + 1 SKIPPED-with-rationale (SP-12).

| Tier | Count | PASS | Other |
|---|---|---|---|
| BLOCKER (SP-01) | 1 | 1 | – |
| MAJOR (SP-02..SP-05) | 4 | 3 | 1 ESCALATE (SP-03) |
| MINOR (SP-06..SP-11) | 6 | 5 | 1 PARTIAL (SP-07) |
| POLISH (SP-12..SP-17) | 6 | 5 | 1 SKIPPED (SP-12) |
| HOUSEKEEPING (SP-18) | 1 | 1 | – |

## Commits (20 total across 3 plans)

**Plan A — BLOCKER + MAJORs (SP-01..SP-05):**
- `bbde1a5d` fix(builder): unclip BulkActionBar Group/Ungroup/Delete via overflow menu
- `88b75216` fix(builder): gate Pending style preview banner on real dirty state
- `5deb2187` feat(builder): shift-click extends layer selection as range
- `05daacc0` fix(builder): subscribe coord readout to maplibre move events
- `7aba7cd9` fix(review): keep selection alive when bulk overflow menu is open
- `33ab51f8` chore(1045-01): plan A summary
- `7056b663` docs(1045-01): SP-03 ESCALATE — B-01 fix did not fully close M-02

**Plan B — MINORs (SP-06..SP-11):**
- `5b4ebcfb` perf(frontend): cache ai-status query with 60s staleTime
- `6b940ca2` fix(api): de-dupe concurrent auth refresh via in-flight promise
- `f5a815d8` fix(builder): remove duplicate Saved badge from header
- `532ca595` fix(a11y): aria-pressed on visibility toggle buttons
- `b70a9caf` fix(search): skip quicklook fetch when thumbnail_status not ready
- `76927b9b` fix(auth): drop trailing slash on /auth/login route
- `be06a4f8` test(quicklook-cache): tighten persistence test via vi.resetModules
- `fbd2e3c2` chore(1045-02): plan B summary

**Plan C — POLISH + HOUSEKEEPING (SP-12..SP-18):**
- `6cbd61ae` fix(builder): polish basemap eye glyph, row hover, and Add data icon
- `4bc0e293` fix(builder): hide BulkActionBar during global Settings scene
- `2f1c3476` test(builder): add failing tests for thumbnail PUT debounce
- `d523f03d` perf(builder): debounce thumbnail PUT by 500ms
- `d10f0dfc` refactor(builder): drop unused args field from SP-16 debounce state
- `9a2ce053` chore(1045-03): plan C summary

## Gates

| Gate | Result |
|---|---|
| `npx tsc --noEmit` (frontend) | clean |
| `npx eslint src/` (frontend) | clean (5 pre-existing errors on `main` noted in `deferred-items.md`; none from this phase) |
| `npm test` on Plan A surface | 174/174 PASS |
| `npm test` on Plan B surface | 174/174 PASS |
| `npm test` on Plan C surface | 168/168 PASS |
| `uv run ruff check` (backend) | clean |
| Backend pytest (auth) | 37/37 PASS |
| i18n parity (en/de/es/fr) | 773/773/773/773 |
| Live CTRL-01 Playwright spot-checks | SP-01, 02, 10, 11, 13, 17, 18 confirmed |

## Deferred (escalate to follow-ups)

1. **SP-03 / M-02 race** — B-01 fix did not fully close it. The tokenMap-keyed gate at `BuilderMap.tsx:687` is correct but a separate race remains (suspected `syncInputs` memo closure on `structuralKey`-only key, or `mapReady` timing on the second effect re-fire when tokens land). Workaround: refresh after add. **Action:** file a B-01-followup quick task.
2. **SP-07 first-request 404** — frontend cache prevents repeats but the very first quicklook request per session still 404s. **Action:** backend `has_quicklook` predicate quick task.
3. **SP-12 / representative-fraction pane** — explicitly scoped out as a small feature; MapLibre `ScaleControl` bar is already on screen. **Action:** new feature ticket if requested.
4. **5 pre-existing lint errors on `main`** (`EmptyStackState.tsx` × 4, `UnifiedStackPanel.test.tsx` × 1) documented in `deferred-items.md`.

## Reviewer findings (inline-fixed)

1. **Plan A self-review** — Radix portal escaped UnifiedStackPanel's outside-click guard; clicking an overflow menuitem cleared selection before `onSelect` ran. Fixed inline with `data-bulk-action-menu` marker + closest-based guard (`7aba7cd9`).
2. **Plan B self-review** — misleading quicklook-cache test name (verified opposite of label). Split into 2 cleaner cases via `vi.resetModules()` (`be06a4f8`).
3. **Plan C self-review** — SP-16 `pendingCaptures` Map stored an unused `args` tuple. Refactored to bare `Map<string, ReturnType<typeof setTimeout>>` (`d10f0dfc`).

`gsd-code-reviewer` agent wasn't spawnable from inside the executor agents' tool sets; all three plans used self-review. The diffs are at `git diff cf40075b..HEAD` if a separate reviewer pass is wanted.

## Files touched

**Frontend (12):**
- `frontend/src/components/builder/BulkActionBar.tsx` (SP-01)
- `frontend/src/components/builder/UnifiedStackPanel.tsx` (SP-01/04/10/13/14/15/17)
- `frontend/src/components/builder/StackRow.tsx` (SP-04/10/14)
- `frontend/src/components/builder/BasemapGroupRow.tsx` (SP-13)
- `frontend/src/components/builder/SidebarRail.tsx` (SP-17)
- `frontend/src/components/builder/LayerStyleEditor.tsx` (SP-05)
- `frontend/src/components/builder/BuilderMap.tsx` (SP-16)
- `frontend/src/components/builder/MapCoordReadout.tsx` (SP-02)
- `frontend/src/pages/MapBuilderPage.tsx` (SP-02/04/06/15)
- `frontend/src/hooks/use-ai-availability.ts` (SP-08)
- `frontend/src/hooks/use-auth.ts` (SP-09 root cause)
- `frontend/src/api/client.ts` (SP-09)
- `frontend/src/lib/quicklook-cache.ts` (SP-07 new)
- `frontend/src/components/builder/DatasetSearchPanel.tsx` (SP-07 extended scope)
- `frontend/src/components/search/SearchResultCard.tsx` (SP-07)
- i18n locales: `en/builder.json`, `de/builder.json`, `es/builder.json`, `fr/builder.json` (SP-17)

**Backend (1):**
- `backend/app/modules/auth/router.py` (SP-11)

## Ready for milestone close

- All plan summaries written (`1045-01-SUMMARY.md`, `1045-02-SUMMARY.md`, `1045-03-SUMMARY.md`)
- VERIFICATION.md complete with per-SP results + CTRL-01 batch gate table
- Commit chain unblocked; ready to tag `v1009.1`
- Recommend: `/gsd-complete-milestone v1009.1`
