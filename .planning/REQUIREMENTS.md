# Requirements: v1019 Hygiene Tail — v1018 Frontend + xdist + Process

**Defined:** 2026-05-22
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.

**Milestone framing:** Hygiene close of the 4 tech-debt items deferred from the v1018 audit (3 frontend cleanup, 1 test-infra environmental cap) + TD-07 runtime symmetry verification (api/worker container rebuild + version probe) + process tightening (REQUIREMENTS authoring nodeID pinning + executor SUMMARY traceability flip) surfaced by v1018 docs/code drift bugs. No new user-facing features, no migrations. Public tag target: `v1.5.4` (patch).

**Source of truth:**
- `.planning/milestones/v1018-MILESTONE-AUDIT.md` frontmatter `tech_debt` (4 items)
- v1018 audit user-direction (TD-07 runtime rebuild + process tightening)

## v1019 Requirements

Each requirement maps to exactly one phase. Plan-level node-IDs / file paths are listed inline so the planner does not need to re-derive them.

### Frontend Hygiene

These items are pre-existing — surfaced during v1018 close-gate live Playwright MCP smoke but explicitly deferred per user decision. Each lands as a small, localized fix.

- [ ] **TD-09**: Resolve the 36 pre-existing TypeScript errors across 14 untouched frontend test files. Scope is `tsc -b` exit 0 with zero `// @ts-expect-error` / `// @ts-ignore` suppressions added during the fix. Files in scope are the 14 surfaced by v1018 Phase 1083 baseline (`frontend/src/**/*.test.{ts,tsx}` set with errors at v1018 audit). Pin behaviour by running `cd frontend && npm run typecheck` and confirming exit 0 against the full project (not just touched files, which was the v1018 baseline gate). Track delta between v1017 baseline (36 errors / 14 files) and v1019 close (0 errors / 0 files) in CHANGELOG.

- [ ] **TD-11**: Eliminate the `/maps/new` 422 console-noise pattern — the page fires 2 spurious 422 requests before the Create dialog short-circuits and renders. Root cause is the v1008 catalog-first empty-state quirk (page mounts, mutation hooks fire against the not-yet-created map, then the Create dialog short-circuit takes over). Fix by gating the network calls behind the dialog-resolution state OR by routing `/maps/new` directly to the Create dialog without mounting the live editor surface. Pin behaviour by visiting `/maps/new` in a Playwright MCP smoke session and asserting zero 422 console entries in the network log.

- [ ] **TD-12**: Restore single-prefix URL path on legacy quicklook proxy endpoints — currently `/api/api/<…>` is generated for quicklook resources due to double-prefix concatenation (one prefix in the proxy base URL, one in the route definition). All current responses return 200 OK (cosmetic only), but the doubled prefix bypasses any future per-prefix auth / rate-limit middleware. Fix at the source: identify whether the duplication lives in the frontend client (`frontend/src/api/`) or the nginx/route-table side. Pin behaviour by grepping the frontend network log during a Playwright MCP smoke session and asserting zero `/api/api/` patterns.

### Test Infrastructure

- [x] **TD-10**: Stabilize `pytest -n auto` on 16 xdist workers so the Postgres recovery cascade does not occur. Symptom: when xdist spawns 16 workers, the asyncpg connection pool fan-out can exceed Postgres `max_connections`, triggering a recovery cycle that cascades across worker test-DBs. Fix is spike-first per evidence: Plan 1085-01 measures `max_connections` + per-worker concurrent connection count in a 16-worker run, then Plan 1085-02 implements the chosen fix shape from these three options:
  - (a) per-worker pool sizing in `backend/tests/conftest.py` — scale asyncpg pool min/max per `PYTEST_XDIST_WORKER`
  - (b) docker-compose / postgres-test container `max_connections` bump
  - (c) Cap `-n` at 4 or 8 in Makefile / CI invocation

  The spike doc lands at `.planning/audits/PYTEST-XDIST-SPIKE-v1019.md` and records the measurement methodology, observed numbers, and chosen fix shape with rationale.

### Process Tightening

- [ ] **TD-13**: Tighten REQUIREMENTS authoring + executor SUMMARY workflow to prevent the two drift patterns surfaced in v1018:
  - **REQ authoring**: v1018 TD-02/03 paraphrased test names that did not exist in code (`test_register_password_too_short` / `test_register_password_diversity`) instead of pinning the actual `test_register_emits_user_register_audit` / `test_register_disabled_does_not_emit_audit`. Also `tasks_common.py` path drift (cited `backend/app/platform/jobs/` but actual is `backend/app/processing/ingest/`) and line drift (231/237 vs 232/238). **Fix shape**: future requirements that pin specific tests must use exact `path::TestClass::test_name` node-IDs, validated against `git grep` before commit. Production-code citations must include path + line, validated against `git grep` before commit.
  - **Executor SUMMARY flip**: v1018 Plan 1081-02 executor closed TD-05 in code but did not flip REQUIREMENTS.md `[ ]` → `[x]` / Pending → Complete (integration check caught it mid-audit, fixed inline as commit `5bf63166`). **Fix shape**: bake "update REQUIREMENTS.md checkbox + traceability row" into the executor's standard SUMMARY workflow before commit.

  Two-file deliverable:
  - **Repo retro** at `.planning/retros/v1019-process.md` — project-scoped narrative + the two specific v1018 incidents that drove the rule changes
  - **Global skill update** at `~/.claude/get-shit-done/` — touch `agents/gsd-planner` (REQ authoring nodeID rule) + `agents/gsd-executor` (SUMMARY checkbox flip) + `templates/requirements.md` (nodeID schema example). Skill updates apply to all GSD projects, not just GeoLens.

### Runtime Symmetry (close-gate bundled)

- [ ] **TD-14**: Verify TD-07 (`connect_args["ssl"]=False` on `database_ssl_mode='disable'` branch from v1018 Phase 1080-02) is live in the deployed `api` and `worker` container images. v1018 Plan 1080-02 baked the fix into the source but the running stack at audit time was 8 hours old (predating the fix commit). Close-gate verification:
  1. `docker compose up -d --build api worker`
  2. Probe the deployed images to confirm the new code is in place (e.g., grep the running container's `app/core/config.py` for the `ssl=False` line, or exercise the disable branch through a config-injection unit-test against the live image).
  3. Record the live-rebuild + probe result in the v1019 close-gate summary.

  Bundled into Phase 1086 close-gate — not a standalone phase. Runtime impact is nil (production never sets `disable`), so this is symmetry between code and deployed runtime.

## Future Requirements

Deferred from v1018 audit. Not in v1019 roadmap but tracked.

### Frontend Quality (post-v1019)

- **FE-FUTURE-01**: 36 TS errors in 14 frontend test files (covered by TD-09 — moving to v1019 active)
- **FE-FUTURE-02**: Server-side map thumbnails (carried from v13.10 OPS-01)

### Backend Architecture (post-v1019)

- **BACKEND-FUTURE-01**: 999.6 tenant-scoping infrastructure (parked phase dir)
- **BACKEND-FUTURE-02**: 999.13 persistent connector registry (parked phase dir)
- **BACKEND-FUTURE-03**: 999.16 extract geolens-schemas package (parked phase dir)

### Distribution (post-v1019)

- **DIST-FUTURE-01**: 999.14 helm chart + AMI packer pipeline (parked phase dir)
- **DIST-FUTURE-02**: 999.15 SBOM + signed image distribution (parked phase dir)

## Out of Scope

Explicitly excluded from v1019 to keep hygiene shape clean.

| Feature | Reason |
|---------|--------|
| New user-facing features | v1019 is a hygiene patch (`v1.5.4`); user-facing work belongs in the next minor milestone |
| Schema migrations | All TD items are non-schema; any migration would push public tag from patch to minor |
| Dependabot sweep | Last clean sweep was v1016 + v1017; no fresh open alerts as of v1018 close |
| Audit reruns (`/sec-audit`, `/ingest-audit`) | v1016 Phase 1072 was the most recent clean double-pass; not due again until a real-feature milestone |
| Frontend feature refactors beyond TD-09/11/12 scope | Out of milestone shape; hygiene fixes only |
| Backend feature refactors beyond TD-10 spike+fix | Out of milestone shape; test-infra only |

## Traceability

Which phases cover which requirements. Updated by the roadmapper during ROADMAP.md creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| TD-09 | Phase 1084 | Pending |
| TD-10 | Phase 1085 | Complete |
| TD-11 | Phase 1084 | Pending |
| TD-12 | Phase 1084 | Pending |
| TD-13 | Phase 1086 / Plan 1086-01 | Pending |
| TD-14 | Phase 1086 / Plan 1086-02 | Pending |

**Coverage:**
- v1019 requirements: 6 total
- Mapped to phases: 6
- Unmapped: 0 ✓

---
*Requirements defined: 2026-05-22*
*Last updated: 2026-05-22 — initial REQUIREMENTS.md for v1019 Hygiene Tail. 6 TD reqs across 3 phases (continued numbering from v1018: 1080-1083 → 1084-1086). Source: v1018 audit `tech_debt` (4 items) + user-direction (TD-07 runtime + process tightening).*
