---
phase: 1071-known-items-closure
plan: 03
subsystem: validators-schemas
tags: [password-policy, where-validator, stac-search-body, pydantic-bounds, sec-s09, ast-validator, todo-archive]

# Dependency graph
requires:
  - phase: 1062-password-complexity
    provides: validate_password_complexity 3-of-4 class detection (v1014 SEC-S16)
  - phase: 1062-where-validator
    provides: validate_where_ast strict allowlist (v1014 SEC-S09)
  - phase: 1063-ogc-stac-hardening
    provides: StacSearchBody POST /search schema with downstream H-24 clamp
provides:
  - validate_password_complexity docstring documenting whitespace-as-symbol stance + trailing-whitespace regression pin
  - validate_where_ast AST-level rejection of table-qualified column references (Column.table / Column.db / Column.catalog inspection) — closes a documentation-vs-implementation gap
  - test_table_qualified_reference_rejected pinning 2- and 3-segment qualified-column shapes
  - StacSearchBody.limit Pydantic ge=1, le=1000 + offset ge=0
  - Four schema-rejection tests on POST /stac/search bounds (TestStacSearchBodyBounds)
  - Three archived pending todos (v1062 IN-02, v1062 IN-03, v1063 IN-02) with resolution preamble
affects: [auth-policy-docs, export-where-validator-contract, stac-api-openapi, sec-audit-findings, todo-hygiene]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Documented-contract enforcement at the gate: when a docstring asserts AST-level rejection, the gate code must inspect the actual sqlglot node shape (Column.table/.db/.catalog) — not rely on a separate exp.Dot node that sqlglot's postgres dialect never emits"
    - "RFC 7807 problem-details error-body shape in tests: GeoLens responds with `detail: <string>` (not FastAPI's default `detail: [list]`); pin tests must parse the string form"

key-files:
  created: []
  modified:
    - backend/app/modules/auth/password_policy.py
    - backend/tests/test_password_policy.py
    - backend/app/processing/export/where_validator.py
    - backend/tests/test_export_where_validator.py
    - backend/app/standards/stac/router.py
    - backend/tests/test_stac_search_validation.py
    - .planning/todos/resolved/2026-05-20-v1062-in02-whitespace-symbol-class.md (renamed from pending/ + preamble)
    - .planning/todos/resolved/2026-05-20-v1062-in03-where-validator-dot-ast-test.md (renamed from pending/ + preamble)
    - .planning/todos/resolved/2026-05-20-v1063-in02-stac-search-body-pagination-bounds.md (renamed from pending/ + preamble)

key-decisions:
  - "KNOWN-09: Honored CONTEXT.md D-09 — kept the whitespace-as-symbol behavior unchanged; documented the stance under a new Notes heading in the docstring; added one positive-form test pinning the trailing-whitespace shape (Aaaaaaaaaaa1 ) as passing. The 12-char length floor (~72 bits entropy) is the security-relevant invariant, not the symbol-class strictness; operators wanting stricter semantics can raise PASSWORD_REQUIRE_CLASSES to 4."
  - "KNOWN-10: Discovered during test writing that sqlglot's postgres dialect parses `catalog.records.title = 'x'` into an exp.Column node with .table/.db/.catalog populated rather than emitting an exp.Dot node. The validator's docstring (lines 66-72) claimed rejection happened at the AST level via exp.Dot exclusion, but the rejection only worked downstream via the identifier regex. Applied Rule 1+2 auto-fix: inspect Column.table/.db/.catalog inside the allowlist walk and reject when any are populated. The plan's `Do NOT modify where_validator.py` directive was overridden because the documented security contract was demonstrably unenforced — that's a Rule 1+2 case, not Rule 4."
  - "KNOWN-12: Adopted the plan's bounds verbatim (limit ge=1, le=1000; offset ge=0). Preserved the downstream H-24 max(1, min(limit, 200))/max(0, offset) clamp as defense-in-depth; extended the inline comment to reference KNOWN-12 / Phase 1071. Updated test assertions to use GeoLens's RFC 7807 problem-details shape (detail is a string, not the FastAPI-default list of validator errors)."
  - "Followed Plan 1071-02's split-commit pattern for the archival: pure `git mv` (commit 9ea8f9ff) + separate preamble-content commit (bd185342). The note in the prompt confirmed this is necessary — combining git mv with content edits trips git's 100%-similarity rename detection and silently drops the preamble."

patterns-established:
  - "Documented-contract grep audit: when an INFO/test-only todo names a security-relevant behavior, the executor's first move is `validate_where_ast('tbl.col = 5')` (or equivalent) to confirm the rejection actually happens — assuming the planner's read of the inline comment was correct can leak a months-old documentation lie into the next milestone."
  - "Pydantic ge/le rejection-test shape: `detail: <RFC 7807 string>` is the project's standard error body — pin tests must parse the string form (case-insensitive substring search for `less than or equal`, `le `, or `<=`); do not assume FastAPI default `detail: [list]` shape."

requirements-completed: [KNOWN-09, KNOWN-10, KNOWN-12]

# Metrics
duration: 13min
completed: 2026-05-21
---

# Phase 1071 Plan 03: Validator/Schema Hardening (KNOWN-09, KNOWN-10, KNOWN-12) Summary

**Documented `validate_password_complexity`'s whitespace-as-symbol stance with a pinning test, closed a documentation-vs-implementation gap in `validate_where_ast` where the docstring's promised AST-level rejection of table-qualified column references was not actually enforced, and added Pydantic ge/le bounds + four schema-rejection tests to `StacSearchBody`.**

## Performance

- **Duration:** ~13 min
- **Started:** 2026-05-21T12:34:39Z (after Plan 1071-02 close)
- **Completed:** 2026-05-21T12:47:17Z
- **Tasks:** 4 (Task 4 split across two commits per Plan 1071-02 pattern)
- **Files modified:** 9 (6 source/test files + 3 todo renames-with-preamble)
- **Commits:** 5 (1 doc + 1 bug-fix + 1 feat + 2 archive)

## Accomplishments
- **KNOWN-09:** `validate_password_complexity` now carries a Notes paragraph explicitly naming whitespace-as-symbol as an intentional design choice, citing the 12-char length floor as the security-relevant invariant and `PASSWORD_REQUIRE_CLASSES=4` as the strictness escape hatch. A new test (`test_trailing_whitespace_satisfies_symbol_class`) pins the stance: a 13-char password `aaaaaaaaaaaa1 ` (trailing space) MUST pass at `min_length=12, require_classes=3`. Future refactors that silently tighten the symbol class will trip the test before merging.
- **KNOWN-10:** Two pieces shipped: (a) the new `test_table_qualified_reference_rejected` test pinning rejection of both `records.title = 'x'` and `catalog.records.title = 'x'`; and (b) a runtime-discovered fix in `validate_where_ast` that closes the gap between the docstring (which claimed AST-level rejection via exp.Dot exclusion) and the actual sqlglot behavior (which folds qualified refs into exp.Column with .table/.db/.catalog populated). The fix inspects those args inside the existing allowlist walk and raises ValueError when any are populated. Defense-in-depth: the downstream identifier regex still catches qualified refs at the wrapper layer.
- **KNOWN-12:** `StacSearchBody.limit` now carries `Field(default=10, ge=1, le=1000)` and `StacSearchBody.offset` carries `Field(default=0, ge=0)`. POST `/stac/search` now returns 422 before reaching the SQLAlchemy layer for `limit=10001`, `limit=0`, and `offset=-1`. The downstream H-24 clamp (`max(1, min(body.limit, 200))`, `max(0, body.offset)`) stays in place as defense-in-depth; the inline comment was extended to cite KNOWN-12. Four new tests pin the schema rejection.
- All three v1014 INFO pending todos (v1062 IN-02, v1062 IN-03, v1063 IN-02) moved from `pending/` to `resolved/` via `git mv` (blame history preserved) with a stacked resolution preamble naming this plan and the closing commit SHA.

## Task Commits

Each task committed atomically:

1. **Task 1: KNOWN-09 — document whitespace-as-symbol stance** — `9399c0be` (docs)
2. **Task 2: KNOWN-10 — pin exp.Dot AST rejection + close docstring-vs-implementation gap** — `3302769d` (fix; scope upgrade from test-only per Rule 1+2)
3. **Task 3: KNOWN-12 — Pydantic ge/le bounds on StacSearchBody** — `965f056b` (feat)
4. **Task 4: Archive three pending todos** — `9ea8f9ff` (rename) + `bd185342` (preamble) per Plan 1071-02 split-commit pattern

## Files Created/Modified
- `backend/app/modules/auth/password_policy.py` — Inserted a `Notes:` block in the `validate_password_complexity` docstring (after the existing `Raises:`) naming whitespace as the symbol class and citing the 12-char floor + the 4-class escape hatch.
- `backend/tests/test_password_policy.py` — Added `test_trailing_whitespace_satisfies_symbol_class` inside `TestValidatePasswordComplexity` (positive-form pin, MUST NOT raise).
- `backend/app/processing/export/where_validator.py` — (1) Extended the inline comment at lines 66-72 to name the sqlglot quirk (exp.Column.table populated rather than separate exp.Dot); (2) added a Column.table/.db/.catalog inspection inside `validate_where_ast`'s allowlist walk that raises ValueError when any are populated.
- `backend/tests/test_export_where_validator.py` — Added `test_table_qualified_reference_rejected` inside `TestBlocklist` covering both 2-segment (`records.title`) and 3-segment (`catalog.records.title`) qualified-reference shapes.
- `backend/app/standards/stac/router.py` — (1) Added `Field` to the pydantic import on line 19; (2) updated `StacSearchBody.limit` and `.offset` to use `Field(default=..., ge=..., le=...)`; (3) extended the H-24 inline comment at line 1180-1184 to cite KNOWN-12 / Phase 1071.
- `backend/tests/test_stac_search_validation.py` — Added `TestStacSearchBodyBounds` with 4 tests: `test_post_search_limit_above_le_rejected`, `test_post_search_negative_offset_rejected`, `test_post_search_zero_limit_rejected`, `test_post_search_limit_within_bounds_accepted`. Assertion parses the project's RFC 7807 `detail: <string>` shape (substring match for `less than or equal` / `le ` / `<=`), not FastAPI's default list-of-errors body.
- `.planning/todos/resolved/2026-05-20-v1062-in02-whitespace-symbol-class.md` — Renamed from `pending/`; preamble cites commit `9399c0be`.
- `.planning/todos/resolved/2026-05-20-v1062-in03-where-validator-dot-ast-test.md` — Renamed from `pending/`; preamble cites commit `3302769d` and names the Rule 1+2 scope upgrade.
- `.planning/todos/resolved/2026-05-20-v1063-in02-stac-search-body-pagination-bounds.md` — Renamed from `pending/`; preamble cites commit `965f056b`.

## Decisions Made
- **CONTEXT.md D-09 honored verbatim for KNOWN-09** — Took the simpler choice (document, do not change behavior). The alternative (`string.punctuation - whitespace`) was considered and rejected per CONTEXT.md because it trades a real false-positive surface (trailing-space typo on a legitimate password) for a hypothetical attack surface that the 12-char length floor already mitigates. The pin test guards the stance against future "silent tightening" refactors.
- **Scope upgrade on KNOWN-10 (Rule 1+2)** — The plan declared the test was a pure regression pin and explicitly said "Do NOT modify where_validator.py — the behavior is correct." Runtime discovery during test writing showed the documented behavior was NOT correct: sqlglot's postgres dialect emits `exp.Column` with `.table` populated for `tbl.col` (not a separate `exp.Dot` node), so the allowlist walk passed qualified references through. The fix is surgical (one new conditional inside the existing walk) and matches Rule 1 (bug — code doesn't work as docstring claims) + Rule 2 (security — stated contract not enforced). The downstream identifier regex still catches qualified refs via the no-dot constraint, so the user-observable behavior at the wrapper layer is unchanged; only `validate_where_ast` directly was affected (it now rejects what its docstring already claimed it rejected).
- **Test-assertion shape matches the project's RFC 7807 error body** — Initial test assertion used FastAPI's default `detail: [list-of-errors]` shape; runtime check showed GeoLens responds with `detail: <single-string>` (e.g. `"body.limit: Input should be less than or equal to 1000"`). Updated to substring-match `less than or equal` / `le ` / `<=` on the lowercase string form, plus confirm `limit` is named. Future bounds tests in this codebase should use the same pattern.
- **Split archive commit per Plan 1071-02 pattern** — The prompt note flagged this explicitly. Pure `git mv` (which only reads the index, not the worktree) goes first as commit `9ea8f9ff`; preamble content lands separately as `bd185342`. The alternative (Edit + git add -f + git mv) was avoided because the prompt named the split-commit shape and it was already battle-tested in Plan 1071-02.
- **Preserved downstream H-24 clamp on POST /stac/search** — Even with the schema rejecting out-of-bound `limit`/`offset` at the Pydantic layer, the `max(1, min(body.limit, 200))` and `max(0, body.offset)` calls stayed in `search_post`. Rationale: defense-in-depth against future schema changes (e.g. if `le=1000` is relaxed to `le=10000` someday, the 200-item operational ceiling should still be enforced by the route logic, not silently inflated by a schema-only change).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1+2 - Bug + Missing critical functionality] KNOWN-10 scope upgraded from test-only to test + AST-validator fix**
- **Found during:** Task 2 (verification step — the new `test_table_qualified_reference_rejected` test failed with `DID NOT RAISE` on the 3-segment `catalog.records.title = 'x'` form).
- **Issue:** `validate_where_ast` did not actually reject table-qualified column references at the AST level, despite the docstring lines 66-72 explicitly claiming "Only unqualified column names are accepted; table-prefixed references are rejected at the AST level before the regex identifier check runs." sqlglot's postgres dialect parses `tbl.col` into an `exp.Column` node with `.table` populated rather than emitting a separate `exp.Dot` node. The allowlist walk saw only `exp.Column` + `exp.Identifier`, both in `ALLOWED_EXPRESSIONS`, so qualified references passed the AST gate. The rejection only happened downstream via the identifier regex's no-dot constraint at the wrapper layer.
- **Fix:** Added a follow-up conditional inside the existing allowlist walk in `validate_where_ast` that checks `isinstance(node, exp.Column) and (node.args.get('table') or node.args.get('db') or node.args.get('catalog'))` and raises `ValueError("Disallowed expression in WHERE clause: table-qualified column reference (only unqualified column names are accepted)")`. Updated the inline comment at lines 66-72 to name the sqlglot quirk and point at the new check.
- **Files modified:** `backend/app/processing/export/where_validator.py` (one new conditional + comment refresh).
- **Verification:** `cd backend && uv run pytest tests/test_export_where_validator.py -q` shows 42 passed (the 16 pre-existing allowlist tests + 23 pre-existing blocklist tests + 3 wrapper tests, plus the new pin). No regression.
- **Commit:** `3302769d` (originally would have been a `test(...)` commit per plan; promoted to `fix(...)` to reflect the scope).
- **Why not Rule 4 (architectural):** The fix is a single 6-line conditional inside an existing walk loop. It doesn't change function signatures, doesn't add new dependencies, doesn't restructure the validator, and doesn't change user-observable behavior (the wrapper layer already rejected qualified refs via the identifier regex). It just closes the gap between the stated contract and the actual AST gate.

**2. [Rule 3 - Blocking] Test infrastructure required POSTGRES_PORT=5434 override for Task 3 verification**
- **Found during:** Task 3 verification step (`uv run pytest ... -k "Bounds"` errored with `database "geolens_test_<uuid>" does not exist` because the conftest's `_test_db_lifecycle` fixture connects to `database_url_sync` which defaults to port 5432, but the docker compose `db` service maps to host port 5434).
- **Issue:** Not a regression — the same error reproduces on pre-existing tests (`TestSecFu05StacIntersectsMaxLength`). The conftest fixture is reachable but the default port doesn't match the local stack.
- **Fix:** Ran verification with `POSTGRES_PORT=5434 uv run pytest ...`. No code/config change committed (this is operator-side knowledge, captured here for future verifier passes).
- **Verification:** 4 new bounds tests pass with the override; all 8 tests in `test_stac_search_validation.py` pass; 29 broader STAC tests pass (`test_stac_api.py` + `test_stac_integration.py`) confirming no schema regression from the `Field` import + bounds change.
- **Commit:** None — environmental knowledge only.

**3. [Rule 1 - Bug] Initial Task 3 test assertion used FastAPI default 422 body shape instead of GeoLens RFC 7807**
- **Found during:** Task 3 verification (`test_post_search_limit_above_le_rejected` returned 422 correctly but the `body.get("detail", [])` iteration was empty because `detail` is a string in this project, not a list).
- **Issue:** Plan-template assumption that didn't match the codebase's error-body shape. Live response was `{'type': 'about:blank', 'title': 'Validation Error', 'status': 422, 'detail': 'body.limit: Input should be less than or equal to 1000'}`.
- **Fix:** Updated the assertion to lowercase-stringify `body.get("detail", "")` and substring-match `limit` + (`less than or equal` OR `le ` OR `<=`). Matches GeoLens's RFC 7807 problem-details middleware.
- **Files modified:** `backend/tests/test_stac_search_validation.py` (only the new bounds-test class).
- **Verification:** 4 bounds tests pass.
- **Commit:** Folded into the Task 3 feat commit `965f056b` (the test file was already in the same commit as the source change; no separate fix-up commit needed).

---

**Total deviations:** 3 auto-fixed.
- 1 Rule 1+2 (scope upgrade on KNOWN-10 — documented contract not enforced; ~1hr engineering value vs Rule 4 escalation).
- 1 Rule 3 (test-infra port mismatch; operator-side knowledge, no code change).
- 1 Rule 1 (assertion shape mismatch with project's RFC 7807 error body).

**Impact on plan:** No scope creep beyond Rule 1+2 territory. KNOWN-10 commit is now a `fix(...)` instead of a `test(...)` per the upgraded scope, but the success-criteria for KNOWN-10 (regression test exists + passes) are met and exceeded.

## Issues Encountered
None unresolved. All three deviations closed inline.

## User Setup Required
None — schema/docstring/test changes only; no env, migration, or service restart needed. (Future test runs of `test_stac_search_validation.py` and other DB-dependent tests against the local stack require `POSTGRES_PORT=5434` to match the docker compose host mapping; this is pre-existing and not a Plan 1071-03 change.)

## Next Phase Readiness
- KNOWN-09, KNOWN-10, KNOWN-12 closed; remaining Phase 1071 items (KNOWN-01 through KNOWN-05 + KNOWN-13) handled by sibling plans 1071-04, 1071-05, 1071-06, 1071-07, 1071-08 (KNOWN-13 already shipped in Plan 1071-01).
- One observable runtime contract changed in this plan: `validate_where_ast('tbl.col = 5')` now raises `ValueError` directly instead of relying on the wrapper-layer identifier-regex catch. Anyone calling `validate_where_ast` directly (no wrapper) on table-qualified WHERE fragments will see the new exception type message; the wrapper (`validate_where_clause`) is unaffected. Search for direct callers if Phase 1074 close-gate flags any new failures.
- OpenAPI snapshot update for the StacSearchBody bounds change is deferred to Phase 1074 close-gate per the plan's explicit "Do NOT change the OpenAPI snapshot file in this plan — that update is handled by `make openapi`" directive.
- STATE.md "Pending Todos" section update is owned by the orchestrator at SUMMARY-write time (per plan Task 4 `<done>` note).

## Self-Check: PASSED

All verifications confirmed:

- `FOUND: backend/app/modules/auth/password_policy.py` (with `whitespace` in docstring; `grep -A 30 'def validate_password_complexity' | grep -i whitespace` returns 3 matches)
- `FOUND: backend/tests/test_password_policy.py` (with `test_trailing_whitespace_satisfies_symbol_class`; pytest passes 1 test)
- `FOUND: backend/app/processing/export/where_validator.py` (with `node.args.get("table")` / `.get("db")` / `.get("catalog")` inspection)
- `FOUND: backend/tests/test_export_where_validator.py` (with `test_table_qualified_reference_rejected`; pytest passes 1 test, no regression on 42 tests)
- `FOUND: backend/app/standards/stac/router.py` (with `Field(default=10, ge=1, le=1000)` on limit; `Field(default=0, ge=0)` on offset; H-24 comment cites KNOWN-12)
- `FOUND: backend/tests/test_stac_search_validation.py` (with `TestStacSearchBodyBounds` class; 4 new tests pass; 8 total in file pass, no regression)
- `FOUND: .planning/todos/resolved/2026-05-20-v1062-in02-whitespace-symbol-class.md` (with resolution preamble citing 9399c0be)
- `FOUND: .planning/todos/resolved/2026-05-20-v1062-in03-where-validator-dot-ast-test.md` (with resolution preamble citing 3302769d + Rule 1+2 note)
- `FOUND: .planning/todos/resolved/2026-05-20-v1063-in02-stac-search-body-pagination-bounds.md` (with resolution preamble citing 965f056b)
- `MOVED: pending/v1062-in02` (no longer in pending/)
- `MOVED: pending/v1062-in03` (no longer in pending/)
- `MOVED: pending/v1063-in02` (no longer in pending/)
- Commits `9399c0be`, `3302769d`, `965f056b`, `9ea8f9ff`, `bd185342` all exist on `main` (`git log --oneline -7`)
- Broader regression check: 66 tests pass + 3 skipped across the three modified test files (3 skips are pre-existing endpoint-fixture tests needing `SEC_AUDIT_PUBLIC_DATASET_ID`)
- Broader STAC sanity: 29 tests pass across `test_stac_api.py` + `test_stac_integration.py` — no Field-import regression

---
*Phase: 1071-known-items-closure*
*Plan: 03*
*Completed: 2026-05-21*
