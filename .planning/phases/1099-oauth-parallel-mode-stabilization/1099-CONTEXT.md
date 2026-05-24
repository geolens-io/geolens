# Phase 1099: OAuth Parallel-Mode Stabilization - Context

**Gathered:** 2026-05-24
**Status:** Ready for planning
**Mode:** Smart-discuss (autonomous, 1 grey area resolved via AskUserQuestion — scope expansion to OAUTH-03)

<domain>
## Phase Boundary

Eliminate the 3 OAuth callback/login flakes in `backend/tests/test_oauth.py` so the post-v1023 `-n 4` and `-n auto` pytest baselines achieve `failed == 0` literal. Test-infra hygiene only — smallest-milestone charter applies (no production-code refactors beyond targeted fixes; fix at the test-isolation layer per REQUIREMENTS OAUTH-01 (b)).

**3 OAuth flakes in scope** (file: `backend/tests/test_oauth.py`):

1. **OAUTH-01** — `test_callback_missing_state_returns_error` at line 869. Flakes under `-n 4` (per `.planning/audits/PYTEST-XDIST-PERF-v1020.md` §2). Sequential passes.
2. **OAUTH-02** — `test_callback_invalid_code_returns_error` at line 901. Paired flake — REQUIREMENTS notes "one fix may close both".
3. **OAUTH-03** — `test_oauth_login_redirect` at line 826. Surfaced 2026-05-24 during Phase 1098 verify-gate (`-n auto` Run B; recorded in `.planning/phases/1098-oos-triad-closure/1098-01-SUMMARY.md` carry-forward note). Same file + same fixtures (`client` + `test_db_session`) + same `create_provider → commit → GET /auth/oauth/.../{login|callback}` pattern as OAUTH-01/02. User chose "Include — same root cause" via smart-discuss AskUserQuestion (2026-05-24).

**Common pattern across all 3 tests:**
```python
suffix = uuid.uuid4().hex[:6]
await create_provider(test_db_session, OAuthProviderCreate(slug=f"...-{suffix}", ...))
await test_db_session.commit()
resp = await client.get(f"/auth/oauth/...-{suffix}/{login|callback}", follow_redirects=False)
assert resp.status_code in (302, 404)  # OAUTH-01/02 expect 302 error, OAUTH-03 expects 302 IdP redirect
```

The hypothesis (planner to confirm at T2 diagnose): `test_db_session.commit()` doesn't reliably make the new provider visible to `client`'s connection in `-n 4` / `-n auto` modes — likely a session-pool / connection-snapshot timing issue between the two fixtures (they're separate AsyncClient + AsyncSession objects sharing a Postgres database but with potentially distinct connections + transaction snapshots).

**Out-of-scope reaffirmations** (from REQUIREMENTS.md):
- Production callback handler refactor (`backend/app/modules/auth/oauth/router.py`) unless a real production concurrency bug is found (rationale + security review note required if so)
- New fixture-isolation surfaces beyond the targeted OAUTH fix (v1022 closed PARA-* / HYG-* envelope work; v1023 inherits stabilized state)
- Broader OAuth refactor (schemas, service, dependencies)
- CHANGELOG `[1.5.8]` entry — Phase 1100's CLOSE-01 work
- OOS triad re-touching (Phase 1098 closed; sequential `failed == 0` literal achieved at SHA `b9be9027`)
- CI live-verify (Phase 1100)

</domain>

<decisions>
## Implementation Decisions

### D-01: Scope — 3 tests (OAUTH-01 + OAUTH-02 + OAUTH-03)

- **D-01a:** Include OAUTH-03 (`test_oauth_login_redirect`) in Phase 1099 alongside the originally-pinned OAUTH-01/02. Rationale: same file + same fixtures + same pattern → almost certainly same root cause → one fix likely closes all 3. Matches REQUIREMENTS OAUTH-02's "one fix may close both" precedent.
- **D-01b:** If T2 diagnosis reveals OAUTH-03 has a DISTINCT root cause from OAUTH-01/02, planner has discretion to EITHER fold the fix into Phase 1099 with rationale OR escalate to v1024+ (smallest-milestone charter preserved). REQUIREMENTS OAUTH-03 (e) authorizes this fork.
- **D-01c:** Plan-checker MUST validate all 3 pin node-IDs via `git grep -n` at plan-write time (v1019 TD-13 REQ citation pinning).

### D-02: Fix layer — test-isolation ONLY (unless real concurrency bug found)

- **D-02a:** Default fix surface: `backend/tests/conftest.py` (fixture redesign for `test_db_session` ↔ `client` consistency) OR `backend/tests/test_oauth.py` (per-test fixture override). Forbidden: production callback handler (`backend/app/modules/auth/oauth/router.py`, `service.py`, `dependencies.py`).
- **D-02b:** **Escape valve:** If T2 diagnosis reveals a genuine production concurrency bug (e.g., session-pool ordering issue in the FastAPI app, dependency-override race), production-code change IS allowed BUT requires (i) inline rationale at the production fix site, (ii) security review note in SUMMARY.md, (iii) explicit T2 finding pinned to the offending production line. REQUIREMENTS OAUTH-01 (b) authorizes this fork.
- **D-02c:** **Autonomous-mode-safe preference (D-15 carry-from-1098):** prefer fixture-isolation fix over production-code fix unless the production bug is unambiguous. If diagnosis is inconclusive at T2, fall back to fixture-isolation — the SSRF Phase 1098 D-08 "behavioral over identity-check" precedent applies: test the contract, not the wiring.

### D-03: Hypothesis (planner to confirm at T2)

- **D-03a:** **Primary hypothesis:** `test_db_session` and `client` open separate asyncpg connections from the per-worker pool. When the test commits via `test_db_session`, the `client`'s connection may have an in-progress transaction at READ COMMITTED isolation that snapshotted BEFORE the commit. The subsequent HTTP GET reads from the snapshot and finds no provider → 404 (instead of the expected 302).
- **D-03b:** **Diagnostic strategy at T2:**
  1. Re-run all 3 tests under `-n 4` 5-10 times to capture stable failure shape (status code mismatch vs Location header mismatch vs DB row mismatch).
  2. Add tactical print statements before/after the `client.get` call to dump:
     - The `test_db_session`'s connection ID (`(await test_db_session.connection()).engine_kwargs`)
     - The fresh provider row count in the DB at GET-time
     - The actual response body + Location header on 404
  3. Cross-reference `.planning/audits/PYTEST-XDIST-PERF-v1020.md` §2's flake taxonomy.
- **D-03c:** **Alternate hypotheses to consider** (don't waste time if D-03a confirms):
  - Connection-pool exhaustion under `-n 4` (would surface as `too many clients already`, not 404)
  - Provider mock leaking across tests (uuid4 suffixes make this unlikely)
  - Async event-loop ordering under xdist's `--dist=loadgroup` (would surface as intermittent rather than systematic)

### D-04: Fix shape (planner to pick after T2 diagnosis)

Three viable shapes ordered by autonomous-mode-safety:

- **D-04a (PREFERRED):** **Per-test fixture override pattern** — in `test_oauth.py`, replace `test_db_session` with an alternate fixture that uses the SAME connection as `client` (e.g., `client_session` that pulls the session from `client.app.dependency_overrides[get_db]`). This forces single-connection writes-then-reads, eliminating the snapshot gap. Smallest blast radius — only `test_oauth.py` changes.
- **D-04b:** **conftest.py fixture redesign** — change `test_db_session` to share `client`'s connection by default. Higher blast radius — could affect 70+ tests that use `test_db_session`. Per REQUIREMENTS, this is allowed but planner SHOULD prefer D-04a if it works.
- **D-04c:** **Production-code change** — only if D-02b's escape valve is triggered. Document offending production line + security review note.

### D-05: Plan structure — 1 plan / 5-6 atomic tasks / 1 verify gate

- **D-05a:** **Plan `1099-01-PLAN.md`** — single plan, 5-6 tasks (matches Phase 1098 D-12 precedent + Phase 1096 4-sub-item pattern):
  - T1: Pre-flight — re-confirm 3 OAuth pin node-IDs via `git grep -n` (v1019 TD-13 / D-17 from Phase 1098); spot-check docker stack health (5 services healthy); confirm `backend/tests/conftest.py` `test_db_session` + `client` fixture line numbers haven't drifted.
  - T2: **Diagnose** — run `-n 4` 5× with tactical instrumentation; capture actual failure shape; confirm or refute D-03a hypothesis; produce a 1-paragraph FINDINGS scratch (lives in SUMMARY.md, not as a separate file).
  - T3: **Fix** — implement D-04a (or D-04b/c per T2 diagnosis). NO behavior change in production code unless D-02b triggered.
  - T4: **Verify gate** — sequential pytest + `-n 4` 3 consecutive runs + `-n auto` 3 runs with stale-DB cleanup. Pass criteria: `failed == 0` literal in sequential + `-n 4`; ≤30 distinct (failed+errors) per `-n auto` run + 0 ICN cascade frames (PARA-01 invariant).
  - T5: **Sibling test family regression sweep** — run `backend/tests/test_oauth.py` in full 3 consecutive times in `-n 4` mode. All ~20-25 tests pass deterministically. Plus run `backend/tests/test_callback*.py` family if other callback tests exist.
  - T6: **Atomic commit** — flip REQUIREMENTS.md OAUTH-01/OAUTH-02/OAUTH-03 `[ ]` → `[x]` + `Pending` → `Complete` in the SAME commit as `1099-01-SUMMARY.md` + ROADMAP.md Phase 1099 checkbox/plan checkbox flip (v1019 TD-13 traceability rule; D-18 from Phase 1098).
- **D-05b:** File-disjoint surfaces — no contention between OAUTH fix sub-edits.
- **D-05c:** Single shared verify gate (T4 + T5 combined). Wallclock budget: ~50 min total (~9 min sequential + ~18 min `-n 4` × 3 runs + ~22 min `-n auto` × 3 runs).

### D-06: HARD INVARIANTS (carried from Phase 1098 D-16/D-17/D-18)

- **D-06a:** **Sequential pytest `failed == 0` literal** is non-negotiable (Phase 1098's D-16 invariant must be PRESERVED — adding OAUTH fixes must not regress sequential).
- **D-06b:** **`-n 4` `failed == 0` literal** is the v1023 close target (the original v1022 4-failure baseline becomes 0 after Phase 1099 closes OAUTH-01/02; OAUTH-03 surfaces only in `-n auto`, so `-n 4` after Phase 1099 = `2 OAUTH failed - 2 fixed = 0`).
- **D-06c:** **REQ citation pinning** — planner MUST validate all 3 OAUTH pin node-IDs via `git grep -n "def <test_name>" <path>` BEFORE plan commit (T1 enforces).
- **D-06d:** **Atomic traceability flip** (D-18 from Phase 1098): REQUIREMENTS.md OAUTH-01/02/03 + ROADMAP.md Phase 1099 row in SAME commit as 1099-01-SUMMARY.md (T6 enforces).

### D-07: Autonomous-mode-safe choices (D-15 from Phase 1098)

- **D-07a:** No leaker-hunting (the SSRF Phase 1098 D-10 precedent). If D-04a fixture-isolation fix holds across all 3 OAuth tests + `-n 4` 3-run + `-n auto` 3-run, do NOT investigate why the snapshot gap existed — the defensive fix addresses the symptom permanently.
- **D-07b:** No broader fixture refactor — per REQUIREMENTS out-of-scope: "New retry envelopes / engine wrappers / fixture-isolation surfaces" remain v1022's closed envelope. Phase 1099 adds at most ONE small fixture override scoped to `test_oauth.py` (D-04a) OR a tightly-scoped `test_db_session` change in conftest.py (D-04b).
- **D-07c:** No production-code refactor — D-02b escape valve is hard-gated by "real concurrency bug found" + 3-evidence requirement.
- **D-07d:** **30-min diagnostic budget at T2** — if T2 instrumentation can't confirm/refute D-03a within 30 minutes, fall back to D-04a (per-test fixture override) as a defensive fix. Diagnostic value isn't worth blooming the smallest-milestone charter.

### Claude's Discretion

- Specific instrumentation shape at T2 (print statements vs `pytest --capture=tee-sys -s` vs adding a `caplog.at_level(logging.DEBUG)` — planner picks lowest-cost shape).
- Exact `client_session` fixture name if D-04a is chosen (e.g., `client_session`, `client_db`, `test_db_session_shared` — planner picks the clearest name that doesn't collide with sibling fixtures).
- Whether to add 1-2 explicit regression tests for the fixture-isolation contract (D-04a defensive pattern) or rely on the existing 3 OAuth tests as the regression pin. Planner discretion; prefer NOT adding new pins unless the fixture override surface has a non-obvious failure mode.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements + roadmap

- `.planning/REQUIREMENTS.md` — v1023 milestone requirements. OAUTH-01/02/03 acceptance criteria (lines 38-42). Hard invariants. Out-of-scope reaffirmations (lines 60-68).
- `.planning/ROADMAP.md` §"Phase 1099" (lines 113-125) — phase goal + success criteria + dependency map.
- `.planning/STATE.md` — v1023 state. After Phase 1098: sequential 3062/0/38 baseline (down from 3060/3 OOS/38).

### Phase 1098 close-gate evidence

- `.planning/phases/1098-oos-triad-closure/1098-01-SUMMARY.md` — sequential failed==0 literal achieved at SHA `b9be9027`. OAUTH-03 surfaced in carry-forward note.
- `.planning/phases/1098-oos-triad-closure/1098-VERIFICATION.md` — passed 7/7. Notable findings include OAUTH-03 expansion hint.
- `.planning/phases/1098-oos-triad-closure/1098-CONTEXT.md` — D-12..D-18 patterns reused here as D-05/D-06.

### v1020-v1022 close-gate evidence (xdist flake taxonomy)

- `.planning/audits/PYTEST-XDIST-PERF-v1020.md` §2 — flake taxonomy (OAUTH-01/02 classified as `-n 4` flakes; same classification likely applies to OAUTH-03 under `-n auto`).
- `.planning/milestones/v1022-phases/1097-live-verify-close-gate/1097-01-CLOSE-GATE.md` — v1022 baseline: `-n 4` 3059/2 OOS + 2 oauth/38. After Phase 1098 + Phase 1099 closes, target: `-n 4` 3062/0/38.

### OAuth test pins

- `backend/tests/test_oauth.py:826` — `test_oauth_login_redirect` (OAUTH-03, surfaced 2026-05-24).
- `backend/tests/test_oauth.py:869` — `test_callback_missing_state_returns_error` (OAUTH-01).
- `backend/tests/test_oauth.py:901` — `test_callback_invalid_code_returns_error` (OAUTH-02).

### OAuth production code (read-only context — NOT to be modified unless D-02b triggered)

- `backend/app/modules/auth/oauth/router.py` — callback + login handlers.
- `backend/app/modules/auth/oauth/service.py` — `create_provider` + DB ops.
- `backend/app/modules/auth/oauth/schemas.py` — `OAuthProviderCreate` + `OAuthProviderUpdate`.
- `backend/app/modules/auth/oauth/dependencies.py` — FastAPI dependency injection.

### Test fixtures (PRIMARY fix surface)

- `backend/tests/conftest.py:1262` — `client` fixture (AsyncClient with app dependency overrides). Reads ~230 lines of retry/pool/cleanup logic.
- `backend/tests/conftest.py:1490` — `test_db_session` fixture. Read the entire fixture + the surrounding tech-debt comment at lines 1513-1540 (single-DB-per-worker isolation model).
- `backend/tests/conftest.py:359, 463, 553` — `_run_with_too_many_clients_retry` and `_acquire_test_session_with_retry` (v1020/1021/1022 retry envelope — read for context, do NOT modify).

### Project conventions (carried)

- `.planning/PROJECT.md` — project-level patterns.
- v1019 TD-13 rules (REQ citation pinning + atomic flip) — load-bearing.
- Atomic-N-file commit pattern (carried from v1010+ closes; satisfied by Phase 1098 commit `b9be9027`).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- **Per-test fixture override pattern** — `backend/tests/conftest.py` already has ~20 fixture overrides (e.g., `_point_ogr2ogr_at_test_db` at line 1543). The autouse pattern + monkeypatch idiom is well-established.
- **`uuid.uuid4().hex[:6]` slug suffix** — already used in all 3 OAuth tests to avoid intra-test slug collision. Per-worker DB isolation handles inter-test collision.
- **Diagnostic instrumentation pattern** — Phase 1098 OOS-03's T5 diagnosed contamination via `grep -rn "mock.patch.*security.*"` (cheap, fast). Phase 1099 T2 can use the same low-cost approach: re-run flaky tests + tactical print/log, NO heavy debugger / strace / etc.

### Established Patterns

- **Single-database-per-worker isolation** (`conftest.py:1513-1540`) — the comment explicitly notes "transaction-rollback-per-test model would be safer but is incompatible with the way request handlers call `await session.commit()`". This means the current model RELIES ON HTTP handlers committing to a SHARED database visible to subsequent reads. The OAuth flake suggests this shared-visibility contract is timing-dependent under parallel-mode connection pooling.
- **`pytest.mark.architecture` / `pytest.mark.anyio` markers** — OAuth tests use `async def` (anyio); already opt-in to async pytest. No marker change needed.
- **Hygiene-milestone fix shape** (v1018 / v1019 / v1020-v1022 / v1098) — atomic per-finding edits + single shared verify-gate at plan close. Phase 1098 (1 plan / 6 tasks / shared gate) is the IMMEDIATE precedent.

### Integration Points

- **REQUIREMENTS.md flip site:** `.planning/REQUIREMENTS.md` Traceability table (lines 78-86 after OAUTH-03 row added). OAUTH-01/02/03 rows flip `Pending` → `Complete` atomic with SUMMARY.md.
- **ROADMAP.md flip site:** `.planning/ROADMAP.md` Phase 1099 checkbox (line 94) + plan checkbox (line 125).
- **CHANGELOG.md** — NO `[1.5.8]` entry for Phase 1099 (that's Phase 1100's CLOSE-01 work).

### Verification gate commands (T4)

```bash
# Sequential — confirm Phase 1098 baseline NOT regressed (3062/0/38)
cd backend && set -a && source ../.env.test && set +a && uv run pytest tests/

# -n 4 — target 3062/0/38 (down from 3062/2 OAUTH/38). Run 3 CONSECUTIVE times per REQUIREMENTS OAUTH-01 (c).
cd backend && set -a && source ../.env.test && set +a && uv run pytest -n 4 tests/  # ×3 consecutive

# -n auto 3-run (stale-DB cleanup between runs per PYTEST-XDIST-PERF-v1020.md §1)
docker compose exec -T db psql -U geolens -d geolens -At -c \
  "SELECT datname FROM pg_database WHERE datname LIKE 'geolens%test_gw%' OR datname LIKE 'geolens%test_master%';" \
  | xargs -I{} docker compose exec -T db psql -U geolens -d geolens -c "DROP DATABASE IF EXISTS \"{}\" WITH (FORCE);"
cd backend && set -a && source ../.env.test && set +a && uv run pytest -n auto tests/  # ×3 with cleanup between

# Sibling test family regression (T5)
cd backend && set -a && source ../.env.test && set +a && uv run pytest -n 4 tests/test_oauth.py  # ×3 consecutive
```

Per MEMORY.md known issue: the `.env.test` host-port mapping (`POSTGRES_HOST=localhost`, `POSTGRES_PORT=5434`) is required — without sourcing, you get `InvalidCatalogNameError`.

</code_context>

<specifics>
## Specific Ideas

### T2 diagnostic instrumentation suggestion (planner discretion)

Approximate shape:

```python
# In test_oauth.py — wrap one of the 3 failing tests temporarily to dump state
async def test_callback_missing_state_returns_error(self, client, test_db_session):
    suffix = uuid.uuid4().hex[:6]
    await create_provider(test_db_session, OAuthProviderCreate(slug=f"csrf-test-{suffix}", ...))
    await test_db_session.commit()

    # DIAGNOSTIC (remove before T3 fix): print conn IDs + DB row count
    test_db_conn = await test_db_session.connection()
    print(f"\n[DIAG] test_db_session conn: {id(test_db_conn.sync_connection)}")

    # Probe the DB directly to confirm the provider exists post-commit
    result = await test_db_session.execute(
        sa.text("SELECT slug FROM oauth_providers WHERE slug = :slug"),
        {"slug": f"csrf-test-{suffix}"}
    )
    print(f"[DIAG] provider row count from test_db_session: {result.scalar()}")

    resp = await client.get(f"/auth/oauth/csrf-test-{suffix}/callback", follow_redirects=False)
    print(f"[DIAG] response status: {resp.status_code}, location: {resp.headers.get('location')}")

    assert resp.status_code == 302  # likely fails as 404 in -n 4
```

This confirms whether the provider EXISTS in the DB at GET-time but is INVISIBLE to client (snapshot gap = D-03a hypothesis) or DOESN'T EXIST yet (commit-ordering issue = different hypothesis).

### T3 fix shape sketch (D-04a — preferred)

Approximate shape — single-connection fixture override in `test_oauth.py`:

```python
@pytest.fixture
async def client_session(client):
    """Yield an async session that shares client's connection.

    Forces single-connection writes-then-reads so commit() is immediately
    visible to subsequent client.get() calls under -n 4 / -n auto.
    Replaces test_db_session for tests that combine direct DB writes with
    HTTP requests in the same test body (OAUTH-01/02/03 pattern).
    """
    # Pull the session factory the client fixture installed into the app
    from app.core.db import async_session
    from app.api.deps import get_db  # canonical dependency

    overridden_get_db = client.app.dependency_overrides[get_db]
    async for session in overridden_get_db():
        yield session
```

Then replace `test_db_session` with `client_session` in the 3 OAuth test signatures. Planner refines the exact import paths after reading the actual conftest.

### Out-of-phase 1099 scope (explicit guard-rails for planner)

- NO Phase 1100 work (CI live-verify, CHANGELOG, tags).
- NO Phase 1098 OOS triad re-touch (sequential `failed == 0` literal already at SHA `b9be9027`).
- NO production OAuth code refactor unless D-02b triggered with explicit rationale.
- NO new fixture-isolation surfaces beyond targeted D-04a/b override (REQUIREMENTS out-of-scope).
- NO broader OAuth refactor (schemas, service, deps).
- NO CHANGELOG `[1.5.8]` entry (Phase 1100's CLOSE-01).
- NO additional regression test pins beyond the existing 3 OAuth tests + any single-fixture-contract test if D-04a's failure mode is non-obvious (Claude's Discretion).

</specifics>

<deferred>
## Deferred Ideas

### Fixture model refactor — transaction-rollback-per-test (DEFERRED to v1024+)

Per `conftest.py:1513-1540` tech-debt comment, the current single-DB-per-worker model could be replaced with a SAVEPOINT-per-test rollback pattern. This is a major refactor (~70+ tests use `test_db_session`) and is explicitly DEFERRED. Phase 1099 only does the smallest fix — fixture override scoped to OAuth tests — without touching the project-wide isolation model.

### OAUTH-03 leaker / xdist scheduling investigation (DEFERRED — possibly never)

If D-04a fixture-isolation fix holds across all 3 OAuth tests + `-n 4` 3-run + `-n auto` 3-run, the precise xdist scheduling / connection-pool ordering that caused the snapshot gap becomes irrelevant. If we ever DO need to identify it:

- Run `pytest -n auto --dist=loadgroup tests/test_oauth.py` with `--log-cli-level=DEBUG` to capture per-worker connection acquisition order.
- Cross-reference with `_run_with_too_many_clients_retry` events.
- Could surface as a v1024+ test-infra audit if other tests start showing similar fixture-isolation timing issues.

Cost-of-investigation is high (multi-hour xdist scheduling dive) and value-of-fix is low (defensive fixture override addresses the symptom permanently). Park indefinitely. Same precedent as Phase 1098 D-10 leaker-hunt deferral.

### Production OAuth dependency override hardening (DEFERRED — not in Phase 1099 scope)

If T2 diagnosis reveals a genuine production race in `client.app.dependency_overrides[get_db]` (unlikely — overrides are per-request), the fix could be in `app/core/db.py` or `app/api/deps.py`. But this is the D-02b escape valve, only triggered by explicit evidence. Planner does NOT proactively explore this surface.

### Phase 1099 sibling-test sweep beyond `test_oauth.py` (DEFERRED — never needed)

Per D-07b and REQUIREMENTS out-of-scope. Phase 1099 fixes ONLY the 3 OAuth tests + sibling family regression sweep of `test_oauth.py` (~20-25 tests). Does NOT proactively sweep `test_callback*.py` or `test_auth*.py` for similar fixture-isolation patterns. If any future flake surfaces with the same shape, address it then; don't proactively sweep.

</deferred>

---

*Phase: 1099-oauth-parallel-mode-stabilization*
*Context gathered: 2026-05-24 (smart-discuss + AskUserQuestion on OAUTH-03 scope expansion)*
*Meta: User directive — autonomous lifecycle via `/gsd-autonomous --use-playwright-mcp` for full v1023 close. OAUTH-03 surfaced from Phase 1098 carry-forward; user chose "Include — same root cause" at smart-discuss checkpoint.*
