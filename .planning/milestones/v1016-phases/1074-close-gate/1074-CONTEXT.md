# Phase 1074: Close Gate - Context

**Gathered:** 2026-05-21
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

Run all close-gate verification + write CHANGELOG entry + cut local `v1016` + public `v1.5.1` tags. This is the final phase of v1016 Hardening Sweep.

**In scope (8 reqs):**

- **KNOWN-06**: `e2e:smoke:builder` + `npm run typecheck` enforced in close-gate (v1015 process item)
- **KNOWN-07**: Full backend pytest enforced in close-gate (v1015 process item)
- **GATE-01**: CHANGELOG.md `[1.5.1] - 2026-05-21` entry listing every closed item
- **GATE-02**: Full backend pytest passes (`uv run pytest` in `backend/`)
- **GATE-03**: Frontend vitest passes (`npm run test` in `frontend/`)
- **GATE-04**: `e2e:smoke:builder` + `npm run typecheck` pass in `frontend/`
- **GATE-05**: Live Playwright MCP smoke on `localhost:8080` against rebuilt containers — 5/5 surfaces PASS (catalog, dataset detail, builder, viewer, AI/embed status)
- **GATE-06**: Local `v1016` tag + public `v1.5.1` tag cut at the close-gate commit; pushed to `origin`

**Plus radar items from earlier phases:**

- **OpenAPI dual-snapshot refresh** — REMED-02 changed JobStatusResponse shape; per project memory ["OpenAPI dual-snapshot refresh order"], run `make openapi` (in `backend/`) BEFORE `npm run fetch-openapi` (in sibling `getgeolens.com/`). Note: project memory says sibling docs repo path; the local frontend snapshot at `frontend/src/types/openapi.ts` also needs refresh via `npm run fetch-openapi` in `frontend/`.
- **Alembic clean-DB live smoke** — run `backend/scripts/test_alembic_upgrade_clean_db.sh` against live docker daemon. This is KNOWN-02 carryover from Phase 1071 + verifies migration 0022 (REMED-02).
- **SEC-OBSV-03 CI gate wiring** — wire `test_alembic_upgrade_clean_db.sh` into `.github/workflows/`. Optional (could defer to v1017 if scope tight).
- **Triage 18 pre-existing baseline failures** — 15 v1015 baseline failures flagged in 1071-01 SUMMARY + 3 in 1073-02 (test_ingest.py max_size_bytes mocks + DNS-resolution fail for example.arcgis.com). Determine: regression vs flaky vs accept-with-rationale.

**Out of scope:**
- 8 v1015-carried P2 → v1017 (already deferred per Phase 1072 triage)
- New features or refactors

</domain>

<decisions>
## Implementation Decisions

### Locked Decisions

- **Public version:** `v1.5.1` (patch — backward-compatible hygiene/hardening). Confirmed in REQUIREMENTS.md GATE-06.
- **CHANGELOG header:** `## [1.5.1] - 2026-05-21` — list KNOWN closures + REMED closures + audit-PASS verdicts.
- **Plan organization (4 plans, sequential — close-gate phases are inherently serial):**
  - `1074-01`: OpenAPI snapshot refresh + alembic live smoke (verifies Phase 1071's script + Phase 1073's migration 0022)
  - `1074-02`: Test gate runs (backend pytest, frontend vitest, e2e:smoke:builder, typecheck) + baseline-failure triage
  - `1074-03`: CHANGELOG entry + Playwright MCP live smoke 5/5 surfaces (catalog, dataset detail, builder, viewer, AI/embed status)
  - `1074-04`: Tag + push (local `v1016` + public `v1.5.1`; only after all prior gates green)

- **SEC-OBSV-03 CI wiring:** DEFER to v1017. v1016 is hygiene/patch; adding CI infrastructure expands scope beyond patch semantics. Document in tech-debt followup.

### Claude's Discretion

- Triage approach for 18 pre-existing baseline failures: try to fix the cheapest ones inline if < 30 min total; otherwise document and accept-with-rationale (they reproduce on v1015 baseline, not regressions from v1016).
- Whether to push the dependent commits/tags or stop at "tag created locally" and ask the user to push manually. Default: push to origin since v1015 was pushed autonomously.
- Whether to run `e2e:smoke:fixtures` + `e2e:export` (INGEST-OBSV-01 deferral) as part of GATE-04 or separately. Default: include them — they're cheap if the live stack is up.

</decisions>

<code_context>
## Existing Code Insights

- v1014/v1015 close-gate patterns at `.planning/milestones/v1014-phases/1064-*` and `.planning/milestones/v1015-phases/1070-*` — mirror the structure.
- CHANGELOG.md template: existing `[1.5.0]` entry from v1015 archive. Add `[1.5.1]` ABOVE `[1.5.0]`.
- Playwright MCP usage pattern from v1011 (live MCP re-verify): orchestrator-driven, not executor-delegated.

</code_context>

<specifics>
## Specific Ideas

- **CHANGELOG `[1.5.1]` content outline:**
  - **Security & Hardening (Phase 1071 closures):** idna ≥ 3.15 (CVE-2026-45409); AST-level table-qualified column reference rejection in WHERE validator; `_resolve_download_user` anonymous-public consumer fix; gdal_safe_env clamp extended to all GDAL subprocesses; VRT VSI allow-list single source of truth; password whitespace symbol-class stance documented; StacSearchBody pagination bounds; `_sanitize_authorization_token` 8-char docstring; alembic clean-DB upgrade script; export 403 revoked-viewer regression pin.
  - **Audit re-pass (Phase 1072):** /sec-audit + /ingest-audit both PASS; v1014/v1015 closures verified; 0 HIGH/MEDIUM remediation needed.
  - **Polish (Phase 1073 closures):** TanStack invalidation for reupload + VRT mutations; JobStatusResponse progress/current_step/rows_processed fields; ingest worker brief-session pattern + _job_phase_session helper; build_titiler_cog_url helper with SEC-OBSV-01/02 docstrings.
  - **Migrations:** alembic 0022 (ingest_jobs progress columns, reversible).
  - **Tags:** local v1016 + public v1.5.1.

- **Playwright MCP 5/5 surfaces** (mirroring v1015 close-gate pattern):
  1. Catalog page loads, shows datasets, 0 console errors
  2. Dataset detail page loads for a vector + raster dataset, 0 console errors
  3. Builder page loads, can add a layer from catalog, no JS errors
  4. Viewer page loads a saved map, tiles render, no JS errors
  5. AI/embed status endpoint responds correctly (authed + anonymous-public)

</specifics>

<deferred>
## Deferred Ideas

- SEC-OBSV-03 CI wiring → v1017 tech-debt
- INGEST-OBSV-01 e2e gates → fold into GATE-04 if cheap; defer to v1017 if not
- 18 baseline failure triage → try to close cheap ones; document remainder as v1015-carryover for v1017

</deferred>
