---
phase: 1061
fixed_at: 2026-05-20T00:00:00Z
review_path: .planning/phases/1061-security-audit-2026-05-19-remediation/1061-REVIEW.md
iteration: 1
findings_in_scope: 4
fixed: 4
skipped: 0
status: all_fixed
---

# Phase 1061: Code Review Fix Report

**Fixed at:** 2026-05-20
**Source review:** `.planning/phases/1061-security-audit-2026-05-19-remediation/1061-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 4 (CR-01, CR-02, WR-01, WR-02)
- Fixed: 4
- Skipped: 0
- Info findings (IN-01, IN-02): deferred to `.planning/todos/pending/`

## Fixed Issues

### CR-01: Publication-status mutation endpoints missing check_dataset_access (IDOR)

**Files modified:** `backend/app/modules/catalog/datasets/api/router_data.py`, `backend/tests/test_dataset_metadata_idor.py`, `backend/tests/test_workflow_extension.py`
**Commit:** `1a443f49` (primary fix), `e92e4156` (test compatibility followup)
**Applied fix:** Added `check_dataset_access` import and call in both `update_publication_status` (after line 254) and `set_target_status` (after line 310) handlers, after the 404 existence check. Added 2 regression tests:
- `test_update_publication_status_other_user_private_returns_404` — PASS
- `test_set_target_status_other_user_private_returns_404` — PASS

Followup commit `e92e4156` added `_bypass_dataset_access_check` autouse fixture to `test_workflow_extension.py` to stub `check_dataset_access` in the workflow unit tests (which use a `_FakeDB` not wired for role/grant queries). This also resolved a pre-existing failure in `test_metadata_patch_endpoint_uses_overlay_block` caused by Phase 1061 Plan 02 adding `check_dataset_access` to `router.py`.

**Verification:** 9/9 IDOR tests PASS; 10/10 workflow extension tests PASS.

---

### CR-02: SSRF pre-commit hook does not catch multi-line httpx.AsyncClient declarations

**Files modified:** `.pre-commit-config.yaml`
**Commit:** `8a58b4e8`
**Applied fix:** Replaced the `pygrep` per-line hook (`language: pygrep`) with a `system` bash hook that greps both `follow_redirects=True` and `httpx.AsyncClient` across the full file. Added `backend/app/processing/tiles/router.py` to the `exclude` pattern with a rationale comment (fixed internal URL to `http://titiler:8000`, not user-controlled). The `description` block documents the exact multi-line shape that motivated the switch so future maintainers understand the hook boundary.

**Verification:** Manual hook simulation confirmed:
- A synthetic multi-line file is caught: `CAUGHT: ...`
- `tiles/router.py` would be caught but is correctly excluded
- `security.py` passes (contains `make_safe_client`)
- YAML validated with `python -c "import yaml; yaml.safe_load(...)"`

---

### WR-01: AGENTS.md Rule 3 inaccurately claims minioadmin is blocked by validate_demo_credentials_guard

**Files modified:** `AGENTS.md`
**Commit:** `1e122868`
**Applied fix:** Split Rule 3 into two clearly labeled enforcement layers:
1. **Python boot guard** (`validate_demo_credentials_guard`): three `Settings` fields only (`DEMO_JWT_SECRET`, `DEMO_ADMIN_PASSWORD`, `DEMO_POSTGRES_PASSWORD`). MinIO credentials not inspected.
2. **Docker Compose required-variable syntax** (`:?required`): prevents startup if env var is unset, but does NOT block `minioadmin/minioadmin` if explicitly set.

Added explicit note that MinIO protection requires `scripts/init-demo-env.sh`.

**Verification:** File re-read confirms correct content; no code changes, no syntax check needed.

---

### WR-02: dataset_maps endpoint has no dataset-visibility gate (dataset-existence oracle)

**Files modified:** `backend/app/modules/catalog/datasets/api/router_data.py`, `backend/tests/test_related_datasets_idor.py`
**Commit:** `3568949b`
**Applied fix:** Added `get_dataset` existence check + `check_dataset_access_or_anonymous` gate in `dataset_maps` before querying maps. `user_roles` from the gate replaces the previous `get_user_roles` call so no extra DB round trip is added. Added 1 regression test:
- `test_maps_anonymous_private_returns_404` — PASS

**Verification:** 6/6 related datasets IDOR tests PASS.

## Skipped Issues

None — all in-scope findings were fixed.

## Deferred Info Findings

### IN-01: _revalidate_redirect does not handle HTTP 305 (Use Proxy)

**Deferred to:** `.planning/todos/pending/2026-05-20-in01-revalidate-redirect-http-305.md`
**Reason:** No practical risk — httpx does not follow HTTP 305 redirects. RFC 7231 deprecated 305. Informational finding only.

### IN-02: GDAL_HTTP_FOLLOWLOCATION=NO missing comment on run_ogr2ogr

**Deferred to:** `.planning/todos/pending/2026-05-20-in02-run-ogr2ogr-gdal-followlocation-comment.md`
**Reason:** Maintainability-only change (add a one-line comment explaining intentional omission). No security impact.

---

## Regression Test Results

**Phase 1061 security tests (all files):** 41/41 PASS
```
test_dataset_metadata_idor.py   9 passed (7 pre-existing + 2 new CR-01)
test_related_datasets_idor.py   6 passed (5 pre-existing + 1 new WR-02)
test_ssrf_redirect.py           7 passed
test_demo_credentials_guard.py  5 passed
test_stac_visibility.py         6 passed
test_column_ddl_idor.py         8 passed
```

**Workflow extension tests:** 10/10 PASS (5 pre-existing failures resolved by `_bypass_dataset_access_check` fixture)

**Full backend suite (excluding pre-existing failures):**
- 2734 passed, 37 skipped
- 6 pre-existing failures in `test_maps_style_json.py` (5) and `test_phase_275_compose_alignment.py` (1) — unrelated to Phase 1061 changes
- 1 pre-existing failure in `test_layering.py::test_no_processing_imports_catalog` — Phase 1061 Plan 04 (SEC-S04) introduced `make_safe_client` import from `app.modules.catalog.sources.security` into the processing layer without updating the layering guard exclusions; not introduced by this review fix

---

_Fixed: 2026-05-20_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
