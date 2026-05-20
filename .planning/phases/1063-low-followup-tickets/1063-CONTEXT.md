# Phase 1063: LOW follow-up tickets - Context

**Gathered:** 2026-05-20
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

Close 10 LOW-severity follow-up tickets surfaced as non-blocking in the audit's §"Not blocking — follow-up tickets" — defense-in-depth additions, ESLint rules, validation hardening, observability primitives, nginx config hygiene, and operator-facing role-scoping documentation.

**Requirements:** SEC-FU-01..FU-10 (10 total)

**Source of truth:** `docs-internal/audits/sec-audit-20260519.md` §"Not blocking — follow-up tickets" (lines 530-541).

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — discuss phase was skipped per `workflow.skip_discuss=true`.

### Key technical decisions

1. **Grouping by file surface (minimize cross-plan conflicts):**
   - Plan 01: SEC-FU-01 + SEC-FU-08 (STAC test fixtures + pg_audit/column-DDL change log) — observability/test infra
   - Plan 02: SEC-FU-02 + SEC-FU-09 + SEC-FU-10 (demo-guard literal refusal + nginx server_tokens + .env DATABASE_URL docs) — config hardening
   - Plan 03: SEC-FU-03 + SEC-FU-04 (frontend react/no-danger ESLint + GDAL Auth header base64url charset) — input validation hardening
   - Plan 04: SEC-FU-05 + SEC-FU-06 + SEC-FU-07 (STAC intersects max_length + parse_bbox isfinite + ILIKE escape in maps service modules) — Postgres/PostGIS hardening

2. **Plan ordering:** All 4 plans independent (different file surfaces). Wave 1 = all 4 in parallel (sequential dispatch under USE_WORKTREES=false).

3. **Phase 1063 follow-ups identified during Phase 1061/1062 execution should also be addressed:**
   - `router_reupload.py` IDOR gap (from Phase 1061 Plan 06 task 1 grep evaluation) — already excluded from pre-commit hook with tracked rationale; verify with Plan 01 or sweep separately
   - Various IN-* deferred items from Phase 1061 + 1062 reviews (5 items total in pending todos)

### Test strategy
- Each plan adds backend pytest tests for its FU finding where testable.
- ESLint rule (SEC-FU-03) has regression fixture.
- pg_audit (SEC-FU-08) needs migration + integration test.

</decisions>

<code_context>
## Existing Code Insights

- **`validate_demo_credentials_guard`:** Phase 1061 extended to refuse 3 known literal defaults. SEC-FU-02 adds `JWT_SECRET_KEY=demo-only-do-not-use-in-production-change-me` as a 4th literal (or it might already be covered — check).
- **react/no-danger:** ESLint rule already available via `eslint-plugin-react`. Add to `frontend/eslint.config.js`.
- **GDAL Authorization header:** `backend/app/processing/ingest/ogr.py` `run_ogr2ogr_service` builds the Authorization header. Use base64url charset filter.
- **STAC intersects param:** `backend/app/standards/stac/router.py` — already has shape validation; add `max_length` to the GeoJSON string.
- **parse_bbox NaN/Inf:** Search for `parse_bbox` — likely in `backend/app/standards/ogc/` or shared bbox utilities.
- **ILIKE escape:** `backend/app/modules/catalog/maps/service_crud.py:140-147` and `service_collections.py:29-35`. Pattern: `.replace("%", r"\%").replace("_", r"\_")` BEFORE ILIKE concatenation.
- **pg_audit:** PostgreSQL extension. Migration adds it as opt-in (community edition stays no-extension); per-table change log via trigger on `data_versions` table or similar.
- **nginx server_tokens:** `frontend/nginx.conf` or root `nginx.conf` — add `server_tokens off;` to prod server block.
- **DATABASE_URL_OVERRIDE docs:** `.env.example` — add role-scoping commentary for least-privilege.

</code_context>

<specifics>
## Specific Ideas

**SEC-FU-01 (STAC 5xx-mutation test fixtures):**
- Add pytest fixture in `backend/tests/conftest.py` that monkeypatches `apply_visibility_filter` to raise on a flag.
- e2e/sec-audit.spec.ts S01 can use the fixture to assert no information disclosure on 5xx.

**SEC-FU-02 (validate_demo_credentials_guard literal):**
- Phase 1061 Plan 05 already added 3 literals — verify `JWT_SECRET_KEY=demo-only-do-not-use-in-production-change-me` is one of them. If not, add it. If already present, mark SEC-FU-02 as redundant and close.

**SEC-FU-03 (react/no-danger ESLint):**
- Add `'react/no-danger': 'error'` to `frontend/eslint.config.js` plugins/rules.
- Regression test file with `dangerouslySetInnerHTML` violation.

**SEC-FU-04 (GDAL Authorization base64url charset):**
- `run_ogr2ogr_service` in `backend/app/processing/ingest/ogr.py`: filter the header value to base64url alphabet (`A-Za-z0-9_-=`).
- Test: malicious header with CR/LF rejected.

**SEC-FU-05 (STAC intersects max_length):**
- Add `max_length=10000` (large enough for complex polygons, small enough to prevent abuse) to the `intersects` `Query` declaration in `backend/app/standards/stac/router.py`.

**SEC-FU-06 (parse_bbox isfinite):**
- Find `parse_bbox` helper; add `math.isfinite()` check on each coordinate. Reject with 422 if NaN/Inf.

**SEC-FU-07 (ILIKE escape):**
- `backend/app/modules/catalog/maps/service_crud.py:140-147` and `service_collections.py:29-35`: wrap user input in `.replace("%", r"\%").replace("_", r"\_")` before ILIKE concatenation.

**SEC-FU-08 (pg_audit / column DDL change log):**
- Migration adds opt-in pg_audit extension (community edition no-op).
- Alternative: per-table trigger on column-DDL operations writing to `audit_log`.
- Choose lowest-friction approach.

**SEC-FU-09 (nginx server_tokens):**
- `frontend/nginx.conf`: add `server_tokens off;` to the main server block.

**SEC-FU-10 (DATABASE_URL_OVERRIDE role-scoping):**
- `.env.example`: add commentary block on creating a least-privilege Postgres role for the application (vs. running as superuser).

</specifics>

<deferred>
## Deferred Ideas

None — discuss phase skipped.

Related but out of scope for Phase 1063:
- Close gate (SEC-CTRL-01) → Phase 1064

</deferred>
