# Phase 1066: Ingest Entry-Point Hardening - Context

**Gathered:** 2026-05-20
**Status:** Ready for planning
**Mode:** Auto-generated (autonomous mode — file paths confirmed)

<domain>
## Phase Boundary

Two ship-blocking ingest entry-point defects:

1. **IA-P0-02** — `/ingest/upload` accepts files larger than `max_file_size_bytes` because the HTTP entry point doesn't enforce the limit. The check happens later in the worker, but by then staging disk is already consumed. Symmetric with the presigned path (`router.py:154-165`) which already validates upfront.
2. **IA-P0-03** — `commit_import` doesn't re-validate `job.source_url` for SSRF after preview. DNS rebinding between preview (job creation) and commit (60s default TTL) lets an attacker resolve a public address at preview and a private one at commit. The `_revalidate_redirect` event hook (v1014 SEC-S04) already defends per-hop redirect chains, but the pre-fetch URL check at commit time is missing.

Out of phase: worker heartbeat (1067), subprocess env / VRT (1068), export (1069), hygiene (1070).

</domain>

<decisions>
## Implementation Decisions

### IA-P0-02 — Chunked Size Check in `save_upload_file`

- **Signature change:** `save_upload_file(file, job_id, max_size_bytes: int | None = None)` — keyword-only optional kwarg avoids breaking ad-hoc callers (none exist in production today; this is forward-compat).
- **Caller update:** the route handler at `router.py:394` looks up `max_size_bytes` from `UPLOAD_MAX_SIZE_MB.get(db) * 1024 * 1024` (mirroring the presigned path at `:159-160`) and passes it through.
- **S3 path:** also enforce — currently `await storage.put(s3_key, file.file)` streams in one shot. For S3 mode, read in chunks and accumulate size; abort + raise 413 if exceeded. Don't rely on S3 reject — the goal is to fail fast before any disk/network spend.
- **Local path:** add `total += len(chunk); if total > max_size_bytes: raise HTTPException(413)`. Re-uses existing 64 KiB chunk reads. On exceed, the partial file is already cleaned up via the existing `except: os.unlink(dest)` block.
- **Error shape:** `HTTPException(413, detail=f"File size exceeds maximum allowed ({max_mb} MB).")` — matches the presigned 422 message style.
- **Status code choice:** **413 (Payload Too Large)** is the right code per RFC 7231; the presigned path uses 422 which is technically a Pydantic-style choice (the request schema validates `file_size`). For chunked multipart, 413 is more semantically correct and matches reverse-proxy responses (nginx `client_max_body_size`). Document the deliberate asymmetry in the test.
- **Test:** `test_upload_size_limit.py` — upload a fake stream that streams beyond the limit; assert 413 + no file in staging dir + no `IngestJob` row created (the job is created before `save_upload_file` runs in the current handler — see `router.py:380-395` for ordering; the test asserts the partial-cleanup contract, not row-absence).

### IA-P0-03 — Re-Validate `source_url` at Commit + Worker

- **`commit_import` (route at router.py:609):** Add a re-validation block for service commits before `queue_ingest_job`. Pattern:
  ```python
  if isinstance(commit, ServiceCommitRequest) and job.source_url:
      try:
          await validate_url_for_ssrf(job.source_url)
      except SSRFError as exc:
          raise HTTPException(400, detail=f"source_url failed safety check: {exc}")
  ```
- **`ingest_service` worker (tasks_vector.py:362):** Add a defense-in-depth call BEFORE `build_gdal_source(...)`. Manifest-path jobs bypass `commit_import` entirely, so the worker is the only chokepoint. Pattern:
  ```python
  # IA-P0-03 defense-in-depth: re-validate at fetch time for the manifest path
  # which bypasses commit_import.
  try:
      await validate_url_for_ssrf(source_url)
  except SSRFError as exc:
      raise RuntimeError(f"source_url failed safety check at fetch time: {exc}")
  ```
- **`reupload_service` worker (tasks_reupload.py:323):** Same defense-in-depth — service reuploads also fetch a URL the worker re-resolves.
- **TOCTOU windowing:** Even with re-validation, there's a residual TOCTOU between `validate_url_for_ssrf` and the GDAL/ogr2ogr fetch. The `_revalidate_redirect` event hook (v1014 SEC-S04) closes the redirect-chain TOCTOU; what we're closing here is the preview→commit TOCTOU on the FIRST hop. Cite v1014's pattern in the docstring.
- **Tests:**
  - `test_commit_revalidates_source_url.py` — mock `validate_url_for_ssrf` to raise on the second call; assert `commit_import` returns 400 even when preview succeeded. Use `unittest.mock.patch` on the function directly (it's imported at module scope in router.py).
  - For the worker, a unit test on `ingest_service` is heavy (Procrastinate task wrapper). Acceptable alternative: a smaller `test_ingest_service_revalidates.py` that calls the un-wrapped function with mocked DB session + SSRF validator side-effect.

### Claude's Discretion

- Exact import structure (whether to put `validate_url_for_ssrf` at module-level import or function-scope) — the security module is small enough that module-level is fine, but follow whatever convention exists in tasks_vector.py.
- Whether to emit an audit event on commit-time SSRF rejection. Probably yes (mirror v1014's audit emissions for security gates).

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets

- `backend/app/modules/catalog/sources/security.py:33` — `validate_url_for_ssrf` async function. Raises `SSRFError`. Already imported at preview sites.
- `backend/app/processing/ingest/service.py:115` — `save_upload_file` async function. Two branches (S3, local) — both need size enforcement.
- `backend/app/processing/ingest/schemas.py:422` — `UploadConfigResponse.max_file_size_bytes` exposes the limit to the frontend.
- `backend/app/processing/ingest/router.py:159-165` — presigned path's reference `max_size_bytes` enforcement (returns 422 — we use 413 for multipart per RFC).
- `app.modules.catalog.sources.security.SSRFError` — exception type.
- v1014 SEC-S04 pattern (`make_safe_client()` + `_revalidate_redirect`) — established SSRF defense pattern; cite in docstrings.

### Established Patterns

- **HTTPException shape:** existing `router.py` uses `status.HTTP_4XX_*` constants + `detail=` strings; match exactly.
- **Partial-file cleanup:** existing `except: os.unlink(dest)` pattern in `save_upload_file` — extend to cover the size-exceeded path.
- **Async session usage in workers:** `async_session()` context manager pattern from `tasks_vector.py:401`.
- **Service commit discrimination:** `ServiceCommitRequest` subclass + `_pick_commit_subclass` in `router.py:584`.

### Integration Points

- New `max_size_bytes` parameter flows: `router.py` → `save_upload_file` → chunk-read loop.
- New SSRF re-validation flows: `commit_import` route + `ingest_service` / `reupload_service` workers.
- No OpenAPI snapshot regeneration needed — these are internal hardening changes, no new endpoints.

</code_context>

<specifics>
## Specific Ideas

- **Don't refactor `save_upload_file` into helpers** — keeping the two branches (S3 vs local) inline with size accumulation is the smallest readable diff. The function is 50 lines and stays under 100 after the change.
- **413 vs 422 status code** — go with 413 for multipart (it's a streaming upload reaching a transport-level limit) and document the asymmetry with presigned (422) in a docstring comment.

</specifics>

<deferred>
## Deferred Ideas

- Streaming pre-flight HEAD on `source_url` to estimate response size before fetch — speculative, out of audit scope.
- Allow-list/deny-list for `source_url` hosts — separate phase if needed; SSRF validator already covers private IPs.
- Move SSRF validation into a FastAPI dependency — refactor scope, not security scope.

</deferred>
