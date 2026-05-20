# Phase 1060: Close Gate - Context

**Gathered:** 2026-05-20
**Status:** Ready for planning (constrained — Playwright MCP disconnected)
**Mode:** Auto-generated under workflow.skip_discuss=true

<domain>
## Phase Boundary

Milestone v1013 close gate. Verify all 10 v1013 requirements through smoke gates + live Playwright MCP re-verify against `localhost:8080`; delete 3 fixture datasets used as smoke repros; promote CHANGELOG `[Unreleased]` → `[1.4.0]`; create local `v1013` tag and public `v1.4.0` tag.

**In scope (this phase):**
- Run all smoke gates: typecheck, vitest, e2e:smoke:builder, i18n parity
- Populate CHANGELOG `[Unreleased]` with all v1013 changes; promote to `[1.4.0]`
- Apply any cross-cutting code-review fixes that surfaced across 1057-1059 (already done inline per `feedback_review_findings_inline.md`)
- Live Playwright MCP re-verify of WFS-04, PROBE-05, GPKG-01, GPKG-02, BSE-01 — **REQUIRES MCP RESTORATION**
- Delete 3 fixture datasets — `ec18b546-d86d-4375-8e1f-8564b6a75687`, `54763119-0cf4-448e-a950-81551d090267`, `667a6c65-cdbc-4158-87f2-21a7e791ba7c`
- Create local `v1013` tag
- Create public `v1.4.0` tag (minor bump — GPKG affordances + BSE styling persistence)

**Not in scope:**
- New code changes beyond CHANGELOG + dataset cleanup
- Re-running already-passed verification on 1057/1058/1059 (already done at each phase close)
- Live MCP re-verify cannot be executed by Claude this session (MCP disconnected)

</domain>

<decisions>
## Implementation Decisions

### Constraints This Session

- **D-01:** **Playwright MCP disconnected** — `mcp__playwright__browser_*` tools unavailable. The CTRL-01 "live MCP re-verify" gate (acceptance criterion #3 of Phase 1060 ROADMAP) cannot be executed in this autonomous session. Plan 1060 ships the work I CAN complete and explicitly flags the live-MCP-required gates as deferred to a follow-up session.

- **D-02:** **Database access for dataset cleanup** — dropping the 3 fixture datasets requires running `DELETE` against the live PostGIS catalog. I can produce the SQL or the curl commands; whether to actually execute them is a user decision (deferred dataset cleanup ≠ blocking the milestone tag if the user accepts the residual datasets in the dev catalog).

### Tasks I CAN complete

- **D-03:** Run smoke gates:
  - `cd backend && uv run pytest -x` (full backend suite, no v1013 regressions)
  - `cd frontend && npm run typecheck` (0 errors)
  - `cd frontend && npm run test:i18n` (2/2 PASS)
  - `cd frontend && npm run test` or `npx vitest run --pool=forks` (full frontend suite)
  - `cd frontend && npx playwright test e2e/smoke` or `npm run e2e:smoke:builder` (headless playwright smoke; not live MCP — different surface)
  - Stack health check via `docker compose ps`

- **D-04:** Populate CHANGELOG `[Unreleased]` block with the v1013 changes. Promote to `[1.4.0]` once tags are decided. Format per existing CHANGELOG conventions in repo root.

- **D-05:** Document dataset-cleanup SQL/commands in a runbook so the user can execute when they have live DB access.

### Tasks DEFERRED to user / follow-up session

- **D-06:** Live Playwright MCP re-verify (requires `mcp__playwright__browser_*` tools restored):
  - WFS-04: `ahocevar.com/geoserver/wfs` → Countries of the World → Import succeeds end-to-end
  - PROBE-05: `demo.pygeoapi.io/master` probe completes ≤5s
  - GPKG-01: Reupload File path shows layer-select for multi-layer GPKG
  - GPKG-02: Preview pane surfaces layer name + schema diff
  - BSE-01: Basemap sublayer overrides round-trip through builder + viewer
  - Phase 1059 5-item human-verification list (from 1059-VERIFICATION.md)

- **D-07:** Dataset deletion against live catalog (requires running stack + admin auth)

- **D-08:** `git tag v1013` (local) + `git tag v1.4.0` (public). Defer to user — tag creation is the user's "ship" decision per session-level git operation policy.

### Plan Split

- **D-09:** Single plan `1060-01-PLAN.md` covering:
  - Smoke gate execution + result capture
  - CHANGELOG `[Unreleased]` population
  - Cleanup runbook (SQL for dataset deletion)
  - Live-MCP-gate runbook (explicit list of MCP commands the user can execute after MCP restore)
  - Tag-creation runbook (user-executable)

</decisions>

<canonical_refs>
## Canonical References

- `.planning/REQUIREMENTS.md` §"CLEAN-01" + §"CTRL-01" — the 2 close-gate requirements
- `.planning/ROADMAP.md` Phase 1060 — 5 success criteria
- `.planning/quick/260519-smoke-v1012/SMOKE-v1012-REPORT.md` — original source of truth for all 7 findings; tag-time MCP re-verify should target the same endpoints
- `.planning/phases/1057-service-url-reliability/1057-VERIFICATION.md` — 4 live-MCP gates deferred
- `.planning/phases/1058-multi-layer-gpkg-handling/1058-VERIFICATION.md` — 3 live-MCP gates deferred
- `.planning/phases/1059-basemap-sublayer-editor-path-b-fix/1059-VERIFICATION.md` — 5 live-MCP gates deferred (from human_verification frontmatter)
- `feedback_review_findings_inline.md` — close-gate inline-fix posture (already applied across 1057/1058/1059)

</canonical_refs>

<code_context>
## Existing Code Insights

- CHANGELOG location: project root `CHANGELOG.md` (verify via `ls CHANGELOG.md`)
- Tag convention from STATE.md: local `v1013`, public `v1.4.0` (minor bump)
- Stack health: `docker compose ps` lists all services; should see all healthy
- Migration: Alembic 0017 added in Phase 1058 — `docker compose down -v && up -d --build` OR `alembic upgrade head` before live MCP test
- Smoke gates as established in v1011/v1011.1 close patterns:
  - `cd backend && uv run pytest` (full suite)
  - `cd frontend && npm run typecheck`
  - `cd frontend && npm run test:i18n`
  - `cd frontend && npx vitest run` (or `npm test`)
  - `cd frontend && npm run e2e:smoke:builder` (headless)

</code_context>

<specifics>
## Specific Ideas

- **CHANGELOG entry format:** mirror v1.3.0's structure (additions / fixes / improvements). Reference each phase by name + REQ IDs.
- **Dataset cleanup runbook:** provide SQL `DELETE FROM datasets WHERE id IN (...)` cascade-safe + a curl alternative against `DELETE /api/datasets/{id}` for each of the 3 IDs.
- **Live-MCP gate runbook:** the user can paste the exact MCP commands (mcp__playwright__browser_navigate, mcp__playwright__browser_click sequences) after MCP restore. Don't over-script — let the orchestrator drive when MCP is back.

</specifics>

<deferred>
## Deferred Ideas

- All items in D-06, D-07, D-08 — explicitly user-execute.
- Any v1013.1 hygiene phase — NO. Inline-fix posture means no v1013.1.
- Re-running phase-level verification (1057/1058/1059 already passed) — no need.

</deferred>

---

*Phase: 1060-Close Gate*
*Context gathered: 2026-05-20 — MCP-constrained session*
