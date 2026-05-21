# Phase 1071: Known Items Closure - Context

**Gathered:** 2026-05-21
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

All v1015 tech-debt items, v1014 INFO pending todos, and the Dependabot #40 idna bump are closed in code, tests, and docs before fresh audits run.

This phase is the FIRST phase of v1016. It closes known items so the Phase 1072 re-audit reflects post-known-items state (not the v1015 ship state).

**In scope (11 reqs):**

- **KNOWN-01**: `_resolve_download_user` consumes JWT `sub` claim correctly for anonymous download tokens
- **KNOWN-02**: `alembic upgrade head` against a clean DB is exercised
- **KNOWN-03**: `CPL_VSIL_CURL_ALLOWED_EXTENSIONS` clamp applied to all GDAL subprocesses (raster ingest, COG conversion), not only `_build_vrt`
- **KNOWN-04**: VRT VSI allow-list consolidated to a single source of truth
- **KNOWN-05**: Export endpoint returns 403 for revoked-export-on-viewer
- **KNOWN-08**: `.env.example` documents `PASSWORD_MIN_LENGTH` and `PASSWORD_REQUIRE_CLASSES`
- **KNOWN-09**: `validate_password_complexity` whitespace symbol-class decision
- **KNOWN-10**: `where_validator.py` `exp.Dot` AST bypass-path test
- **KNOWN-11**: `_sanitize_authorization_token` 8-char minimum documented inline
- **KNOWN-12**: `StacSearchBody.limit`/`offset` Pydantic `ge`/`le` constraints
- **KNOWN-13**: `idna` bumped to ≥ 3.15 in `backend/uv.lock`

**Out of scope (deferred to other phases):**

- KNOWN-06, KNOWN-07 (close-gate process items — Phase 1074)
- AUDIT-01..03 (re-audit + triage — Phase 1072)
- REMED-01..02 (audit remediation — Phase 1073)
- GATE-01..06 (close-gate — Phase 1074)

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion

All implementation choices at Claude's discretion — discuss phase was skipped per `workflow.skip_discuss=true`. Use:

- ROADMAP phase goal + REQUIREMENTS.md req descriptions
- Pending todo files for KNOWN-08..12 (each has a Finding + Solution section)
- v1015 milestone "Tech-debt followups" section in PROJECT.md for KNOWN-01..05
- Existing codebase patterns from v1014/v1015 (modular routers, `_revalidate_redirect`, `validate_url_for_ssrf`, etc.)

### Plan Granularity

Group reqs by "code surface" rather than 1 plan per req to keep plans coherent:

- **Plan A (KNOWN-13):** Dependabot idna bump — single dependency change, separate commit
- **Plan B (KNOWN-08, 11):** Documentation closures in `.env.example` + ogr.py inline doc
- **Plan C (KNOWN-09, 10, 12):** Validator / schema hardening (password whitespace decision + where_validator AST test + Pydantic bounds)
- **Plan D (KNOWN-01):** Download-token JWT `sub` consumption
- **Plan E (KNOWN-02):** Alembic clean-DB upgrade exercise (script in `backend/scripts/`)
- **Plan F (KNOWN-03):** `CPL_VSIL_CURL_ALLOWED_EXTENSIONS` clamp expansion to all GDAL subprocesses
- **Plan G (KNOWN-04):** VRT VSI allow-list consolidation
- **Plan H (KNOWN-05):** Export 403-for-revoked-viewer parity

That's 8 plans for Phase 1071. Within each plan, atomic commits per req.

</decisions>

<code_context>
## Existing Code Insights

Will be gathered during plan-phase research. Key files per req:

- KNOWN-01: `backend/app/modules/auth/dependencies.py` (`_resolve_download_user`)
- KNOWN-02: `backend/scripts/` (new script) + `backend/alembic/`
- KNOWN-03: `backend/app/processing/ingest/{raster,cog,vrt}` (search for `gdalbuildvrt`, `gdal_translate`, `gdalwarp`)
- KNOWN-04: `backend/app/processing/ingest/vrt.py` (`_VRT_SAFE_ENV`, `validate_vrt_body`)
- KNOWN-05: `backend/app/modules/export/router.py` (`export_dataset_endpoint`)
- KNOWN-08: `.env.example`
- KNOWN-09: `backend/app/modules/auth/password.py` (`validate_password_complexity`)
- KNOWN-10: `backend/app/processing/export/where_validator.py` + `backend/tests/test_where_validator.py`
- KNOWN-11: `backend/app/processing/ingest/ogr.py` (`_sanitize_authorization_token`)
- KNOWN-12: `backend/app/standards/stac/schemas.py` (`StacSearchBody`)
- KNOWN-13: `backend/uv.lock` + `backend/pyproject.toml` (if direct dep)

</code_context>

<specifics>
## Specific Ideas

- **KNOWN-09 whitespace decision:** Treat whitespace as symbol with docstring caveat (per v1062 IN-02 pending todo). This is the simpler choice — don't change validator behavior, just document.
- **KNOWN-13 idna bump:** Transitive dep from `httpx` or `requests`. Use `uv lock --upgrade-package idna` or pin in pyproject.toml constraints.
- **Plan A through H** order: idna bump first (fastest close), docs/tests middle (low risk), then larger code changes (download-token, alembic, GDAL clamp, VRT consolidation, export parity).

</specifics>

<deferred>
## Deferred Ideas

None — all 11 reqs in scope.
</deferred>
