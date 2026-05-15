# Phase 1045 — Deferred items

Discovered during Plan A execution but out of scope per the
"only auto-fix issues directly caused by the current task" rule. Not
introduced by Plan A; pre-existing on `main` before commit `bbde1a5d`.

## Pre-existing lint errors (5)

`npx eslint src/` reports these before any Plan A commit; confirmed by
`git checkout HEAD~5 -- <files>` baseline check.

1. `frontend/src/components/builder/EmptyStackState.tsx:82` —
   `<li role="listitem">` redundant role.
2. `frontend/src/components/builder/EmptyStackState.tsx:93` —
   `<button role="button">` redundant role.
3. `frontend/src/components/builder/EmptyStackState.tsx:112` —
   `<button role="button">` redundant role.
4. `frontend/src/components/builder/EmptyStackState.tsx:236` —
   `<ul role="list">` redundant role.
5. `frontend/src/components/builder/__tests__/UnifiedStackPanel.test.tsx:59` —
   `role="option"` does not support `aria-expanded`.

Fixes are 1-line each but should be a follow-up plan since they touch the
`EmptyStackState` test surface and `UnifiedStackPanel` mock contract.
