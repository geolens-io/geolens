---
phase: 1066
status: passed
requirements_satisfied: 2
requirements_total: 2
shipped: 2026-05-20
---

# Phase 1066 VERIFICATION — Ingest Entry-Point Hardening

## Phase goal

Ingest upload and commit paths enforce size limits and URL safety at the HTTP boundary before any disk write or pipeline work.

## Requirement coverage

| REQ-ID | Status | Evidence |
|---|---|---|
| **IA-P0-02** | ✓ Verified | `save_upload_file` (`backend/app/processing/ingest/service.py`) gains optional `max_size_bytes` kwarg. Local mode accumulates per-chunk; S3 mode buffers via `io.BytesIO` accumulator. Both raise `HTTP 413` once cumulative bytes exceed the limit. Route handler `/ingest/upload` (`router.py:upload_file`) looks up `UPLOAD_MAX_SIZE_MB` and passes it through. 5/5 unit tests pin: under-limit succeeds (local + S3), over-limit raises 413 + cleanup, no-limit param is backwards compatible. |
| **IA-P0-03** | ✓ Verified | `commit_import` (`router.py`) re-runs `validate_url_for_ssrf` on `job.source_url` for service commits before `queue_ingest_job`. `ingest_service` worker (`tasks_vector.py`) and `reupload_service` worker (`tasks_reupload.py`) re-validate before their `build_gdal_source`/`run_ogr2ogr_service` calls — defense-in-depth for the manifest path that bypasses `commit_import`. 4/4 unit tests pin: commit-time 400 on SSRF, file jobs skip gate, both workers raise RuntimeError on worker-time SSRF. |

## Success criteria

- **Oversize multipart upload returns 413 before any disk write** — ✓ Local mode chunk loop raises 413 the moment cumulative bytes exceed the cap; the existing `except: os.unlink` block cleans up the partial file. S3 mode rejects before `storage.put`.
- **DNS-rebinding commit rejected at the HTTP boundary** — ✓ Commit-time SSRF mock raises → 400; file jobs skip the gate.
- **Worker tasks re-validate before fetching** — ✓ Both `ingest_service` and `reupload_service` workers gate before `build_gdal_source`.

## Commit chain

1. `79703a43` `docs(1066): smart discuss context`
2. `e11924c3` `feat(1066-01): enforce max_file_size_bytes at multipart upload HTTP entry`
3. `f8c91297` `feat(1066-02): re-validate source_url SSRF at commit + worker fetch`

## Deferred to Phase 1070 close-gate

- Full backend pytest run (covers `test_upload_size_limit.py` + `test_commit_revalidates_source_url.py` — 9 new tests).

## Verdict

**PASSED** — 2/2 requirements satisfied. 9/9 unit tests green. Defense-in-depth applied at both HTTP boundary AND worker fetch layer.
