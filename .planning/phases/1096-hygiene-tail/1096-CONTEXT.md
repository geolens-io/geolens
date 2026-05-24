# Phase 1096: Hygiene Tail - Context

**Gathered:** 2026-05-23
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss); consumes Phase 1095 + Phase 1093 review findings

<domain>
## Phase Boundary

Retire HYG-01 — the 3 remaining Phase 1093 review findings (WR-01, WR-03, WR-04) + the Phase 1095 review WR-01 carry-forward (single-pin `test_init_tile_pool_*` family vs 4-pin `test_engine_retry_*` family). All findings target the engine wrapper code (`_RetryingAsyncEngine` + `_install_dbapi_connect_retry`) at `backend/tests/conftest.py:701-880`. Phase 1096 lands AFTER Phase 1095 so test pins target the post-fix stabilized engine wrapper, not the pre-fix shape.

### Findings retired by this phase

**WR-01 — Pin coverage for `do_connect` event handler retry path** (from Phase 1093 review)
- The 4 existing `test_engine_retry_*` pins at `backend/tests/test_fixture_isolation_v1020.py:904/977/1029/1070` exercise the `_RetryingAsyncEngine.connect()` + `.dispose()` wrapper-method retry paths.
- The load-bearing production-effective path is `_install_dbapi_connect_retry._retry_do_connect` (the `@event.listens_for(sync_engine, "do_connect")` handler installed at `conftest.py:701-746`).
- No existing pin exercises the event-handler branch — verified production effectiveness via -91% `-n auto` measurement, but the pin gap means a future refactor could silently degrade the event-handler retry coverage.
- **Required new pin:** `test_engine_retry_do_connect_event_handler_retries_on_transient_error` (or similar). Asserts the event handler fires retries on `_TRANSIENT_CONTENTION_EXCEPTIONS` (TooManyConnectionsError, CannotConnectNowError) and respects `_SETUP_PHASE_RETRY_BACKOFFS`.

**WR-03 — Narrow bare-except in `_RetryingAsyncEngine.__init__`** (from Phase 1093 review)
- Location: `backend/tests/conftest.py:830-836` (post Phase 1095 line shift — was line ~820 pre-Y2 docstring expansion).
- Current code:
  ```python
  try:
      _install_dbapi_connect_retry(
          sync_engine, sleep_fn=sleep_fn, backoffs=backoffs
      )
  except Exception:
      # Test doubles (MagicMock sync_engine) cannot accept
      # event.listens_for. Silently skip — the .connect() /
      # .dispose() retry wrappers above still apply for those
      # surfaces. Production engines DO accept the event hook
      # because they are real SQLAlchemy Engine instances.
      pass
  ```
- The `except Exception: pass` is the anti-pattern v1020 audit Section 4.1 condemned (silent-swallow). If SQLAlchemy's event API changes shape in a future version, the install will silently fail and production retry coverage will degrade.
- **Required fix:** Narrow to specific exception types caught from `event.listens_for` failure paths, OR loud-fail (raise) with a clear error message. Recommended: catch `(TypeError, AttributeError)` (the documented failure modes for `event.listens_for` against test doubles/MagicMock) and re-raise everything else.

**WR-04 — Listener teardown removal hook** (from Phase 1093 review)
- The `do_connect` event listener installed via `event.listens_for(sync_engine, "do_connect")` at `conftest.py:726-727` has NO teardown removal call.
- Latent risk: if a future refactor wraps an existing shared engine multiple times (e.g., shares one base engine across multiple `_RetryingAsyncEngine` wrappers), listeners stack and fire on every connection N times.
- **Required fix:** Add removal hook. Candidates:
  - (a) `event.remove(sync_engine, "do_connect", _retry_do_connect)` in a new `_RetryingAsyncEngine.dispose()` override (the wrapper class's dispose passes through to underlying, but can also call the SQLAlchemy `event.remove` here).
  - (b) pytest fixture-level finalizer that calls `event.remove` after the test session ends.
  - (c) Store a reference to the registered handler and provide a `_RetryingAsyncEngine.unwrap()` method that removes it (cleanest API, more code).
- Recommended: (a) — fits the existing wrapper-method pattern.

**WR-01 carry-forward from Phase 1095 review** (1 finding from `.planning/phases/1095-cascade-fix-wr-02-closure/1095-REVIEW.md`)
- Plan 01 of Phase 1095 shipped a single pin (`test_init_tile_pool_retries_on_transient_too_many_clients` at `test_fixture_isolation_v1020.py:1144`) for the new `_init_tile_pool_for_tests` retry surface.
- The existing `test_engine_retry_*` family has 4 pins covering succeeds / catches-raw-asyncpg / propagates-non-transient / exhausts-budget cases.
- Symmetry gap: `test_init_tile_pool_*` family should mirror the 4-case coverage (or at least 3 cases — exhausts-budget might be redundant given the envelope is shared).
- **Required new pins** (under `test_init_tile_pool_*` family):
  - `test_init_tile_pool_catches_raw_asyncpg_too_many_connections` (sibling to `test_engine_retry_catches_raw_asyncpg_too_many_connections`)
  - `test_init_tile_pool_propagates_non_transient_error` (sibling to `test_engine_retry_propagates_non_transient_operational_error`)
- The exhausts-budget case is already covered transitively because the wrapped envelope reuses `_run_with_too_many_clients_retry` which has its own exhaust-budget pin via the existing `test_engine_retry_exhausts_budget_then_fails_loudly`. Don't duplicate.

### Requirements satisfied at this phase

- **HYG-01 full closure** — all 4 sub-items (WR-01 + WR-03 + WR-04 from Phase 1093 + WR-01-1095 carry-forward) addressed. `[ ]` → `[x]` flip + `Pending` → `Complete` lands at Phase 1096 close.

### Out-of-scope reaffirmations

- CI-01 (live-verify) — Phase 1097.
- CLOSE-01 (CHANGELOG + tags) — Phase 1097.
- App-engine retry (FastAPI request path) — restated from v1021/v1022 Out-of-Scope tables.
- IN-* findings from Phase 1095 review (IN-01 pin-name-vs-assertion + IN-02 docstring imprecision + IN-03 rationale block missing second call site + IN-04 perf-test out-of-scope sites) — these are nice-to-have polish; do NOT bloom Phase 1096 scope.
</domain>

<decisions>
## Implementation Decisions

### Fix sequencing within Phase 1096

Single plan recommended (Plan 1096-01) with 3 atomic edits + 3 new pins:
1. WR-03 narrow bare-except — 1-line edit, no test change needed (existing pins cover both branches).
2. WR-04 listener teardown — ~5-10 LOC (override `dispose` OR add fixture-level finalizer).
3. WR-01 new event-handler pin — new pin `test_engine_retry_do_connect_event_handler_retries_on_transient_error`.
4. WR-01-1095 carry-forward pins — 2 new pins under `test_init_tile_pool_*` family.

All 4 sub-items target `backend/tests/conftest.py` (WR-03, WR-04) + `backend/tests/test_fixture_isolation_v1020.py` (WR-01, WR-01-1095). Single plan is cleaner than splitting because:
- Same file surface (2 files).
- Same verification gate (all pins pass + baselines preserved).
- Atomic measurement: post-HYG-01 `-n auto` 3-run baseline should match Phase 1095's 3/2/3 floor (no regression).

### Regression pin location

All new pins land in `backend/tests/test_fixture_isolation_v1020.py` — the existing file structure (~1300+ LOC after Phase 1095). If file grows past 1800 LOC, spin out `backend/tests/test_init_tile_pool_v1022.py`; otherwise append.

### Naming convention

- Use existing `test_engine_retry_*` family naming for the WR-01 event-handler pin: `test_engine_retry_do_connect_event_handler_retries_on_transient_error`.
- Use `test_init_tile_pool_*` family naming for WR-01-1095 carry-forward pins (mirrors the existing pin at line 1144).

### Verification gates

- 32+2+3 = 37-test pin subset spot-check at task end (32 v1020 originals + 2 v1022 Plan 01/02 pins + 3 new HYG-01 pins).
- Sequential pytest `3055/0/38` preserved (HARD INVARIANT). +5 NEW passed delta expected (5 new pins).
- `-n 4` `3054/0/38` preserved.
- `-n auto` 3/2/3 distinct floor preserved (no regression vs Phase 1095 close).
- All 4 existing `test_engine_retry_*` pins + 2 Phase 1095 pins + 3 new HYG-01 pins = 9 pins all pass.

### HARD INVARIANT (v1019 TD-13)

- Sequential pytest `failed == 0` non-negotiable.
- REQ citation pinning: planner MUST validate `path::test_name` node-IDs via `git grep -n "def <test_name>" <path>` BEFORE plan commits. Applies to all 3 new pin names.
- Traceability flip: executor MUST flip REQUIREMENTS.md `[ ]` → `[x]` and `Pending` → `Complete` for HYG-01 in the SAME commit as SUMMARY.md.

### Atomic-N-file commit

Plan 01: `backend/tests/conftest.py` (WR-03 + WR-04) + `backend/tests/test_fixture_isolation_v1020.py` (3 new pins) + `.planning/phases/1096-hygiene-tail/1096-01-SUMMARY.md` + `.planning/REQUIREMENTS.md` (HYG-01 flip) = **4 files**.

### Playwright MCP

Not applicable — backend test-infra phase.
</decisions>

<code_context>
## Existing Code Insights

### Files to edit

- `backend/tests/conftest.py:830-836` (WR-03 narrow bare-except — currently `except Exception: pass`).
- `backend/tests/conftest.py:748-880` (WR-04 — `_RetryingAsyncEngine` class; add `dispose()` override OR registration tracking OR fixture finalizer).
- `backend/tests/conftest.py:701-746` (WR-04 — `_install_dbapi_connect_retry` may need to return a handle so dispose can remove the listener).
- `backend/tests/test_fixture_isolation_v1020.py` — append 3 new pins (WR-01 + WR-01-1095 ×2).

### Files to read only

- `backend/tests/conftest.py:726-727` (`@event.listens_for(sync_engine, "do_connect")` — the listener being teardown-tracked).
- `backend/tests/conftest.py:333,352,359` (`_SETUP_PHASE_RETRY_BACKOFFS`, `_TRANSIENT_CONTENTION_EXCEPTIONS`, `_run_with_too_many_clients_retry` — REUSE verbatim).
- `backend/tests/test_fixture_isolation_v1020.py:904/977/1029/1070/1144/1253` (existing pin patterns for naming convention reference).
- `.planning/milestones/v1021-MILESTONE-AUDIT.md:85-92` (canonical WR-01/03/04 finding text).
- `.planning/phases/1095-cascade-fix-wr-02-closure/1095-REVIEW.md` (Phase 1095 WR-01 carry-forward finding).
</code_context>

<specifics>
## Specific Ideas

### Plan 01 task structure (suggested 6-7 tasks)

1. **Pre-flight** — line-number re-validation; 34-test pin subset spot-check (32 v1020 + 2 Plan 1095); docker stack health.
2. **WR-03 narrow bare-except** — replace `except Exception:` at line 830 with `except (TypeError, AttributeError):` + re-raise comment OR re-raise everything else clause.
3. **WR-04 listener teardown** — pick approach (a)/(b)/(c) from CONTEXT.md; implement. Default (a): override `_RetryingAsyncEngine.dispose()` to call `event.remove(sync_engine, "do_connect", <handler>)`. Requires `_install_dbapi_connect_retry` to return the handler reference.
4. **Add WR-01 pin** `test_engine_retry_do_connect_event_handler_retries_on_transient_error` — mock-based: install the handler, invoke `do_connect` event with simulated `TooManyConnectionsError`, assert retry fires.
5. **Add WR-01-1095 carry-forward pin 1** `test_init_tile_pool_catches_raw_asyncpg_too_many_connections` — mirror `test_engine_retry_catches_raw_asyncpg_too_many_connections` pattern for the tile-pool envelope.
6. **Add WR-01-1095 carry-forward pin 2** `test_init_tile_pool_propagates_non_transient_error` — mirror `test_engine_retry_propagates_non_transient_operational_error` pattern.
7. **Verify gates** — 37-test pin subset + 9 pin-family run + sequential 3055/0/38 (+5 NEW = 3060) + `-n 4` 3054/0/38 + `-n auto` 3-run delta vs Phase 1095 floor (3/2/3 ≤30 deterministic preserved).
8. **Atomic-4-file commit + flip HYG-01** — REQUIREMENTS.md HYG-01 `[ ]` → `[x]`; Traceability HYG-01 row to `Phase 1096` + `Complete`.

### Plan 01 close verification expected:
- 5 new tests added → sequential passed count = 3057 → 3060 (Plan 1095 added 2; Plan 1096 adds 3). Skipped count unchanged at 38.
- 9 pin-family run: 4 `test_engine_retry_*` + 1 `test_engine_retry_yields_event_loop_during_backoff` + 1 `test_engine_retry_do_connect_event_handler_*` + 3 `test_init_tile_pool_*` = 9 pins.

### Out of phase 1096 scope

- IN-* findings from Phase 1095 review (deferred — nice-to-have polish).
- CI-01 / CLOSE-01 — Phase 1097.
- Any production code changes.
</specifics>

<deferred>
## Deferred Ideas

None for Phase 1096 — scope is bounded by HYG-01 closure. If a new finding surfaces during execution (e.g., the WR-04 listener removal is more complex than expected and requires `_install_dbapi_connect_retry` signature change), document inline in SUMMARY.md as a Phase 1097 carry-forward or escalate to user decision.
</deferred>
