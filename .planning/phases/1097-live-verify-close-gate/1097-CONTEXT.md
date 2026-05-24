# Phase 1097: Live-Verify + Close Gate - Context

**Gathered:** 2026-05-24
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss); consumes Phases 1094-1096

<domain>
## Phase Boundary

Two final closure requirements:

1. **CI-01** — Operator-driven live-verify of the `pytest-parallel-isolation` CI gate (added in v1020 Phase 1089 at `.github/workflows/ci.yml:499-595`) on its first post-v1022-merge run on real GitHub Actions infrastructure. Closes v1020 Phase 1089 deferred operator action.

2. **CLOSE-01** — Milestone close-gate: sequential baseline re-confirmed + `-n 4` baseline re-confirmed + `-n auto` 3-run measurement table re-confirmed + CHANGELOG `[1.5.7]` written with per-requirement evidence + tags `v1022` (local) + `v1.5.7` (public) cut at the close-gate commit SHA. MUST land LAST because CI-01 can only verify post-merge of all v1022 code.

### Acceptance criteria (from REQUIREMENTS.md)

**CI-01** —
- (a) Operator runs `gh run list --workflow=ci.yml --limit=1 --json databaseId,status` + `gh run watch <run_id>` to confirm `pytest-parallel-isolation` completes green
- (b) Run log attached/quoted in CLOSE-GATE.md as evidence
- (c) If gate fails on first live run, failure fed back into PARA-01 iteration (not silently ignored)

**CLOSE-01** —
- (a) Sequential pytest result quoted verbatim showing `3060 passed / 0 NEW failed / 38 skipped` (3 pre-existing OOS may remain — explicit table)
- (b) `-n 4` result quoted showing `3057 passed / 0 NEW failed / 38 skipped` (4+ OOS — explicit table)
- (c) `-n auto` 3-run measurement table showing ≤30 distinct (failed+errors) per run with stale-DB cleanup between runs (Phase 1096 floor: 5/2/2)
- (d) Live docker stack health spot-check (`docker compose ps` 5 services healthy + `curl http://localhost:8080/api/health/` returns 200)
- (e) CHANGELOG `[1.5.7]` block lists PARA-01, PARA-02, HYG-01, CI-01 closures with the test pin names + line numbers
- (f) CI-01's live-verify run-watch log embedded in CLOSE-GATE.md
- (g) Tags `v1022` (local) + `v1.5.7` (public) cut and recorded in `.planning/MILESTONES.md`

### Requirements satisfied at this phase

- **CI-01 full closure** — `[ ] **CI-01**` → `[x] **CI-01**` + Traceability flip.
- **CLOSE-01 full closure** — close-gate document, CHANGELOG, tags cut.

### Out-of-scope reaffirmations

- No code changes (this phase is verification + close-gate only).
- No new pins.
- No test refactors.
- Pre-existing OOS rows (`test_layering`, `test_phase_275`, `test_ssrf_redirect`) — restated from v1022 OOS table.
- GitHub release notes generation — operator decision post-tag (this phase produces the CHANGELOG `[1.5.7]` block; the operator decides whether/when to cut a GH release from it).
</domain>

<decisions>
## Implementation Decisions

### Plan structure

**Two plans** recommended (sequential dependency: 02 depends on 01 commit + push):

**Plan 1097-01: CLOSE-01 close-gate baselines + CHANGELOG**
- Re-confirm sequential / `-n 4` / `-n auto` baselines vs Phase 1096 close state.
- Live docker stack health spot-check (`docker compose ps` + `curl /api/health/`).
- Optional: Playwright MCP visual smoke if requested (CONTEXT.md says Phase 1097 may use MCP per `--use-playwright-mcp` directive).
- Write CHANGELOG `[1.5.7]` block listing PARA-01, PARA-02, HYG-01 closures + test pin names + line numbers.
- Write CLOSE-GATE.md with baselines tables + health spot-check + CHANGELOG cross-reference.
- DO NOT cut tags yet — CI-01 must verify first (live-verify requires post-merge state, but we cut tag at close-gate SHA).

**Plan 1097-02: CI-01 live-verify + tag cut + flip CI-01/CLOSE-01**
- After Plan 1097-01 commits (the v1022 close-gate commit), push to remote: `git push origin main`.
- Run `gh run list --workflow=ci.yml --limit=1 --json databaseId,status` to capture the run ID.
- Run `gh run watch <run_id>` to confirm `pytest-parallel-isolation` completes green.
- Extract job log: `gh run view <run_id> --log --job=<job_id>` for `pytest-parallel-isolation` job specifically.
- Quote the relevant log block in CLOSE-GATE.md.
- Cut tags: `git tag v1022 <close-gate-sha> && git tag v1.5.7 <close-gate-sha> && git push origin v1022 v1.5.7`.
- Record tags in `.planning/MILESTONES.md`.
- Flip CI-01 + CLOSE-01 in REQUIREMENTS.md (both `[ ]` → `[x]` + `Pending` → `Complete`).
- Write `1097-02-SUMMARY.md`.

### Atomic-N-file commit per plan

- Plan 01: `CHANGELOG.md` + `.planning/phases/1097-live-verify-close-gate/1097-01-CLOSE-GATE.md` + `.planning/phases/1097-live-verify-close-gate/1097-01-SUMMARY.md` = **3 files**.
- Plan 02: `.planning/phases/1097-live-verify-close-gate/1097-01-CLOSE-GATE.md` (append CI-01 live-verify section) + `.planning/MILESTONES.md` (record tags) + `.planning/REQUIREMENTS.md` (CI-01 + CLOSE-01 flip) + `.planning/phases/1097-live-verify-close-gate/1097-02-SUMMARY.md` = **4 files**.

### Push gate

Plan 02 requires `git push origin main` BEFORE CI can fire. This is an explicit operator-visible action — orchestrator should confirm before pushing. Per `--use-playwright-mcp` directive, autonomous mode is active but `git push` is a destructive-to-shared-state action that warrants confirmation per global CLAUDE.md "Executing actions with care" rule.

**Recommendation:** AskUserQuestion before push: "Phase 1097 needs to push v1022 commits to remote so CI-01 can live-verify the `pytest-parallel-isolation` gate. Push now or stop here for operator review?"

### Tag cut decision tree

- If CI-01 GREEN: cut tags at the close-gate SHA, record in MILESTONES.md, flip CI-01 + CLOSE-01 to Complete.
- If CI-01 RED: do NOT cut tags. Feed failure back into a PARA-01 iteration plan (Plan 1098-01 or inline-amendment). Document failure shape in 1097-02-SUMMARY.md.

### Playwright MCP usage

Per `--use-playwright-mcp` directive: Plan 01's docker stack health spot-check MAY include a live MCP browser visit to `http://localhost:8080` to confirm catalog page renders with 109+ datasets + 0 console errors. NOT required for CLOSE-01 acceptance, but adds defense-in-depth signal that v1022's test-infra changes did not regress production app behavior. Recommended IF time permits.

### CHANGELOG `[1.5.7]` block shape

```markdown
## [1.5.7] - 2026-05-24

Test-infrastructure hygiene — closes v1021 carry-forward: per-worker DB lifecycle parallel-mode cascade + WR-02 sleep footgun + WR-01/03/04 engine-retry envelope hygiene + `pytest-parallel-isolation` CI gate live-verify.

### Test Infra
- **PARA-01:** Wrap `_init_tile_pool_for_tests` `asyncpg.create_pool` in existing `_run_with_too_many_clients_retry` envelope (3 call sites: `test_tiles.py:152`, `test_embed_tokens.py:57`, `test_tile_signing.py:108`). `-n auto` distinct failures: 14/14/21 → 3/2/3 → 5/2/2 (Plans 1095-01 → 1096). Regression pin at `test_fixture_isolation_v1020.py:1144`.
- **PARA-02:** Close WR-02 `_invoke_sleep_in_sync_context` loop-starvation footgun via Shape Y2 load-bearing rationale (greenlet context cannot yield via `asyncio.run`). Regression pin at `test_fixture_isolation_v1020.py:1253`.
- **HYG-01:** Narrow WR-03 bare-except at `conftest.py:842` to `(TypeError, AttributeError, InvalidRequestError)`; add WR-04 listener teardown via `_RetryingAsyncEngine.dispose()` override + `event.remove(..., "do_connect", handler)`. 3 new regression pins: `test_engine_retry_do_connect_event_handler_retries_on_transient_error` + `test_init_tile_pool_catches_raw_asyncpg_too_many_connections` + `test_init_tile_pool_propagates_non_transient_error`.

### CI
- **CI-01:** First post-merge live-verify of `pytest-parallel-isolation` CI gate (added v1020 Phase 1089). Status: [GREEN/RED — fill in at Plan 02 close].

### Known Limitations
- 3 pre-existing OOS sequential failures preserved: `test_layering` (LOC-cap decomposition), `test_phase_275` (README sync), `test_ssrf_redirect` (flake). These are documented OOS per REQUIREMENTS.md and tracked for a future hygiene milestone.

### Migrations
None. All v1.5.7 changes are test-infra hygiene (conftest + test fixtures + CI yaml).
```

### HARD INVARIANT (v1019 TD-13)

- Sequential `failed == 0` (NEW failures) non-negotiable. Baselines from Phase 1096: sequential 3060/3 OOS/38, `-n 4` 3057/6 OOS/38, `-n auto` 5/2/2.
- Traceability flip: Plan 02 close commit flips CI-01 + CLOSE-01 to `[x]` + Complete atomically.
</decisions>

<code_context>
## Existing Code Insights

### Files to edit

- `CHANGELOG.md` — write `[1.5.7]` block (Plan 01).
- `.planning/MILESTONES.md` — record `v1022` + `v1.5.7` tag entries (Plan 02).
- `.planning/REQUIREMENTS.md` — flip CI-01 + CLOSE-01 (Plan 02).

### Files to read only

- `.github/workflows/ci.yml:499-595` (the `pytest-parallel-isolation` job being live-verified).
- `.planning/REQUIREMENTS.md` (CI-01 + CLOSE-01 acceptance criteria).
- `.planning/audits/PYTEST-XDIST-PERF-v1020.md` (stale-DB cleanup recipe for `-n auto` re-baseline).
- `.planning/phases/1096-hygiene-tail/1096-VERIFICATION.md` (Phase 1096 close baselines that Plan 01 re-confirms).

### Operator commands

```bash
# Plan 02:
git push origin main
RUN_ID=$(gh run list --workflow=ci.yml --limit=1 --json databaseId --jq '.[0].databaseId')
gh run watch $RUN_ID
gh run view $RUN_ID --log --job=<pytest-parallel-isolation-job-id>
git tag v1022 <close-gate-sha>
git tag v1.5.7 <close-gate-sha>
git push origin v1022 v1.5.7
```
</code_context>

<specifics>
## Specific Ideas

### Plan 01 task structure (suggested 5-6 tasks)

1. **Pre-flight** — stack health (5 services); current sequential / `-n 4` baselines green (spot-check).
2. **Re-confirm sequential baseline** — full sequential pytest run; expect `3060 passed / 3 OOS / 38 skipped`. Capture log.
3. **Re-confirm `-n 4` baseline** — `-n 4` pytest run; expect `3057 passed / 6 OOS / 38 skipped`. Capture log.
4. **Re-confirm `-n auto` 3-run baseline** with stale-DB cleanup → expect ≤30 distinct deterministic. Capture to `/tmp/v1022-1097-close-gate-nauto-run{1,2,3}.{log,xml}`.
5. **Live docker stack health spot-check** — `docker compose ps` 5 services healthy + `curl http://localhost:8080/api/health/` → 200. Optional: Playwright MCP browser visit to `http://localhost:8080` for catalog page render + 0 console errors.
6. **Write CHANGELOG `[1.5.7]` + CLOSE-GATE.md** + atomic-3-file commit.

### Plan 02 task structure (suggested 4-5 tasks)

1. **Operator confirmation** — AskUserQuestion before push: confirm whether to push v1022 commits to remote NOW.
2. **Push + capture run ID** — `git push origin main` then `gh run list --workflow=ci.yml --limit=1`.
3. **Live-verify `pytest-parallel-isolation`** — `gh run watch $RUN_ID`; extract `pytest-parallel-isolation` job log; embed in CLOSE-GATE.md.
4. **Cut tags + record in MILESTONES** — `git tag v1022 <SHA> && git tag v1.5.7 <SHA> && git push origin v1022 v1.5.7`. Update MILESTONES.md.
5. **Flip CI-01 + CLOSE-01 + atomic-4-file commit + SUMMARY**.

### Out of phase 1097 scope

- Any code change to `backend/`, `frontend/`, or `.github/workflows/`.
- New test pins.
- GitHub release notes generation (operator decides post-tag).
- Milestone audit + complete + cleanup (lifecycle phase — orchestrator handles after Phase 1097 close).
</specifics>

<deferred>
## Deferred Ideas

None for Phase 1097 — scope is bounded by CI-01 + CLOSE-01. If CI-01 fails on first live-verify run, document the failure shape and feed back into a PARA-01 iteration plan (do NOT silently ignore per REQUIREMENTS.md CI-01 (c)).
</deferred>
