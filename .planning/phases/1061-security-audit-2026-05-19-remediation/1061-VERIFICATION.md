---
phase: 1061-security-audit-2026-05-19-remediation
verified: 2026-05-20T00:00:00Z
status: passed
score: 8/8
re_verification: true
gap_closed: "Layering invariant restored via commit 5f8a6b86 — lazy import inside _download_http_source. test_no_processing_imports_catalog PASS."
gaps_initial:
  - truth: "Phase 1061 does not introduce test suite regressions (existing tests still pass)"
    status: closed
    reason: >
      Phase 1061 Plan 04 (SEC-S04, commit 2658e8ac) introduced a module-level import
      `from app.modules.catalog.sources.security import make_safe_client` at line 16 of
      `backend/app/processing/ingest/manifest_service.py`. This violates the Phase 225
      PROCESS-02/04 architectural invariant that no file in `backend/app/processing/`
      may have a module-level import from `app.modules.catalog.*`. The guard
      `test_no_processing_imports_catalog` in `backend/tests/test_layering.py` fails
      with exit code 1 when run against the current HEAD. The REVIEW-FIX.md incorrectly
      characterised this as a pre-existing failure; `git show 927a6770` (the last
      pre-Phase-1061 commit on that file) confirms no `app.modules.catalog` import
      existed before this phase.
    artifacts:
      - path: "backend/app/processing/ingest/manifest_service.py"
        issue: "Line 16: `from app.modules.catalog.sources.security import make_safe_client` — module-level cross-layer import violates Phase 225 PROCESS-02/04 invariant"
      - path: "backend/tests/test_layering.py::test_no_processing_imports_catalog"
        issue: "Test FAILS with `Phase 225 PROCESS-02/04 invariant violated` when run locally"
    missing:
      - "Move make_safe_client (or an equivalent HTTP-safety primitive) to a location reachable from processing/ without crossing the catalog boundary — e.g. `app.core.http_safety` or `app.platform.http_safety` — OR restructure manifest_service.py to call make_safe_client lazily (function-scope import, which the guard explicitly exempts per its docstring), OR add the import to the guard's documented allowlist with rationale. See `test_layering.py:1112-1115` for the function-scope exemption note."
---

# Phase 1061 Verification Report

**Phase Goal:** Close 7 HIGH findings from `/sec-audit` 2026-05-19 (merge gate currently BLOCK) and pin the visibility-filter coverage pattern in AGENTS.md to prevent regression.
**Verified:** 2026-05-20
**Status:** GAPS_FOUND — one BLOCKER (layering test regression introduced by Phase 1061)
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | STAC router applies visibility filter matching OGC API peer | VERIFIED | `stac/router.py`: `_base_published_raster_query(user, user_roles)` + `_resolve_roles` helper; `apply_visibility_filter` called at line 245; 5 item-returning endpoints thread `user`/`user_roles`; 6 new tests in `test_stac_visibility.py` |
| 2 | Dataset metadata IDOR closed (3 handlers in router.py) | VERIFIED | `datasets/api/router.py`: `check_dataset_access` at lines 280, 359 (per-item), 429; `check_dataset_access` imported at line 26; 9 tests in `test_dataset_metadata_idor.py` including 2 CR-01 tests |
| 3 | Column DDL IDOR closed (4 handlers in layers/router.py) | VERIFIED | `layers/router.py`: `check_dataset_access` at lines 109, 165, 221, 280; imported at line 13; 8 tests in `test_column_ddl_idor.py` |
| 4 | SSRF redirect-bypass closed via make_safe_client + GDAL_HTTP_FOLLOWLOCATION=NO | VERIFIED | `sources/security.py`: `_revalidate_redirect` at line 70, `make_safe_client` at line 91; 4 call sites updated (router.py, stac.py, manifest_service.py); `ogr.py` lines 645+648 set `GDAL_HTTP_FOLLOWLOCATION=NO`; 7 tests in `test_ssrf_redirect.py` pass locally |
| 5 | Related-datasets IDOR closed (/datasets/{id}/related/) | VERIFIED | `router_data.py` line 75: `check_dataset_access_or_anonymous` before embedding read; `dataset_maps` endpoint also gated at line 216 (WR-02 fix); 6 tests in `test_related_datasets_idor.py` |
| 6 | Demo credentials cannot start the stack with committed defaults | VERIFIED | `config.py` lines 236/244/252: guard refuses 3 literal values unconditionally; early-return on `geolens_demo_mode=True` removed; `.env.demo.example` has REPLACE_ME values; `.env.demo` gitignored; 63/63 config tests pass locally |
| 7 | MinIO cannot start with minioadmin defaults | VERIFIED | `docker-compose.yml` lines 510-511, 541-542: `${MINIO_ROOT_USER:?required}` fail-closed expansion; no `:-minioadmin` defaults remain; `minio-setup` uses `$$MINIO_ROOT_USER`/`$$MINIO_ROOT_PASSWORD` |
| 8 | AGENTS.md guardrail + pre-commit grep hooks (SEC-GUARD-01) | VERIFIED | `AGENTS.md` lines 57-90: 3-rule Security pre-commit checklist with explicit function names and file paths; `.pre-commit-config.yaml` created with `ssrf-safe-client` (system bash, multi-line capable) + `visibility-filter-coverage` hooks; both hooks pass on current codebase |
| 9 | Phase 1061 does not introduce test suite regressions | FAILED | `test_layering.py::test_no_processing_imports_catalog` FAILS — Phase 1061 commit `2658e8ac` introduced `from app.modules.catalog.sources.security import make_safe_client` at module level in `backend/app/processing/ingest/manifest_service.py:16`, violating Phase 225 PROCESS-02/04 invariant |

**Score:** 7/8 truths verified (the 8th truth — no test regressions — is derived from the ROADMAP acceptance gates that require regression-free baseline; the 8 stated requirements are fully implemented, but the layering violation is a blocking side effect)

---

## Per-Requirement Verification

### SEC-S01 (HIGH, CVSS 7.5): STAC Visibility Filter

**Status:** PASS

**Implementation:** Commits `1c10a9e0`, `2eb2f9bc` — `backend/app/standards/stac/router.py`
- `_base_published_raster_query` refactored to accept `user: Identity | None, user_roles: set[str]`
- `apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)` called at line 245
- `_resolve_roles(db, user)` helper at line 248 (returns `set()` for anonymous)
- 5 item-returning endpoints updated: `get_collection_items`, `get_collection_item`, `get_item`, `search_get`, `search_post`

**Test evidence:** `backend/tests/test_stac_visibility.py` — 6 tests (DB required, pass per SUMMARY; confirmed as non-stub by test content); commit `a69184ec`

**Audit fix shape match:** YES — matches OGC API peer pattern (`apply_visibility_filter` + `get_optional_user` + role threading)

**Carve-out:** `get_collections`/`get_collection` aggregate endpoints (count/bbox/keyword only, no item bodies) deferred to SEC-FU per T-1061-02 accept disposition. Correctly bounded.

---

### SEC-S02 (HIGH, CVSS 8.1): Dataset Metadata IDOR

**Status:** PASS

**Implementation:** Commits `36b909a4` (3 handlers), `1a443f49` (CR-01: 2 additional handlers) — `backend/app/modules/catalog/datasets/api/router.py` and `router_data.py`
- `update_dataset_metadata` (router.py:280): `check_dataset_access` after 404 check
- `bulk_delete_datasets_endpoint` (router.py:359): per-item `check_dataset_access` in loop
- `delete_dataset_endpoint` (router.py:429): `check_dataset_access` + owner-or-admin guard
- `update_publication_status` (router_data.py:268): CR-01 fix — `check_dataset_access` added
- `set_target_status` (router_data.py:324): CR-01 fix — `check_dataset_access` added

**Test evidence:** `backend/tests/test_dataset_metadata_idor.py` — 9 tests (7 original + 2 CR-01 additions); commit `f4d9e6c4` + `1a443f49`

**Audit fix shape match:** YES — `check_dataset_access` after `get_dataset` in each handler

**e2e:** `SEC_AUDIT_PRIVATE_DATASET_ID` + `SEC_AUDIT_EDITOR_B_TOKEN` env-var-gated; 3 S02 e2e tests written in `e2e/sec-audit.spec.ts`

---

### SEC-S03 (HIGH, CVSS 8.1): Column DDL IDOR

**Status:** PASS

**Implementation:** Commit `bcae9610` — `backend/app/modules/catalog/layers/router.py`
- `add_column_endpoint` (line 109): `check_dataset_access` after 404
- `rename_column_endpoint` (line 165): `check_dataset_access` after 404
- `alter_column_type_endpoint` (line 221): `check_dataset_access` after 404
- `drop_column_endpoint` (line 280): `check_dataset_access` after 404
- `check_dataset_access` imported at line 13

**Test evidence:** `backend/tests/test_column_ddl_idor.py` — 8 tests (4 deny + 4 allow); commit `f4d9e6c4`

**Audit fix shape match:** YES — same `check_dataset_access` pattern as SEC-S02

---

### SEC-S04 (HIGH, CVSS 8.5): SSRF Redirect-Bypass

**Status:** PASS (with BLOCKER side effect — see layering gap)

**Implementation:** Commits `09628707`, `2658e8ac`, `49116056` — `backend/app/modules/catalog/sources/security.py`, `router.py`, `adapters/stac.py`, `processing/ingest/ogr.py`, `processing/ingest/manifest_service.py`
- `_revalidate_redirect(response: httpx.Response)` at `security.py:70` — intercepts every 3xx, validates `Location` via `validate_url_for_ssrf`
- `make_safe_client(timeout)` factory at `security.py:91` — `follow_redirects=True`, `max_redirects=5`, event hook installed
- 4 raw `AsyncClient(follow_redirects=True)` sites replaced: `sources/router.py` (×2), `adapters/stac.py`, `manifest_service.py`
- `ogr.py` lines 645+648: `GDAL_HTTP_FOLLOWLOCATION=NO` in both env branches of `run_ogr2ogr_service`
- Grep gate: zero raw `AsyncClient(follow_redirects=True)` sites outside `security.py` in `backend/app/` (confirmed)

**Test evidence:** `backend/tests/test_ssrf_redirect.py` — 7 tests; **ALL PASS locally** (no DB required); commit `1ceebaa1`

**Audit fix shape match:** YES — `event_hooks={"response": [_revalidate_redirect]}` + `GDAL_HTTP_FOLLOWLOCATION=NO`

**Side effect — BLOCKER:** The fix to `manifest_service.py` introduced a module-level import from `app.modules.catalog.sources.security` (line 16), violating the Phase 225 PROCESS-02/04 architectural layering invariant. `test_no_processing_imports_catalog` FAILS. See Gaps Summary.

---

### SEC-S05 (HIGH, CVSS 7.5): Related-Datasets IDOR

**Status:** PASS

**Implementation:** Commits `02c3f35d` (S05), `3568949b` (WR-02) — `backend/app/modules/catalog/datasets/api/router_data.py`
- `list_related_datasets` (line 75): `check_dataset_access_or_anonymous` added before `_load_self_record_and_embedding`; return value reused as `user_roles` (no extra DB round-trip)
- `dataset_maps` (line 216): WR-02 fix — `check_dataset_access_or_anonymous` gate closes dataset-existence oracle
- Defense-in-depth docstring in `service_relationships.py:_load_self_record_and_embedding`

**Test evidence:** `backend/tests/test_related_datasets_idor.py` — 6 tests (5 S05 + 1 WR-02); commit `07bef8ff` + `3568949b`

**Audit fix shape match:** YES — `check_dataset_access_or_anonymous` before embedding read

---

### SEC-S06 (HIGH, CVSS 7.5): Demo Credentials

**Status:** PASS

**Implementation:** Commits `a8cba68d`, `751108b6` — `backend/app/core/config.py`, `.gitignore`, `.env.demo.example`, `scripts/init-demo-env.sh`
- `validate_demo_credentials_guard` (`config.py:207-259`): early-return on `geolens_demo_mode=True` REMOVED; all 3 literals (`DEMO_JWT_SECRET`, `DEMO_ADMIN_PASSWORD`, `DEMO_POSTGRES_PASSWORD`) refused unconditionally
- `.env.demo` removed from git tracking; `.gitignore` line 8 covers it; `.env.demo.example` has `REPLACE_ME_WITH_init-demo-env.sh` placeholders
- `scripts/init-demo-env.sh` generates random credentials via `openssl rand`; refuses to overwrite without `--force`; writes at permissions 600

**Test evidence:** `backend/tests/test_demo_credentials_guard.py` — 5 tests; `backend/tests/test_config.py` — 63 tests (2 updated for new behavior); **ALL PASS locally** (no DB required)

**e2e:** S06 e2e test passes locally per SUMMARY (`admin/demodemo → 401` against dev stack)

**Audit fix shape match:** YES — no-literal-default boot guard + per-deploy generator script

---

### SEC-S07 (HIGH, CVSS 7.0): MinIO Default Credentials

**Status:** PASS

**Implementation:** Commit `8d854603` — `docker-compose.yml`
- `minio` service: `MINIO_ROOT_USER: "${MINIO_ROOT_USER:?MINIO_ROOT_USER is required...}"` at line 510
- `minio` service: `MINIO_ROOT_PASSWORD: "${MINIO_ROOT_PASSWORD:?...}"` at line 511
- `minio-setup` entrypoint: hardcoded `minioadmin minioadmin` → `$$MINIO_ROOT_USER` / `$$MINIO_ROOT_PASSWORD` env vars
- Grep gate: zero `:-minioadmin` matches (confirmed)

**Test evidence:** `docker compose --profile cloud-dev config` errors with "MINIO_ROOT_USER is required" when var is unset (verified per SUMMARY)

**Audit fix shape match:** YES — `:?required` fail-closed shell expansion replacing `:-minioadmin` defaults

---

### SEC-GUARD-01 (Architectural): AGENTS.md Guardrail

**Status:** PASS

**Implementation:** Commits `80a84829` (AGENTS.md), `64fb7992` (pre-commit), `1e122868` (WR-01 AGENTS.md correction) — `AGENTS.md`, `.pre-commit-config.yaml`

**AGENTS.md content verified (grep-confirmed):**
- Rule 1 (Visibility): `check_dataset_access_or_anonymous`, `check_dataset_access`, `apply_visibility_filter` named with reference implementations
- Rule 2 (SSRF): `make_safe_client()` + `_revalidate_redirect` named; ogr2ogr `GDAL_HTTP_FOLLOWLOCATION=NO` noted
- Rule 3 (Demo creds): accurate two-layer description — Python boot guard (3 Settings fields only) + Docker Compose `:?required` syntax (not Python); MinIO not Python-guarded explicitly stated

**Pre-commit hooks verified:**
- `ssrf-safe-client` hook: `language: system` bash, file-level grep (catches multi-line declarations); excludes `security.py` + `tiles/router.py` with rationale (CR-02 fix applied)
- `visibility-filter-coverage` hook: route-decorator-scoped bash; excludes `router_reupload.py` with documented rationale (tracked SEC-FU, Phase 1063)
- YAML validated; both hooks pass on current codebase

---

## Regression Suite

### Backend pytest (no-DB tests — runnable locally)

| Suite | Result |
|-------|--------|
| `test_ssrf_redirect.py` (7 tests) | 7/7 PASS |
| `test_demo_credentials_guard.py` (5 tests) | 5/5 PASS |
| `test_config.py` (63 tests including 2 updated guard tests) | 63/63 PASS |
| `test_layering.py::test_no_processing_imports_catalog` | **FAIL** |

### Backend pytest (DB-required tests — require running stack)

| Suite | Claimed Result (REVIEW-FIX.md) | Verifiable? |
|-------|------|------|
| `test_stac_visibility.py` (6 tests) | 6/6 PASS | No (DB required) |
| `test_dataset_metadata_idor.py` (9 tests) | 9/9 PASS | No (DB required) |
| `test_column_ddl_idor.py` (8 tests) | 8/8 PASS | No (DB required) |
| `test_related_datasets_idor.py` (6 tests) | 6/6 PASS | No (DB required) |
| Full suite (excluding pre-existing) | 2734 PASS, 6 pre-existing FAIL | No (DB required) |

### e2e/sec-audit.spec.ts

19 tests — all env-var-gated for S01-S05, S04 requires external redirector service. S06 test (no env var needed against dev stack) passes per SUMMARY. Full suite execution is Phase 1064 close-gate responsibility per ROADMAP.

---

## Human Verification Required

### 1. Full backend pytest suite against running Docker stack

**Test:** `cd backend && python -m pytest` with Docker stack up
**Expected:** 41/41 Phase 1061 security tests pass; pre-existing 6 failures unchanged; `test_no_processing_imports_catalog` passes ONLY IF the layering gap is fixed
**Why human:** Database connection required; cannot run without Docker stack

### 2. e2e/sec-audit.spec.ts full suite

**Test:** Provision env vars (`SEC_AUDIT_PRIVATE_RECORD_ID`, `SEC_AUDIT_PRIVATE_DATASET_ID`, `SEC_AUDIT_EDITOR_B_TOKEN`, `SEC_AUDIT_SSRF_TEST_REDIRECTOR`) then run `npx playwright test e2e/sec-audit.spec.ts`
**Expected:** All 19 tests pass or skip with clear env-var reason for not-yet-provisioned fixtures
**Why human:** Requires live stack + ngrok-style external redirector for S04

### 3. Demo overlay boot verification

**Test:** `scripts/init-demo-env.sh && docker compose -f docker-compose.yml -f docker-compose.demo.yml --env-file .env.demo up -d`
**Expected:** Stack boots without credential-guard errors; `admin/demodemo` → 401; generated password → 200
**Why human:** Dev stack occupies ports concurrently; deferred to Phase 1064

---

## Gaps Summary

### BLOCKER: test_no_processing_imports_catalog FAILS — layering violation introduced by Phase 1061

**Root cause:** Commit `2658e8ac` (SEC-S04, Plan 04, Task 2) added `from app.modules.catalog.sources.security import make_safe_client` at line 16 of `backend/app/processing/ingest/manifest_service.py`. This is a module-level import from `app.modules.catalog.*` in the `backend/app/processing/` subtree. The Phase 225 PROCESS-02/04 architectural invariant (`test_layering.py::test_no_processing_imports_catalog`) prohibits all such module-level cross-layer imports. The test uses `git grep` and FAILS with exit code 0 (violation found).

**Misclassification:** The REVIEW-FIX.md (`backend/tests/test_layering.py::test_no_processing_imports_catalog` — Phase 1061 Plan 04 introduced `make_safe_client` import ... **not introduced by this review fix**) correctly identified the source commit but then classified it as "pre-existing" when the full sentence makes clear it was introduced BY this phase. `git show 927a6770` (last pre-Phase-1061 commit on `manifest_service.py`) confirms no `app.modules.catalog` import existed before Phase 1061.

**Fix options (verifier's assessment):**
1. Move `make_safe_client` (or a thin wrapper) to `app.core.http_safety` or `app.platform.http_safety` — either is reachable from `processing/` without crossing the catalog boundary.
2. Convert the import in `manifest_service.py` to a function-scope lazy import inside `_download_http_source` (the guard's docstring at line 1112 explicitly exempts "function-scope lazy imports ... indented, e.g. inside async def bodies").
3. Add `manifest_service.py` to the guard's allowlist with documented rationale — least preferred as it weakens the invariant without fixing the coupling.

**Impact on merge gate:** This test failure means the full backend pytest suite cannot pass on Phase 1061's HEAD. Per REQUIREMENTS.md SEC-CTRL-01 (Phase 1064 close gate), "all standard smoke gates green: backend pytest" is a merge gate prerequisite. Phase 1061 cannot be considered fully complete until this is resolved.

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/app/standards/stac/router.py` | visibility filter threaded | VERIFIED | `apply_visibility_filter` at line 245; 5 endpoints updated |
| `backend/app/modules/catalog/datasets/api/router.py` | 3 handlers gated | VERIFIED | `check_dataset_access` at lines 280, 359, 429 |
| `backend/app/modules/catalog/layers/router.py` | 4 handlers gated | VERIFIED | `check_dataset_access` at lines 109, 165, 221, 280 |
| `backend/app/modules/catalog/sources/security.py` | make_safe_client + hook | VERIFIED | `_revalidate_redirect` line 70, `make_safe_client` line 91 |
| `backend/app/processing/ingest/ogr.py` | GDAL_HTTP_FOLLOWLOCATION=NO | VERIFIED | Lines 645, 648 |
| `backend/app/processing/ingest/manifest_service.py` | make_safe_client used | VERIFIED (content) / BLOCKER (layering) | Line 98 uses factory; line 16 import violates invariant |
| `backend/app/core/config.py` | unconditional credential guard | VERIFIED | Early-return removed; 3 literals refused at lines 236, 244, 252 |
| `docker-compose.yml` | fail-closed MinIO expansion | VERIFIED | `:?required` at lines 510-511, 541-542 |
| `.env.demo.example` | placeholder values only | VERIFIED | `REPLACE_ME_WITH_init-demo-env.sh` values |
| `scripts/init-demo-env.sh` | per-deploy credential generator | VERIFIED | Exists; openssl rand; --force guard; chmod 600 |
| `.gitignore` | .env.demo gitignored | VERIFIED | Line 8: `.env.demo`; line 5: `!.env.demo.example` |
| `AGENTS.md` | 3-rule security checklist | VERIFIED | Lines 57-90; Rule 3 WR-01 correction applied |
| `.pre-commit-config.yaml` | 2 hooks with CR-02 fix | VERIFIED | Multi-line capable bash hooks; correct excludes |
| `backend/tests/test_stac_visibility.py` | 6 tests | VERIFIED (file exists, count confirmed) |
| `backend/tests/test_dataset_metadata_idor.py` | 9 tests (7+2 CR-01) | VERIFIED | All 9 functions present |
| `backend/tests/test_column_ddl_idor.py` | 8 tests | VERIFIED |
| `backend/tests/test_related_datasets_idor.py` | 6 tests (5+1 WR-02) | VERIFIED | All 6 functions present |
| `backend/tests/test_ssrf_redirect.py` | 7 tests | VERIFIED + PASS (local) |
| `backend/tests/test_demo_credentials_guard.py` | 5 tests | VERIFIED + PASS (local) |
| `e2e/sec-audit.spec.ts` | 19 tests, env-var-gated | VERIFIED | File exists; 19 test() calls confirmed |

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `backend/app/processing/ingest/manifest_service.py` | 16 | Module-level import from `app.modules.catalog.*` in `processing/` subtree | BLOCKER | Fails `test_no_processing_imports_catalog`; blocks full backend pytest pass |

---

## Conclusion

Phase 1061 achieves its security goal: all 7 HIGH findings (SEC-S01 through SEC-S07) and the SEC-GUARD-01 architectural guardrail are implemented with substantive, wired, tested code. The review cycle (REVIEW.md + REVIEW-FIX.md) caught and fixed 4 additional gaps (CR-01, CR-02, WR-01, WR-02), which were appropriately closed.

One BLOCKER gap remains: the SEC-S04 fix to `manifest_service.py` introduced a module-level import from `app.modules.catalog.sources.security` in the `backend/app/processing/` subtree, violating the Phase 225 PROCESS-02/04 architectural invariant enforced by `test_no_processing_imports_catalog`. This test FAILS on the current HEAD. The REVIEW-FIX.md incorrectly characterised this as pre-existing; git history confirms Phase 1061 introduced it. Resolving this requires either moving the `make_safe_client` symbol to a layer reachable from `processing/` (preferred), or converting the import to function-scope inside `_download_http_source` (also acceptable per the guard's documented exemption).

**Phase 1061: GAPS_FOUND** — all 8 requirements implemented, but one architectural test regression blocks the clean pytest baseline required by SEC-CTRL-01 (Phase 1064 close gate).

---

_Verified: 2026-05-20_
_Verifier: Claude (gsd-verifier)_
