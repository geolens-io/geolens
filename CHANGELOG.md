# Changelog

All notable changes to GeoLens are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

GitHub release notes are generated from this file, so `CHANGELOG.md` is the release-note source of truth.

> **Note on version history.** GeoLens 1.0.0 marks the first public release. Prior to 1.0.0, the project was internally versioned as 2.0 → 14.0 during pre-public development. The legacy entries below 1.0.0 are preserved for historical context only — they do not represent prior public releases. There is no migration path from any pre-1.0.0 version; 1.0.0 is the first version anyone outside the project has run.

## [Unreleased]

## [1.5.2] - 2026-05-21

### Test infrastructure (v1017 milestone — Phase 1075)

- Refactored `backend/tests/conftest.py` to use per-worker test-DB isolation
  via `PYTEST_XDIST_WORKER`. Eliminates the 1363
  `asyncpg.exceptions.InvalidCatalogNameError` errors observed in v1016
  Phase 1074 full-suite runs. Adds 6 regression tests pinning the lifecycle
  invariants. Adds `pytest-xdist>=3.6.0` to dev dependencies.
- Fixed 11 v1015 baseline pytest failures across `test_defer_orphan_guard.py`
  (3 — mock-fixture drift from Phase 1065-02 IDOR closure), `test_ingest.py`
  (3 — mock signature drift + SSRF re-validation from Phase 1066 IA-P0-02/03),
  and `test_maps_style_json.py` (5 — snake_case canonicalization from
  Phase 1060 `a400eb89`).
- Captured post-v1017 pytest baseline at
  `.planning/audits/PYTEST-BASELINE-2026-05-21.md`. Future regressions are
  now spotted by diff.

### Backend ingest P2 closure (Phase 1076)

- **ING-02:** Removed 4 internal `await session.commit()` from `metadata.py`
  phase-2 helpers (`ensure_geom_column`, `clip_to_mercator_bounds`,
  `add_4326_column`, `grant_reader_access`). `_finalize_ingest` is now the
  single phase-2 commit point. Added regression test asserting rollback
  undoes column-add.
- **ING-03:** New `StorageProvider.get_stream()` Protocol method +
  local-storage 1 MiB chunked impl. Local-storage COG export now streams
  instead of buffering — 5 GB COG no longer pins 5 GB resident memory.
  S3 redirect path untouched.
- **ING-04:** Worker exports temp-dir sweep at `worker.py` now gates on
  `stat.st_mtime > 1 hour`; in-flight large exports survive worker restarts.
  New helper `_sweep_orphaned_exports`.
- **ING-06:** `_apply_reupload_swap` now retries once on
  `LockNotAvailableError` with `SET LOCAL lock_timeout = '15s'` + 200ms
  sleep. Logs contention event for autovacuum correlation.
- **ING-07:** New optional `RasterCommitRequest.strict_cog: bool = False`
  field. When `True`, raster commit rejects non-COG TIFFs at the
  magic-byte rule. Backward-compatible default.

### Frontend ingest P2 closure (Phase 1077)

- **ING-01:** New `getCogDownloadUrl(id)` helper in
  `frontend/src/api/datasets.ts`. `JobProgress.tsx` no longer string-concats
  the URL.
- **ING-05:** Extracted `uploadChunks(urls, file, partSize)` into new
  `frontend/src/api/_presignedUpload.ts`. Both `ingest.ts` and `datasets.ts`
  chunked-PUT loops now share the canonical helper.

### CI hardening (Phase 1078)

- **CI-01:** Wired `backend/scripts/test_alembic_upgrade_clean_db.sh` into
  GitHub Actions as the `alembic-clean-db` job. Migration regressions
  against a fresh DB now fail the build immediately, not at production
  rollout. Closes SEC-OBSV-03 from v1016 Phase 1072 triage.

### Verification (Phase 1079)

- **TI-03:** Pytest baseline captured.
- **VG-01:** Re-verified Phase 1071 KNOWN-02 (alembic clean-DB script)
  against live `docker compose up -d --build` stack.
- **HYG-01:** Trimmed accumulated `.planning/quick/` tail from 196 → <50
  active items.

### Internal

- 5 phases (1075-1079), 13 requirements, all closed.
- Tag: `v1017` (local) + `v1.5.2` (public).

## [1.5.1] - 2026-05-21

### Hardening sweep (v1016 milestone)

Phases 1071-1074 — 26 requirements closing the v1015 tech-debt tail + 5 v1014
INFO pending todos + Dependabot #40, plus 4 P2 findings surfaced by the fresh
`/sec-audit` + `/ingest-audit` re-runs. Both re-audits returned PASS at
HIGH/MEDIUM severity — v1014's 27 closures + v1015's 9 closures + Phase 1071's
11 KNOWN closures all verified clean by both auditors.

### Security & Hardening (Phase 1071 — Known Items Closure)

- **KNOWN-13:** Bumped `idna` to ≥ 3.15 in `backend/uv.lock` and pinned the
  floor in `backend/pyproject.toml`, closing Dependabot #40 (CVE-2026-45409 /
  GHSA-65pc-fj4g-8rjx — DoS via `idna.encode()` with crafted inputs).
- **KNOWN-10:** `where_validator.py` now enforces AST-level rejection of
  table-qualified column references. The prior implementation's docstring
  claimed AST-level rejection but sqlglot's postgres dialect folds `tbl.col`
  into an `exp.Column` with `.table` populated rather than emitting a separate
  `exp.Dot` node, so the validator silently accepted bypasses. A 6-line
  conditional in the allowlist walk honors the documented security contract,
  with a permanent regression test covering both `tbl.col` and `db.tbl.col`.
- **KNOWN-01:** `_resolve_download_user` now returns `Identity | None` (Shape A)
  so anonymous download tokens for public datasets can flow through the COG
  download path end-to-end. Previously the consumer rejected any token
  missing `sub` with HTTP 401, breaking the entire anonymous flow that the
  mint endpoint nominally supported. `AuditEvent.user_id` retyped to
  `uuid.UUID | None` to persist anonymous audit rows. 6 regression tests pin
  authenticated + anonymous-public + anonymous-private-rejected + expired +
  wrong-scope + defense-in-depth-private paths.
- **KNOWN-03:** Promoted `_gdal_safe_env` → `gdal_safe_env` as a shared helper
  with an optional `extras=` keyword, and wired all 3 raster GDAL subprocesses
  (`gdaladdo`, `gdalwarp`, `gdal_translate` in `cog.py`) through it.
  `CPL_VSIL_CURL_ALLOWED_EXTENSIONS` now clamps every raster CLI call, not
  only `_build_vrt`. 7 regression tests pin the clamp at each call site.
- **KNOWN-04:** Consolidated the 7-prefix VRT VSI allow-list into a single
  module-level `VRT_VSI_ALLOWED_PREFIXES` constant in `raster/vrt.py`,
  consumed by both `validate_vrt_body` and the `_VRT_SAFE_ENV` overlay.
  Adding a new VSI scheme now requires editing exactly one place; the prior
  dual-edit risk that v1015 flagged is closed.
- **KNOWN-05:** Added `TestExportRevokedViewerParity` integration test that
  pins the export endpoint returns 403 for a viewer whose `export` permission
  was revoked (full parity with v1014 SEC-S04; previously only anonymous-401
  was verified). Production code unchanged — the `require_permission("export")`
  guard was already correct.
- **KNOWN-08, KNOWN-11:** Documentation closures for v1014 INFO findings —
  `.env.example` now documents `PASSWORD_MIN_LENGTH` + `PASSWORD_REQUIRE_CLASSES`
  near the existing auth settings, and `_sanitize_authorization_token` has an
  inline docstring noting the 8-character minimum it enforces.
- **KNOWN-09:** `validate_password_complexity`'s whitespace-as-symbol-class
  stance documented in the function docstring with rationale; pinned by a
  trailing-whitespace regression test.
- **KNOWN-12:** `StacSearchBody.limit` and `offset` now carry Pydantic `ge`/`le`
  bounds (`limit ∈ [1, 200]`, `offset ≥ 0`) to match the GET endpoint and
  reject `limit=999999` / `offset=-1` at the validation layer.
- **KNOWN-02:** Added `backend/scripts/test_alembic_upgrade_clean_db.sh` that
  runs `alembic upgrade head` against a throwaway PostGIS container,
  exercising the full migration chain (0001 → 0022) on a clean DB rather
  than verifying via `down_revision` linkage alone.

### Hardening (Phase 1073 — Audit Remediation)

Closes 4 P2 findings surfaced by the Phase 1072 re-audits:

- **REMED-01:** `useReuploadCommit`, `useCreateVrt`, and the VRT-mutation
  hooks now call `queryClient.invalidateQueries({ queryKey: jobStatusByDataset(...) })`
  on success, so dataset-detail no longer shows stale ingest warnings until a
  forced refresh.
- **REMED-02:** Added `progress` / `current_step` / `rows_processed` to
  `JobStatusResponse` + `IngestJob` (migration `0022_ingest_jobs_progress_columns`).
  Vector and raster ingest workers write these fields at phase boundaries via
  a new "brief-session" pattern, so 10-minute raster ingests show progress in
  the UI instead of appearing dead.
- **REMED-03:** Extracted `_job_phase_session` async context manager into
  `tasks_common.py` with consistent rollback-on-exception semantics. Both
  vector (19 sites) and raster (12 sites) workers now consume the helper
  instead of duplicating the load+yield+commit/rollback pattern.
- **REMED-04:** Consolidated Titiler URL construction into a single
  `build_titiler_cog_url` helper in `backend/app/platform/storage/titiler_url.py`,
  consumed by the tiles router and STAC connector. Pinned defense-in-depth
  docstrings at `tiles/router.py` (internal-only proxy contract) and
  `stac_router.py` (`_fetch_cog_info` dual-gate: `validate_url_for_ssrf` +
  Titiler extension allowlist). Structural tests prevent re-inlining.

### Audit verification (Phase 1072)

- Fresh `/sec-audit` re-run: **PASS**, 0 findings. v1014's 16 HIGH/MEDIUM
  closures all verified in code; Phase 1071 KNOWN closures additionally
  verified.
- Fresh `/ingest-audit` re-run: **PASS**, 0 P0/P1, 9 P2 (8 v1015-carried
  deferred to v1017 hygiene, 1 reframed). Lifecycle map healthy end-to-end —
  every prior hazard has a verified guard at the correct waypoint.
- Triage at `.planning/audits/TRIAGE-2026-05-21.md` maps each open finding to
  its remediation phase.

### Migrations

- `0022_ingest_jobs_progress_columns` — adds `progress`, `current_step`,
  `rows_processed` to `catalog.ingest_jobs`. Reversible.

### Tags

- Local: `v1016`
- Public: `v1.5.1`

## [1.5.0] - 2026-05-20

### Ingest/Export lifecycle hardening (v1015 milestone)

Phases 1065-1070 — 13 requirements closing the 4 P0 + 5 P1 findings from
the 2026-05-19 `/ingest-audit`, the `router_reupload.py` IDOR that v1014
acknowledged but deferred, and v1014 hygiene tail.

### Security — Tier A ship-blocking (Phases 1065-1067)

- **IA-P0-01 (Phase 1065):** Wire the download-token mint flow. The
  `downloadCog()` frontend helper now mints a short-lived `typ='download'`
  JWT via `POST /api/auth/download-token/{dataset_id}` and opens the
  download URL with the minted token, instead of putting the session
  JWT in a URL query parameter (which 401'd against the strict
  `_resolve_download_user` check shipped in v1014 SEC-S04). Closes the
  in-production COG download failure. Playwright spec pins the
  two-request order; OpenAPI snapshot regenerated.
- **REUPLOAD-IDOR-01 (Phase 1065):** All 6 handlers in
  `router_reupload.py` now enforce `check_dataset_access` (write-mode +
  ownership) in addition to the existing `require_permission(
  "edit_metadata")` role gate. Non-owner editors get HTTP 404 from each
  handler. The pre-commit `visibility-filter-coverage` exclusion that
  shielded the file is deleted; future regressions fail at commit.
- **IA-P1-02 (Phase 1065):** `reupload_service_preview` now calls
  `_assert_compatible_record_type` at function entry — surfacing
  vector→raster or any→VRT swaps as HTTP 400 before pipeline execution.
  The helper gained a keyword-only `service_type` parameter to cover
  service-URL paths (which carry no filename).
- **IA-P0-02 (Phase 1066):** `/ingest/upload` now enforces
  `max_file_size_bytes` at the HTTP entry via a chunked size check in
  `save_upload_file`. Local-mode rejects with HTTP 413 (Content Too
  Large) once cumulative bytes exceed the cap, before the partial file
  is left on disk; S3-mode rejects before `storage.put`. Symmetric with
  the presigned path's request-time 422 check.
- **IA-P0-03 (Phase 1066):** `commit_import` re-runs
  `validate_url_for_ssrf` on `job.source_url` for service commits before
  `queue_ingest_job`, closing the preview→commit DNS-rebinding TOCTOU on
  the FIRST hop (default 60s job TTL window). `ingest_service` and
  `reupload_service` worker tasks also re-validate before fetch —
  defense-in-depth for the manifest path that bypasses `commit_import`.
- **IA-P0-04 (Phase 1067):** Resolved the
  `IngestJob.last_heartbeat_at` inconsistency by dropping the column
  (Alembic 0021) and switching `recover_stale_jobs` to use
  `started_at < now - JOB_TIMEOUT_SECONDS` (1 hour), matching the
  steady-state `fail_stale_jobs` sweep that already runs every 5
  minutes. The previous heartbeat-based logic was broken-by-design:
  the column was declared and queried but never written, so every
  running job looked heartbeat-less + 5-min-old after a deploy and got
  force-killed. **Result:** a 6-minute ingest now survives a rolling
  worker restart. Long-running ingests (>1h) still get force-failed by
  both startup recovery and the periodic sweeper.

### Security — Tier B follow-ups (Phases 1068-1069)

- **IA-P1-06 (Phase 1068):** `run_ogr2ogr_service` no longer passes the
  Authorization header via `GDAL_HTTP_HEADERS` env var (visible via
  `/proc/<pid>/environ` for the subprocess lifetime). Switched to
  `GDAL_HTTP_HEADER_FILE` pointing at a 0600 tempfile that holds the
  `Authorization: Bearer <token>` line. The env var is the file path,
  not the token; the file is unlinked in `finally` even on subprocess
  failure.
- **IA-P1-03 (Phase 1068):** Three-layer VRT hardening: (1)
  `validate_vrt_body` checks for `<VRTDataset` root + scans every
  `<SourceFilename>` for `..` segments and rejects absolute paths
  outside the GDAL VSI allowlist (7 prefixes); (2) `validate_file_content`
  routes `.vrt` through the body validator; (3) `gdalbuildvrt` subprocess
  inherits a safe env overlay (`CPL_VSIL_CURL_ALLOWED_EXTENSIONS=tif,
  tiff,vrt`, `VRT_VIRTUAL_OVERVIEWS=NO`, `GDAL_HTTP_FOLLOWLOCATION=NO`).
  Admin-only blast-radius today; defense-in-depth.
- **IA-P1-04 (Phase 1069):** `validate_where_clause` rejects statement
  terminators (`;`), comments (`--`, `/*`, `*/`), and unbalanced
  single-quotes via fast-path string-level checks, before the v1014
  SEC-S09 AST allowlist runs.
- **IA-P1-01 (Phase 1069):** `export_dataset_endpoint` gates on
  `require_permission("export")` instead of `get_current_active_user`,
  closing the asymmetry with `download_cog` (v1014 SEC-S04 capability
  matrix). An admin revoking the `export` capability from `viewer` now
  produces HTTP 403 from vector export, matching COG download semantics.

### Hygiene (Phase 1070)

- **HYG-01:** Created 5 pending-todo files for v1014 deferred INFO
  findings (Phase 1062 IN-01/02/03, Phase 1063 IN-01/02).
- **HYG-02:** Verified — all 6 v1014 REQUIREMENTS.md boxes
  (SEC-S12/S13/FU-05/FU-06/FU-07/CTRL-01) were already ticked at v1014
  archive time. No retroactive edit needed.
- **HYG-03:** Closed 2 cheap v1014 INFO todos inline:
  `_revalidate_redirect` now handles HTTP 305 (RFC 7231 Use Proxy);
  `run_ogr2ogr` docstring documents why `GDAL_HTTP_FOLLOWLOCATION` is
  intentionally absent (local-file path; service-URL sibling sets it).
  Both todo files moved from `pending/` to `resolved/`.

### Testing

- 59 new unit tests across 7 files: download token (5), reupload IDOR
  (7), record-type guard (11), upload size limit (5), commit-time SSRF
  revalidation (4), worker heartbeat decision incl. rolling-deploy
  regression (12), subprocess env Authorization (4), VRT body validation
  + subprocess env (14), where-clause injection rejection + export
  capability gate (9). 134/134 pure-unit tests pass in the modified
  areas (no regressions).
- 1 Playwright spec (`e2e/download-cog-token.spec.ts`) pins the COG
  download mint→open two-request order.

### Migrations

- `0021_drop_ingest_job_last_heartbeat_at` (reversible).

### Compatibility

No breaking changes. `save_upload_file` gains an optional `max_size_bytes`
keyword-only parameter; legacy callers continue to work without size
enforcement when None is passed.

## [1.4.0] - 2026-05-20

### Security audit remediation (v1014 milestone)

Phases 1061-1063 — 17 security requirements across HIGH / MEDIUM / LOW
severity tiers, surfaced by the internal 2026-05-19 security audit.
Closes SEC-S01..S16, SEC-FU-01..10, and SEC-GUARD-01.

### Security — HIGH (Phase 1061)

- **SEC-S01:** STAC catalog visibility filter — anonymous users no longer
  retrieve private raster records via `/api/stac/*` endpoints. The
  `apply_visibility_filter` predicate now gates the STAC item, search,
  and asset routes so unauthenticated callers see only public records.
- **SEC-S02:** Dataset metadata mutation IDOR closed — 3 handlers
  (`PUT /datasets/{id}/metadata/`, `PUT /datasets/{id}/record/`,
  `PATCH /datasets/{id}/`) are now gated by `check_dataset_access`,
  preventing owners of other datasets from mutating records they do not own.
- **SEC-S03:** Column DDL IDOR closed — 4 handlers (add / rename / retype /
  drop column) now call `check_dataset_access` before any DDL, closing the
  path where an authenticated user could alter another owner's table schema.
- **SEC-S04:** SSRF redirect-bypass closed — `make_safe_client()` factory
  wraps every outbound HTTP call in a per-hop revalidation hook; private IP
  ranges are blocked at each redirect step, not just the initial host.
  `GDAL_HTTP_FOLLOWLOCATION=NO` applied to all ogr2ogr service-ingest calls.
- **SEC-S05:** pgvector related-datasets IDOR closed — `GET /datasets/{id}/related/`
  now checks dataset visibility before returning embedding-similarity neighbours,
  preventing leakage of private dataset identities through vector proximity.
- **SEC-S06:** Demo deployment cannot start with committed credentials —
  `.env.demo` renamed to `.env.demo.example` (removed from repository);
  `scripts/init-demo-env.sh` generates a fresh secret file on first run,
  blocking `docker compose up` from starting when the example file is used
  verbatim. `validate_demo_credentials_guard` extended with a third literal.
- **SEC-S07:** MinIO fail-closed defaults — `docker-compose.yml` now uses
  `${VAR:?required}` bash-style expansion for MinIO credentials so compose
  fails fast instead of silently booting with empty passwords.
- **SEC-GUARD-01:** `AGENTS.md` updated with a visibility-filter coverage
  rule documenting the contract for future endpoint contributors; pre-commit
  grep hooks added to catch missing `apply_visibility_filter` calls on new
  STAC / catalog routes before they land in main.

### Security — MEDIUM (Phase 1062)

- **SEC-S08:** Dynamic `frame-ancestors` CSP on embed iframes — the shared-map
  endpoint now emits `Content-Security-Policy: frame-ancestors 'self' <origins>`
  derived from the active `EmbedToken.allowed_origins`. `SecurityHeadersMiddleware`
  skips `X-Frame-Options: DENY` when the route already sets a CSP with
  `frame-ancestors`; nginx `/m/*` location inherits the header without
  duplicating the global `X-Frame-Options`.
- **SEC-S09:** `ogr2ogr -where` clause uses sqlglot AST allowlist validator —
  `validate_where_ast()` wraps the fragment as `SELECT 1 FROM _t WHERE <input>`
  and applies a deny-by-default node allowlist (Column / Literal / comparisons /
  logical / IN / IS / LIKE / BETWEEN / Paren / Neg). Called before the
  identifier check in `validate_where_clause()` for defense-in-depth. 41
  pytest tests cover valid fragments, injections, and edge cases.
- **SEC-S10:** Basemap `api_key` public-exposure — `get_basemaps` docstring
  documents the public API-key resolution model so callers understand that
  keys embedded in basemap tile URLs are intentionally public-facing CDN keys.
  Rate limit added to `/settings/basemaps/` (120 req/min per IP, configurable).
- **SEC-S11:** Per-route rate limits on `/search/datasets/` and
  `/datasets/{id}/related/` — 30 req/min per IP (configurable via
  `SEMANTIC_SEARCH_RATE_LIMIT` PersistentConfig key) caps OpenAI embedding
  cost from anonymous amplification. `/search/facets/` is NOT rate-limited
  (pure SQL aggregation, no embedding call — per WR-02 review fix).
- **SEC-S12:** `simple-regconfig` GIN index for non-English FTS — migration
  `0020_records_simple_search_vector_idx` adds
  `ix_records_simple_search_vector` on a `simple` tsvector so catalog
  searches against non-English content use the index instead of a seqscan.
  The expression uses an IMMUTABLE `catalog.immutable_text_array_join` wrapper
  around `array_to_string` (required for functional index creation).
- **SEC-S13:** `max_length=1000` on `/search/facets/?q=` — matches the peer
  `/search/datasets/?q=` cap, preventing oversized embedding payloads on the
  facets path.
- **SEC-S14:** ESLint `no-restricted-syntax` rule banning
  `localStorage.setItem('*token*|*jwt*|*auth*', ...)` in frontend TS/TSX
  source. Per-file exemption applied to `auth-store.test.ts`. httpOnly-cookie
  migration ADR documented in `security-lessons.md` with trigger conditions,
  effort estimate, and tradeoffs.
- **SEC-S15:** JWT `jti` + `token_version` revocation primitives —
  `create_access_token` now embeds `jti` (UUID) and `token_version` (from the
  user row). `get_current_user` / `get_optional_user` reject JWTs whose
  `token_version` is stale; `revoke_all_tokens` atomically bumps
  `token_version` on logout and password change, invalidating all outstanding
  access tokens for that user.
- **SEC-S16:** Password complexity validator — `password_policy.py` enforces a
  minimum of 12 characters + 3-of-4 class diversity (uppercase, lowercase,
  digit, special). Wired to all 4 entry points (register, change-password,
  admin create-user, admin reset-password). Configurable via
  `PASSWORD_MIN_LENGTH` and `PASSWORD_REQUIRE_CLASSES` env vars.

### Security — LOW (Phase 1063)

- **SEC-FU-01:** STAC 5xx-mutation pytest fixture — `stac_visibility_force_5xx`
  patches both the authorization module AND the STAC router namespace bindings,
  ensuring the 500-response test fires on the correct code path and cannot be
  silently bypassed by import aliasing.
- **SEC-FU-02:** `validate_demo_credentials_guard` literal refusal — explicit
  pytest regression pin (`test_sec_fu_02_jwt_demo_literal_refused`) confirms
  the guard refuses the literal `"demo-jwt-secret-32chars-padding!!"` JWT
  secret value regardless of deployment context.
- **SEC-FU-03:** `react/no-danger` ESLint rule enabled at `error` level in
  `eslint.config.js`, preventing `dangerouslySetInnerHTML` in TSX. Regression
  fixture confirms the rule fires; `--no-inline-config` lock prevents bypass
  via inline comments.
- **SEC-FU-04:** GDAL Authorization header pinned to base64url charset —
  `_sanitize_authorization_token` helper in `ogr.py` validates the token
  against a `_BASE64URL_CHARSET` frozenset before composing
  `GDAL_HTTP_HEADERS`. CRLF characters, Unicode, and whitespace raise
  `ValueError` with `SEC-FU-04` prefix; 6 pytest tests cover valid and
  invalid inputs.
- **SEC-FU-05:** STAC `intersects` `max_length=10000` — GeoJSON geometry query
  param on `GET /stac/search` is now bounded; POST body is bounded by the
  existing 500 MB `RequestBodyLimitMiddleware`.
- **SEC-FU-06:** `parse_bbox` `isfinite` NaN/Inf guard — `math.isfinite()`
  loop applied after `float()` conversion in `parse_bbox` before the 6-to-4
  envelope reduction; catches Z-axis NaN from malformed coordinate strings.
- **SEC-FU-07:** ILIKE wildcard escape across maps/audit service modules —
  `%` and `_` characters in free-text search inputs are now escaped via
  `str.replace` before ILIKE pattern composition in `service_crud.py`
  `list_maps()` and audit service query helpers, preventing wildcard injection.
- **SEC-FU-08:** Owner-facing column-DDL audit feed endpoint —
  `GET /audit/datasets/{id}/column-ddl/` returns the DDL audit log for a
  dataset gated by `check_dataset_access`, enabling dataset owners to review
  schema-change history without admin privileges.
- **SEC-FU-09:** `nginx.conf` `server_tokens off` — suppresses the nginx
  version string from the `Server:` response header and error pages.
- **SEC-FU-10:** `.env.example` `DATABASE_URL_OVERRIDE` documents the
  least-privilege role pattern — inline SQL recipe for creating a
  `geolens_app` Postgres role restricted to the `geolens` database with
  `NOLOGIN`-by-default pattern documented alongside the override variable.

### Fixed (post-v1013 smoke, 2026-05-20)

Three findings from the post-archive live MCP smoke
(`.planning/quick/260520-smoke-v1013/SMOKE-v1013-REPORT.md`) — all fixed
inline, no v1013.1 release tag needed.

- **SMOKE-v1013-F1 (P0): GPKG-03 fan-out parent-job polling no longer 500s.**
  `JobStatusResponse.status` Pydantic Literal was missing `'fanned_out'`, the
  terminal status set on the parent IngestJob after `POST /ingest/commit-fan-out`
  dispatches N child tasks. Every `GET /api/jobs/{parent_id}` poll raised
  `ValidationError` → HTTP 500, leaving the UI stuck on
  "Loading job status..." indefinitely (children completed correctly in
  background). Fix extends the Literal to include `'fanned_out'` at
  `backend/app/platform/jobs/schemas.py:62`. Frontend (`use-ingest.ts` /
  `BulkTrackingList.tsx` / `status-colors.ts`) now treats `fanned_out` as
  terminal — refetchInterval stops, the parent moves out of the active-jobs
  list, and the badge renders in the success palette. Closes the
  user-perceived "Loading..." loop visible on `Ingest all N layers` flows.
  Regression pinned by
  `tests/test_jobs_router.py::test_get_job_status_fanned_out_returns_200`.
- **SMOKE-v1013-F2 (P2): OGC API preview now resolves URI-form CRS to EPSG.**
  Phase 1057 wired `parse_crs_uri` into commit-time SRID extraction but the
  preview path still returned `crs: null` for OGC API collections (ogrinfo
  on a GeoJSON feature response carries no coordinateSystem; CRS84 is
  assumed). The collection metadata DOES expose URI-form CRS via
  `crs: ["http://www.opengis.net/def/crs/OGC/1.3/CRS84"]`. Preview now
  falls back to fetching `/collections/{layer_name}?f=json` and parsing
  `storageCrs` then `crs[0]` through `parse_crs_uri` when ogrinfo returns
  no srid AND `service_type == "OGC API Features"`. User-facing impact:
  the preview pane now displays "EPSG:4326" instead of "CRS: Unknown +
  CRS Override field". Regression pinned by
  `tests/test_services_endpoints.py::test_preview_ogcapi_uri_form_crs_fallback`.
- **SMOKE-v1013-F3 (P2): Map delete clears per-map React Query cache.**
  `useDeleteMap` previously only invalidated `queryKeys.maps.all`, leaving
  stale `maps.detail(id)`, `maps.shareToken(id)`, `maps.embedTokens(id)`,
  and `map-history` entries. Any subsequent re-mount of those queries
  (recent-maps strip, a pinned tab to the deleted map, admin panel) would
  refetch from deleted-map endpoints — yielding `404` noise and the
  `/api/maps/shared/{deleted_id}` errors observed in the smoke run.
  `removeQueries` now drops those caches entirely on delete. Regression
  pinned by `frontend/src/hooks/__tests__/use-maps.test.tsx`.

### Internal

- 60+ commits across Phases 1061-1063
- 200+ new pytest cases pinning the security regression surfaces
- `e2e/sec-audit.spec.ts` — 18-test Playwright regression suite (env-var-gated)
  covering S01/S04/S05/S08/S09/S11/S12/S13 at the HTTP layer
- 21 review fixes applied inline (6 BLOCKER + 13 WARNING + 2 INFO) across the
  3 implementation phases

## [1.3.0] - 2026-05-20

### Ingest hardening + multi-layer GPKG + basemap sublayer styling (v1013 milestone)

Phases 1057-1060 — closes 10 v1013 requirements surfacing from the v1012
live-smoke addendum. Mixes a P0 GeoServer commit-failure fix (WFS-04),
P1 latency win on the OGC API probe path (PROBE-05), P0 silent-data-swap
fix on Reupload (GPKG-01), and the v1011.1-deferred Path B FIX for
basemap sublayer styling persistence (BSE-01). Next public tag bump:
**minor** — new affordances (Reupload layer-select, Bulk Review fan-out,
basemap sublayer editor restoration) justify the bump even with a P0
fix at the head of the milestone.

#### Added

- **GPKG-01 (P0): Reupload File path layer-select step.** When
  reuploading a multi-layer GeoPackage, the dialog now shows a
  `selecting-file-layer` step mirroring the Service URL flow at
  `ReuploadDialog.tsx:581`. Default selection is the dataset's previous
  `source_layer`; if the previously-ingested layer is absent from the
  new file, a warning banner forces explicit user selection. Closes a
  silent-data-swap risk where multi-layer GPKG reuploads silently
  picked `layers[0]`.
- **GPKG-02 (P1): Reupload preview pane parity with Service URL.**
  Preview now surfaces `Layer: {name}` line + column-level schema diff
  (`Columns Added` / `Columns Removed` with types) + schema-change
  advisory banner when columns differ. Derived from existing
  `compute_schema_diff` payload — no new backend wire field.
- **GPKG-03 (P2): Bulk Review "Ingest all layers" fan-out.** A single
  click on a multi-layer GPKG entry now creates N independent datasets
  via a new `POST /ingest/commit-fan-out/{job_id}` endpoint that clones
  the IngestJob per layer and dispatches independent Procrastinate
  tasks. Original job marked `'fanned_out'` (terminal); partial
  failures preserve the original job in `'pending'` state for retry.
- **BSE-01 (Feature): Basemap sublayer styling editor restored** with
  real persistence path. The `BasemapSublayerEditorScene` STROKE +
  CASING + ZOOM RANGE controls (removed in v1011.1 EMRG-FN-01 Path A)
  are back, now backed by `MapBasemapConfig.sublayer_overrides` jsonb-
  additive field (no Alembic migration). New shared
  `applySublayerOverrides(map, overrides)` helper applies overrides
  across builder + viewer + shared/embed render contexts. Idle-retry
  recovery handles MapLibre `!isStyleLoaded()` race. Backward-compat:
  legacy saved maps without `sublayer_overrides` render with default
  basemap styling (zero-migration).
- **CLASS-07 (P2): Backend-classified `kind: 'vector' \| 'raster'`
  field on probe response.** Layers without `geometry_type` now
  default to `'vector'` unless an explicit raster signal is present
  (STAC adapter, `coverage_format`, `bands`, or `mediaType: image/*`).
  Frontend `ServiceUrlForm.tsx` consumes `layer.kind` directly instead
  of re-deriving from string contents.
- **CRS-06 (P2): URI/URN-form CRS auto-detection.** OGC API Features
  sources declaring CRS via URI/URN are now parsed automatically:
  `http(s)://www.opengis.net/def/crs/OGC/1.3/CRS84` → 4326,
  `http(s)://www.opengis.net/def/crs/EPSG/0/{N}` → {N},
  `urn:ogc:def:crs:EPSG::{N}` → {N},
  `urn:ogc:def:crs:OGC:1.3:CRS84` → 4326. Frontend CRS Override field
  auto-hides when probe carries non-null CRS. Unrecognized URIs fall
  through to today's behavior (Override stays visible).

#### Fixed

- **WFS-04 (P0): WFS commit succeeds on abstract OGC geometry types.**
  Polygon-heavy GeoServer WFS layers declaring `MultiSurface`,
  `MultiCurve`, `CompoundSurface`, etc. now ingest end-to-end. The fix
  has TWO layers — both shipped in this milestone, second one caught by
  the live MCP re-verify gate G-01 at close-gate time:
  - **Layer 1 (Phase 1057):** Root cause was `run_ogr2ogr_service`
    honoring the WFS-declared abstract type as the PostGIS column
    constraint via `-nlt PROMOTE_TO_MULTI`, then the post-ingest
    `clip_to_mercator_bounds` UPDATE failed because actual feature
    geometries are concrete (MultiPolygon, LineString). Fixed by
    replacing the `-nlt` flag with `-nlt GEOMETRY` for the service
    path, yielding a constraint-free `geometry(Geometry, 4326)` column.
    File-ingest path (`run_ogr2ogr`) is untouched.
  - **Layer 2 (Phase 1060 close-gate):** With the column constraint
    relaxed, ingest proceeded further but `extract_metadata()` still
    returned the raw `GeometryType(geom)` (e.g. `MULTISURFACE`) which
    failed the `chk_datasets_geometry_type` CHECK constraint (only 7
    concrete OGC simple-features types allowed). New
    `_normalize_geometry_type()` helper in `metadata.py` maps abstract
    GML 3 types → closest concrete equivalent (`MULTISURFACE` →
    `MULTIPOLYGON`, `MULTICURVE` → `MULTILINESTRING`, etc.). 9 new
    regression tests pin the mapping. Verified live against
    `ahocevar.com/geoserver/wfs` Countries of the World — 241 features,
    `geometry_type=MULTIPOLYGON`, `srid=4326`.
- **PROBE-05 (P1): Service URL probe completes ≤5s** for fast services.
  Root cause was misdiagnosed in the original report (claimed
  `try_all_probes()` short-circuit issue, but the orchestrator already
  short-circuits per-probe). Real bottleneck was per-layer `ogrinfo`
  enrichment in `enrich_ogcapi_layers` and `enrich_wfs_layers`:
  Semaphore(5) × 17 collections × ~3-4s per call ≈ 60s wall clock.
  Fix: drop enrichment from the probe phase entirely; lazy-enrich
  when the user picks a layer at preview time. ArcGIS HTTP enrichment
  preserved (different shape, not the bottleneck).
- **GPKG-03 fan-out 3-bug close (close-gate):** the
  `POST /ingest/commit-fan-out/` endpoint had three latent issues
  surfaced by live MCP re-verify gate G-07:
  - **Migration branching collision:** `0017_ingest_job_fanned_out_status`
    collided with `0017_map_basemap_config` (both claimed revision
    `0017_*` with the same `down_revision`). Applied migration was
    `0017_map_basemap_config`; the fan-out status migration never ran
    so `'fanned_out'` was rejected by the `chk_ingest_jobs_status`
    CHECK constraint. Renumbered to `0018_ingest_job_fanned_out_status`
    chained off `0017_map_basemap_config`.
  - **Defer-before-commit race:** `service.create_fan_out_jobs()`
    called `session.flush()` then `defer_async()` while the actual
    `session.commit()` was deferred to the end of the fan-out loop in
    `router.commit_fan_out`. Procrastinate uses a separate DB connection
    so the worker would pick up the task before our session committed,
    log "Ingest job not found, skipping", and the job stayed `pending`
    forever. Now commits per-layer inside `create_fan_out_jobs` (orphan
    risk on defer failure still handled by `defer_with_orphan_guard`).
  - **File-cleanup race:** `ingest_file` task unlinked the staging file
    in its `finally` block on `final_status == "complete"`. Multiple
    fan-out siblings share one staging file, so the second sibling
    failed with FileNotFoundError when the first one cleaned up. Now
    checks `fan_out_parent_id` in `user_metadata` and skips unlink for
    fan-out children. Orphan-file cleanup is a v1014 followup
    (`TECH-DEBT-GPKG-03-ORPHAN-CLEANUP`); staging dir retention policy
    handles eventual cleanup.
- **BSE-01 sublayer overrides apply on initial load (close-gate fix
  for G-09/G-10).** The `applySublayerOverrides` helper had an
  idle-retry recovery for the fresh-mount race, but the BuilderMap +
  ViewerMap callers wrapped the call inside an `if (!isStyleLoaded())
  return` gate. When saved `basemap_config` arrived from the API
  before the basemap style finished loading, the call was dropped —
  and because `basemapConfig` didn't change reference on subsequent
  re-renders, the effect never re-fired to retry. Saved overrides
  stayed invisible until the user manually re-picked a swatch. Fix:
  call `applySublayerOverrides` BEFORE the `isStyleLoaded()` guard;
  the helper's internal idle-retry handles the race. Verified live
  across builder, shared, and embed contexts.
- **Layer duplicate now persists snake_case style_config builder
  keys (close-gate fix for e2e regression).** The frontend's
  `normalize-style-config.ts` rewrites storage-canonical snake_case
  keys (e.g. `outline_color`) to camelCase (e.g. `outlineColor`) on
  layer load — the React-state contract. When a layer was duplicated,
  React state passed camelCase back through the POST body and the new
  layer was persisted with camelCase while the original kept
  snake_case. New backend helper `canonicalize_builder_style_config()`
  in `schemas.py` rewrites incoming camelCase builder keys to
  snake_case in both `MapLayerInput` and `MapLayerPatch` validators
  before storage. Idempotent: snake_case input passes through
  unchanged. Restores byte-equal style_config across duplicates.
- **E2E test contract drift (close-gate fix).** Phase 1052 dropped
  `role="listbox"`/`role="option"` from `StackRow` due to
  nested-interactive a11y issues but the e2e tests kept asserting
  `aria-selected="true"`. Updated `e2e/builder-v1-5.spec.ts` Test 3 +
  Test 4 (6 assertions) to use `data-selected="true"` (the post-Phase
  1052 contract). Headless smoke now 25/0/1.

#### Notes

- **Architecture hygiene swept inline.** Phase 1060 close gate caught
  one Phase 1057 import-layering regression (moved `crs_uri.py` from
  `app.modules.catalog.sources` to `app.core` so processing/ may
  import it without crossing the catalog boundary), one Phase 1058
  broad-except sites that needed rationale comments, and one Phase
  1047-era pre-existing layering violation in `maps/router.py`
  (re-exported `remove_layers_bulk` through the service facade). All
  fixed inline per `feedback_review_findings_inline.md`.
- **maps/router.py decomposition queued for v1014.** The file is now
  1761 LOC against a 1700-line cap; close gate carve-out raises the
  cap to 1800 with an explicit HARD ceiling — decomposition (split
  into facade + sub-routers per Phase 226/238 pattern) is the v1014
  follow-up.

## [1.2.1] - 2026-05-19

### New-user hardening + Reupload discoverability (v1012 milestone close)

Follow-up to v1.2.0's three Critical M001-7n8vpc audit fixes. Closes the
remaining 17 still-open audit findings + 6 enhancements across 4 phases
(1053-1056), plus surfaces the already-shipped Reupload affordance that
the audit's DOM-snapshot path failed to discover. Tag is patch (not
minor) because Phase 1055 turned out to be defect-fix + UX polish, not
net-new feature work — the Reupload backend (`router_reupload.py` 613
LOC, `tasks_reupload.py`, 30+ pytest cases, full ReuploadDialog) was
already in production.

#### Added

- **EW-05: STAC import wizard "Confirm" step.** Wizard now reads
  `assets.{key}.file:size` from selected STAC items, aggregates the
  total, and shows "You're about to download N items totaling X MB"
  before committing. Falls back to "(Size unavailable)" when the
  manifest lacks size. 14 i18n keys × 4 locales. Commit `4e484cae`.
- **ROUTE-01: `/admin/saml` "Enterprise Feature" placeholder.**
  Previously silently redirected to `/admin/overview`; now renders an
  inline notice with a docs link in community edition. URL stays at
  `/admin/saml`. 5 i18n keys × 4 locales. Commit `1629ee05`.
- **ROUTE-03: `/register` shows a banner for already-authenticated
  users.** `toast.info('Already signed in — redirected to home')` fires
  before `navigate('/')`. Commit `51009641`.
- **IMPORT-04 / Plan 1055-02: Visible "More" label on dataset-detail
  overflow trigger.** Header overflow button now renders a visible
  "More" text label next to the kebab icon (desktop). Overflow menu
  items carry HTML `title` tooltips. Closes the M001 audit's "missing
  reupload affordance" finding (actually a discoverability gap, not a
  missing feature). New `IMPORT-04: M001 audit replay` e2e regression
  test. 4 i18n keys × 4 locales. Commits `f4b7242a` + `d944407b`.
- **IMPORT-05: Register Table empty-state success framing.** When all
  available tables are already registered, the tab shows "All tables
  are registered" instead of absence-framed "no tables found".
  Differentiates via cheap `useDatasetCountHint` probe. 4 i18n keys
  × 4 locales. Commit `47fc184b`.

#### Fixed

- **CONSOLE-01: Anonymous `/login` no longer fires admin-only 401s.**
  `useAIAvailability` tightened to `enabled: !!token && isAdmin`
  (mirrors v1010.2 SF-06 pattern). Closes 3 of the 12 errors the audit
  recorded; remaining auth-store rehydration probes are by-design per
  the audit's own recommendation. Commit `0b0c3564`.
- **ROUTE-02: 404 page now sets a proper `<title>`.** `NotFoundPage`
  wires `useDocumentTitle`; tab now reads "Page not found - GeoLens".
  Commit `322dd181`.
- **ROUTE-04: `/m/{invalid-share-token}` no longer throws a JS-layer
  error.** New `expected404?: boolean` option on `apiFetch` returns
  null on 404 instead of throwing. "Map not found" UI renders cleanly.
  (Browser-built-in network-tab "Failed to load resource: 404" log
  remains — browser behavior, audit-acceptable for Low severity.)
  Commit `ce7f5742`.
- **IMPORT-02: Choose File button no longer intercepted by decorative
  dashed-ring span.** Added `pointer-events-none` + `aria-hidden` to
  the absolute-positioned border ornament on `FileDropzone.tsx`.
  Commit `20b65164`.
- **IMPORT-03: Upload File commit no longer triggers React 19
  `setState during render` warning.** Three `setPhase()` calls hoisted
  out of `setEntries()` updaters into a single `useEffect`. Commit
  `ad6b94ec`.
- **IMPORT-04 / Plan 1055-01: Reupload rejects cross-record-type
  swaps.** Backend `_assert_compatible_record_type` guard at both
  `reupload_dataset` and `request_presigned_reupload` returns HTTP 400
  when uploading `.tif` against a vector dataset. Prevents downstream
  invariant breaks. 3 new pinned pytest cases. Commit `aa852239`.
- **SEED-02: `seed-ago-data.py` survives ogr2ogr timeouts.** New
  `OGR2OGR_TIMEOUT_SECONDS` env var (default 300) + `--timeout` flag +
  retry-with-doubled-timeout on first failure. Commits `14b45d16` +
  `8ce7ed76`.
- **SEED-03: Upstream AGO data-quality noise summarized.** Skip-counter
  aggregated into run summary instead of verbatim line-by-line dump.
- **SEED-04: `ogr2ogr` failure output strips the driver list.**
  `_strip_ogr_driver_list()` helper drops the "supported drivers" block
  from error output; users see only actionable errors. Commit
  `14b45d16`.

#### Docs (cross-repo `~/Code/getgeolens.com`)

- **DOC-01 + EW-01: Quickstart documents the API-seeder path.** New
  "## 4. Seed sample data" section with both seeder invocations. Demo
  overlay demoted to "Alternative: bundled bake-time demo". Commit
  `d50b9ec`.
- **DOC-02 + DOC-03 + DOC-05: API-key creation + Python/httpx prereqs
  + interactive credential prompt.** New "Create your first API key"
  subsection (5-step recipe). Python 3.10+ + httpx added to prereqs.
  `install.sh` prompt + `GEOLENS_ADMIN_*` env-var alternatives
  documented. Commit `30e9361`.
- **DOC-04 + BU-03: "1-2 minutes" qualified + Apple Silicon platform
  warning documented.** Replaced with "1-2 min cached / 3-4 min cold
  build" anchored to install.sh "GeoLens is ready." output. Aside
  after `docker compose ps` declares Apple Silicon `linux/amd64`
  warning expected/harmless. Commit `d467a74`.

#### Internal

- **EW-04: `.env.example` expanded `DATABASE_SSL_MODE` block** from 3
  → 11 lines with per-deployment-target table (`prefer` for local
  docker-compose, `disable` for local system postgres, `require` /
  `verify-full` for managed Postgres) + inline BU-01 root-cause
  callout. Defense-in-depth against BU-01 regression. Commit
  `14e0b8c5`.
- **UX-01: API Keys discoverability closed as zero-code.** Cross-repo
  quickstart commit `30e9361` (DOC-02) signposts the 5-step recipe
  adjacent to `seed-ago-data.py` usage. Commit `9b1b386b`.

## [1.2.0] - 2026-05-19

### New-user install — three Critical reliability fixes (M001-7n8vpc dry-run audit)

A full new-user dry-run audit (`.planning/M001-7n8vpc-dry-run-audit.md`)
surfaced three independent Critical blockers preventing a literal first
install following the public quickstart. All three are fixed in this
release.

#### Fixed

- **BU-01: Compose SSL default no longer kills `migrate` on a fresh
  install.** `docker-compose.yml`'s `x-db-ssl-env` anchor fell back to
  `""` instead of the documented `"prefer"` when `DATABASE_SSL_MODE`
  was unset. Pydantic Settings treated the empty string as an explicit
  override, skipped the field default, and landed in the strict-SSL
  branch — which the bundled postgres image (no SSL configured)
  rejected. The migrate one-shot died with
  `ConnectionError: PostgreSQL server at "db:5432" rejected SSL upgrade`,
  and api / worker / frontend cascaded into `Created` state and never
  started. One-char fix: `${DATABASE_SSL_MODE:-prefer}`. Existing
  deployments that set `DATABASE_SSL_MODE` explicitly (e.g. `disable`
  for local dev, `require` for cloud Postgres) are unaffected. Commit
  `7b168bde`.
- **BU-02: `scripts/install.sh` now waits for stack health and surfaces
  failed services with logs.** Previously install.sh printed
  `"GeoLens is starting."` and exited 0 immediately after `docker
  compose up -d` returned, with no awareness of post-up failures. The
  worst kind of false success signal: clean shell prompt on a dead
  stack. New `wait_for_healthy` polls up to 90s (18 × 5s); if the
  migrate one-shot exits non-zero, the last 30 log lines are surfaced
  and install.sh exits non-zero immediately. On all-healthy, prints
  `"GeoLens is ready."` and the documented UI/API URLs as before.
  Healthy-stack path is unchanged in behavior. Commit `b4ad03d9`.
- **SEED-01: `scripts/seed-natural-earth.py` `--username/--password`
  bootstrap now works.** `bootstrap_api_key()` and
  `cleanup_bootstrap_key()` POSTed to `/api/auth/login/` (trailing
  slash) — but the route is registered without it. The proxy
  307-redirected to the internal Docker hostname
  `http://api:8000/auth/login`, and httpx (which follows redirects by
  default) tried to resolve `api` on the host and died with
  `httpx.ConnectError: [Errno 8] nodename nor servname provided`. The
  documented `--username admin --password admin` happy path was
  unusable; only the explicit `--api-key` flag worked. Other endpoints
  the seeder touches (`/api/auth/api-keys/`, `/api/datasets/`,
  `/api/ingest/*`, etc.) use the trailing-slash form that matches
  their registered routes, so only the two login calls needed the fix.
  Commit `787f4e43`.

### Map Builder — tabbed LayerEditorPanel + composite map export

#### Added

- **Composite map export (PNG) with title, description, legend, and
  edition mark.** `handleExportPNG` now composites map chrome around
  the WebGL canvas capture on an offscreen 2D canvas — title
  (28px bold) + description (14px muted) + legend (one swatch per
  visible `show_in_legend !== false` layer) + `"Powered by GeoLens"`
  mark on community edition. All metrics expressed in srcCanvas pixel
  space (dpr-scaled) so text stays crisp on retina. New i18n keys
  `export.legendHeader` + `export.poweredBy` across en/de/es/fr.
  Commit `8370e19e`.

#### Changed

- **`LayerEditorPanel` switched from section-based body to a
  4-tab tablist** (Style / Filter / Labels / Popup), matching the v3
  design. Style tab embeds Render-as pills plus LayerStyleEditor (or
  RasterLayerControls). Tab pips surface a filter-count badge and
  labels/popup on-dots. Destructive render-mode switches now go through
  an inline alertdialog. Drop the dead `enableLegacyTabs` prop and the
  panel-footer Delete affordance (Delete already lives in StackRow
  kebab). `StackRow` gains a read-only Source info block at the top of
  the (···) kebab (Dataset / Features / Type / Geometry / Columns
  count). Point `symbol` capability label renamed `Symbol → Labels` to
  match the new tab vocabulary; i18n updated in all four locales with
  new keys for `layerEditor.tabsLabel`, `layerEditor.confirmRenderAs.*`,
  `layerEditor.source.*`. Tests rewritten from section-based to
  tab-based assertions. Commit `b285f305`.

#### Fixed

- **Pointer drag across all draggable rows** (`BasemapGroupRow`,
  `FolderGroupRow`, `StackRow`) was silently broken because
  `onPointerDown={stopPropagation}` declared AFTER
  `{...dragHandleProps.listeners}` overrode dnd-kit's PointerSensor
  activator (JSX last-wins). Only the KeyboardSensor still worked,
  which hid the regression from anyone using ArrowUp/ArrowDown. Fix:
  drop the pointerdown override on the grip. Sibling `onClick`
  stopPropagation alone handles row-selection suppression. Also fixes
  the rename-input focus race that lost to Radix `restoreFocus` in
  real browsers — gate `restoreFocus` deterministically via
  `onCloseAutoFocus` controlled by a `skipCloseAutoFocusRef` flag.
  Commit `c2b65176`.
- **Empty-state inline-search Enter** now reliably opens the Add Data
  modal. Two converging bugs: handler read `inlineQuery` from a stale
  React state closure (replaced with `e.currentTarget.value`); and the
  Enter keyup synthesized a click on the lazy Dialog's only focusable
  element (the close X button while the panel was still suspending),
  closing the dialog ~500ms after opening. `preventDefault` on the
  keydown suppresses the synthesized activation. Commit `0ab1b512`.
- **Layer rows no longer claim `role="listbox"` / `role="option"`** —
  the pattern produced axe `aria-required-children` and
  `nested-interactive` violations (rows had `role="option"
  tabindex="0"` while also containing focusable buttons: drag handle,
  eye, kebab, expand toggle). Rows aren't selection-widget options;
  they're rich cards with multiple controls each, so the WAI-ARIA
  listbox/option contract doesn't fit and is dropped. Selection now
  conveyed via `data-selected` + `aria-current="true"`. `tabIndex={0}`
  and Enter/Space keyboard activation preserved. E2E queries updated
  to `[aria-label="Map layers"]` / `[id^="stack-row-"]`. Commit
  `fdefd7f0`.
- **Three pre-existing builder-unified-stack e2e failures fixed**
  (drag-reorder filtering out basemap-group from drag candidates;
  settings panel awaits the lazy chunk; empty-state accepts either
  "Suggested datasets" or "Browse catalog" depending on
  `SUGGESTED_DATASETS` config). Commit `b06c204e`.

### Vector tiles — data-driven styling at all zooms (?cols= opt-in)

#### Fixed

- **Phase 269 H-23's `_DEFAULT_NO_ATTR_BELOW_ZOOM=10` no longer breaks
  categorical/graduated paint at low zooms.** Tiles can now opt in to
  attribute columns at any zoom via `?cols=<comma-separated>` query
  param (auth-unsigned, allowlisted). Frontend's
  `getDataDrivenColumnsForSource` appends the right cols per layer in
  both `BuilderMap` and `ViewerMap`, including the `/m/<token>` and
  `?embed=1&token=...` shared/embed surfaces. Cache key includes the
  cols set so cached tiles don't leak attribute data across requests.
  6 backend integration tests + 22 frontend unit tests (heatmap-shape
  + extraCols edge cases). Commits `c8c9d08f` + `911061d1` +
  `46d11f7b` + `414c7ff7`.

### Dependencies

- Bump `brace-expansion` 5.0.5 → 5.0.6 to clear moderate DoS advisory
  GHSA-jxxr-4gwj-5jf2 (CVE-2026-45149). Transitive dev dep via
  `typescript-eslint -> minimatch@10`. The older 1.1.13 copy on the
  `eslint-plugin-jsx-a11y -> minimatch@3` path is outside the
  advisory's vulnerable range. Commit `409c0e93`.

### Map Builder polish & bug sweep (v1011 — closes Phase 1051)

Closed all 11 user-reported Map Builder polish/bug items in a single hygiene
phase with 13 sequential plans (11 user-reported + INV-01 disposition + EMRG-01
triage + CTRL-01 close gate). Mirrors the v1009.1 / v1010.1 / v1010.2 hygiene
shape per `feedback_hygiene_milestone_pattern.md`. Playwright MCP re-verify of
each item is orchestrator-scoped per the v1010.1 lesson and runs against the
live `localhost:8080` stack as the tag gate.

#### Fixed

- **BUG-01: Layer visibility eye toggle now dispatches to MapLibre.** Root cause
  was non-sync re-add paths (`swapLayerOnMap`, raster re-add in
  `handleStyleConfigChange`) skipping `syncVisibility`, plus an adapter contract
  gap where fill/line/circle/heatmap `addLayers` ignored `input.visible`. Fixed
  at both levels: adapters now honor `input.visible` directly, and every
  non-sync caller explicitly invokes `syncVisibility` after `addLayers`. 5 new
  vitest regression cases. Commits `ea56ae78` + `8c6de637`.
- **BUG-02: Delete-layer now removes the layer from the sidebar and the map
  render**, with optimistic state update + rollback on error (mirrors the
  `handleBulkDelete` pattern). Pre-fix: user clicked delete and the sidebar row
  stayed visible until full page reload because the React-Query invalidation
  refetch was gated by the `!hasUnsavedChanges` resync useEffect. 5 new vitest
  regression cases. Commit `eeeb8be8`.
- **BUG-03: Rename-group input now autofocuses on open** (DropdownMenu
  `restoreFocus` race fixed via rAF-deferred focus + removal of the kebab
  `onSelect` `_e.preventDefault()` that kept the menu open during the input
  mount). Defense in depth — a regression on either lever alone won't
  re-introduce the bug. 7 new vitest regression cases. Commit `80bddc14`.
- **RESP-01: Collapsed right sidebar no longer overlaps the MapLibre
  NavigationControl** at 800–1099px viewports. `NavigationControl` repositioned
  from `position="top-right"` to `position="top-left"` in `BuilderMap.tsx` —
  pure-positioning fix (no conditional dispatch) since the colliding sibling
  (BuilderRail) is rendered at all viewports ≥800px. Commit `391459bb`.
- **RESP-02: Coordinate readout pill no longer overlaps the top-right widget
  zone** at narrow viewports. RESP-01's NavigationControl move freed the
  top-right zone in `BuilderMap` context, but the `MapCoordReadout` pill's
  56px `right-14` offset is **load-bearing in ViewerMap context** (which keeps
  NavigationControl top-right). Resolution-by-upstream-wave: docstring
  contract codified at the shared component to prevent a future "clean up dead
  clearance" refactor from breaking the viewer. Commit `c6ab4fbd`.
- **RESP-03: Right-sidebar Sheet overlays render exactly one close button at
  <800px viewport.** Both `<SheetContent>` instances in `MapBuilderPage.tsx`
  (editor flyout + mobile-rail flyout) gain `showCloseButton={false}` so the
  wrapped inner panels' canonical close affordances (LayerEditorPanel's X +
  BuilderRail's ChevronRight) become the single source of truth. Includes a
  NEGATIVE-CONTROL bug-shape regression pin against shadcn Sheet default-
  behavior drift. 8 new vitest regression cases. Commit `0a72cb58`.

#### Changed

- **UX-01: Layer-group expand caret meets 24×24 px touch target.** Caret button
  in `BasemapGroupRow` and `FolderGroupRow` swapped from `text-xs` Unicode `▸`
  to a `<ChevronRight h-4 w-4>` (Lucide) inside a `h-6 w-6 -mx-1` button. The
  `-mx-1` negative margin extends the visual hit-box 24px without altering the
  locked 16px grid-cell column. 4 new vitest regression cases. Commit
  `278e8933`.
- **UX-02: Basemap sublayer rows now show config-state indicator badges
  instead of a per-row opacity slider.** New `SublayerConfigIndicators`
  component renders 0–4 derived Lucide-icon badges (Labels / Filter /
  DataDriven / OpacityModified) based on live `MapLayerResponse` config. Pure
  derivation — no internal state. Opacity editing for basemap sublayers
  remains canonical via the `LayerEditorPanel` flyout. 16 new i18n entries
  (4 keys × en/de/es/fr). 8 + 32 regression cases in the new and updated
  test files. Commits `79b0c0c6` + `a69d00ac`.
- **UX-03: Basemap row is now draggable in the layer order with saved-map
  persistence.** `BasemapGroupRowWrapper` lifted from `useDroppable` to
  `useSortable`; new `MapBasemapConfig.basemap_position?: 'top' | 'bottom'`
  field (jsonb-additive, zero backend migration); `reorderBasemapAboveData`
  map-sync helper performs the inversion when position='top'. Legacy maps
  load with `undefined` and default to 'bottom'. 14 new vitest regression
  cases + 2 new i18n keys × 4 locales. Commit `0957cf6d`.
- **UX-04: Map Settings → Widgets section now uses state-specific
  Enable/Disable labels** ("Enable {{name}}" when off / "Disable {{name}}"
  when on) instead of the composite `{action} {name} widget` template —
  better screen-reader semantics + per-locale word-order grammar. Adds a
  descriptive note paragraph ("Controls whether each widget appears on the
  map."). Audit confirmed zero duplicate Widget-Availability toggles
  (SettingsEditorScene is the single source of truth). 12 new i18n entries
  (3 keys × 4 locales). 5 new vitest regression cases. Commit `57d88d01`.

#### Removed

- **INV-01: DETAIL LEVEL toggle removed from BasemapSublayerEditorScene.**
  Disposition was REMOVE (not FIX). Investigation confirmed dead wiring since
  v1008 — `MapBuilderPage.tsx` passed hardcoded `activeDetailLevel="default"` +
  `isCustomized={false}` + `onDetailLevelChange={() => { /* Phase 1038 TODO */ }}`,
  with no consumer ever mutating MapLibre style. FIX requires 3–5 days of
  MapLibre style-mutation work across basemap presets — out of v1011 scope.
  REMOVE pattern includes an inline disposition comment + a removed-feature
  regression pin. 6 i18n keys × 4 locales = 24 entries cleaned up; locale
  parity preserved. Sibling Phase 1038 TODO no-op callbacks
  (`onStrokeColorChange`/`onStrokeWidthChange`/`onCasingColorChange`/
  `onCasingWidthChange`/`onZoomChange`) deliberately NOT touched per plan
  directive; flagged for EMRG-FN-01 follow-up todo. Commit `6078b82a`.

#### Internal

- **EMRG-01: 4 emergent findings triaged, all P2/defer.** FINDINGS.md authored
  at `.planning/phases/1051-map-builder-polish-bug-sweep/FINDINGS.md` (108
  lines, v1009.1 reference shape). **EMRG-FN-01:** BasemapSublayerEditorScene
  5 sibling Phase 1038 no-op callbacks (tracking artifact: new pending todo at
  `.planning/todos/pending/2026-05-18-basemap-sublayer-phase-1038-dead-stubs.md`
  documenting REMOVE / FIX decision tree). **EMRG-FN-02:** `settings.toggleWidget`
  orphan i18n key × 4 locales (tracking via 1051-07-SUMMARY cross-reference).
  **EMRG-FN-03:** pre-existing UnifiedStackPanel.tsx unused-eslint-disable
  warnings from Phase 1041 (SCOPE BOUNDARY-correct deferral). **EMRG-FN-04:**
  `SublayerConfigIndicators` receives `layer=null` for basemap sublayers
  (dependent on EMRG-FN-01 resolution). Zero fix-now per plan directive —
  default-defer rule prevented scope expansion. Commit `60b0f536`.
- **CTRL-01 inline gate-fix:** disable `basemap-group` droppable for catalog
  non-basemap drags. Surfaced by `e2e/builder-v1-5.spec.ts:152`
  ("drag-from-catalog happy") regressing 25/26 → 26/26 against the v1010.2
  baseline. Root cause: Plan 06's `useSortable` lift on the basemap row made
  it a `closestCenter` collision target when shadcn Dialog's overlay backdrop
  intercepts `pointerWithin` over the sidebar. Fix uses the sortable
  `disabled: { droppable: ... }` option so basemap-group is invisible to
  collision detection during a non-basemap catalog drag while staying
  draggable. Per `feedback_review_findings_inline.md` — fixed inline at the
  close gate, not deferred to v1011.1. Commit `befe6a3b`.

#### Smoke gate evidence (Phase 1051 CTRL-01)

- **Frontend typecheck (`tsc --noEmit`):** 0 errors
- **Frontend vitest (full suite):** 1974 / 1974 passing (200 test files,
  13.09s). Above v1010.2 baseline (1909) by 65 cases from new regression
  pins across Plans 01/02/03/04/05/06/07/10/11.
- **`e2e:smoke:builder`:** 26 / 26 passing in 1.4 min — matches v1010.2
  baseline.
- **i18n parity (`test:i18n`):** 2 / 2 passing — locale parity preserved
  across en/de/es/fr after 16 + 2 + 12 + (−24) net key changes.
- **Stack restart for re-verify:** `docker compose restart api worker frontend`
  (less-destructive than `down -v && up -d --build` since pgdata volume
  contains user maps + datasets — no backend image rebuild needed because
  v1011 touched only frontend code). All 5/5 services healthy post-restart.
- **Playwright MCP re-verify:** orchestrator-scoped; runs against the live
  `http://localhost:8080` stack to confirm all 11 user-reported items +
  v1010.2 SF-04..08 surfaces clean. See FINDINGS.md § Orchestrator-Deferred
  MCP Backlog appendix table for the 11-row per-plan checklist.

### Builder hygiene carryover (v1011.1 — closes Phase 1052)

Closed all 4 EMRG-FN findings carried forward from v1011 Phase 1051 Plan 12
(EMRG-01 triage) in a single hygiene phase with 7 sequential plans. Mirrors
the v1009.1 / v1010.1 / v1010.2 / v1011 hygiene shape per
`feedback_hygiene_milestone_pattern.md`.

#### Removed

- **EMRG-FN-01: BasemapSublayerEditorScene STROKE section + zoom range
  inputs removed** (Path A REMOVE — mirror INV-01 precedent at v1011 commit
  `6078b82a`). The 5 sibling no-op `TODO(BUILDER-SUBLAYER-PERSIST)` callbacks
  (`onStrokeColorChange`, `onStrokeWidthChange`, `onCasingColorChange`,
  `onCasingWidthChange`, `onZoomChange`) were dead-wired since v1008. Path B
  (FIX — implement sublayer styling persistence with
  `MapBasemapConfig.sublayer_overrides[sublayerId]`) deferred as a 3-5 day
  feature phase. Live consumers preserved: opacity slider (`onOpacityChange`
  → `handleSublayerOpacityChange`) and Reset section (`onResetSublayer` →
  `setSublayerState` mutation). Test 14 added as REMOVE-disposition regression
  pin mirroring v1011 Plan 11's Test 13. Commits `3629ec04` (surface deletion)
  + `3e48d331` (orphan i18n keys) + `e8748d9b` (vitest cleanup + Test 14).
- **EMRG-FN-02: orphan `settings.toggleWidget` i18n key removed** from all 4
  locales (en/de/es/fr). The v1011 Phase 1051 Plan 07 UX-04 replaced the
  composite template with state-specific `enableWidget`/`disableWidget` keys;
  the old key was left behind in the locale JSON files. Commit `205e5a70`.

#### Changed

- **EMRG-FN-03: 2 unused `eslint-disable-next-line react-hooks/exhaustive-deps`
  directives removed** from `UnifiedStackPanel.tsx` (lines 735 + 776 at
  execution time; Phase 1041 SCOPE-BOUNDARY-correct deferral). Verified inert
  via `npx eslint --report-unused-disable-directives` before removal — both
  directives were flagged as unused (no rule would fire on the target dep
  arrays). No behavioral change. Commit `a299f5ee`.

#### Internal

- **EMRG-FN-04: SublayerConfigIndicators `layer={null}` branch closure**
  documented in `SublayerConfigIndicators.test.tsx`. The live caller is
  `UnifiedStackPanel.tsx:556` (basemap sublayer row); `BasemapSublayerInfo`
  only carries id/name/visible/opacity/kind, so per UI-SPEC §UX-02 footnote
  the indicator strip renders empty for basemap sublayers. Test 1 ("renders
  nothing when layer is null") is the canonical regression pin (shipped in
  v1011 Phase 1051 Plan 05 UX-02). The original CONTEXT.md claim that Plan 01
  Path A would auto-resolve EMRG-FN-04 was incorrect — the `layer={null}`
  callsite is in UnifiedStackPanel, not BasemapSublayerEditorScene. Closure is
  documentation-shaped (no production code change). Commit `06fbe98f`.
- **CTRL-01: close gate** — typecheck 0 errors; vitest 1979/1979 (201 test
  files); e2e:smoke:builder 26/26; i18n parity 2/2. Playwright MCP re-verify
  of basemap sublayer flyout (STROKE / Stroke color / Casing color / Minimum
  zoom / Maximum zoom absent; opacity slider + Reset section live; sublayer
  rows render cleanly) is orchestrator-scoped (Half B). Tag `v1011.1` (local).
  Commit `e1d3d093`.

### Builder smoke carryover (v1010.2 — closes Phase 1050)

Closed all 5 carried-forward smoke findings from v1010.1's 2026-05-17
Playwright MCP smoke (1 P1 + 4 P2). Map Builder now ships clean of all
2026-05-17 smoke noise. Single phase (1050), 6 sequential plans, 12 task
commits across 5 SF closures + 1 CTRL-01 close gate.

- **SF-04 / SMOKE-08 — Dedupe MapLibre vector tile sources**
  (commits `cab57a32` initial dedupe + `c1c84cc7` scope expansion):
  Non-cluster vector layers now share a MapLibre source per unique
  `dataset_table_name` via the new `getSourceIdForLayer(layer)` helper
  in `frontend/src/components/builder/map-sync.ts` (3-branch contract:
  cluster → per-layer; raster/DEM → per-layer; non-cluster vector with
  `dataset_table_name` → `source-data-${dataset_table_name}`). Predicted
  measurable impact on the v1010.1 8-layer / 2-dataset test map: initial-
  paint vector tile requests drop **from ~80 to ~16-24** per the SF-04
  evidence in `1049-SMOKE-FINDINGS.md` (live re-count pending Plan 06
  Playwright MCP re-verify). Cluster sources remain per-layer (cluster
  radius / minPoints are per-layer settings). `swapLayerOnMap` +
  `handleAiRemoveLayer` route through the helper; per-layer
  `removeSource` calls replaced by desired-set prune in
  `removeStaleSourcesAndLayers` (reference-count-safe by construction).
  4 hooks call sites in `use-layer-map-sync.ts` were swept under Rule 3
  scope expansion. 8 new dedupe tests + 2 handleAiRemoveLayer tests
  added; existing `map-sync.cluster.test.ts` and
  `map-sync.line-gradient.test.ts` rekeyed.

- **SF-05 / SMOKE-09 — Defer thumbnail blob revoke** (commit `4473d21e`):
  Post-login redirect to `/`: predicted **4 → 0** `blob:`
  `net::ERR_FILE_NOT_FOUND` console errors. `use-map-thumbnail.ts`
  mirrors the `use-quicklook.ts:67-74` cleanup pattern — `useEffect`
  cleanup keyed on the React Query `data` string fires
  `URL.revokeObjectURL(data)` on data change AND component unmount, not
  on cache eviction without `<img>` teardown. 3 new vitest cases (revoke
  on key change, revoke on unmount, no revoke when data undefined); 9
  total tests in the suite (up from 6).

- **SF-06 / SMOKE-10 — Gate anonymous pre-auth probes**
  (commits `912458e8` + `aca42c99`): Predicted **5 → 0** 401-error
  console entries on `/login` for `/api/auth/me/`,
  `/api/auth/me/permissions/`, `/api/admin/ai-status/`,
  `/api/search/saved/`, `/api/auth/refresh/`. `useSavedSearches` gated
  on `!!token` (`use-saved-searches.ts:13`); `useAIStatus` consumers
  (`AIStatusCard`, `SettingsAITab`) pass
  `{ enabled: !!token && isAdmin }` — admin probe never fires from
  anonymous OR non-admin authed pages. Hook signature
  (`use-admin.ts:186`) preserved per caller-controlled contract; the
  existing `use-ai-availability.ts:7` precedent was the analog.

- **SF-07 / SMOKE-11 — Single thumbnail PUT on mount** (commit
  `37fee435`): Hard-reload of `/maps/{id}`: predicted **2 → 1**
  `PUT /api/maps/{id}/thumbnail/` requests. Root cause was different
  than first guess: per-instance `thumbCaptured` ref doesn't survive
  Vite-dev StrictMode unmount/remount, and the module-level
  `pendingCaptures` Map was already cleared by the first capture's
  trailing-edge `setTimeout` — so the second hook instance fired a
  second PUT. Fix Option C: added module-scoped `autoCapturedMapIds:
  Set<string>` guard + `shouldAutoCapture(mapId)` helper that survives
  hook remount; `maybeAutoCaptureThumbnail` consults the new guard
  BEFORE invoking `captureThumbnail`. The v1009.1 SP-16 module-level
  debounce (`captureThumbnail`) was already correct; the fix was
  upstream of it at the auto-capture entry point. 3 new vitest cases
  including a StrictMode-style hook remount reproducer (asserts
  render-frame registration count `expected 2 to be 1` pre-fix → 1
  post-fix).

- **SF-08 / SMOKE-12 — Suppress false-positive basemap toast** (commit
  `9fe0b4ec`): Saving a clean-basemap map: 2 toasts → 1 toast
  (`'Basemap connection issue'` suppressed; `'Map saved'` preserved).
  `basemapLoadedAtRef: useRef<number | null>(null)` latch added in
  `BuilderMap.tsx` next to `errorHandlerRef` (line 91); reset at the
  start of the basemap style-fetch effect (line 149) so a basemap
  change re-arms first-load failure detection; set in the `.then()`
  success branch (line 161); consulted in the `errorHandlerRef` 5xx
  branch (line 409) to suppress the toast for transient post-load
  errors. Real first-load failures still surface
  (`setBasemapNotice('style')` path NOT gated). 3 new vitest cases in
  `BuilderMap.a11y.test.tsx` (loaded-then-error suppressed, never-
  loaded-then-error surfaces, basemap-change resets latch).

### Smoke gate evidence (Phase 1050 CTRL-01)

- **Frontend typecheck (`tsc --noEmit`):** 0 errors
- **Frontend vitest (full suite):** 1909 / 1909 passing (194 test files,
  12.71s). Matches v1010.1 baseline plus the new Plan 02/03/04/05 tests
  accommodated within the suite total.
- **Targeted vitest sweep (9 touched test surfaces):** 132 / 132
  passing in 1.40s.
- **`e2e:smoke:builder`:** 26 / 26 passing in 1.5 min — matches v1010.1
  baseline.
- **Playwright MCP re-verify:** orchestrator-scoped; runs against a
  fresh `docker compose down -v && up -d --build` stack to confirm all
  5 SF surfaces clean against v1010.1 SMOKE-FINDINGS "Observed"
  evidence + 3 v1010.1 inline fixes (SF-01 bulk-delete, SF-02 render-
  mode swap, SF-03 StyleJsonDialog lazy) show no regression.

---

> v1010 Builder Performance & Code Quality milestone — large-map performance
> wins (bulk-op batching, MapLibre paint coalescing, builder entry chunk
> reduction), code-quality refactor of the unified-stack Map Builder
> (LayerStyleEditor split, paint setter centralization), and three
> carried-forward builder follow-ups closed (popup_config error surface,
> Add Data modal audit, SourcesTab test backlog drained to zero).

### Added

- Backend `POST /api/maps/{id}/layers/bulk-delete` endpoint — batched
  multi-layer deletion in a single transactional request with full audit
  and history event coverage. Replaces N sequential `DELETE` calls in
  the builder's multi-select bulk-delete flow.
- `coalesceFrame(key, fn)` rAF-coalescing utility at
  `frontend/src/lib/builder/raf-coalesce.ts` — last-write-wins semantics
  per animation frame; routes opacity-slider and color-picker paint
  updates through a single MapLibre repaint per frame.
- `SceneSpinnerFallback` Suspense fallback for lazy-loaded editor scenes
  (DEMEditorScene, SettingsEditorScene, BasemapGroupEditorScene,
  BasemapSublayerEditorScene, DatasetSearchPanel).
- Bulk-op progress affordance: `BulkActionBar` shows `Loader2` spinner
  + `aria-live="polite"` announcement during the deleting state.
- 65+ new vitest cases across `raf-coalesce.test.ts`,
  `use-layer-map-sync.raf.test.ts`, the LayerStyleEditor sub-component
  suite, and the SourcesTab live tests (Phase 1048 FOLLOWUP-03). Vitest
  suite total: 1887 tests (was 1875 at Phase 1046 baseline).

### Changed

- Map Builder route entry chunk reduced **281.76 KB → 233.10 KB
  (−17.3% uncompressed, −13.9% gzip 64.35 KB → 55.38 KB)** via
  lazy-loaded editor scenes. Reduces JS parse/compile budget on
  `/maps/:id` cold open.
- `LayerStyleEditor` split **1231 LOC → 468 LOC orchestrator + 8
  per-render-mode child editors** (FillEditor, LineEditor, CircleEditor,
  SymbolEditor, HeatmapEditor, ClusterEditor, RasterEditor,
  RenderModeSwitch) + AdvancedJsonEditor + StrokeControls (−62%
  orchestrator LOC). RenderModeSwitch lookup-table replaces a 200+ LOC
  nested ternary (CODE-01/CD-19).
- Bulk-delete on N selected layers now sends **1 batched HTTP POST
  instead of N sequential DELETEs** (−98% request count at N=50). Wall-
  clock hover input latency measured live at p50=4.9ms, p95=7.1ms
  against a 50-layer stack (target ≤30ms — 6× margin).
- `BulkActionBar` selected-count label changed from `text-[13px]`
  arbitrary size to `text-xs` (12px) — aligns with declared type scale.
  Container adds `cursor-not-allowed` during the deleting state.
- `bulkActions.deletePartialFailure` toast copy appends a translated
  "— Tap to retry." suffix in all four locales (en/de/es/fr).
- `setLayerProperty` centralized in `layer-adapters/shared.ts` —
  replaces 5 scattered try-catch `setPaintProperty` patterns in
  `fill-adapter.ts` with a single dev-logging setter (CODE-01/CA-03).
- Cold Vite build time: **1.2–1.5s baseline → 364ms measured** (Phase
  1047 Plan 06 SHA) — no regression from lazy-load splits. Vitest wall-
  clock: **12.877s → 12.14s (−0.74s)**.

### Fixed

- Invalid layer `popup_config` no longer silently blocks the map save
  action — the save-blocker toast now names the offending layer
  (`"Cannot save: layer '{name}' has an invalid popup expression."`)
  instead of a generic message. Backend rejection of a malformed
  `popup_config` payload (HTTP 422) produces a distinct, translated
  error toast instead of falling through to the generic save-failed
  path. Vitest (4 cases) + Playwright cover both surfaces. (FOLLOWUP-01)
- 6 code-quality findings from `1046-BUILDER-CODE-AUDIT.md` remediated
  with regression tests: filter-sync extraction (CA-01), paint-setter
  centralization (CA-03), LayerStyleEditor split (CB-07), nested-ternary
  lookup-table (CD-19). 12 additional P1 findings explicitly deferred
  with written rationale in `1047-06-AUDIT-CLOSEOUT.md`. (CODE-02,
  CODE-03)

### Internal

- `.planning/phases/1046-builder-perf-and-code-audit/1046-BUILDER-CODE-AUDIT.md` —
  24 builder-surface findings (P0=3, P1=14, P2=7) classified across
  duplication, file-size, dead code, complexity, and test-coverage
  dimensions.
- `.planning/phases/1046-builder-perf-and-code-audit/1046-BUILDER-PERF-BASELINE.md` —
  Baseline metrics for all six PERF requirements (large-map FCP, input
  latency, bulk-op batching, paint repaint coalescing, route chunk
  sizes, smoke runtime).
- `.planning/phases/1048-followups-and-closeout/1048-ADDDATA-MODAL-AUDIT.md` —
  Add Data modal structural audit (BuilderDialogs.tsx + DatasetSearchPanel.tsx);
  13 findings (P0=0, P1=5, P2=8); v1008 unified-stack alignment
  confirmed clean (no legacy six-section assumptions). (FOLLOWUP-02)
- SourcesTab `it.todo` backlog drained to zero — 8 deferred tests
  shipped as live vitest cases; net `it.todo` count = 0. (FOLLOWUP-03)

## [1.1.1] - 2026-05-08

> v13.14 Smoke Stabilization milestone — bug fixes for 4 smoke-test
> regressions surfaced by a fresh local env reset + thematic-demo seed,
> plus a follow-up post-implementation audit that closed 7 cosmetic
> findings and one bug-class (typed `Capability` literal union for the
> frontend permissions hook). Brand assets shipped via the v0.1.0 sync
> are also rolled into this release.

### Added

- **Browser tab favicon** switched to the simplified favicon variant from
  `geolens-io/branding` v0.1.0 — no graticule, optimized for 16–64 px tab
  rendering per brand guide §3. Adds 16/32/64 PNG fallbacks for older
  browsers and `sizes="any"` on the SVG `<link>` for the Chromium
  favicon-pick path.
- **PWA manifest** at `/manifest.webmanifest` with `theme_color: #3b6fd4`
  (frozen sRGB approximation of `--primary-500`), `display: standalone`,
  and 192/512/1024 app-icon entries. Enables "Add to Home Screen" /
  install prompts on supported browsers. App icons (light + dark
  1024×1024 sources, 192/512 sips downscales) live under
  `frontend/public/`.
- **`apple-touch-icon.png`** (180×180) for legacy iOS Safari
  Add-to-Home-Screen.
- **`BRANDING-VERSION`** marker at repo root pinning the brand-asset
  sync to `geolens-io/branding` v0.1.0. See [README §Branding](./README.md#branding)
  for the bump procedure.
- `<meta name="theme-color">` on the HTML head matching the manifest
  `theme_color` so Android Chrome's address bar and the standalone PWA
  title bar stay visually consistent.

### Changed

- `<meta name="viewport">` and `<meta name="theme-color">` moved to
  immediately after `<meta charset>` in `index.html`, before the FOUC
  prevention script, per the WHATWG "important meta" recommendation.

### Fixed

- **`POST /api/maps/{id}/layers/` and `PATCH /api/maps/{id}/layers/`** no
  longer return a 307 redirect that leaked the in-container
  `http://api:8000/...` hostname through Vite's dev proxy, which broke
  programmatic clients (Node `fetch`, `openapi-python-client`-generated
  SDKs) and 17 of 18 builder smoke tests. Both routes are now declared
  on both slash variants directly via a dual-decorator alias
  (`include_in_schema=False` on the trailing-slash form so OpenAPI
  canonicalizes on the no-slash sub-collection convention per
  `docs/api-style.md`). v13.14 Phase 280 (POST) + v13.14 followup
  (PATCH).
- **Admin Audit Logs page-guard** at `AdminAuditPage.tsx:29` was checking
  the capability key `view_audit`, which is not part of the canonical
  `ALL_CAPABILITIES` registry — admins were always redirected away from
  `/admin/audit` to `/admin/overview` before the heading rendered. The
  guard now checks `manage_settings`, the capability the backend already
  enforces on `/admin/audit-logs/*`. v13.14 Phase 281.
- **`e2e/collections.spec.ts:91`** smoke test searched for the dataset
  `Reefs`, which was present in the legacy Natural Earth fixture but not
  in the thematic-demo seed catalog — the test timed out waiting for an
  Add button against an empty search result and cascaded `:115`/`:130`
  skips. Search term updated to `Coastline`, which is registered in
  `scripts/demo/themes/theme1.py` and present in both seeders. v13.14
  Phase 281.
- **`e2e/dataset-detail.spec.ts:90`** `getByText('FEATURES')` was
  strict-mode-failing against the thematic-demo seed catalog because
  related-dataset card text like `"75 features"`, `"248 features"`
  substring-matched the locator. Now uses `getByText('Features',
  { exact: true })` to resolve uniquely to the `DatasetStatsBar` label
  (the underlying text node is `"Features"` — Tailwind's `uppercase`
  class is presentation-only and does not change Playwright's matched
  text). v13.14 Phase 282.
- **`e2e/builder.spec.ts:343` sidebar-resize flake** — the test asserted
  `localStorage` value equals `sidebar.offsetWidth` after drag, but
  `expect.poll(offsetWidth)` resolved at the first onMove step (mid-drag)
  while `localStorage` was only written at pointerup, so the two values
  diverged by ~20 px on every run. Replaced with `expect.poll` against
  the persisted `localStorage` value directly so the poll waits for the
  pointerup commit; reload assertion now compares `offsetWidth` to the
  persisted value. Latent flake hidden by Phase 280's POST 307 cascade
  for ~6 weeks; surfaced once the cascade cleared. v13.14 followup.

### Internal

- **Typed `Capability` literal union** for the frontend `usePermissions().can()`
  hook at `frontend/src/lib/capabilities.ts`, mirroring the backend's
  canonical `ALL_CAPABILITIES` list at `backend/app/core/permissions.py`.
  Closes the bug class that allowed Phase 281's `view_audit` typo to
  silently return `false` for everyone (including admins) — typos on
  unregistered keys now fail at TypeScript compile time. New CI guard at
  `backend/tests/test_capability_drift.py` reads both sources and asserts
  byte-for-byte alignment, so future drift fails fast. v13.14 post-impl
  audit P2.

## [1.1.0] - 2026-05-07

> Pre-public-release security & audit hardening sweep (v13.12) plus a
> 9-phase backlog sweep (v13.13) that closed 130 Medium+Low follow-up
> requirements across security, performance, API contracts, code quality,
> i18n, tests, and admin polish. The breaking changes below come from the
> v13.12 hardening pass; v13.13 is purely additive/internal.

### v13.13 highlights (additive, no breaking changes)

- **Frontend perf wins:** the 1052 KB MapLibre `map-vendor` chunk is now
  lazy-loaded only on map-rendering routes, removing it from initial
  payloads on Login/Dashboard/Settings. The `DatasetPage` route bundle
  shrank 217 KB → 34 KB raw (-84%) via lazy `ReuploadDialog`,
  `VrtCreateDialog`, and `DetailPanel`. The attribute table now
  virtualizes via `@tanstack/react-virtual` for datasets with 10k+ rows.
- **Backend perf wins:** in-memory LRU tile cache fallback when `REDIS_URL`
  is unset; `_bulk_fetch_dataset_metadata` parallelizes its independent
  blocks via `asyncio.gather`; ingest's 4 sequential post-COPY scans
  consolidated into a single CTE; AI chat schema cache partitioned on
  `(map_id, content_hash)`; `has_embeddings` cache partitioned on the
  active embedding model name; `tile_cache_hits/misses` Prometheus
  counters gain a `table_name` label.
- **Admin polish:** audit-log full-text search now uses the existing
  pg_trgm GIN trigram indexes via `lower(unaccent(...))` for fast typing;
  enterprise-only admin tabs are now driven by a server-side registry
  (`GET /admin/settings/enterprise-tabs/`) rather than a frontend
  hardcoded frozenset; `register_user` emits an audit event;
  `delete_user` FK SET NULL behavior is locked by a migration regression
  test; `ApiKey.name` declares `max_length=255`.
- **i18n completeness:** the entire builder `style.*` namespace
  (zoomExpression, symbol, raster, hillshade, uploadIcon — 138 strings)
  now has full es/fr/de translations.
- **Code quality:** `chat_service.py` (1013 LOC) decomposed into 5
  cohesive sub-modules behind a Phase-226-style facade with zero public
  API change. Architecture-guard test enforces a 1500-LOC cap on routers
  with an explicit allowlist for over-cap legacy routers. 113 broad
  `except Exception:` sites annotated with rationale comments + a
  regression-guard test forbids new unjustified ones. Cross-feature
  zustand stores (`drawing-store`, `map-widget-store`, `search-store`)
  relocated to `src/stores/` for consistent layout. Auth zustand persist
  declares `version: 1` + `migrate` for forward compatibility.
- **Test health:** backend `--cov-fail-under` raised 58.5 → 60 (actual
  77%); frontend coverage thresholds ratcheted across all four
  dimensions; 6 raw `page.waitForTimeout(...)` calls in E2E specs
  replaced with deterministic locator polling; 35 inline `pytest.skip`
  calls migrated to `@pytest.mark.skipif` decorator form for cleaner
  gather-time skipping.
- **CI hygiene:** non-blocking `license-check` job uploads a
  `license-report` artifact (30-day retention); MinIO image bumped from
  `RELEASE.2025-04-22` to `RELEASE.2025-09-07` and pinned by sha256
  digest.

### v13.12 hardening pass (Critical+High remediation)

### Changed (BREAKING)

- `PUT /maps/{id}/thumbnail/` request body changed from `text/plain` raw
  `data:image/...` string to `application/json` `{"data_uri": "..."}`.
  Required to enable Python SDK generation (the `text/plain` body shape was
  silently dropped by `openapi-python-client`). Custom callers must send
  `Content-Type: application/json` with `{"data_uri": "data:image/png;base64,..."}`.
  Internal SDKs (`pip install geolens`, `@geolens/sdk`) at 1.0.2+ already use
  the new shape.
- Lowered max `limit` query parameter from 1000 to 200 on OGC Features
  `/items`, STAC `/collections/{id}/items`, STAC `/search` (GET+POST), and
  `/datasets/{id}/features`. Use the new `after_gid` keyset cursor for paging
  through large result sets — see `### Added` below. Offset-based paging
  remains supported as a legacy path.

### Added — Map Builder API surface

The Map Builder feature shipped 10 new public routes between v1.0.0 and the
upcoming v1.1.0 tag. All routes are documented in `/api/docs` and exposed
through the auto-generated `geolens` (Python) and `@geolens/sdk`
(TypeScript) SDKs.

- `POST /maps/import` — Import a MapLibre style JSON document into a new
  GeoLens map. Accepts a typed `MapStyleImportRequest` body (Pydantic v2,
  `extra="allow"` for forward-compat MapLibre fields). Per-layer dataset
  access is enforced via the existing RBAC layer; inaccessible datasets
  return 403 with the offending dataset IDs in the detail.
- `GET /maps/{map_id}/style.json` — Export a saved GeoLens map as a
  complete MapLibre style JSON document, ready to round-trip through
  `POST /maps/import` or feed into any MapLibre client.
- `PATCH /maps/{map_id}/layers` — Apply incremental layer changes (added,
  updated, removed, reorder) without a full PUT replacement. Body is a
  `MapLayerDiffRequest` with `added`/`updated`/`removed`/`order` arrays
  plus a `fallback_full_replace` client hint. Avoids the lost-write
  problem of full PUT for concurrent builder edits.
- `GET /maps/{map_id}/history` — Return recent builder edit history for a
  map (paginated, owner/admin only). Each event records actor, target,
  action, summary, and a structured details bag for the History panel.
- `GET /maps/icons` — List reusable map icons (bundled defaults plus
  user-uploaded). Powers the symbol-layer icon picker.
- `POST /maps/icons` — Upload a reusable SVG or PNG icon for symbol
  layers. SVG uploads are validated through `defusedxml` and re-serialized
  to defeat attribute-encoding bypasses (SEC-09 / Phase 273).
- `GET /maps/icons/{icon_id}/asset` — Serve an uploaded or bundled icon
  asset by stable icon ID. SVG responses carry
  `Content-Security-Policy: default-src 'none'; sandbox` (SEC-01 /
  Phase 273) so an uploaded SVG cannot fetch other origins, run scripts,
  or read auth cookies even if validation is bypassed in the future.
- `GET /maps/sprites/geolens.json` — Serve the stable GeoLens sprite
  JSON index. Used by MapLibre to map sprite IDs to atlas coordinates.
- `GET /maps/sprites/geolens.png` — Serve the generated GeoLens sprite
  sheet. Cache-Control: `public, max-age=3600`.

(Continuation) `POST /ingest/manifest/apply` was first announced in
[1.0.1]; the route is now part of the auto-generated SDKs and accepts a
typed `ManifestApplyRequest` body. See [1.0.1] § "Manifest-driven catalog
automation" for the full feature description.

### Added

- New CLI auth flags: `scripts/seed-natural-earth.py` accepts
  `--username`/`--password` and mints a temporary API key for the run
  (cleaned up on exit). Replaces the pre-existing `--api-key` flow that
  required operators to mint a key out-of-band.
- `after_gid` keyset cursor on `/datasets/{id}/features` and OGC Features
  `/items` endpoints. The `rel=next` link emits a keyset URL when a page is
  full, providing constant-time pagination over large catalogs.
- Per-dataset `tile_columns` attribute allowlist (new
  `catalog.datasets.tile_columns` array column, Alembic revision `0012`).
  Defaults to no attribute columns at z<10 to bound MVT tile size for wide
  schemas.
- Public operator runbook stubs at `docs/saml.md`,
  `docs/edition-deactivation.md`, `docs/edition-reactivation.md` (full
  enterprise runbooks live in the private overlay; stubs link out).
- New Alembic revisions: `0008_refresh_tokens_expires_idx`,
  `0009_audit_logs_indexes`, `0010_trgm_search_indexes`,
  `0011_record_embeddings_hnsw_idx`, `0012_dataset_tile_columns`.
- Extended `@pytest.mark.perf` coverage to OGC Records, OGC Features, STAC
  landing/collections, and ingest-upload latency budgets (perf-marker count
  5 → 14).

### Changed

- Composite indexes on `audit_logs(created_at DESC, action, resource_type)`
  and `audit_logs(resource_id)` to keep admin filter+sort hot paths fast.
- pg_trgm GIN trigram indexes on `lower(unaccent(records.title))`,
  `records.summary`, `records.keywords`, and `maps.name` so ILIKE+unaccent
  search no longer seq-scans.
- HNSW vector index for `record_embeddings.embedding` is now created in
  Alembic migration `0011`. Previously it was lazy-created at first
  embedding-backfill run, which left fresh installs with no index.
- Index added on `refresh_tokens.expires_at` for cleanup DELETE.
- Tile pool now drops to the `geolens_reader` role on every connection
  checkout via a `SET ROLE` setup callback. Previously it ran as the
  privileged app user.
- TTL LRU cache (300s) for query embeddings keyed on
  `(query_text.lower(), model_name)` reduces redundant embedding API calls.
- Helm chart `secret.yaml` env name renamed `SECRET_KEY` → `JWT_SECRET_KEY`
  to match Pydantic Settings (previously broke deploys silently).
- Per-service memory caps in `docker-compose.yml` matching the documented
  2GB VPS budget.
- README adds §"Add Your First Dataset" with the manifest-driven
  `geolens init/validate/apply` flow + cross-link from Demo Mode to the
  `examples/manifests/first-catalog/` example. README §Demo lists Manhattan
  Skyline (was missing).
- CONTRIBUTING.md project tree synced to current `modules/` / `platform/` /
  `processing/` / `standards/` layout. Test commands updated to flat
  backend test directory (replaced stale `tests/unit` / `tests/api` paths).
- `StyleJsonDialog` and `ImportSummary` user-facing strings wrapped via
  `useTranslation('builder')`; new `builder.styleJson.*` block with i18next
  plural keys ships in en/es/fr/de.
- `alembic check` filter for known SAML overlay drift; new H-06/H-07/H-09
  indexes declared in SQLAlchemy models so drift-as-CI-gate is usable.
- CI `e2e-test` job rationale documented inline in
  `.github/workflows/ci.yml` and `.github/CONTRIBUTING.md` (cron-revival
  path noted). New `npm run e2e:smoke:audit` script wires up 5 previously
  unreferenced E2E specs.
- Co-located smoke tests added for `AdminUsersPage`, `AdminAuditPage`, and
  `AdminSettingsPage`.

### Removed

- Duplicate `backend/Dockerfile` deleted. The canonical multi-stage root
  `Dockerfile` is the single source.

### Fixed

- README quickstart's `seed-natural-earth.py --api-key admin` example
  could not work as written — `admin` is a username, not an API key, and
  no API key was created at bootstrap. The seed script now supports
  `--username`/`--password` (mints + cleans up a temp API key) so the
  documented one-line invocation succeeds against a fresh `docker compose
  up` deployment.
- Tile MVT SQL gained `LIMIT 50000` per-tile feature cap and per-zoom
  geometry simplification extended through z<10. The existing perf marker
  only exercised z=0 single-row paths, masking regressions on real-world
  wide datasets.
- `/maps/{id}/layers/` (with trailing slash) and `/maps/icons/` (with
  trailing slash) previously returned a misleading 405/422 because they
  shadowed `/maps/{map_id}` parameter routes. The trailing-slash variants
  are removed; use `/maps/{id}/layers` and `/maps/icons` (no slash).
- Replaced unowned `geolens.io` domain references with `getgeolens.com` in
  `sdks/python/pyproject.toml` author email, `cli/pyproject.toml` author
  email, and `.env.demo` demo-sandbox host comments. PyPI metadata for
  already-shipped 1.0.x wheels is immutable; the next published version
  will carry the corrected author email.
- Corrected widget developer guide path: `frontend/docs/widgets.md`
  referenced `src/components/widgets/` but the directory is named
  `src/components/map-widgets/`.
- Manifest `local://` source URI parsing now rejects `..` traversal
  segments and validates the resolved path is under `upload_staging_dir`,
  closing a server-side file-read primitive that any user with `upload`
  permission could exploit.
- `e2e/dataset-detail.spec.ts` had two undocumented `test.skip()` calls
  masking editable-field/validation regressions on a top-3 user flow. One
  obsolete skip was deleted; one was re-skipped with a documented
  rationale and a follow-up todo for the next test-cleanup milestone.

### Security

- `.env.demo` boot guard now refuses production use unless
  `GEOLENS_DEMO_MODE=true` is set explicitly. Prevents accidental deploys
  with hardcoded demo credentials and the well-known JWT signing key.
- OAuth `redirect_uri` resolution now requires an explicit `PUBLIC_APP_URL`
  for OAuth flows. The previous fallback to the request `Origin`/`Host`
  header was vulnerable to host-header injection from non-browser clients.
- JWT secret length validator now rejects known-public example values (the
  `.env.example` default and similar). Operators booting with such a value
  must regenerate via `openssl rand -hex 32` — `.env.example` ships with an
  empty `JWT_SECRET_KEY=` to force the choice.
- OAuth email-match auto-link now requires `email_verified=True` from the
  IdP. Previously, accounts could be silently linked on any matching email,
  enabling account takeover via IdPs that allow unverified emails.
- Embed-token `Origin: http://localhost` bypass scoped to loopback TCP
  peer source. Previously honored from any caller, allowing trivial
  domain-locking bypass from non-browser callers.

## [1.0.2] - 2026-05-05

### Added

- GitHub-ready GeoLens organization avatar asset sized to GitHub profile image
  guidance.

### Changed

- Synchronized backend, frontend, CLI, and SDK package metadata for the
  sanitized public-release tag.
- Enterprise-only SAML and lifecycle operator runbooks now live with the private
  `geolens-enterprise` source; public docs keep short ownership stubs only.
- AWS Marketplace environment examples moved out of the public `.env.example`
  and into the enterprise overlay documentation.
- Public issue and discussion templates now use `v1.0.2` examples and generic
  cloud image wording instead of pre-public version or AWS Marketplace labels.

## [1.0.1] - 2026-05-04

### Added

- Manifest-driven catalog automation: schema validation, CLI init/validate/apply commands, backend manifest apply endpoint, example manifests, and generated SDK surfaces.
- Root multi-stage Dockerfile targets for API, worker, and frontend containers.
- Focused CI gates for manifest CLI contracts, backend apply contracts, OpenAPI drift, SDK drift, and published-package verification.

### Changed

- Map and search services were decomposed behind stable facade modules with architecture guards to prevent direct imports of private split modules.
- Advanced sharing, permission, workflow, AI provider, and embedding provider extension contracts were tightened for the open-core boundary.
- Documentation now covers CLI manifest workflows, SDK manifest apply support, and CI verification commands.

### Fixed

- Public map raster tile URL resolution for VRT datasets.
- DEM terrain tiles no longer apply an incorrect rescale path for terrainrgb output.
- Builder styling test locators were hardened for the labels switch flow.

## [1.0.0] - 2026-05-03

### Added — Public package distribution (2026-05-03)

- **Python SDK published to PyPI as `geolens==1.0.0`.** Install with `pip install geolens`; the generated SDK exposes the hand-written `GeolensClient` auth wrapper plus the OpenAPI-generated endpoint clients.
- **CLI published to PyPI as `geolens-cli==1.0.0`.** Install with `pip install geolens-cli`; the executable command remains `geolens`.
- **TypeScript SDK published to npm as `@geolens/sdk==1.0.0`.** Install with `npm install @geolens/sdk`; the package exports `createGeolensClient`.
- **Prebuilt API and frontend images published to GHCR.** Pull `ghcr.io/geolens-io/geolens-api:1.0.0` and `ghcr.io/geolens-io/geolens-frontend:1.0.0`; the same images are also tagged `1.0`, `1`, and `latest`.
- **Clean-machine package verifier added.** `.github/workflows/verify-published.yml` installs `geolens`, `geolens-cli`, and `@geolens/sdk` inside fresh Docker containers and smoke-tests the runtime exports.

### Changed — Pre-public migration squash (2026-05-02)

- **Alembic migration chain squashed from 23 migrations to 2** (`0001_baseline` + `0002_procrastinate`). The pre-public chain `0001_fdn` → `0002_tbl` → `0003_prc` → ... → `t6u7v8w9x0y1` collapses into a single application-schema baseline plus the procrastinate queue infrastructure migration kept separate. Verified by round-tripping every migration against a throwaway database and diffing the resulting `pg_dump` schema-only output against the squashed-baseline output: all 37 tables / 39 indexes / 24 functions / 8 triggers / 3 sequences / 3 types match 1:1; remaining diff is column-ordering only (no functional impact).
- **Existing pre-1.0.0 dev databases** must run a one-shot `UPDATE catalog.alembic_version SET version_num = '0002_procrastinate'` to align with the new chain (alembic-stamp won't work because the prior revision IDs are no longer in the script directory). New clean installs run the 2-migration baseline directly. Per the existing changelog header, no migration path from any pre-1.0.0 version is supported by GeoLens 1.0.0+.

### Fixed — Model ↔ DB drift (2026-05-02)

Resolved 5 instances of model-vs-DB drift uncovered by the migration squash. The squashed baseline now produces the model-defined schema (clean installs) and the SQLAlchemy models accurately describe what's in the database:

- `AITokenUsage.input_tokens` / `output_tokens` — added `server_default="0"` to model (DB had it; model didn't).
- `Record.language` — added `server_default="en"` to model (DB had it; model didn't).
- `MapShareToken.token_hint` — removed `server_default="***"` from model (DB doesn't have it; the migration that created the column did not set a default).
- `MapShareToken.token_hash` — moved inline `unique=True` to a named `UniqueConstraint("token_hash", name="uq_map_share_tokens_token_hash")` in `__table_args__` so the constraint name matches the live DB.
- `Map.chk_maps_visibility` — the live DB's constraint had a stale `'unlisted'` value the model never knew about and no application code ever produced. Tightened the live DB constraint to the model's 3-value form (`'private', 'public', 'internal'`); no rows were affected.

Two further "drift" items are intentional open-core boundaries and are preserved as fixups in `0001_baseline.upgrade()`:

- `OAuthProvider.chk_oauth_providers_type` — the model declares the OSS+enterprise *union* (`'oidc', 'google', 'microsoft', 'saml'`); the OSS baseline narrows the constraint to OSS-only values; enterprise migration `e002_add_saml_columns` re-adds `'saml'` when the overlay is loaded.
- `OAuthProvider` SAML columns (`idp_entity_id`, `idp_sso_url`, `idp_certificate`, `sp_entity_id`) — the model declares them with `deferred=True` so the OSS overlay never selects them; the OSS baseline does not create them; enterprise migration `e002_add_saml_columns` adds them.

### Added — Open-core boundary cleanup (2026-04-30)

- **`AuditSink` Protocol** (Phase 222) — write-side hook for audit-event emission, sibling to the existing `AuditExtension` (read-side export-format gating). Defined in `backend/app/platform/extensions/protocols.py`; default implementation (`DefaultAuditSink`) writes one `audit_logs` row per emit. Enterprise overlays subscribe by appending to `_extensions["audit_sinks"]` via `setdefault + append`. New facade `audit_emit(session, event)` in `backend/app/modules/audit/service.py` wraps each sink in per-sink try/except + `structlog.exception()` so a failed sink never rolls back the surrounding business operation. Mechanically rewrote 65 `log_action(...)` call sites across 19 files to use the new facade. New `make audit-sink-discipline` Makefile target enforces the invariant that no application code calls `log_action()` directly.
- **`BillingExtension` Protocol** (Phase 223) — startup hook for billing-system registration. Defined in `backend/app/platform/extensions/protocols.py` with signature `async def on_startup(self, app: FastAPI) -> None`. Default implementation (`DefaultBillingExtension`) is a no-op. The FastAPI lifespan dispatches each registered extension under `asyncio.wait_for(timeout=10.0)` with per-extension try/except so a hung or buggy overlay cannot block startup or crash the application. The `geolens-enterprise` overlay's `MarketplaceBillingExtension` registers the AWS Marketplace `RegisterUsage` call via this seam.
- **`make billing-extraction-discipline`** Makefile target — architecture guard asserting `app.core.marketplace` is no longer importable from any `backend/app/` module.

### Changed — Open-core boundary cleanup (2026-04-30)

- **AWS Marketplace metering moved out of core** — `backend/app/core/marketplace.py` deleted (the 30-line `register_marketplace_usage` body relocated verbatim to `geolens-enterprise`'s `MarketplaceBillingExtension._register`). The lifespan startup block at `backend/app/api/main.py:184-203` is now a generic `for ext in get_billing_extensions(): ...` dispatch loop that fires zero AWS API calls in community deployments.
- **`AWS_MARKETPLACE_PRODUCT_CODE` and `AWS_MARKETPLACE_PUBLIC_KEY_VERSION` are now enterprise-overlay-only env vars.** Removed from `backend/app/core/config.py:Settings`. The enterprise overlay reads them directly via `os.environ.get(...)` and short-circuits when unset. Operators of the open-core community edition no longer have these settings on the core `Settings` surface.

### Removed — Open-core boundary cleanup (2026-04-30)

- **`backend/app/core/marketplace.py`** — file deleted. AWS Marketplace billing is now exclusively an enterprise-overlay concern.
- **`Settings.aws_marketplace_product_code` / `Settings.aws_marketplace_public_key_version`** — removed from core `Settings`.

### Migration notes — Open-core boundary cleanup

- **Community deployments:** no action required. The marketplace block at `api/main.py:184-203` was inert when `AWS_MARKETPLACE_PRODUCT_CODE` was unset (the default for all community deployments); replacing it with a no-op dispatch loop preserves that behavior byte-identically.
- **Enterprise deployments running the AWS Marketplace AMI:** install the `geolens-enterprise` overlay (already required for SAML/audit-export); the new `MarketplaceBillingExtension` registers automatically via the existing `geolens.extensions` entry-point group. Set `AWS_MARKETPLACE_PRODUCT_CODE` and (optionally) `AWS_MARKETPLACE_PUBLIC_KEY_VERSION` exactly as before — the env-var contract is unchanged. The overlay reads them directly; core no longer does.

### Added — Open-core separation (2026-04-29)

- **`geolens` CLI** (Apache-2.0) — standalone command installed from the `geolens-cli` Python package; supports `login` (OS keyring + `--no-keyring` headless fallback), `scan <dir>` (vector + raster file detection), `publish <file>` (SDK-driven 3-step ingest), `export stac <id>` (STAC API 1.0 raster metadata). Source at `cli/`; published to PyPI as `geolens-cli`.
- **Python + TypeScript SDKs** auto-generated from `backend/openapi.json` — `geolens` (Python via `openapi-python-client`) and `@geolens/sdk` (TypeScript via `@hey-api/openapi-ts`). Source at `sdks/python/` and `sdks/typescript/`; published to PyPI/npm via `.github/workflows/publish-sdks.yml`. Regenerate via `make sdks`; `make sdks-check` is a CI drift gate.
- **Extension hook for enterprise overlays** — `backend/app/core/identity.py` defines `IdentityProtocol`, `RoleProtocol`, and `IdentityExtension`; `backend/app/platform/extensions/__init__.py` exposes `get_identity_extension()` typed accessor. Overlays register via `importlib.metadata` entry_points. The companion `geolens-enterprise` package uses this seam to provide SAML SP-initiated SSO with assertion validation, JIT provisioning via `find_or_create_oauth_user()`, and audited attribute→role mapping.
- **`backend/openapi.json` snapshot committed** as the SDK source of truth — reproducible SDK regeneration from this artifact.
- **SDK and CLI documentation** — user-facing documentation for SDK + CLI surfaces including install, auth modes, exit codes, and known rough edges lives at docs.getgeolens.com.
- **SAML operator documentation** — install + per-IdP configuration walkthroughs, hardening posture, multi-instance limitations, and NameID format guidance for the optional `geolens-enterprise` SAML overlay.

### Changed — Open-core separation (2026-04-29)

- **Open-core boundary closed** — `backend/app/core/` no longer imports from `backend/app/modules/settings/`; `AppSetting` model relocated to `backend/app/core/db/models.py`. New architecture-guard test in `backend/tests/test_layering.py` prevents regression.
- **`backend/app/modules/auth/visibility.py` removed** — visibility/authorization logic moved to `backend/app/modules/catalog/authorization.py`. 23 inbound callers migrated; dataset-visibility semantics unchanged.
- **`IdentityProtocol` introduced** — 51 cross-domain `User` import sites retyped to depend on `Identity` (the Protocol alias) rather than the concrete `User` ORM model. Allowlist guard at `test_layering.py:237` keeps 18 SQL-attribute files on the concrete model. Enables enterprise overlays to register custom identity backends without modifying core.
- **OAuth IdP→role mapping is now enterprise-only** — `group_claim` and `group_role_mapping` are rejected by `OAuthProviderCreate`/`OAuthProviderUpdate` schemas with `ValueError("Group-based role mapping requires the GeoLens Enterprise overlay")` in community deployments; only applied at the service layer when `is_enterprise()` returns True. Pre-existing OAuth providers without group mapping are unaffected.

### Note on SAML availability

The "**SAML support has been removed**" entry below remains accurate for the **community edition** — the dead scaffold (XML metadata parser, broken `provider_type='saml'` accepted but non-functional, 4 unused `oauth_providers` columns) is gone from core. As of v13.1, working SAML is available via the optional `geolens-enterprise` overlay, which registers via the new auth-extension hook. The community edition is unchanged: no SAML controls in admin UI, `/admin/saml` returns 404, no `provider_type='saml'` accepted by API.

### Security

- **BREAKING: `JWT_SECRET_KEY` must now be at least 32 characters.** The backend validates the length at startup; shorter values fail fast with an actionable error. HS256 requires ≥ 256 bits of entropy — shorter secrets were brute-forceable. See the [upgrade guide](https://docs.getgeolens.com/guides/quickstart/upgrade/) for rotation instructions. The `.env.example` default passes unchanged; only deployments with custom short secrets are affected.
- Secret fields (`POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, `GEOLENS_ADMIN_PASSWORD`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `S3_SECRET_ACCESS_KEY`, `TILE_SIGNING_SECRET`) now use Pydantic `SecretStr` internally. Values are masked (`**********`) in `repr()`, structured-log dict coercion, and `ValidationError` output — they can no longer leak into exception traces or log lines by accident. Downstream behavior is unchanged; values are unwrapped via `.get_secret_value()` only at the library boundary (JWT encode/decode, HMAC tile signing, Fernet KDF, boto3, Anthropic/OpenAI clients).
- New `reveal()` helper in `app/config.py` centralizes `SecretStr | None → str | None` unwrapping for optional credential fields.

### Added
- Astro-based marketing site scaffold (phases 212-214)
- `seed_tiles` CLI script for pre-seeding Redis tile cache
- Public map viewer UX improvements and legend unification
- 3D data and maps support feasibility design doc
- `LOG_LEVEL` value validation at startup: typos like `LOG_LEVEL=verbose` now fail fast instead of crashing the stdlib logger at first call.
- `ENV_ONLY_CONFIG` and `GEOLENS_EDITION` documented in `.env.example` (previously undocumented but referenced in code and the admin UI lockdown banner).

### Removed
- **SAML support has been removed.** The OAuth provider system shipped with `provider_type='saml'` accepted by the API but no working SAML login flow ever existed (only an XML metadata parser). An admin could create a SAML provider and have it appear on the login page, but clicking it produced no authentication. The dead code path has been removed across the stack:
  - `provider_type='saml'` is no longer accepted by the OAuth API; the database CHECK constraint has been tightened to `('oidc', 'google', 'microsoft')`.
  - The `oauth_providers` table loses 4 columns: `idp_entity_id`, `idp_sso_url`, `idp_certificate`, `sp_entity_id`. Any pre-existing SAML provider rows are deleted by the migration before the constraint tightens.
  - The `chk_users_auth_provider` constraint on `users.auth_provider` is also tightened to `('local', 'oidc', 'oauth')`.
  - The `app/auth/saml/` Python module (XML metadata parser) is removed.
  - The admin UI no longer offers SAML in the OAuth provider dropdown; the metadata-XML upload field, SP Entity ID, and ACS URL display are removed.
  - SAML i18n keys are removed from all 4 locales (en, es, de, fr).

### Changed
- Landing page removed — root route (`/`) now serves the Search page directly. The previous `/search` route is no longer used; existing bookmarks redirect to `/`.
- `SHOW_LANDING_PAGE` environment variable removed from backend config and branding API.
- Internal documentation moved out of the public repository tree; user-facing docs live on docs.getgeolens.com.
- Connection pool pre-ping now defaults to `True` to detect broken connections in managed databases.
- Top-level `CONTRIBUTING.md` consolidated into `.github/CONTRIBUTING.md`.
- OAuth `client_id` and `client_secret` are now required fields when creating a provider (previously optional placeholders for the SAML branch).
- `backend/.env` symlink removed. `app/config.py` now resolves the project-root `.env` via `Path(__file__).resolve().parents[2] / ".env"` so host-side workflows (`cd backend && uv run pytest|uvicorn|alembic`) continue to work without the symlink.
- `VITE_API_PROXY_TARGET` renamed to `API_PROXY_TARGET` in `docker-compose.yml` (frontend service) and `frontend/vite.config.ts`. The old name still works for one release via a fallback in `vite.config.ts` — local compose overrides can migrate at leisure. The var is only consumed by the Node-side Vite dev-server proxy and was never exposed to the browser bundle, so the misleading `VITE_` prefix has been dropped.
- Settings `model_config` is now a typed `SettingsConfigDict` (Pydantic v2) so typos in config keys fail at mypy/runtime instead of being silently ignored.
- `.env.example` cleanup: deprecated `PUBLIC_BASE_URL=...` active default commented out; `API_PORT` and `FRONTEND_PORT` gained per-variable comments matching the rest of the file; `POSTGRES_HOST` / `POSTGRES_PORT` / `POSTGRES_DB_TEST` now carry a pointer to `.env.test.example` for host-side test runs.

### Fixed
- `app/main.py:193` S3 health-check error-branch typo: `settings.s3_endpoint_url` (which does not exist) corrected to `settings.s3_endpoint`. The bug was pre-existing; it would have crashed the app with `AttributeError` the first time the S3 startup health check actually failed, masking the real S3 error behind an unrelated traceback. Found and fixed during the env-audit post-implementation review.
- CI E2E workflow sed commands were silently no-op'ing: they targeted empty values (`^VAR=$`) that never existed in `.env.example`. The patterns were rewritten to match any value (`^VAR=.*`) so the E2E job actually injects the CI-distinct secrets it claims to set. CI `JWT_SECRET_KEY` values were also padded to ≥ 32 characters so the new length validator passes in CI. The 1879-test full backend suite continues to pass.
- Test infrastructure: removed brittle `os.environ.setdefault` / `del sys.modules["app.config"]` blocks from `test_cache.py`, `test_health.py`, `test_metrics.py`, `test_tile_cache.py`, and `test_config.py`. These were workarounds for a module-level import failure that no longer exists now that config.py resolves the project-root `.env` at import time. The old pattern also caused cross-test stale-settings pollution when `test_config.py` ran before `test_auth.py`.
- **Post-impl audit 2026-04-10 follow-ups:**
  - **S1 — source `geom`/`geometry` column collision (P1):** vector uploads with an attribute literally named `geom` or `geometry` no longer crash `ogr2ogr` at CREATE TABLE time. `run_ogr2ogr`/`run_ogr2ogr_service` now use `GEOMETRY_NAME=_geolens_geom` as a placeholder, which `ensure_geom_column` renames to `geom` after `rename_reserved_columns` has moved the source attribute to `src_geom`. Regression test lives in `tests/test_ingest_column_preservation.py::test_source_geom_attribute_renamed_to_src_geom`; the `reserved_names.geojson` fixture once again includes a source `geom` attribute.
  - **S2 — cross-module mypy cleanup (P1):** resolved 7 errors in `app/datasets/service.py` (including the UUID-vs-Dataset attr-defined errors in `get_related_datasets`), 2 in `app/storage/provider.py`, 2 in `app/public_urls.py`, 6 in `app/audit/service.py`, 3 in `app/maps/service.py`, 3 in `app/persistent_config.py`, and 1 in `app/services/preview.py`. `mypy` is now clean across `app/ingest/`, `app/datasets/service.py`, and the audited supporting modules.
  - **S3 — structured ingest warnings surfaced to the UI (P2):** `JobStatusResponse` now exposes `warnings`, `archive_failed`, and `temporal_parse_errors` alongside the existing `warning_message`. A new `IngestWarningsBanner` component renders reserved-name renames, Shapefile DBF collisions, archive failures, and temporal-parse failures in `JobProgress` on the upload success screen AND permanently on the dataset detail page. A new `GET /jobs/by-dataset/{dataset_id}` endpoint powers the persistent banner by looking up the most recent ingest job for a dataset with visibility filtering. Translations added for en/de/es/fr.
  - **Post-impl audit test coverage gaps closed:** added 31 new tests across the helpers introduced by the audit — `_resolve_effective_srid` (5 tests), `_detect_and_override_geometry` (5), `_archive_original_file` (3), `_bind_task_log_context` (3), `_parse_temporal_fields` (8), `create_vrt_job` (5), `GET /jobs/by-dataset/{id}` (6), and `JobStatusResponse` warning surfacing (6). Keeps every new helper regressible in isolation.
  - **Flaky test resolved:** `test_publish_blocked_when_hard_validation_fails` is no longer flaky. Two back-to-back full-suite runs (1848/1848 each) completed cleanly — the `_geolens_geom` collision fix, transaction/session hygiene changes, and the structlog contextvar clearing in `_bind_task_log_context` likely removed the fixture leakage.
  - **N1 — worker log correlation (P3, R-18/R-24):** each ingest task entry point (`ingest_file`, `ingest_service`, `reupload_file`, `reupload_service`, `ingest_raster`, `ingest_vrt`, `regenerate_vrt`) now binds `job_id` + task name to structlog contextvars so operators can correlate log lines from concurrent uploads without manual grep-stitching.
  - **N2 — validation-failure file retention (P3):** removed the inline `Path(file_path).unlink(missing_ok=True)` on validation failure in `ingest_file`. The `finally` block's retry-preserving cleanup is now authoritative so retryable validation failures keep the local upload around.
  - **N3 — quicklook failure phase (P3):** quicklook commit failures are now tagged with `phase="commit"` vs `phase="generate"` so operators can distinguish "PostGIS query died" from "session commit died" when reading logs.
  - **N4 — HTTPException re-raise ordering (P3):** documented the except clause ordering requirement in `router.upload_file` so future refactors don't silently rewrite 4xx → 500.
  - **N5 — temporal parse errors surfaced to UI (P3):** raster ingest now persists unparseable `temporal_start`/`temporal_end` values to `job.user_metadata.temporal_parse_errors`, which the new warnings banner displays so users know which values were dropped.
  - **K1 — `ingest_file` phase helpers (P3, partial):** extracted `_resolve_effective_srid`, `_detect_and_override_geometry`, and `_archive_original_file` helpers from the 260-line `ingest_file` task body.
  - **K3-PRE — VRT test mock warnings:** `test_vrt_source_management_174.py::TestRegenerateVrtTask` no longer emits `RuntimeWarning: coroutine 'AsyncMockMixin._execute_mock_call' was never awaited` — `mock_session.add` is now explicitly bound to a synchronous `MagicMock` to match real SQLAlchemy semantics.
  - **K5 — `create_vrt` validation moved to service layer (P3, KISS-10):** `create_vrt_job` lives in `app/ingest/service.py`; the router handler is now a 3-line wrapper.
  - **K7 — `_finalize_ingest` IngestContext refactor (P3, KISS-2):** the 11-parameter signature is now a dataclass. Both `ingest_file` and `ingest_service` construct a single `IngestContext` instead of repeating the call-site noise.
- **Post-impl audit 2026-04-10 (B) follow-ups** — a narrow-scope audit of the above remediation work itself surfaced 22 new findings. 5 were fixed in the original session; the remaining 14 landed as a follow-up pass. Fixes landed in this session:
  - **RESILIENCE-1 (P1):** `_archive_original_file` had an unguarded `session.commit()` inside its best-effort exception block. A transient DB error during archive-metadata persistence (deadlock, pooler drop) would propagate out of the helper and flip the already-successful ingest into a `failed` job via the outer task `except Exception`, triggering Procrastinate retries and potentially producing duplicate datasets. The metadata commit is now wrapped in its own try/except with rollback-on-failure, matching the quicklook commit pattern. Regression test: `test_archive_original_file_commit_failure_does_not_raise`.
  - **KISS-1/CLEANUP-1 (P2):** removed the dead `assumes_4326` parameter from `_resolve_effective_srid` that was being `del`'d immediately on entry.
  - **KISS-3/CLEANUP-3/TYPE-6 (P2):** deleted the unused `IngestJobUserMetadata` TypeScript interface that had zero references in the codebase (the named-key + `[key: string]: unknown` index signature also defeated type safety for the listed fields).
  - **RESILIENCE-3 (P3):** `IngestWarningsBanner` on `DatasetPage` now only renders when `datasetJob?.status === 'complete'`, matching the `JobProgress.tsx` gate. Prevents showing warnings from a failed re-import on the still-functional dataset page.
  - **RESILIENCE-4 (P3):** `_archive_original_file` warning log now includes `dataset_id` as a structured kwarg (previously only embedded in `archive_key`), and the error string is consistently truncated to 500 chars.
  - **TYPE-1/TYPE-2/TYPE-3 (P2 + P3):** closed the backend→frontend ingest-warning contract. `_append_job_warning` now accepts an `IngestJobWarning` TypedDict union (`app/ingest/warnings.py`) built via `make_reserved_rename_warning` / `make_dbf_truncation_warning` producers; `JobStatusResponse.warnings` is a Pydantic discriminated union (`ReservedRenameWarning | DbfTruncationCollisionWarning`) validated per-entry in `_job_to_status_response` — malformed or unknown-kind entries are logged and dropped rather than 500ing the endpoint. `JobStatusResponse.temporal_parse_errors` narrowed to `dict[Literal["temporal_start", "temporal_end"], str]`. New regression tests in `test_jobs_router.py` (unknown-kind drop, temporal-key narrowing) and `test_ingest_ogr_pure.py` (producer→Pydantic round-trip).
  - **RESILIENCE-2 (P2):** `create_vrt_job` now wraps `ingest_vrt.defer_async` in a try/except that marks the already-committed IngestJob `failed` before re-raising, so a Procrastinate outage returns a clean 503 instead of leaving a pending orphan that waits 60 minutes for stale-cleanup. Regression test: `test_defer_failure_marks_job_failed_and_raises_503`.
  - **PERF-1 (P3):** `_extract_common_layer_metadata` now populates `columns` from the target layer's `fields`, so shapefile ingest no longer has to spawn a second `run_ogrinfo_preview` subprocess just to get the column list for the DBF collision detector. The text-fallback path (GDAL < 3.7) still falls through to the preview helper.
  - **PERF-2 (P3):** `useDatasetJobStatus` upgraded from `staleTime: 5 min` to `staleTime: Infinity` + `gcTime: 30 min` since the underlying ingest metadata is immutable once the dataset exists. Stops refetch-on-mount and caches 404 ("no job") responses across navigations.
  - **PERF-3 (P3):** added `index=True` to `IngestJob.dataset_id` in the ORM to match the existing `ix_catalog_ingest_jobs_dataset_id` migration. Prevents Alembic autogenerate from re-adding the index and keeps tests that skip migrations honest about the index.
  - **PERF-4 (P3):** `query_audit_logs` switched from two sequential round trips (list + count) to `COUNT(*) OVER ()` on the main query, halving the endpoint's latency for the audit-log page. Empty-slice pagination still falls back to a count-only query so "page out of range" returns the correct total.
  - **CLEANUP-2 (P3):** inlined the redundant `x_column`/`y_column`/`geom_column` locals in `ingest_file` into the `user_wants_geom` boolean — they were re-derived inside `_detect_and_override_geometry` anyway.
  - **CLEANUP-4 (P3):** `reupload_file` now calls `_archive_original_file` via a new `log_message` + `commit=False` knob, removing the inlined duplicate archive block. The reupload path rides the existing `status=complete` commit so the archive-failed flag is durable without a second round trip.
  - **KISS-2 (P3):** `_detect_and_override_geometry` now returns `str | None` instead of `tuple[bool, str | None]` — the bool was always `True` at the only callsite because the caller guarded on the exact inverse condition. Also added a `_validate_table_name` call at the top (**RESILIENCE-5**) to match the rest of `metadata.py`'s defense-in-depth convention.
  - **TYPE-4 (P3):** annotated `**extra: object` in `_bind_task_log_context` instead of implicit `Any`.
- **Security:** upgraded `anthropic` from 0.86.0 to 0.88.0 to patch CVE-2026-34450 and CVE-2026-34452.
- Pydantic constraints added to user-input string fields (basemaps, OAuth, settings) to prevent oversized payloads.
- Embedding backfill now returns a structured 502 on provider failures instead of swallowing exceptions.
- Embedding stats endpoint guards against missing `record_embeddings` table during early bootstrap.
- Embedding OpenAI client uses `max_retries=2` for transient failure resilience.
- Embedding auto-detect and column rebuild log exceptions instead of swallowing them.
- OGC catch-all 500 handler returns RFC 7807 `ProblemDetail` format.
- Datasets router uses HTTP status constants and explicit return type annotations.
- Last-admin guard extracted to a shared private method to prevent admin lockout regressions.
- Settings updates batched into a single query with deferred commits for performance.
- Branding update now routes through the unified settings endpoint with type alignment.
- Admin router authorization, CBAC, and audit logging hardened (admin audit remediation).
- Builder bug-fix sweep: 68 files, 181 findings from the builder audit (filter persistence, layer styling, drag-and-drop, raster controls).
- Database tuning sweep: PostgreSQL `random_page_cost` and `jit` settings, missing foreign-key indexes added on high-traffic tables, backup service hardening.
- Test audit + post-implementation audit remediation: type safety, resilience, KISS refactors across backend.
- Themed demo seeder (Phase 218) post-implementation audit remediation:
  - Orchestrator now propagates non-zero exit codes when any fixture fails to apply, so Docker Compose correctly reports seeder failures instead of hiding them behind a successful bash exit.
  - `apply_fixture` is idempotent across re-runs: GET-by-name is checked before POST so repeated seeder runs update existing demo maps in place instead of accumulating duplicate catalog entries.
  - Seeder `run-seeder.sh` wrapper now installs a SIGTERM/SIGINT/EXIT trap that rotates the `demo-seed` API key on exit (graceful or abnormal), preventing stale keys from accumulating when the container is killed mid-run.
  - Seeder auth + API-key lifecycle extracted from embedded bash heredocs into a lint-testable `scripts/demo/lib/create_api_key.py` module.
  - Bundled demo data (GeoJSON + CSV) is gzipped after checksum validation in Stage 1 of the seeder Dockerfile and decompressed in-place at container start, shaving ~290 MB off the `/data/demo` layer. Combined with the `uv pip install --system httpx` swap (replacing apt's `python3-pip`) and other layer optimizations, the total shipped seeder image shrunk from **637 MB → 261 MB** (~376 MB total savings). Rasters left untouched because they're already DEFLATE-compressed.
  - World Bank GDP CSV is now fetched via `python3 -c "urllib.request..."` instead of curl inside the Dockerfile's data-fetcher stage. Cloudflare started JA3-fingerprinting and blocking curl on `api.worldbank.org`, returning HTTP 502 for every curl request regardless of headers or TLS version; Python's stdlib `ssl` module presents a different TLS fingerprint that Cloudflare accepts. Only the one affected RUN step was changed — all other upstream fetches (NACIS, source.coop, OpenTopography, OWID, Geofabrik, UCDP, UNHCR) still use curl and still work.
  - Seeder service in `docker-compose.demo.yml` now depends on `worker: service_healthy` in addition to `api: service_healthy`, closing a cold-start race where ingest jobs could be submitted before the Celery worker was ready.
  - `BuilderMap` mirrors the `ViewerMap` `data-tiles-loaded` DOM attribute that flips to `true` on the maplibre `idle` event, giving the Playwright demo-smoke suite a deterministic signal on both the authenticated `/maps/:id` editor path and the anonymous public viewer. Replaces 16 s of arbitrary `waitForTimeout(2_000)` across the 8 required demo maps, so the suite now completes ~17 s faster per run.

### Operators
- Environments that created public raster datasets before the anonymous raster viewer fix may still have `catalog.records` rows stuck at `record_status='draft'`. Review and backfill only those public raster rows before the next release:

```sql
SELECT id, title, visibility, record_status, created_at
FROM catalog.records
WHERE record_type = 'raster_dataset'
  AND record_status = 'draft'
  AND visibility = 'public';

UPDATE catalog.records
   SET record_status = 'published',
       published_at = NOW()
 WHERE record_type = 'raster_dataset'
   AND record_status = 'draft'
   AND visibility = 'public';
```

### Added
- Heatmap visualization mode in map builder with gradient legend, opacity controls, and render mode toggle
- Widget system for map builder — measurement tool, layer legend, basemap picker as sidebar widgets
- Layer adapter infrastructure decoupling render logic from map builder core
- Search result card redesigned with 4-band layout, inline thumbnails, and auto-description
- Map thumbnails migrated from inline base64 to storage with `useMapThumbnail` hook
- Static basemap thumbnail assets replacing generated ImageMagick thumbnails
- Public maps browsing for anonymous users
- VRT mosaic creation button on bulk import review page
- Bulk dataset delete endpoint
- Audit log export endpoint (CSV and JSON)
- Config-ops validate endpoint wired into admin frontend
- Centralized query key factory for TanStack Query hooks
- Heatmap gradient legend with Low/High labels
- Anonymous public browsing support
- `language` field added to records via new Alembic migration
- Design guide token system with status-colors utility and WCAG 2.1 AA compliance

### Changed
- Squashed 12 incremental Alembic migrations into single foundational schema
- Datasets router split into sub-routers with `get_dataset_service_url` helper
- Batched collection and map lookup queries to eliminate N+1 patterns
- Filter editor rebuilt with OR combinator and raw JSON toggle for resilience
- Data-driven styling generalized to support radius and width beyond color
- Comprehensive i18n remediation — formatting standards, RTL support, Unicode handling
- Frontend state management refactored with typed search store and centralized query keys
- Widget placement API redesigned with `WidgetAnchor` and `WidgetPlacement` discriminated union
- Basemap toggle redesigned with thumbnail trigger, labeled popover, and right-opening layout

### Fixed
- ArcGIS preview fetches capped with `result_limit=5` and timeout increased to 120s to prevent 502 errors
- Basemap switching now preserves user layers; stable ref prevents `setStyle` race conditions
- Orphaned basemap layers skipped in `transformStyle` to prevent source-not-found errors
- COG download uses browser-native streaming with authenticated fetch
- Export permission check restored on COG download endpoint
- Non-spatial ArcGIS tables skip spatial post-processing
- Trailing slashes normalized across all API routes
- Collection dataset response aligned with canonical dataset response
- AI rate limiting and raster RBAC parity
- OGC/STAC/DCAT standards compliance gaps resolved
- Docker config hardened — restart policies, security headers, PostGIS image pinned to 17-3.5
- PostgreSQL tuned with `random_page_cost=1.1` and `jit=off`
- Missing foreign key indexes added on high-traffic join/cascade tables
- `BuilderMap` mousemove throttled with `requestAnimationFrame`
- Embedding client cached with LLM timeouts to prevent event loop blocking
- OOM risks fixed in S3 upload and reupload file hash
- Deprecated `HTTP_422_UNPROCESSABLE_ENTITY` references replaced
- Raster and spreadsheet types included in default allowed extensions

## [14.0] - 2026-03-30

> *Internal pre-public version. Most marketing-site content listed here was relocated to the [getgeolens.com](https://github.com/geolens-io/getgeolens.com) repo before public release; only the core fixes below remained in this codebase.*

### Fixed
- Shared map raster tile URL path resolution for VRT datasets
- DEM terrain tiles skip rescale for terrainrgb algorithm
- Duplicate Alembic revision ID and broken chain for 3D columns migration
- Post-implementation audit findings across 3D and shared vector staging phases

## [13.0] - 2026-03-27

### Added
- Open-core architecture with enterprise extension points
- Plugin entrypoint system for modular feature loading
- CI pipeline with path-filtered conditional jobs, security scanning (bandit + pip-audit), and E2E tests
- Docker image publishing to GHCR with Trivy scan gate and SBOM attestation

### Changed
- Upgraded all dependencies (backend and frontend) to latest stable versions
- Pinned Docker base images to specific digests for reproducible builds

### Fixed
- IDOR vulnerabilities in dataset and map endpoints
- CORS configuration tightened to explicit allowed origins
- Rate limiting added to authentication endpoints
- Graceful shutdown and init process in Docker containers

## [12.3] - 2026-03-21

### Added
- Keyboard-accessible map builder with full tab navigation
- Builder save/load unit and E2E tests
- Alembic migrations run automatically on API container startup

### Fixed
- Basemap E2E test selector alignment
- Missing i18n keys in builder components

## [12.2] - 2026-03-19

### Added
- No-tile badge for raster datasets without a configured tile URL
- Tile error tracking and hero state machine for raster/VRT previews

### Fixed
- Raster hero state now correctly shows no-tile badge instead of infinite spinner

## [12.1] - 2026-03-17

### Added
- Smart timestamps in audit log (relative for recent, absolute for older entries)
- Client-side search on collections browse page
- Responsive overflow tabs on dataset detail panel

### Fixed
- Login form test selector ambiguity
- Missing i18n keys for dataset card provenance fallback
- Trailing slash on collections/datasets API call causing 307 redirect

## [12.0] - 2026-03-17

### Added
- Record-first discovery architecture -- catalog now surfaces individual records, not just datasets
- Keyword facet picker integrated into filter panel
- Search ranking with faceted filtering backend
- Publish button wired to dataset status endpoint

### Changed
- Catalog search rewritten around record-level results
- Filter panel now supports keyword facets alongside existing filters

### Fixed
- Keyword URL encoding in search queries
- Missing i18n metadata keys

## [11.0] - 2026-03-16

### Added
- Performance regression test suite for 5 critical API paths
- Load test framework with tuning documentation
- Connection pool and query optimization for large catalogs

## [10.1] - 2026-03-15

### Added
- VRT-based raster mosaics from multiple source GeoTIFFs
- Sources tab on dataset detail showing VRT member files
- Delete guard UX showing dependent VRT links on 409 conflict
- VRT i18n keys for all 4 locales (en, de, es, fr)

### Fixed
- VRT regeneration banner and error display
- SQL string concatenation bugs in VRT source link queries
- AlertDialogAction auto-close behavior on 409 delete errors

## [10.0] - 2026-03-14

### Added
- Raster dataset support -- upload GeoTIFF and Cloud-Optimized GeoTIFF (COG) files
- Automatic COG conversion for non-optimized GeoTIFFs
- Raster tile serving via Titiler integration
- Raster layer controls in map builder (opacity, band selection)
- AI chat awareness of raster datasets with set_opacity action
- `layer_type` field round-trip in saved maps

### Changed
- Map builder layer item rendering now conditional on vector vs raster type
- TileToken schema extended to union of vector and raster token types

## [8.2] - 2026-03-10

### Added
- Inline-editable share link settings (title, description, allowed origins)
- PATCH endpoints for share tokens and embed tokens
- SharePanel redesigned with inline editing replacing read-only summary

## [8.0] - 2026-03-09

### Added
- Spatial intelligence -- AI can execute spatial queries and display results as ephemeral map layers
- Ephemeral result layer rendering with dismiss UI
- Backend GeoJSON extraction from spatial query results
- Semantic search powered by pgvector
- Related datasets discovery based on vector similarity
- Semantic search toggle in filter panel

### Changed
- Enterprise configuration consolidated and cleaned up
- AI prompts optimized for spatial query generation

## [7.2] - 2026-03-08

### Added
- pgvector-based semantic search across dataset metadata
- Related datasets API endpoint and frontend card
- Semantic search toggle with store and API support

## [6.2] - 2026-03-07

### Added
- OAuth 2.0 / OIDC authentication support
- Enterprise configuration management UI
- Settings tabs reorganized into sidebar sub-navigation
- Config import/export functionality

### Fixed
- File dialog double-trigger on config import
- Missing sidebar translation keys for config and permissions sections

## [6.0] - 2026-03-03

### Added
- Redis circuit breaker for cache provider resilience
- Procrastinate queue splitting with file-size-based routing
- Upload limits admin UI with database-driven enforcement
- CORS deployment documentation
- Type-safe filter specifications replacing `unknown[]` types

### Changed
- Production hardening across 9 phases (102-110)
- Abort cleanup wired into collection membership manager

## [3.0] - 2026-02-28

### Added
- Collections for organizing datasets into groups
- Batch dataset operations
- Dataset export in multiple formats (GeoJSON, Shapefile, GeoPackage, CSV)
- CRS reprojection on export

## [2.4] - 2026-02-26

### Added
- Theme support (light/dark) with system preference detection
- Admin settings API for basemaps, map defaults, and feature toggles
- Basemap utilities and theme-aware basemap selection
- Admin layout with sidebar navigation

## [2.0] - 2026-02-22

### Added
- Initial public release
- PostGIS-backed spatial data catalog
- Full-text and spatial search
- Vector file upload and ingestion (Shapefile, GeoPackage, GeoJSON, CSV)
- Interactive map preview with MapLibre GL
- OGC API - Features compliance
- JWT authentication with role-based access control
- Docker Compose deployment

[Unreleased]: https://github.com/geolens-io/geolens/compare/v1.0.2...HEAD
[1.0.2]: https://github.com/geolens-io/geolens/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/geolens-io/geolens/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/geolens-io/geolens/releases/tag/v1.0.0
[14.0]: https://github.com/geolens-io/geolens/compare/v13.0...v14.0
[13.0]: https://github.com/geolens-io/geolens/compare/v12.3...v13.0
[12.3]: https://github.com/geolens-io/geolens/compare/v12.2...v12.3
[12.2]: https://github.com/geolens-io/geolens/compare/v12.1...v12.2
[12.1]: https://github.com/geolens-io/geolens/compare/v12.0...v12.1
[12.0]: https://github.com/geolens-io/geolens/compare/v11.0...v12.0
[11.0]: https://github.com/geolens-io/geolens/compare/v10.1...v11.0
[10.1]: https://github.com/geolens-io/geolens/compare/v10.0...v10.1
[10.0]: https://github.com/geolens-io/geolens/compare/v8.2...v10.0
[8.2]: https://github.com/geolens-io/geolens/compare/v8.0...v8.2
[8.0]: https://github.com/geolens-io/geolens/compare/v7.2...v8.0
[7.2]: https://github.com/geolens-io/geolens/compare/v6.2...v7.2
[6.2]: https://github.com/geolens-io/geolens/compare/v6.0...v6.2
[6.0]: https://github.com/geolens-io/geolens/compare/v3.0...v6.0
[3.0]: https://github.com/geolens-io/geolens/compare/v2.4...v3.0
[2.4]: https://github.com/geolens-io/geolens/compare/v2.0...v2.4
[2.0]: https://github.com/geolens-io/geolens/releases/tag/v2.0
