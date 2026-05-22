# Phase 1090: Skip Audit + Flake Hunt + Close-Gate - Context

**Gathered:** 2026-05-22
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

A reader of the close-gate doc can see every sequential-mode skip dispositioned, every flake surfaced + dispositioned, and the v1019 WR-01 paper-trail closed — and can confirm tags `v1020` + `v1.5.5` cut at the close commit.

This is the v1020 milestone close-gate. Three hygiene requirements + full close-gate verification + tag cuts. No production-code changes.

Phase scope:
- **HYG-01** — Audit the 38 sequential-mode skips (`pytest --collect-only -q | grep "SKIPPED"` or equivalent on post-1088 HEAD). Disposition each as `KEEP (with one-line rationale)`, `FIX (with referencing plan)`, or `REMOVE`. Output: close-gate doc as a table.
- **HYG-02** — Flake hunt: 3× consecutive `pytest -n auto` runs after Plans 1088 + 1089 land. Log non-deterministic failures with planned disposition (defer / fix in-milestone / quarantine). The 4.3 residual at 48 (above audit's <30 threshold) gets explicit disposition here per Phase 1088 close-out deferral.
- **HYG-03** — Paper-trail v1019 WR-01: CHANGELOG `[1.5.5]` line referencing v1019 audit + confirming `frontend/package.json:23` `lint:sec-fu-03-no-false-positive` script preserved. (Confirmed at HEAD — see Code Context below.)
- **Close gate full verification:** sequential pytest, parallel pytest -n 4 (the chosen default), frontend typecheck, e2e:smoke:builder, live Playwright MCP 5/5 surfaces.
- **Tag cuts:** `v1020` (local) + `v1.5.5` (public) at the close commit. Both tags MUST point to the same SHA.

</domain>

<decisions>
## Implementation Decisions

### Plan structure (likely 2-3 plans)

- **Plan 1090-01 — Skip audit + flake hunt + WR-01 paper-trail.**
  - HYG-01: collect 38 skip dispositions in a single audit step.
  - HYG-02: run `pytest -n auto` 3× consecutive (or `-n 4` post-PERF-01 — see Decision below); document determinism (or lack of) per cascade category.
  - HYG-03: add CHANGELOG `[1.5.5]` block + WR-01 paper-trail line.
  - Output: close-gate doc with all three sections.

- **Plan 1090-02 — Close gate full verification + tag cuts.**
  - Run full close-gate suite: sequential pytest, parallel pytest, frontend typecheck, e2e:smoke:builder, Playwright MCP 5/5 surfaces (per CLI flag `--use-playwright-mcp`).
  - TD-13 SAME-commit: flip HYG-01 + HYG-02 + HYG-03 in REQUIREMENTS.md + ROADMAP.md + Phase 1090 SUMMARY in ONE commit per `<requirements_traceability_flip>` rule.
  - Cut tags `v1020` (local) + `v1.5.5` (public) at the close SHA.
  - CHANGELOG `[Unreleased]` → `[1.5.5] - 2026-05-22`.

Two plans is the natural shape — splitting the hygiene work (1090-01) from the close-gate-and-tags machinery (1090-02) lets the close-gate plan rest on a stable codebase.

### Which `-n` value for HYG-02 flake hunt?

Audit specifies "`pytest -n auto`" but PERF-01 (Plan 1089-01) selected `-n 4` as the recommended default. Two competing forces:

- **Option A: `-n auto` (16 workers)** — Stress-test the v1088 fixture-isolation work at maximum parallelism. Should surface 4.3 residual flake (48 failures) consistently, validating the deferral was correct.
- **Option B: `-n 4` (PERF-01 default)** — Stress-test the chosen CI default. If 3 runs all show ≤5 cascade failures, the gate is robust; if variance is high, the `-n 4` choice needs revisiting.

**Recommendation:** Do BOTH. Plan 1090-01 runs 3× `-n auto` (to validate flake-class disposition of the 4.3 residual) AND 3× `-n 4` (to validate the CI gate's determinism). Document each run's pass/fail/cascade per category.

### HYG-01 skip audit shape (LOCKED)

For each of the 38 sequential skips:
1. Extract via `cd backend && uv run pytest tests/ -v 2>&1 | grep "SKIPPED" > /tmp/v1020-skips.log`
2. For each line, capture: test node-ID, skip reason (the `(reason)` suffix from pytest output).
3. Disposition: `KEEP (rationale)`, `FIX (referencing plan ID)`, or `REMOVE (commit message)`.
4. Output as a Markdown table in close-gate doc:
   ```
   | Node ID | Reason | Disposition | Rationale |
   |---------|--------|-------------|-----------|
   ```

Most skips will be `KEEP` (e.g., `pytest.skip` on macOS-only / Linux-only / overlay-dependent / requires-network). The few that aren't trivially `KEEP` get either a referenced fix plan ID or a removal commit.

### Close-gate matrix (LOCKED)

Mirror v1019 close-gate exactly:

| Gate | Target | Source |
|------|--------|--------|
| Sequential pytest | 3047/0/38 or higher (M==0) | `cd backend && uv run pytest tests/` |
| Parallel pytest -n 4 | ≤5 cascade failures (flake-class) | `cd backend && uv run pytest -n 4 tests/` |
| Frontend typecheck | exit 0 | `cd frontend && npm run typecheck` |
| Vitest unit tests | 2105/2105 (or current baseline) | `cd frontend && npm run test` |
| e2e:smoke:builder | 25/0/1 (matches v1019 baseline) | `cd frontend && npm run e2e:smoke:builder` |
| Live Playwright MCP | 5/5 surfaces clean (`/`, `/maps`, `/datasets/<uuid>`, `/maps/new`, `/maps/<uuid>`) | orchestrator-driven MCP per `--use-playwright-mcp` flag |
| Tag `v1020` (local) | at close SHA | `git tag v1020` |
| Tag `v1.5.5` (public) | at close SHA | `git tag v1.5.5` |

If any gate fails, HALT and surface to orchestrator — do NOT cut tags on a broken close.

### Playwright MCP smoke (per `--use-playwright-mcp`)

The orchestrator passed `--use-playwright-mcp` to `/gsd-autonomous`. Plan 1090-02 MUST run a 5-surface MCP smoke at close-gate. The 5 surfaces (from v1019 close-gate per memory):
- `/` — landing/home (or whatever's the post-removal root in current codebase)
- `/maps` — map list
- `/datasets/<uuid>` — pick any dataset UUID from `/datasets/` listing
- `/maps/new` — confirms v1019 TD-11 redirect still works (no /api/maps/new 422 noise)
- `/maps/<uuid>` — open any saved map

Each surface: load, check console for errors, check network for 4xx/5xx (excluding expected 403/404/etc), capture screenshot.

Orchestrator runs MCP; executor consumes the result.

### TD-13 rules in effect

1. **REQ citation pinning** — close-gate doc cites every skip node-ID exactly; CHANGELOG cites `frontend/package.json:23` for WR-01; flake hunt cites per-category counts.
2. **Traceability flip** — Plan 1090-02 flips HYG-01 + HYG-02 + HYG-03 in REQUIREMENTS.md + ROADMAP.md + Phase 1090 SUMMARY in ONE commit. Verify via `git diff-tree --no-commit-id --name-only -r HEAD`.

### Tag cut details

After the TD-13 atomic commit + close-gate doc commit + CHANGELOG commit, cut tags:

```bash
git tag v1020 -m "v1020 Fixture Isolation milestone close"
git tag v1.5.5 -m "v1.5.5 - Fixture Isolation hygiene (no user-facing features)"
```

Verify both tags point to the same SHA:
```bash
test "$(git rev-parse v1020)" = "$(git rev-parse v1.5.5)"
```

Document the tag SHA in close-gate + Phase 1090 SUMMARY.

### Out of scope for this phase

- New code (production or test). All changes are docs/CHANGELOG/tags.
- New regression pins (Phase 1088 owns).
- New CI work (Phase 1089 owns).
- Frontend changes beyond CHANGELOG.
- Schema/migration changes.
- Anything outside `.planning/`, `CHANGELOG.md`, and git tags.

</decisions>

<code_context>
## Existing Code Insights

**CHANGELOG.md:**
- Line 12 — `## [Unreleased]` header (empty since v1019 close)
- Line 14 — `## [1.5.4] - 2026-05-22` (v1019)
- Plan 1090-02 inserts `## [1.5.5] - 2026-05-22` between these, OR converts Unreleased to 1.5.5.

**frontend/package.json — WR-01 paper-trail target (confirmed present at HEAD):**
- Line 23 — `"lint:sec-fu-03-no-false-positive": "eslint src/__tests__/sec-fu-03-react-no-danger-regression.skip.tsx"`
- Line 22 — companion `"lint:sec-fu-03-regression"` script

HYG-03 just needs a CHANGELOG line referencing both lines and the v1019 audit's WR-01 finding. No code change.

**v1019 close-gate reference (memory):**
- Sequential pytest: 3036/0/38 (now 3047/0/38 post-1088 + 1089)
- e2e:smoke:builder: 25/0/1
- Playwright MCP: 5/5 surfaces green on `localhost:8080`
- Tag pair: v1019 + v1.5.4 at SHA 02cb25db

**v1020 close-gate targets (this milestone):**
- Sequential pytest: 3047/0/38 (Phase 1088 + 1089 baseline; +11 regression pins from FI-03)
- Parallel pytest -n 4: ≤5 cascade failures (from PERF-01 n=4 measurement: 1 fail / 0 cascade-class)
- Parallel pytest -n auto (HYG-02 stress): flake-class ≤50 (4.3 residual disposition acceptable)
- e2e:smoke:builder: 25/0/1 (unchanged — no frontend changes in v1020)
- Playwright MCP: 5/5 surfaces green

**Stack state for Playwright MCP:**
- Frontend served at `http://localhost:8080` via Vite dev proxy
- Stack must be up: `docker compose ps` should show api/worker/db healthy + frontend dev server running

</code_context>

<specifics>
## Specific Ideas

**Plan 1090-01 (hygiene close + flake hunt + WR-01 paper-trail):**

1. **HYG-01 — Skip audit (~30 min):**
   - Run `cd backend && uv run pytest tests/ -v 2>&1 | tee /tmp/v1020-collect.log`
   - Extract 38 SKIPPED lines.
   - For each: assign disposition. Most will be `KEEP` (platform-specific, overlay-required, network-dependent).
   - Write table to close-gate doc.

2. **HYG-02 — Flake hunt (~20 min):**
   - 3× `cd backend && uv run pytest -n auto tests/ 2>&1 | tee /tmp/v1020-hyg02-nauto-run<N>.log` (drop stale DBs between runs).
   - 3× `cd backend && uv run pytest -n 4 tests/ 2>&1 | tee /tmp/v1020-hyg02-n4-run<N>.log` (drop stale DBs between runs).
   - For each run, count cascade-category failures.
   - Cross-run determinism check: are failures the same node-IDs each run?
   - Document in close-gate doc.

3. **HYG-03 — WR-01 paper-trail (~5 min):**
   - CHANGELOG block referencing v1019 audit WR-01 + confirming `frontend/package.json:23` script preserved.
   - Single line; no code change.

4. Commit all three deliverables atomically + Phase 1090 hygiene SUMMARY.

**Plan 1090-02 (close-gate verification + tags):**

1. **Close-gate run (~30 min):**
   - Sequential pytest
   - Parallel pytest -n 4 (the chosen CI default)
   - Frontend typecheck
   - Vitest
   - e2e:smoke:builder
   - Playwright MCP 5/5 surfaces (driven by orchestrator)

2. **Close-gate doc write (~10 min):**
   - All gate results in a table.
   - Tags pending.

3. **CHANGELOG update (~5 min):**
   - `[Unreleased]` → `[1.5.5] - 2026-05-22` with v1020 summary block.

4. **TD-13 atomic close commit:**
   - Files: `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md`, `.planning/phases/1090-skip-audit-flake-hunt-close-gate/1090-SUMMARY.md`, `CHANGELOG.md`.
   - Flips HYG-01 + HYG-02 + HYG-03 in REQUIREMENTS.md (checkbox + traceability row).
   - Flips Phase 1090 in ROADMAP.md (checkbox + Plans line `2/2 plans complete`).
   - Updates ROADMAP.md milestone status line for v1020: 🚧 → ✅.
   - Verify via `git diff-tree --no-commit-id --name-only -r HEAD` = exactly the 4 files.

5. **Tag cuts:**
   - `git tag v1020`
   - `git tag v1.5.5`
   - Verify both at same SHA.

6. **STATE.md advance** (separate commit AFTER tag cuts).

**Total time budget:** ~100 min for both plans.

**MCP smoke note:** When prompting the orchestrator for live Playwright MCP smoke, the executor should explicitly request `mcp__playwright__browser_navigate` to each of the 5 surfaces with `mcp__playwright__browser_console_messages` + `mcp__playwright__browser_network_requests` capture. The orchestrator can run the MCP tools directly if the executor needs more than tool-shaped help.

</specifics>

<deferred>
## Deferred Ideas

- **Push tags to remote** — defer to operator; not part of the close-gate plan.
- **GitHub release notes** — defer to operator post-tag.
- **CI gate live-verification** — operator runs `gh run watch <run_id>` post-merge. Phase 1090 SUMMARY references this handoff.
- **Engine-level retry for 4.3 residual** — explicitly deferred per Phase 1088 close-out decision; HYG-02 will confirm flake-class disposition was correct.
- **Documentation: parallel-test playbook for developers** — defer to post-milestone or absorb into a v1021 docs phase if it surfaces.

</deferred>
