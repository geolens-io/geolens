# Roadmap: v1019 Hygiene Tail — v1018 Frontend + xdist + Process

**Milestone:** v1019
**Public tag target:** `v1.5.4` (patch)
**Phases:** 1084–1086 (continues from v1018 1080–1083)
**Requirements:** 6 (TD-09..TD-14)
**Granularity:** Coarse (hygiene shape — minimum viable phases, no padding)
**Coverage:** 6/6 requirements mapped — no orphans

---

## Phases

- [ ] **Phase 1084: Frontend Hygiene Tail** - Eliminate the 36 pre-existing TypeScript errors and two console-noise patterns (/maps/new 422s, /api/api/ double-prefix) surfaced at v1018 close-gate
- [ ] **Phase 1085: pytest -n auto Stabilization** - Spike then fix the xdist 16-worker Postgres connection-pool cascade so parallel test runs are clean
- [ ] **Phase 1086: Process Tightening + Close Gate** - Write process retro + global skill update, verify TD-07 runtime symmetry, run full close-gate, cut tags

---

## Phase Details

### Phase 1084: Frontend Hygiene Tail
**Goal:** The frontend build is clean: zero TypeScript errors and zero spurious console noise on the two documented surfaces
**Depends on:** Nothing (all three items are independent frontend fixes; no backend dependency)
**Requirements:** TD-09, TD-11, TD-12
**Success Criteria** (what must be TRUE):
  1. `cd frontend && npm run typecheck` exits 0; the 36 pre-existing TS errors across the 14 test files identified in the v1018 Phase 1083 baseline are resolved with no `@ts-expect-error` or `@ts-ignore` suppressions added
  2. A Playwright MCP smoke session visiting `/maps/new` records zero spurious 422 responses in the network log — the Create dialog short-circuit fires before any mutation hooks reach the backend
  3. A Playwright MCP smoke session records zero `/api/api/` URL patterns in the network log — the quicklook proxy double-prefix is eliminated at source (`frontend/src/api/` client or route definition, not via nginx patch)
**Plans:** TBD

### Phase 1085: pytest -n auto Stabilization
**Goal:** `pytest -n auto` completes a 16-worker xdist run against the backend test suite without triggering a Postgres recovery cascade; the chosen fix is evidence-driven from a committed spike doc
**Depends on:** Phase 1084 (clean frontend baseline before backend test-infra work; ensures the close-gate in 1086 starts from a stable joint baseline)
**Requirements:** TD-10
**Success Criteria** (what must be TRUE):
  1. `.planning/audits/PYTEST-XDIST-SPIKE-v1019.md` is committed and contains: observed Postgres `max_connections`, per-worker concurrent connection count measured during a 16-worker run, identification of which fix shape (pool sizing / `max_connections` bump / cap `-n`) was chosen, and the rationale
  2. `pytest -n auto` (or the capped equivalent if cap was chosen) completes with zero `asyncpg` connection-refused or Postgres recovery-cascade errors; the chosen fix is in place in `backend/tests/conftest.py`, `docker-compose.yml`, or `Makefile` as appropriate
  3. Sequential `uv run pytest backend/` still passes (the fix must not break sequential mode)
**Plans:** TBD

### Phase 1086: Process Tightening + Close Gate
**Goal:** Two process artifacts are committed, TD-07 runtime symmetry is confirmed in the deployed images, and v1019 ships with a full close-gate audit trail and both tags cut
**Depends on:** Phase 1084, Phase 1085 (all hygiene fixes must land before baseline capture)
**Requirements:** TD-13, TD-14
**Success Criteria** (what must be TRUE):
  1. `.planning/retros/v1019-process.md` exists and covers: the TD-02/03 test-name drift incident (paraphrased names vs actual `test_register_emits_user_register_audit` / `test_register_disabled_does_not_emit_audit`), the `tasks_common.py` path+line drift incident, and the Plan 1081-02 REQUIREMENTS.md checkbox-flip miss — with the new rules that prevent recurrence
  2. Three GSD skill files are updated at `~/.claude/get-shit-done/`: `agents/gsd-planner` (REQ authoring node-ID pinning rule), `agents/gsd-executor` (SUMMARY checkbox flip before commit), and `templates/requirements.md` (node-ID schema example) — applicable across all GSD projects
  3. `docker compose up -d --build api worker` succeeds; a probe of the running `api` container confirms `ssl=False` is present on the `database_ssl_mode='disable'` branch (e.g., `docker exec <api> grep -n "ssl=False" app/core/config.py` returns the line from v1018 Phase 1080-02)
  4. Sequential `uv run pytest backend/` passes at 3025+ / 0 failures; `npm run e2e:smoke:builder` exits green; live Playwright MCP smoke covers 5 surfaces on `localhost:8080` and all pass
  5. `CHANGELOG.md` carries a `[1.5.4] - 2026-05-22` entry covering TD-09..TD-14; local tag `v1019` and public tag `v1.5.4` are cut at the post-baseline commit
**Plans:** TBD

---

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1084. Frontend Hygiene Tail | 0/3 | Not started | - |
| 1085. pytest -n auto Stabilization | 0/2 | Not started | - |
| 1086. Process Tightening + Close Gate | 0/2 | Not started | - |

---

## Coverage

| Requirement | Phase | Notes |
|-------------|-------|-------|
| TD-09 | 1084 | 36 TS errors / 14 files — `npm run typecheck` exit 0 gate |
| TD-10 | 1085 | xdist spike (1085-01) then fix (1085-02) |
| TD-11 | 1084 | /maps/new 422 console-noise — network-log assertion |
| TD-12 | 1084 | /api/api/ double-prefix — frontend client or route fix |
| TD-13 | 1086 | Retro + global skill update (3 files under `~/.claude/get-shit-done/`) |
| TD-14 | 1086 | TD-07 runtime rebuild + container probe (bundled in close gate) |

**6/6 requirements mapped — no orphans.**

---

*Roadmap created: 2026-05-22*
*Milestone: v1019 Hygiene Tail — v1018 Frontend + xdist + Process*
*Phase numbering continues from v1018 (1080–1083 → 1084–1086).*
