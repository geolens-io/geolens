---
phase: 1071-known-items-closure
plan: 08
subsystem: backend/export
tags: [export, auth, permissions, regression-test, KNOWN-05, v1014-sec-s04-parity]
requires:
  - backend/app/modules/auth/dependencies.py:require_permission (existing v1014 SEC-S04 factory)
  - backend/app/processing/export/router.py:export_dataset_endpoint (existing v1015 IA-P1-01 wiring)
provides:
  - backend/tests/test_export_hardening.py:TestExportRevokedViewerParity (2 regression tests)
affects:
  - v1015 Phase 1069 IA-P1-01 tech-debt followup CLOSED (live 403-for-revoked-viewer pin)
tech-stack:
  added: []
  patterns:
    - "Self-contained permission-mutation tests: every test that flips role_permissions wraps the live PUT in try/finally and resets via POST /settings/reset/, because clean_tables does NOT truncate the persistent_config table"
    - "Module-local mock-export fixture: the autouse mock_export_service fixture in test_export.py does not cross file boundaries, so test_export_hardening.py grew its own opt-in mock_export_service_for_known05 fixture (mirrors the test_export.py shape, scoped to the new tests only)"
    - "Live capability-gate regression pin: signature inspection alone (TestExportEndpointCapabilityGate) catches the dependency-removal class of bug; the live PUT-then-attempt-export test catches the matrix-consultation-silently-bypassed class of bug"
key-files:
  created: []
  modified:
    - backend/tests/test_export_hardening.py
decisions:
  - "Endpoint path correction: plan's example payload targeted PUT /admin/permissions/role-permissions/, but the actual canonical path (per test_permissions.py:184) is PUT /settings/ with body {settings: {role_permissions: matrix}}. Used the verified path."
  - "Both tests self-contained (NOT just test-1-restores). Plan-checker WARNING 1 noted test 2 must either be self-contained OR depend on test-1 restoring. Belt-and-suspenders: BOTH tests issue their own PUT and reset in try/finally. Pytest test-ordering becomes irrelevant and either test can be run in isolation."
  - "Used reset endpoint (POST /settings/reset/) instead of PUT-back-to-defaults. The existing test_permissions.py pattern uses reset; matches the canonical 'restore to DEFAULT_ROLE_PERMISSIONS' contract rather than freezing a specific matrix snapshot in the test file."
  - "Asserts detail mentions BOTH 'permission' AND 'export' (not OR). The require_permission factory at dependencies.py:314 emits f'Missing permission: {cap}'; the AND assertion catches a regression where the cap name is dropped (which would silently break operator diagnostics)."
  - "Sanity-check 200-before-revoke inside test 1. Defensive: pins that the default matrix DOES grant export, so a future regression that breaks the baseline (e.g., a DEFAULT_ROLE_PERMISSIONS edit that drops viewer.export) trips the test BEFORE the revoke step and reports clearly."
  - "Public dataset (NOT private). Per plan's 403-vs-404 nuance section: viewer on private gets 404 (visibility filter), viewer on public-with-revoke gets 403 (capability gate). Public is the only dataset shape that exercises the gate's 403 branch."
metrics:
  duration_min: ~5
  tasks_completed: 1/1
  files_modified: 1
  files_created: 0
  lines_added: 274
  commits: 1
completed: "2026-05-21T12:30:00Z"
---

# Phase 1071 Plan 08: KNOWN-05 Live 403-for-Revoked-Viewer Export Test Summary

Closed v1015 Phase 1069 IA-P1-01's verification gap. The export endpoint dependency on `require_permission("export")` was previously verified by signature inspection (`test_export_endpoint_uses_require_permission` at `test_export_hardening.py:85`) plus a live 401-for-anonymous Playwright MCP smoke. The 403-for-revoked-viewer path — the actual capability-matrix branch that runs in production — was never exercised by a test that would fail if the matrix-consultation code in `require_permission`'s closure were silently bypassed.

This plan added 2 regression tests to `backend/tests/test_export_hardening.py::TestExportRevokedViewerParity`. No production code touched.

## What Shipped

### Task 1 — TestExportRevokedViewerParity (commit `6ff24454`)

`backend/tests/test_export_hardening.py` (+274 / -2 lines):

**Module-level additions:**

- Imports: `os`, `shutil`, `tempfile`, `AsyncClient`, `FORMAT_MAP`, `create_dataset`, `get_user_id` (mirrors test_export.py patterns).
- `_DEFAULT_PERMISSION_MATRIX`: canonical matrix payload (viewer.export=True baseline; matches DEFAULT_ROLE_PERMISSIONS).
- `_VIEWER_EXPORT_REVOKED_MATRIX`: same matrix with viewer.export=False; editor and admin keep all defaults.
- `mock_export_service_for_known05` fixture (opt-in, scoped to the new test class): monkeypatches `app.processing.export.router.export_dataset` to write a dummy file and return `(path, filename, media)` so the endpoint returns a real FileResponse without invoking ogr2ogr. Cleans up the temp dir on teardown. Mirrors the shape of test_export.py's autouse mock_export_service.
- `_put_permission_matrix(client, admin_auth_header, matrix)`: helper that PUTs `{"settings": {"role_permissions": matrix}}` to `/settings/` and asserts 200.
- `_reset_permission_matrix(client, admin_auth_header)`: helper that POSTs `{"keys": ["role_permissions"]}` to `/settings/reset/` and asserts 200. Used in the `finally:` block of every test.

**TestExportRevokedViewerParity class — 2 tests:**

| Test | What it pins |
|---|---|
| `test_export_403_when_viewer_export_revoked` | Default matrix grants viewer export (sanity 200) → admin PUTs viewer.export=False → viewer attempting same export returns 403 with detail containing both 'permission' and 'export'. Public dataset so visibility filter passes; gate's 403 branch is the only path exercised. Restores defaults in `finally`. |
| `test_export_200_when_editor_export_kept` | Self-contained: applies the SAME revoke matrix (viewer.export=False, editor.export=True) → editor still gets 200. Proves the revoke is scoped to viewer, not blanket. Restores defaults in `finally`. |

Both tests carry the `@pytest.mark.anyio` decorator and consume the `mock_export_service_for_known05` fixture.

## Verification Results

| Check | Result |
|---|---|
| `uv run pytest tests/test_export_hardening.py::TestExportRevokedViewerParity -v` | 2/2 PASS |
| `uv run pytest tests/test_export_hardening.py -v` | 11/11 PASS (8 pre-existing TestWhereClauseInjectionRejection + 1 pre-existing TestExportEndpointCapabilityGate + 2 new TestExportRevokedViewerParity) |
| Test runtime | 4.17s for the full file |
| Production code touched | 0 lines (test-only plan; the production gate at `app/modules/auth/dependencies.py:282` and `app/processing/export/router.py:47` are correct as-shipped in v1015 Phase 1069) |
| Plan must_haves.truths satisfied | 3/3 (viewer-with-revoke→403; default-viewer→200/404 per visibility; live FastAPI app exercised not just signature inspection) |
| Plan must_haves.artifacts | `backend/tests/test_export_hardening.py` contains `revoked.*export` AND `export.*revoked` AND `403` (regex pattern satisfied) |
| Plan must_haves.key_links | `require_permission.*export` pattern satisfied (4 occurrences in the new section) |

## Deviations from Plan

**1. [Rule 1 - Bug fix in plan example] Endpoint path correction**
- **Found during:** Reading test_permissions.py to confirm the admin PUT payload shape
- **Issue:** The plan's example test code targeted `PUT /admin/permissions/role-permissions/` (a guess based on REST conventions; plan explicitly flagged this as needing verification at lines 240-243 of the plan: "the path in the test above is a guess based on REST conventions; correct it if the actual path differs")
- **Fix:** Used the verified canonical path `PUT /settings/` with body `{"settings": {"role_permissions": matrix}}` — matches existing `test_permissions.py::test_get_put_permissions` at line 184
- **Files modified:** `backend/tests/test_export_hardening.py` (helpers `_put_permission_matrix` and `_reset_permission_matrix`)

**2. [Rule 2 - Defensive correctness] Both tests self-contained (belt-and-suspenders)**
- **Found during:** Plan-checker WARNING 1 review at plan-start
- **Issue:** Plan said "test 2 must be self-contained OR test 1 must restore" — either is sufficient. But pytest test ordering is undefined; if test 2 runs before test 1 in some future invocation, depending on test-1-restore would leave test 2 hitting a stale revoked-matrix.
- **Fix:** Both tests do their own PUT + finally-block reset. Tests are independent and either can be run in isolation. No state leaks between them or to other tests in the file.
- **Files modified:** `backend/tests/test_export_hardening.py` (test class implementation)

**3. [Rule 3 - Blocking fix] Added module-local mock_export_service fixture**
- **Found during:** Initial test run would have failed because test_export.py's autouse `mock_export_service` fixture is module-scoped to test_export.py, NOT global. Without it, the export endpoint would attempt to call real `ogr2ogr` against a synthetic dataset (table doesn't exist in test DB).
- **Fix:** Added `mock_export_service_for_known05` opt-in fixture in test_export_hardening.py. Same shape as test_export.py's autouse fixture but scoped to the new class only (opt-in via test parameter, NOT autouse, so pre-existing tests in the file are unaffected).
- **Files modified:** `backend/tests/test_export_hardening.py`

**4. [Rule 2 - Defensive correctness] Sanity-check 200 inside test 1 before revoke**
- **Found during:** Reading the plan's Step 1 comment ("Sanity: with default matrix (viewer.export=True), viewer CAN export. (Skip this assertion if the test stack is slow; it's defensive.)")
- **Issue:** The plan made the sanity check optional. Without it, a regression that breaks the DEFAULT_ROLE_PERMISSIONS dict (e.g., dropping viewer.export accidentally) would cause the revoke step to be a no-op AND the post-revoke assertion to pass for the wrong reason.
- **Fix:** Kept the sanity check. The test stack is fast (4.17s for the full file); the extra GET adds <50ms and pins a meaningful pre-condition.
- **Files modified:** `backend/tests/test_export_hardening.py`

## Known Stubs

None. All assertions hit real code paths in `require_permission`, `get_effective_permissions`, the admin settings router, and the export router. The only mocked surface is `export_dataset` (the ogr2ogr-spawning service function), which is consistent with the existing test_export.py pattern.

## Threat Flags

None. This plan REDUCES the regression-risk surface (adds a pin around an existing security gate). No new network endpoints, auth paths, file access patterns, or schema changes.

## Deferred Issues

None. All plan acceptance criteria met inline.

## Followup

- KNOWN-05 ticks in REQUIREMENTS.md at v1016 milestone close (deferred per plan instructions — this executor was instructed NOT to update STATE.md/ROADMAP.md).
- v1015 Phase 1069 tech-debt followup item closes at v1016 milestone-close PROJECT.md update.

## Self-Check: PASSED

- `backend/tests/test_export_hardening.py` → FOUND (modified; contains `TestExportRevokedViewerParity`, `_VIEWER_EXPORT_REVOKED_MATRIX`, `mock_export_service_for_known05`, and `revoked` + `export` + `403` per regex contract)
- Commit `6ff24454` (test(export): pin 403-for-revoked-export-on-viewer parity (KNOWN-05)) → FOUND in `git log`
- `uv run pytest tests/test_export_hardening.py::TestExportRevokedViewerParity -v` → 2/2 PASS
- `uv run pytest tests/test_export_hardening.py -v` → 11/11 PASS (no regression in pre-existing tests)
- All plan acceptance criteria (must_haves.truths + artifacts.contains + key_links.pattern) met.
