# Phase 216 / Plan 04 — Publish Command Decisions

Investigated by Plan 04 Task 0 spike on 2026-04-27. The Task 1/2 implementations below use these decisions verbatim — no further guessing.

---

## Q1 — Dataset URL strategy

**Strategy: (b) — follow-up GET resolves `job_id → dataset_id`, with an `--no-wait` fallback to (c).**

`CommitResponse` exposes only three fields:
- Cited: `sdks/python/geolens_sdk/models/commit_response.py:25-27` — `job_id: UUID`, `message: str`, `status: str`
- The wire body actually emitted by the backend matches verbatim:
  Cited: `backend/app/processing/ingest/router.py:643-647` — `return CommitResponse(job_id=job.id, status="pending", message="Import queued")`

Commit therefore returns `status="pending"` synchronously and the dataset row does not yet exist — strategy (a) is impossible.

The SDK ships `get_job_status_jobs_job_id_get` (`GET /jobs/{job_id}`). Its response model exposes a `dataset_id` once the job lands:
- Cited: `sdks/python/geolens_sdk/models/job_status_response.py:35` — `dataset_id: None | UUID`
- Cited: `sdks/python/geolens_sdk/models/job_status_response.py:40` — `status: JobStatusResponseStatus`

**Implementation:**
- `--wait` (default) — poll `get_job_status_jobs_job_id_get.sync_detailed(job_id=...)` every ~1s until `status` is `completed` (success), `failed` (error → exit 1), or a watchdog timeout fires (default 120s → emit fallback URL with note). On success, construct `f"{instance}/datasets/{dataset_id}"`.
- `--no-wait` — skip the poll entirely; emit the fallback URL `f"{instance}/datasets?job_id={job_id}"` (which the GeoLens UI's record list can filter on; failing that, the user has the job_id and can resolve manually).
- Fallback inside `--wait` (timeout / unexpected status) — emit the fallback URL plus an `info` line: `Dataset will be available once ingestion completes — see job <id>`.

**Why poll the SDK's `/jobs/{job_id}` endpoint and not `/ingest/jobs/{job_id}`:** Backend routes register the job-status endpoint at `/jobs/{job_id}` (under the platform jobs router; see `backend/app/platform/jobs/router.py`). The SDK function lives in `api/admin/get_job_status_jobs_job_id_get.py`, but the URL is the generic `/jobs/{job_id}` path. (The "admin" subdir is the SDK generator's grouping by tag, not a permission requirement; the backend dependency on this route is `require_permission("upload")`-equivalent or owner-scoped.)

---

## Q2 — `tags` field on CommitRequest

**Present: NO. `--tags` is DEFERRED with a TODO + verbose-mode log.**

Cited: `sdks/python/geolens_sdk/models/commit_request.py:62-75` — the full attribute list is:
```
title: str
compression: None | str | Unset = UNSET
geom_column: None | str | Unset = UNSET
layer_name: None | str | Unset = UNSET
nodata_override: float | None | str | Unset = UNSET
resampling: None | str | Unset = UNSET
srid_override: int | None | Unset = UNSET
summary: None | str | Unset = UNSET
temporal_end: datetime.datetime | None | Unset = UNSET
temporal_start: datetime.datetime | None | Unset = UNSET
token: None | str | Unset = UNSET
visibility: CommitRequestVisibility | Unset = "private"
x_column: None | str | Unset = UNSET
y_column: None | str | Unset = UNSET
```

No `tags` and no `keywords` field. Plan 04 implementation:
- `--tags a,b,c` flag is **accepted** by the publish command (so users get a clear error path rather than a Typer "no such option") but its value is **not wired through** to the commit body.
- When `--tags` is passed, the publish command emits a `state.output.debug(...)` (`-v` only) line: `tags deferred — CommitRequest does not expose a tags field; see Phase 216 Open Question 4`.
- A `# TODO(OCCLI-deferred): tags requires post-commit PATCH/keywords endpoint; see Phase 216 Open Question 4` comment is left in `publish.py`.
- `docs/cli.md` (Plan 06) will document `--tags` as currently a no-op pending a backend keywords surface. Captured for follow-up phase.

**Description → `summary` mapping:** the plan's `--description` flag maps to CommitRequest's `summary` attribute (no `description` field exists on the model). Cited: `commit_request.py:51, 69`.

---

## Q3 — Duplicate-commit conflict status

**Backend returns 400 (NOT 409) with `detail="Job already processed"`.**

Cited: `backend/app/processing/ingest/router.py:593-597`:
```python
if job.status != "pending":
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Job already processed",
    )
```

The plan's body and Pitfall 6 both say "409"; the actual code path is **400**. Both 400 and 409 are documented in the SDK's commit `_parse_response` (`commit_import_ingest_commit_job_id_post.py:47-70`), so the SDK happily parses either as `ProblemDetail`.

**CLI handling — defensive on both 400 and 409 by detail text:**
- `handle_commit_already_processed(job_id, output)` is invoked when:
  - status_code is 400 OR 409, AND
  - parsed body is `ProblemDetail` whose `detail` string contains `"already processed"` (case-insensitive)
- Print: `Job <id> was already committed (resume not supported in MVP)`
- Exit: `EXIT_GENERIC` (1)

This allows the backend to migrate from 400 → 409 (a more semantically correct status) in a future phase without requiring a CLI change. If neither 400 nor 409 with the matching text is observed but commit still fails, the standard `unwrap()` path renders the ProblemDetail.detail and exits 1.

**Constants added to `cli/geolens_cli/publish.py`:**
- `COMMIT_DUPLICATE_STATUSES = (400, 409)`
- `_DUPLICATE_DETAIL_NEEDLE = "already processed"`

---

## Q4 — Wire status codes for the 3-step flow

**Upload: 201; Preview: 200; Commit: 202 (success path).**

- Upload: Cited `sdks/python/geolens_sdk/api/datasets/upload_file_ingest_upload_post.py:35` — `if response.status_code == 201: ... return UploadResponse`. Backend: `backend/app/processing/ingest/router.py:357` — `status_code=status.HTTP_201_CREATED`.
- Preview: Cited `sdks/python/geolens_sdk/api/datasets/preview_file_ingest_preview_job_id_post.py:49` — `if response.status_code == 200: ... PreviewResponse | RasterPreviewResponse`.
- Commit: Cited `sdks/python/geolens_sdk/api/datasets/commit_import_ingest_commit_job_id_post.py:42` — `if response.status_code == 202: ... CommitResponse`. Backend: `backend/app/processing/ingest/router.py:578` — `status_code=status.HTTP_202_ACCEPTED`.

**Constants in `cli/geolens_cli/publish.py`:**
- `UPLOAD_OK_STATUS = 201`
- `PREVIEW_OK_STATUS = 200`
- `COMMIT_OK_STATUS = 202`
- `JOB_STATUS_OK_STATUS = 200`  (the dataset-id resolution poll)

---

## Q5 (auxiliary) — `--collection` follow-up endpoint

The plan's CONTEXT D-24 mentions `--collection ID` adding the dataset to a collection after commit. Investigated:
- `sdks/python/geolens_sdk/api/` has NO `collections/` subdirectory; the SDK does not expose a "collections" tag.
- A `records/` API does exist, but no obvious "add dataset to collection" endpoint surfaces in the function list.

**Decision: `--collection` is accepted and DEFERRED with a TODO**, mirroring Q2's `--tags` pattern:
- `# TODO(OCCLI-deferred): collection-add endpoint not in SDK; see Phase 216 Open Question`
- A `state.output.debug(...)` line is emitted when `--collection` is passed.
- This matches CONTEXT.md's "Deferred Ideas" — "Collection management — partially covered by `--collection` flag on publish. Standalone collection commands deferred."

---

## Q6 (auxiliary) — Sync ASGI transport for round-trip

**Out of scope for Plan 04** — captured for Plan 06 round-trip work. Plan 04's tests use `CliRunner` with monkeypatched SDK functions (no actual ASGI transport), so this question is irrelevant to the unit slice the plan ships.

---

## Q7 (auxiliary) — `whoami` interaction

**Not applicable.** The publish command does not call `whoami`; it consumes `state.sdk()` directly (Plan 02 surface). Authentication failures surface through the `unwrap()` 401 → EXIT_AUTH path.

---

## Summary of constants and helpers added in Plan 04

| Symbol | Value | Source |
| ------ | ----- | ------ |
| `UPLOAD_OK_STATUS` | 201 | upload_file_ingest_upload_post.py:35 |
| `PREVIEW_OK_STATUS` | 200 | preview_file_ingest_preview_job_id_post.py:49 |
| `COMMIT_OK_STATUS` | 202 | commit_import_ingest_commit_job_id_post.py:42 |
| `JOB_STATUS_OK_STATUS` | 200 | get_job_status_jobs_job_id_get.py:33 |
| `COMMIT_DUPLICATE_STATUSES` | (400, 409) | router.py:593-597 + SDK accepts both |
| `_DUPLICATE_DETAIL_NEEDLE` | `"already processed"` | router.py:596 |
| `_MIME_BY_EXT` | per RESEARCH Pattern 3 | RESEARCH.md:317-325 |
| `_DEFAULT_POLL_INTERVAL_SECONDS` | 1.0 | Claude judgment (snappy enough; configurable later) |
| `_DEFAULT_POLL_TIMEOUT_SECONDS` | 120 | Claude judgment (matches "preview + commit are quick" in D-20) |

These are imported by the publish command (`cli/geolens_cli/main.py`) and by the unit tests (`cli/tests/test_publish_unit.py`).
