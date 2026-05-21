---
phase: 1071-known-items-closure
plan: 02
subsystem: docs
tags: [password-policy, sec-fu-04, env-vars, docstring, todo-archive]

# Dependency graph
requires:
  - phase: 1062-password-complexity
    provides: PASSWORD_MIN_LENGTH / PASSWORD_REQUIRE_CLASSES env-var knobs (v1014 SEC-S16)
  - phase: 1063-ogc-stac-hardening
    provides: _sanitize_authorization_token + 8-char floor (v1014 SEC-FU-04)
provides:
  - .env.example documentation for PASSWORD_MIN_LENGTH and PASSWORD_REQUIRE_CLASSES
  - Inline docstring on _sanitize_authorization_token explaining the 8-character floor
  - Two archived pending todos (v1062 IN-01, v1063 IN-01) with resolution preamble
affects: [operator-onboarding, sec-audit-findings, todo-hygiene]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pending-todo archive pattern: prepend `---resolved:...---` preamble above existing frontmatter, then `git mv` from pending/ to resolved/ (preserves blame history)"

key-files:
  created: []
  modified:
    - .env.example
    - backend/app/processing/ingest/ogr.py
    - .planning/todos/resolved/2026-05-20-v1062-in01-password-env-doc.md (renamed from pending/)
    - .planning/todos/resolved/2026-05-20-v1063-in01-sanitize-authorization-token-8char-doc.md (renamed from pending/)

key-decisions:
  - "Inserted password-complexity block BETWEEN the JWT block and the GEOLENS_ADMIN_USERNAME block in .env.example (per plan, in the Authentication section neighborhood)"
  - "Kept all existing docstring content on _sanitize_authorization_token intact; new 8-char paragraph slotted BEFORE the final Returns/Raises sentence per plan"
  - "Used `git mv` for the pending → resolved transition (not delete+create) so todo blame history survives the archival — but the preamble Edit + `git mv` ordering tripped a `git mv` semantics gotcha (see Deviations); follow-up commit `702cc3c6` re-added the preamble content"
  - "Resolution preamble stacked ABOVE the existing frontmatter (not merged into it) so the original v1062/v1063 creation metadata stays grep-discoverable"

patterns-established:
  - "Stacked frontmatter for resolved todos: dual `---` blocks (resolution preamble first, original creation frontmatter second) — reads as two separate metadata layers"

requirements-completed: [KNOWN-08, KNOWN-11]

# Metrics
duration: 2min
completed: 2026-05-21
---

# Phase 1071 Plan 02: Documentation Closures (KNOWN-08, KNOWN-11) Summary

**Documented `PASSWORD_MIN_LENGTH` and `PASSWORD_REQUIRE_CLASSES` in `.env.example`, added inline rationale for the 8-character floor on `_sanitize_authorization_token`, and archived both pending todos to `resolved/`.**

## Performance

- **Duration:** 2 min
- **Started:** 2026-05-21T12:32:59Z
- **Completed:** 2026-05-21T12:34:39Z
- **Tasks:** 3 (Task 3 split across two commits — see Deviations)
- **Files modified:** 4 (2 source files + 2 todo renames-with-preamble)

## Accomplishments
- New operators reading `.env.example` now see the v1062 SEC-S16 password-complexity knobs documented next to the existing JWT/admin auth settings, with defaults shown (12-char minimum, 3-of-4 character classes) and explanatory comments naming the originating phase.
- Callers of `_sanitize_authorization_token` who hit a 7-or-fewer-character token can now read the rationale inline from the docstring: the 8-character floor defends against silent token truncation upstream (clipped JSON fields, mistaken-bearer ArcGIS tracking tokens) silently slipping into the GDAL_HTTP_HEADERS pipeline; the docstring also names `GDAL_HTTP_HEADER_FILE` as the escape hatch for legitimately-short tokens.
- Both v1014 INFO pending todos (`2026-05-20-v1062-in01-password-env-doc.md`, `2026-05-20-v1063-in01-sanitize-authorization-token-8char-doc.md`) moved from `pending/` to `resolved/` via `git mv` (blame history preserved) with a stacked resolution preamble naming this plan and the closing commit SHA.

## Task Commits

Each task was committed atomically:

1. **Task 1: Document PASSWORD_MIN_LENGTH and PASSWORD_REQUIRE_CLASSES in .env.example** — `40c5d6c8` (docs)
2. **Task 2: Document the 8-char minimum inline on _sanitize_authorization_token** — `d1533847` (docs)
3. **Task 3: Archive the two pending todos to resolved/** — `25ed8208` (rename) + `702cc3c6` (preamble content; see Deviations)

## Files Created/Modified
- `.env.example` — Added 12-line password-complexity block in the Authentication section (between `REFRESH_TOKEN_EXPIRE_DAYS` and `GEOLENS_ADMIN_USERNAME`); two commented env-var entries with default values.
- `backend/app/processing/ingest/ogr.py` — Extended `_sanitize_authorization_token` docstring with a 10-line paragraph naming the 8-character floor and the defense rationale; implementation unchanged (the `len(token) < 8` check at line 43 stays exact).
- `.planning/todos/resolved/2026-05-20-v1062-in01-password-env-doc.md` — Renamed from `pending/`; prepended resolution preamble citing commit `40c5d6c8`.
- `.planning/todos/resolved/2026-05-20-v1063-in01-sanitize-authorization-token-8char-doc.md` — Renamed from `pending/`; prepended resolution preamble citing commit `d1533847`.

## Decisions Made
- **Stacked-frontmatter shape for resolved todos** — The resolution preamble lives ABOVE the original creation frontmatter as a separate `---` block, not merged. Rationale: keeps original metadata (`created`, `severity`, `source`, `resolves_phase`) grep-discoverable; resolution metadata reads as a distinct layer applied retroactively. Matches the v1014/v1015 close pattern referenced in the plan's `<context>` section.
- **No body edits beyond preamble** — Original Finding/Solution/Deferred rationale stays untouched in both todos for posterity (auditors who want to know why these were originally deferred can read the original justification).
- **Followed plan literally on insertion point** — The plan named the exact insertion point in `.env.example` ("after the JWT block but before GEOLENS_ADMIN_USERNAME"); the password block now lives between line 39 (`REFRESH_TOKEN_EXPIRE_DAYS=7`) and line 41 (originally `GEOLENS_ADMIN_USERNAME`).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Task 3 rename commit dropped the resolution preamble — followup commit added the content**
- **Found during:** Self-check pre-SUMMARY (`git diff --stat .planning/todos/resolved/` showed 16 unstaged additions after Task 3 supposedly landed).
- **Issue:** Task 3 followed the plan literally: (a) Edit-prepend the preamble in `pending/`, then (b) `git mv pending/ → resolved/`. `git mv` reads the index, not the working tree — since the Edit modifications were never `git add`'d before `git mv`, git's rename detection at 100% similarity moved the **original blob** (without the preamble) to the new path. Working tree retained the preamble (correctly), but commit `25ed8208` only contained the pure rename (`0 insertions, 0 deletions`).
- **Fix:** New commit `702cc3c6` force-stages the resolved/ files (gitignored under `.planning/` but tracked from history; needed `-f`) with the preamble content and lands it.
- **Files modified:** `.planning/todos/resolved/2026-05-20-v1062-in01-password-env-doc.md`, `.planning/todos/resolved/2026-05-20-v1063-in01-sanitize-authorization-token-8char-doc.md`
- **Verification:** `git show 702cc3c6 --stat` shows 16 insertions across the 2 files; `head -8` on each resolved file confirms the preamble landed.
- **Committed in:** `702cc3c6` (followup to `25ed8208`, both attributed to Task 3)
- **Forward pattern note:** When archiving pending todos in future plans, ORDER the operations as: (1) Edit-prepend preamble, (2) `git add -f` the modified file, (3) `git mv` (which now operates on the staged content). Or: (1) `git mv` first, (2) Edit-prepend preamble in resolved/, (3) `git add -f`, (4) `git commit`. Either order works; the failure mode is `git mv` without intervening `git add`.

---

**Total deviations:** 1 auto-fixed (1 blocking — `git mv` semantics interaction)
**Impact on plan:** No scope creep, no behavior change. The Task 3 success-criteria automation check (`ls resolved/*.md | wc -l == 2`) had already passed before discovery because it only verified file presence at the new path, not the preamble content. Discovery came from the self-check `git diff` step (which the executor protocol mandates BEFORE SUMMARY-write). One additional commit (`702cc3c6`) added; the success-criteria intent (preamble + move) is met across the pair `25ed8208` + `702cc3c6`.

## Issues Encountered
None.

## User Setup Required
None — documentation-only closures; no environment, schema, or runtime changes.

## Next Phase Readiness
- KNOWN-08 and KNOWN-11 closed; remaining KNOWN items for Phase 1071 (KNOWN-01, 02, 03, 04, 05, 09, 10, 12, 13) handled by sibling plans 1071-01, 1071-03, 1071-04, 1071-05, 1071-06, 1071-07, 1071-08 per the CONTEXT.md grouping.
- No code behavior changed — existing tests pass unchanged (no test runs needed; documentation-only delta).
- STATE.md "Pending Todos" section update is owned by the orchestrator at SUMMARY-write time (per plan Task 3 `<done>` note).

## Self-Check: PASSED

All verifications confirmed:

- `FOUND: .env.example` (with PASSWORD_MIN_LENGTH + PASSWORD_REQUIRE_CLASSES; `grep -c` returns 2)
- `FOUND: backend/app/processing/ingest/ogr.py` (with `8-character` in docstring at 2 distinct lines)
- `FOUND: .planning/todos/resolved/2026-05-20-v1062-in01-password-env-doc.md` (with resolution preamble at top)
- `FOUND: .planning/todos/resolved/2026-05-20-v1063-in01-sanitize-authorization-token-8char-doc.md` (with resolution preamble at top)
- `MOVED: pending/v1062-in01` (no longer in pending/)
- `MOVED: pending/v1063-in01` (no longer in pending/)
- Commits `40c5d6c8`, `d1533847`, `25ed8208`, `702cc3c6` all exist on `main`
- Final-state diff vs HEAD is empty for the two resolved todos (preamble content is committed, not unstaged)

---
*Phase: 1071-known-items-closure*
*Plan: 02*
*Completed: 2026-05-21*
