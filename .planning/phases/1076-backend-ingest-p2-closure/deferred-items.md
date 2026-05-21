# Phase 1076 - Deferred Items

Environmental issues observed during Plan 1076-04 execution. All are **pre-existing on `main` before any 1076-04 changes** — verified by stashing the working tree and running the same test selections against HEAD. None are caused by ING-06 / `_apply_reupload_swap` retry behavior.

## ENV-01 — `ogrinfo` binary missing on this dev machine

- **Where:** `tests/test_reupload_idor.py::TestReuploadIDOROwnerAllowed::test_owner_gets_non_404_on_service_preview`
- **Symptom:** `FileNotFoundError: [Errno 2] No such file or directory: 'ogrinfo'`
- **Pre-existing:** Yes — confirmed via `git stash` + rerun against `HEAD` (the RED-test commit prior to implementation). The test invokes the service-preview path which shells out to `ogrinfo`. Not on PATH for this devbox.
- **Disposition:** Defer — install GDAL CLI tools or mark `requires_ogr2ogr` and skip when unavailable. Out of scope for ING-06.

## ENV-02 — Service-reupload worker tests need DNS for `services.example.com`

- **Where:**
  - `tests/test_reupload_service.py::TestServiceReuploadWorker::test_reupload_service_preserves_identity_and_increments_version`
  - `tests/test_reupload_service.py::TestServiceReuploadWorker::test_reupload_service_without_token_returns_retry_guidance_on_auth_failure`
- **Symptom:** `RuntimeError: source_url failed safety check at worker fetch time: Could not resolve hostname: services.example.com`
- **Pre-existing:** Yes — `_validate_url_for_ssrf` calls `socket.getaddrinfo` on the configured `source_url`. The sandbox/test environment has no DNS for `services.example.com`, so the SSRF pre-flight raises. Reproduces on stashed pre-fix tree.
- **Disposition:** Defer — these worker tests should either mock `_validate_url_for_ssrf` (matching the v1015 pattern) or use a hostname guaranteed to resolve in test environments. Out of scope for ING-06.

## ENV-03 — `test_job_phase_session_none_branch_rolls_back_on_exception` event-loop mismatch

- **Where:** `tests/test_tasks_common_phase_brackets.py::test_job_phase_session_none_branch_rolls_back_on_exception`
- **Symptom:** `RuntimeError: Task <...> got Future <...> attached to a different loop` (pytest-asyncio loop boundary)
- **Pre-existing:** Yes — reproduces on the pre-fix tree. This is a pytest-asyncio fixture-scope quirk unrelated to lock-timeout work.
- **Disposition:** Defer — separate hygiene plan for pytest-asyncio loop scoping. Out of scope for ING-06.

---

**Within-scope regression check passed:** `pytest tests/test_reupload.py tests/test_reupload_idor.py tests/test_reupload_record_type_guard.py tests/test_reupload_swap_lock_retry.py --deselect ...IDOROwnerAllowed::test_owner_gets_non_404_on_service_preview` → **48 passed, 1 deselected** as of 2026-05-21.
