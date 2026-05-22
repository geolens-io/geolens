# Phase 1082: Test Environmental - Context

**Gathered:** 2026-05-21
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

Disposition the `ogrinfo` CLI environmental dependency in `backend/tests/test_reupload_idor.py::test_owner_gets_non_404_on_service_preview`. The test currently fails on hosts where `ogrinfo` is not on the PATH because the production code path probes the source via a live `ogrinfo` subprocess. Decision must be documented in the test docstring; no silent environmental failure in CI.

Closes TD-04 from the v1017 milestone audit.

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — discuss phase skipped per `workflow.skip_discuss=true`. Two viable shapes per ROADMAP success criteria:

  (a) **Skip-with-rationale:** guard the test with `pytest.skip(reason="...")` after a `shutil.which("ogrinfo")` probe (or `pytest.importorskip` if appropriate). The reason must link to env-doc explaining when this env is set up (e.g., dev container with GDAL CLI, CI image with `gdal-bin`).
  (b) **Mock-out:** replace the live `ogrinfo` subprocess call with a mock so the test does not depend on host tooling.

The plan should pick ONE based on what the test is actually trying to pin — if the test is exercising an integration with `ogrinfo`'s output parsing, mocking risks false-green (the mock returns whatever the test expects); if the test is exercising authorization/IDOR behavior (which the file name suggests), mocking is safer because the `ogrinfo` call is incidental.

### Required deliverables (from ROADMAP success criteria)
1. The test has a documented disposition: skip-with-rationale OR mock-out.
2. The decision is documented in the test's docstring (one sentence minimum).
3. The test never silently passes on a host lacking `ogrinfo` (no false green) and never fails with an unguided `FileNotFoundError` / `subprocess.CalledProcessError` on a stock CI image.

</decisions>

<code_context>
## Existing Code Insights

- **File**: `backend/tests/test_reupload_idor.py::test_owner_gets_non_404_on_service_preview` — file name (`_idor`) suggests the test pins IDOR/authorization invariants, not GDAL/ogrinfo behavior. This points toward shape (b) mock-out.
- **Production call site**: the `ogrinfo` call originates from somewhere in `backend/app/modules/catalog/sources/` (where the preview / source-probe logic lives). Search for `ogrinfo` in `backend/app/` to find the actual subprocess invocation.
- **Existing mock pattern**: `backend/tests/test_reupload_service.py` (Plan 1081-02) just added `patch("app.modules.catalog.sources.security.validate_url_for_ssrf", ...)`. Mirror that style for any new mocks.
- **CI status**: per v1017 audit, this is environmental on the host (developer Mac without `gdal-bin`); CI may already pass. Confirm by reading the failure log in `.planning/audits/PYTEST-BASELINE-2026-05-21.md` NEW-DISCOVERY row 4.

</code_context>

<specifics>
## Specific Ideas

- Strongly prefer shape (b) mock-out unless reading the test reveals it's specifically exercising `ogrinfo` output parsing. The test file name `test_reupload_idor.py` is a strong signal that the test cares about IDOR/auth, not GDAL.
- If mock-out is chosen: stub the lowest-level subprocess wrapper (e.g., `subprocess.run` or whichever `ogrinfo` helper the source-probe module uses). Return a canned dict shape (driver/layer/CRS) matching what a real `ogrinfo` invocation returns for the test's input URL.
- If skip-with-rationale is chosen: use `shutil.which("ogrinfo")` probe + `pytest.skip(f"ogrinfo not on PATH — see <env-doc link or .env.example comment>")`. Document the env in `AGENTS.md` or `backend/README.md` if not already.

</specifics>

<deferred>
## Deferred Ideas

None — discuss phase skipped. Phase 1083 (close gate) handles the baseline capture + tag cut.

</deferred>
