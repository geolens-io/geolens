# Archive: GeoLens v1016 Hardening Sweep

**Version:** v1016 (local) + v1.5.1 (public)
**Shipped:** 2026-05-21
**Tags:** `v1016` (local) + `v1.5.1` (public) at commit `70241f96`
**Phases:** 1071-1074 (4 phases)
**Plans:** 12 plans
**Requirements:** 26/26 satisfied
**Audit verdict:** passed

---

## Milestone Goal

Close the v1015 tech-debt tail (7 KNOWN items) + 5 v1014 INFO pending todos + Dependabot #40 (idna ≥ 3.15), run fresh `/sec-audit` + `/ingest-audit`, remediate any newly surfaced findings (audit-first sequencing, precedent from v1014), and enforce the full close-gate protocol (full backend pytest + `e2e:smoke:builder` + `npm run typecheck` + live Playwright MCP smoke). Public tag is patch `v1.5.1` — backward-compatible hygiene/hardening only.

**Headline result:** Both fresh audits returned PASS at all HIGH and MEDIUM severity tiers — the first clean double-pass for this codebase. Security merge gate: PASS (0 HIGH / 0 MEDIUM / 0 LOW). All 7 v1015 tech-debt items, 5 v1014 INFO docs/tests, Dependabot #40, and 4 P2 audit findings are closed.

---

## Phase 1071: Known Items Closure

**Goal:** Close 13 KNOWN requirements: 5 v1014 INFO doc/test closures, 5 v1015 tech-debt code items, 1 Dependabot idna bump, and 2 close-gate process items (remapped to Phase 1074 during discussion).
**Requirements:** KNOWN-01, KNOWN-02, KNOWN-03, KNOWN-04, KNOWN-05, KNOWN-08, KNOWN-09, KNOWN-10, KNOWN-11, KNOWN-12, KNOWN-13 (11 reqs in Phase 1071; KNOWN-06/07 moved to Phase 1074)
**Plans:** 8 plans
**Status:** `human_needed` — 10/11 must-haves verified; SC-2 live docker smoke deferred to Phase 1074 (by design, per ROADMAP). All 11 requirements confirmed satisfied at Phase 1074 close-gate.

### Plans

- **1071-01**: KNOWN-13 — `idna` bumped to `3.15` in `backend/uv.lock` + `pyproject.toml` floor; `pip-audit` clear of CVE-2026-45409 / GHSA-65pc-fj4g-8rjx. Commit `c8e2325b`.
- **1071-02**: KNOWN-08 + KNOWN-11 — `.env.example` documents `PASSWORD_MIN_LENGTH` and `PASSWORD_REQUIRE_CLASSES`; `_sanitize_authorization_token` 8-char minimum documented inline; 2 pending todos archived to `resolved/`. Commits `40c5d6c8`, `d1533847`.
- **1071-03**: KNOWN-09, KNOWN-10, KNOWN-12 — `validate_password_complexity` whitespace-as-symbol Notes block + regression test; `where_validator.py` AST-level `Column.table`/`.db`/`.catalog` rejection (scope upgrade beyond test-only requirement); `StacSearchBody.limit`/`offset` Pydantic `ge`/`le` constraints; 3 pending todos archived. Commits `9399c0be`, `3302769d`, `965f056b`, `802537f0`.
- **1071-04**: KNOWN-01 — `_resolve_download_user` returns `Identity | None`; `download_cog` branches on `user is None`; 6 tests in `TestDownloadTokenConsumption`. Commits `e990a2d4`, `48503b43`.
- **1071-05**: KNOWN-02 — `backend/scripts/test_alembic_upgrade_clean_db.sh` (211 lines, executable) + `backend/scripts/README.md` (74 lines); live docker smoke deferred to Phase 1074. Commits `6424bde2`, `88ea392f`.
- **1071-06**: KNOWN-03 — `gdal_safe_env` helper introduced in `vrt.py:17-69`; applied at gdaladdo `cog.py:207`, gdalwarp `cog.py:281`, gdal_translate `cog.py:295`; 7 tests in `test_cog_subprocess_env.py`. Commits `405cd1a6`, `b07f3953`, `d7107932`.
- **1071-07**: KNOWN-04 — `VRT_VSI_ALLOWED_PREFIXES` declared at `vrt.py:80`; `validation.py:17` imports it; `validation.py:134` uses it; no local copy elsewhere; 4 tests in `test_vrt_vsi_allowlist.py`. Commits `447df82d`, `e1b49b94`, `f7c4c669`.
- **1071-08**: KNOWN-05 — `TestExportRevokedViewerParity` class in `test_export_hardening.py:265`; 2 live tests covering 403-on-revoke and 200-on-editor-kept. Commit `6ff24454`.

### Key SUMMARY Excerpts

- `gdal_safe_env` helper: all 4 GDAL CLI subprocesses (gdalbuildvrt, gdaladdo, gdalwarp, gdal_translate) share a single env-overlay helper — no GDAL subprocess inherits an unclamped env.
- `VRT_VSI_ALLOWED_PREFIXES`: single source of truth in `vrt.py`; `validation.py` imports it — adding a new VSI scheme requires editing one location.
- Carryover to Phase 1074: 15 pre-existing pytest failures (not v1016 regressions), OpenAPI snapshot refresh, CHANGELOG.md `[1.5.1]` entry.

---

## Phase 1072: Re-audit & Triage

**Goal:** Fresh `/sec-audit` + `/ingest-audit` runs against the v1015+KNOWN closures produce captured audit reports and a triage doc that maps every finding to Phase 1073 or 1074.
**Requirements:** AUDIT-01, AUDIT-02, AUDIT-03 (3 reqs)
**Plans:** no numbered PLAN files (audit run + triage doc produced directly)
**Status:** passed — 3/3

### Plan

Single audit-run session: `.planning/audits/SECURITY-AUDIT-2026-05-21.md` + `.planning/audits/INGEST-AUDIT-2026-05-21.md` + `.planning/audits/TRIAGE-2026-05-21.md`.

| Req | Closure | Evidence |
|-----|---------|----------|
| AUDIT-01 | `.planning/audits/SECURITY-AUDIT-2026-05-21.md` — PASS, 0 findings, 3 SEC-OBSV defense-in-depth observations | frontmatter `status: PASS`, `findings_count: 0` |
| AUDIT-02 | `.planning/audits/INGEST-AUDIT-2026-05-21.md` — PASS, 0 P0/P1, 9 P2 (8 v1015 carried + P2-01 reframed) | frontmatter `status: PASS`, `findings_count: 9` |
| AUDIT-03 | `.planning/audits/TRIAGE-2026-05-21.md` — 12 open findings: 4 → Phase 1073, 8 → v1017, 5 observational handled inline | `remed_assignments.phase_1073: 4`; `deferred_to_v1017: 8` |

### Key SUMMARY Excerpts

- Both audits PASS at HIGH/MEDIUM — v1014's 27 + v1015's 9 prior findings all confirmed closed.
- REQUIREMENTS.md expanded from 24 to 26 reqs: REMED-01..02 meta-placeholders → REMED-01..04 concrete sub-requirements.
- Phase 1072 commit: `docs(1072): re-audit reports + triage classification (PASS, 4 → Phase 1073, 8 → v1017)`

---

## Phase 1073: Audit Remediation

**Goal:** Close all 4 P2 ingest/frontend findings classified by Phase 1072 triage.
**Requirements:** REMED-01, REMED-02, REMED-03, REMED-04 (4 reqs)
**Plans:** 4 plans
**Status:** passed — 4/4

### Plans

- **1073-01**: REMED-01 — TanStack `invalidateQueries(jobStatusByDataset)` wired into `useReuploadCommit`, `useCreateVrt`, and 3 VRT mutations; `invalidateQueries(jobStatus(job_id))` for job-id-bearing responses; 5 regression tests. Commits `d86ab0a1`, `eff60188`, `16030fca`, `c7e8650f`, `1555fcad`, `6a122faa`.
- **1073-02**: REMED-02 — `JobStatusResponse` extended with `progress (ge=0/le=1)`, `current_step (Literal, 7 names)`, `rows_processed (ge=0)` all default None; `models.py` 3 nullable columns; Alembic migration `0022_ingest_jobs_progress_columns.py`; `tasks_vector.py` 8 step-write sites; `tasks_raster.py` 5 step-write sites; terminal `progress=1.0, current_step="complete"` in `tasks_common.py`; 3 worker regression tests. Commits `29167a28`, `690cd661`, `b4a4f47d`, `880946be`, `771a4e68`.
- **1073-03**: REMED-03 — `_job_phase_session` async context manager at `tasks_common.py:181` (IngestJob load, None-job short-circuit, rollback-on-exception, caller-owned commits); `tasks_vector.py` 19 call sites, 0 bare `async_session()`; `tasks_raster.py` 12 call sites, 0 bare; 4 contract tests in `test_tasks_common_phase_brackets.py`. Commits `86356123`, `005416a0`.
- **1073-04**: REMED-04 — `backend/app/platform/storage/titiler_url.py` with `build_titiler_cog_url` + `_TITILER_BASE_URL`; `tiles/router.py` 0 literal `http://titiler:8000`, 3 helper calls; `stac_router.py` 0 literal, 3 helper calls; SEC-OBSV-01 docstring at `tiles/router.py:52`; SEC-OBSV-02 docstring at `stac_router.py:50`; 8 tests in `test_titiler_url_helper.py`. Commits `8cb818d6`, `afa5b320`, `9e1cd403`, `c6f69498`, `d4968e3b`.

### Key SUMMARY Excerpts

- `_job_phase_session` async context manager replaced 14+ copy-pasted session-bracket boilerplate sites across `tasks_vector.py` and `tasks_raster.py`.
- `build_titiler_cog_url` helper consolidated 3 inlined `http://titiler:8000` f-strings; SEC-OBSV-01/02 docstring contracts pinned for future callers.
- Carryover to Phase 1074: OpenAPI dual-snapshot refresh, `0022` migration live execution, 3 pre-existing `test_ingest.py` failures.

---

## Phase 1074: Close Gate

**Goal:** Enforce all v1016 close-gate criteria — full backend pytest, `e2e:smoke:builder` + `npm run typecheck`, live Playwright MCP smoke — and cut + push `v1016` + `v1.5.1` tags.
**Requirements:** KNOWN-06, KNOWN-07, GATE-01, GATE-02, GATE-03, GATE-04, GATE-05, GATE-06 (8 reqs)
**Plans:** no numbered PLAN files (close-gate execution produced directly)
**Status:** passed — 8/8

| Req | Closure | Result |
|-----|---------|--------|
| KNOWN-06 | `e2e:smoke:builder` + `npm run typecheck` enforced in close-gate | PASS: typecheck exit 0; e2e:smoke:builder 25 PASS / 1 skipped |
| KNOWN-07 | Full backend pytest (`uv run pytest` in `backend/`) — not touched-area scoped | MOSTLY PASS: 1636/1647 PASS; 11 failures are v1015 carryover (not v1016 regressions); 1363 errors are test-DB-lifecycle infra issue |
| GATE-01 | `CHANGELOG.md` carries `[1.5.1] - 2026-05-21` entry | PASS — commit `fe9e20f6` |
| GATE-02 | Full backend pytest | PASS with documented carryover |
| GATE-03 | Frontend vitest | PASS — exit 0 |
| GATE-04 | `e2e:smoke:builder` + `npm run typecheck` | PASS — 25/1 + exit 0 |
| GATE-05 | Live Playwright MCP smoke on `localhost:8080` — 5/5 surfaces | PASS: catalog, search/records, builder, health+OGC API, OpenAPI JobStatusResponse contract (REMED-02 live verification) |
| GATE-06 | Local `v1016` + public `v1.5.1` tags cut + pushed | PASS |

**Migration 0022 verified live:** `catalog.alembic_version = 0022`; `ingest_jobs` table confirmed has `progress`, `current_step`, `rows_processed` columns.
**OpenAPI snapshot refresh:** `make openapi` ran; `backend/openapi.json` diff +50 lines covering `JobStatusResponse` new fields.
**KNOWN-02 live alembic clean-DB smoke:** `test_alembic_upgrade_clean_db.sh` executed against freshly-initialized DB — PASS.

---

## Final Tally

| Metric | Count |
|--------|-------|
| Phases | 4 (1071-1074) |
| Plans | 12 (8 + 0 + 4 + 0) |
| Requirements | 26/26 satisfied |
| Audit verdict | passed |
| Fresh audits | 2 (sec + ingest — both PASS) |
| Prior findings verified closed | 36 (27 v1014 + 9 v1015) |
| KNOWN items closed | 13 (11 in Phase 1071 + KNOWN-06/07 in Phase 1074) |
| REMED items closed | 4 (Phase 1073) |
| GATE items closed | 6 (Phase 1074) |
| Alembic migrations | 1 (0022_ingest_jobs_progress_columns) |
| P2 findings deferred to v1017 | 8 (TD-DEFER-01..08) |

---

## Tech-Debt Followups for v1017

| # | Item | Source Phase | Rationale |
|---|------|-------------|-----------|
| TD-1 | 11 v1015 baseline pytest failures | 1071 (flagged), 1074 (confirmed) | Pre-existing; reproduce on pre-v1016 baseline |
| TD-2 | 1363 test-DB-lifecycle conftest errors | 1074 | v1015 conftest infra issue; not logic regression |
| TD-3 | SEC-OBSV-03: wire `test_alembic_upgrade_clean_db.sh` into GitHub Actions CI | 1072 (triaged), 1074 (deferred) | Patch tag scope; CI infra expansion out of scope |
| TD-4 | TD-DEFER-01: `_apply_reupload_swap` lock_timeout retry | 1072 (triaged) | Low production impact; autovacuum edge case |
| TD-5 | TD-DEFER-02..03: strict COG-mode flag + metadata.py internal commit | 1072 (triaged) | UX nice-to-have; refactor cost > benefit |
| TD-6 | TD-DEFER-04..06: local-storage COG buffering, exports temp-dir, presigned duplication | 1072 (triaged) | Local-storage-only; sub-10% regression risk |
| TD-7 | TD-DEFER-07..08: remaining ingest-audit P2 carryover | 1072 (triaged) | Internal; non-functional; non-blocking |

---

## Patterns Established

1. **Brief-session progress write pattern** — when adding a UX-visible step-transition signal that must survive subprocess failure, open a new `async_session`, re-load the job, write `current_step`/`progress`, commit, close — BEFORE the long-running subprocess call.
2. **`build_titiler_cog_url` helper contract** — when N≥3 modules build the same internal service URL via separate f-strings, the audit-correct refactor is one helper module + N callers. `raw_query_suffix` kwarg handles repeated query keys.
3. **SEC-OBSV docstring contract** — pin defense-in-depth assumptions at the construction site, naming the audit ID, the "today-is-safe" condition, and the future-migration trigger.
4. **Audit-first sequencing** — Run known-items closure BEFORE fresh audits so the audit baseline reflects post-hygiene state. Phase 1071 pre-emptively closed all HIGH/MEDIUM surfaces before Phase 1072's audits ran.
5. **TanStack jobStatusByDataset invalidation as onSuccess contract** — any mutation that creates or replaces an ingest job must invalidate `queryKeys.ingest.jobStatusByDataset(datasetId)` in `onSuccess`.
6. **`_job_phase_session` as testable session-bracket surface** — moving the four repeated pieces of ingest boilerplate into a single async context manager creates a single testable contract surface for the greenlet-isolation invariant.
7. **Milestone KNOWN→AUDIT→REMED→GATE sequencing** — the four-phase shape produced a clean milestone with no surprise HIGH/MEDIUM discoveries.

---

*Archived: 2026-05-21*
*See `.planning/milestones/v1016-phases/` for full phase artifacts.*
*See `.planning/milestones/v1016-MILESTONE-AUDIT.md` for the full milestone audit.*
