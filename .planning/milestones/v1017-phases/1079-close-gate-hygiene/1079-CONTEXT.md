# Phase 1079: Close Gate + Hygiene - Context

**Gathered:** 2026-05-21
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via `workflow.skip_discuss`)

<domain>
## Phase Boundary

The final phase of v1017. Three requirements + close-gate protocol + tag:

- **TI-03:** Capture post-v1017 pytest baseline doc at `.planning/audits/PYTEST-BASELINE-2026-05-21.md`. Must document: total tests, pass/fail/skip counts, zero `InvalidCatalogNameError` errors, exact pass count with rationale for any skips. Future regressions get spotted by diffing against this baseline.

- **VG-01:** Run `backend/scripts/test_alembic_upgrade_clean_db.sh` against the running `docker compose up -d --build` stack (db + api + worker). Document any discrepancies between in-script test approach and live container runtime. Closes the deferred Phase 1071 KNOWN-02 verification gap.

- **HYG-01:** Review the `.planning/quick/` tail (196 items, similar to the 174 quoted in STATE.md — count drifted slightly with v1016 close). Archive superseded items, promote still-relevant ones to `.planning/todos/pending/`, target <50 active items.

**Close-gate protocol (must all pass before tag):**
1. Full `uv run pytest backend/tests/` exits 0 OR documents skip reasons
2. `cd frontend && npx tsc -b` exits 0
3. `cd frontend && npm run e2e:smoke:builder` exits 0
4. Live Playwright MCP smoke against rebuilt `localhost:8080` containers — 5/5 surfaces green (orchestrator-driven, not delegated)
5. `CHANGELOG.md` has `[1.5.2] - 2026-05-21` entry summarizing v1017 work
6. Local tag `v1017` + public tag `v1.5.2` cut

**Out of scope:**
- Closing the 7 newly-discovered Phase 1075 verification gap failures — those go to v1018 with the documented rationale already in `1075-05-VERIFICATION.md`
- Production traffic verification on staging — local stack is the gate
- New feature work — v1017 is hygiene only

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices at Claude's discretion. Use ROADMAP success criteria, prior-phase SUMMARYs, and the close-gate template established in v1011, v1013, v1014, v1015, v1016 milestones.

### Known Defaults

- **PYTEST-BASELINE-2026-05-21.md format:** Match the audit doc convention (frontmatter + sections). Include:
  - Baseline counts (pass/fail/skip/error) in both `-x` and `-n auto` modes
  - Per-test-file skip table with rationale
  - `InvalidCatalogNameError` count (must be 0)
  - The 7 Phase 1075 newly-discovered failures with disposition reference
  - Comparison vs v1016 Phase 1074 audit
- **Tag convention:** `v1017` local + `v1.5.2` public, both at the final commit
- **CHANGELOG section structure:** Match v1016's `[1.5.1] - 2026-05-21` format
- **Playwright MCP smoke surfaces:** Per project memory, the 5 standard surfaces for builder milestones are:
  1. Catalog page loads (datasets list rendered, 0 console errors)
  2. Dataset detail page loads (preview map, metadata, downloads)
  3. Map Builder loads with an existing saved map
  4. Re-upload flow visible (UI affordances correct)
  5. Auth flow (login, anonymous access)
  For a hygiene/test-infra milestone like v1017, the 5 standard surfaces may shift to:
  1. Catalog loads
  2. Dataset detail loads + COG download succeeds (ING-03 streaming) 
  3. Map Builder loads
  4. Reupload UI loads (re-confirm UI helpers from ING-01/ING-05)
  5. Auth flow
  Adjust as needed when the smoke runs.

### Investigation order

1. Land HYG-01 quick_tasks triage first (mechanical, can be done in parallel with other work) — Plan 01.
2. Land TI-03 pytest baseline doc — Plan 02. Requires full pytest run.
3. Land VG-01 docker-smoke re-verify — Plan 03. Requires docker compose up.
4. CHANGELOG entry — Plan 04 (final pre-tag).
5. Orchestrator runs Playwright MCP smoke + tags — Plan 05 (close-gate).

</decisions>

<code_context>
## Existing Code Insights

- `.planning/quick/` — 196 items, accumulated from v1014/v1015/v1016 era
- `.planning/todos/pending/` — currently empty (0 items)
- `.planning/todos/resolved/` — 8 items (v1014 INFO closures from v1016)
- `.planning/audits/` — has `INGEST-AUDIT-2026-05-21.md`, `SECURITY-AUDIT-2026-05-21.md`, `TRIAGE-2026-05-21.md`. New: `PYTEST-BASELINE-2026-05-21.md`
- `CHANGELOG.md` — has `[Unreleased]` placeholder and `[1.5.1] - 2026-05-21` entry
- `backend/scripts/test_alembic_upgrade_clean_db.sh` — the docker-smoke script (Phase 1071)
- Docker compose stack — `docker-compose.yml`, with services: db, api, worker, frontend, titiler

Live MCP smoke pattern (project memory): orchestrator-driven `mcp__playwright__browser_navigate` against `http://localhost:8080`, checking console messages + page snapshots. Not delegated to executor since MCP runs in orchestrator scope only.

</code_context>

<specifics>
## Specific Ideas

- 5 plans:
  - Plan 01: HYG-01 quick_tasks triage
  - Plan 02: TI-03 pytest baseline doc
  - Plan 03: VG-01 docker-smoke re-verify
  - Plan 04: CHANGELOG entry [1.5.2]
  - Plan 05: Orchestrator close-gate (Playwright MCP smoke + tag v1017 + v1.5.2 + phase SUMMARY/VERIFICATION + state finalization)

</specifics>

<deferred>
## Deferred Ideas

- The 7 Phase 1075 newly-discovered baseline failures → v1018 with patterns documented in `1075-05-VERIFICATION.md`
- Docker layer caching for the CI alembic job → revisit if v1017 CI shows it's a bottleneck
- Pre-existing typecheck noise in frontend test files → cleanup task for v1018

</deferred>
