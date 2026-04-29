---
phase: 216-geolens-cli-mvp
plan: 04
subsystem: cli
tags: [cli, publish, ingest, multipart, occli-04, occli-06, wave-3, tdd]
dependency_graph:
  requires:
    - cli/geolens_cli (Plans 01-03 — main.py, AppState.sdk(), Formatter, _sdk_helpers)
    - sdks/python/geolens_sdk (Phase 215 — datasets/upload/preview/commit + admin/jobs)
    - rich >=14 (rich.progress.Progress + SpinnerColumn + TextColumn — already in manifest)
  provides:
    - geolens_cli.publish — guess_mime, upload_file, build_commit_request,
      construct_dataset_url, resolve_dataset_id, is_duplicate_commit_response,
      handle_commit_already_processed, status-code constants
    - working `geolens publish <file>` command with --name, --description,
      --tags (deferred no-op), --collection (deferred no-op), --wait/--no-wait
    - cli/tests/test_publish_unit.py — 30 unit tests
    - .planning/phases/216-geolens-cli-mvp/216-04-DECISION-LOG.md — Task 0 spike
  affects:
    - Plan 05 (export stac) — the only remaining stub command after 04
    - Plan 06 (round-trip + CI + docs) — round-trip will exercise the publish
      flow end-to-end against in-process ASGI; docs/cli.md publish section
      lands here; OCCLI-06 grep gate inherits the publish.py + main.py
      invariant proof from this plan
tech-stack:
  added: []
  patterns:
    - "Multipart upload via SDK-owned httpx client (RESEARCH Pattern 3) —
      bypasses broken to_multipart() while keeping OCCLI-06 invariant"
    - "Defensive duplicate-commit detection on 400 OR 409 by detail-text
      match (Pitfall 6 + DECISION-LOG Q3 — backend currently uses 400)"
    - "Job-status polling for job_id → dataset_id resolution
      (DECISION-LOG Q1 strategy b)"
    - "Deferred-flag pattern — accept --tags/--collection but no-op with
      verbose debug log + TODO comment (DECISION-LOG Q2 + Q5)"
    - "Progress UI auto-suppression via rich.Progress(disable=json|not_tty)"
    - "Lazy SDK + rich imports inside command body to keep `--help` snappy"
key-files:
  created:
    - cli/geolens_cli/publish.py
    - cli/tests/test_publish_unit.py
    - .planning/phases/216-geolens-cli-mvp/216-04-DECISION-LOG.md
    - .planning/phases/216-geolens-cli-mvp/216-04-SUMMARY.md
  modified:
    - cli/geolens_cli/main.py
    - cli/tests/test_exit_codes.py
key-decisions:
  - "Q1 dataset URL: strategy (b) — CommitResponse exposes only {job_id, message, status},
    so resolve_dataset_id polls GET /jobs/{job_id} (SDK ships the binder). With
    --wait (default) the URL becomes /datasets/<dataset_id>; with --no-wait or
    on poll-timeout, falls back to /datasets?job_id=<id>"
  - "Q2 --tags: deferred. CommitRequest has no tags field (only title, summary,
    visibility, etc.). Flag accepted, value dropped with verbose debug log + TODO"
  - "Q3 duplicate-commit: backend returns 400 (NOT 409) with detail
    'Job already processed'. CLI handles 400 OR 409 with the matching detail
    needle so future backend migration to 409 doesn't require a CLI change"
  - "Q4 status codes: upload=201, preview=200, commit=202, job_status=200.
    Pinned as module-level constants in publish.py"
  - "Q5 (auxiliary) --collection: deferred. SDK has no collections/ subdir;
    no add-to-collection endpoint surfaced. Flag accepted, no-op with debug log"
  - "Description→summary mapping: --description maps to CommitRequest.summary
    (the actual field name); CommitRequest has no 'description' field"
  - "publish stub test removed from test_exit_codes.py per the same handoff
    pattern Plans 02-03 followed; per-command behavior lives in
    test_publish_unit.py::TestPublishCli"
requirements-completed:
  - OCCLI-04
metrics:
  duration_seconds: 407
  duration_human: "6m 47s"
  completed_date: "2026-04-27"
  tasks_completed: 3
  tests_passing: 92
  tests_added: 30
  files_created: 4
  files_modified: 2
---

# Phase 216 Plan 04: publish-command Summary

**Closes OCCLI-04** — `geolens publish <file>` runs the 3-step ingest flow
(upload → preview → commit) via the SDK, with the documented multipart
workaround for the broken `to_multipart()` generator quirk, optional
metadata flags, rich.Progress UI that auto-degrades on non-TTY, defensive
duplicate-commit handling, and a `--wait` job-status poll that resolves
the dataset URL bound by ROADMAP SC#4.

## Performance

- **Duration:** ~6 min 47 s
- **Started:** 2026-04-27T22:16:15Z
- **Completed:** 2026-04-27 (same session)
- **Tasks:** 3/3 (Task 0 spike + Task 1 TDD + Task 2 TDD)
- **Files created:** 4 (publish.py, test_publish_unit.py, DECISION-LOG.md, this SUMMARY.md)
- **Files modified:** 2 (main.py, test_exit_codes.py)

## Accomplishments

- 3-step ingest flow wired end-to-end with mocked SDK (30 unit tests).
- Multipart upload workaround per RESEARCH Pattern 3 — uses
  `client.get_httpx_client()` (SDK-owned) rather than constructing an
  httpx.Client directly. OCCLI-06 invariant verified.
- `--wait` polling resolves `job_id → dataset_id` via the SDK's
  `get_job_status_jobs_job_id_get` binder; on success the published URL
  is the canonical `/datasets/<dataset_id>`. `--no-wait` falls back to
  the job-search URL form so users can return immediately.
- Defensive duplicate-commit detection: matches both 400 (current
  backend behavior) and 409 (forward-compatible) with the
  "already processed" detail needle.
- Progress UI auto-suppressed when stdout is not a TTY OR `--json` is
  set; CLI runner output stays free of spinner frames.
- `--tags` and `--collection` accepted as flags but no-op with
  verbose-mode `debug` log (DECISION-LOG Q2 + Q5 deferrals); `# TODO(OCCLI-deferred)`
  markers in `main.py` capture the follow-up work.

## Task 0 Spike Findings (DECISION-LOG.md)

| Question | Resolution | Citation |
| -------- | ---------- | -------- |
| **Q1 — Dataset URL** | Strategy (b): `CommitResponse` has only `{job_id, message, status}`; resolve via `GET /jobs/{job_id}` poll which exposes `dataset_id: None \| UUID`. Fallback to `/datasets?job_id=<id>` on `--no-wait` / timeout. | `commit_response.py:25-27`; `job_status_response.py:35`; `router.py:643-647` |
| **Q2 — `tags` field** | NOT present on `CommitRequest`. `--tags` accepted but no-op with debug log + TODO. | `commit_request.py:62-75` |
| **Q3 — Duplicate status** | Backend returns **400** (not 409) with `detail="Job already processed"`. CLI handles both 400 and 409 defensively. | `router.py:593-597` |
| **Q4 — Status codes** | Upload=201, Preview=200, Commit=202, JobStatus=200. | `upload_file_*.py:35`; `preview_*.py:49`; `commit_*.py:42`; `get_job_status_*.py:33` |
| **Q5 — `--collection`** | No `collections/` API in SDK; flag deferred (no-op with debug log + TODO). | `sdks/python/geolens_sdk/api/` — no collections subdir |

The `--description` flag maps to `CommitRequest.summary` (the actual
field name); CommitRequest has no `description` attribute.

The dataset URL strategy (b) — polling `/jobs/{job_id}` — is the only
viable path because the commit endpoint returns synchronously while
ingestion runs asynchronously. The job's `dataset_id` materializes only
after the worker creates the dataset row. With `--wait`, the CLI polls
every 1 s up to a 120 s watchdog; on timeout it surfaces the fallback
URL and keeps exit code 0 (the user can resolve later).

## What Shipped

### `cli/geolens_cli/publish.py` (NEW, ~278 lines)

**Module docstring** explicitly states the OCCLI-06 policy and references
both Pitfall 1 (broken `to_multipart`) and Pitfall 6 (commit not
idempotent). The dependency on `client.get_httpx_client()` (the SDK's
public surface) is called out as the structural enforcement point.

| Symbol | Purpose |
| ------ | ------- |
| `UPLOAD_OK_STATUS = 201` | Upload success status (Task 0 Q4) |
| `PREVIEW_OK_STATUS = 200` | Preview success status |
| `COMMIT_OK_STATUS = 202` | Commit success status |
| `JOB_STATUS_OK_STATUS = 200` | Job-status poll success status |
| `COMMIT_DUPLICATE_STATUSES = (400, 409)` | Defensive duplicate-commit detection |
| `_DUPLICATE_DETAIL_NEEDLE = "already processed"` | Detail-text match |
| `_DEFAULT_POLL_INTERVAL_SECONDS = 1.0` | Job-status poll cadence |
| `_DEFAULT_POLL_TIMEOUT_SECONDS = 120.0` | Watchdog before fallback URL |
| `_MIME_BY_EXT` | 7-entry MIME map per RESEARCH Pattern 3 |
| `guess_mime(path)` | Returns MIME for spatial file (or octet-stream) |
| `upload_file(client, path)` | Multipart workaround using SDK httpx client |
| `build_commit_request(*, title, description)` | Wraps `CommitRequest` with description→summary |
| `construct_dataset_url(instance, *, dataset_id, job_id)` | Canonical or fallback URL |
| `resolve_dataset_id(client, job_id, *, interval, timeout, sleep, monotonic)` | Polls GET /jobs/{job_id} |
| `is_duplicate_commit_response(resp)` | Status + detail-text duplicate detection |
| `handle_commit_already_processed(job_id, output)` | Pitfall 6 print + Exit(1) |

`resolve_dataset_id` exposes `sleep` and `monotonic` as injectable params
so unit tests run in zero real time. The function returns `None` on:
- non-200 status (auth error, server error, 404)
- ProblemDetail body
- terminal `status="failed"`
- watchdog timeout

…all of which trigger the fallback URL path in the caller.

### `cli/geolens_cli/main.py` (MODIFIED — publish stub replaced)

`@app.command() publish(...)`:
- File argument validated via Typer's `exists=True, dir_okay=False, readable=True`.
- Active-instance check returns `EXIT_AUTH` when no instance configured.
- Lazy imports for `_publish`, rich.Progress, and the SDK API modules
  (preview, commit) — keeps `geolens --help` snappy per Pitfall 9 / lazy-import discipline.
- Progress disabled when `state.json_mode` OR `not state.output.is_tty`.
- 4 stages emitted: Uploading → Previewing → Committing → Resolving dataset.
- Duplicate-commit handler invoked via `_publish.is_duplicate_commit_response(commit_resp)`.
- `--wait` (default) calls `_publish.resolve_dataset_id`; `--no-wait` skips.
- JSON mode emits `{dataset_url, job_id, dataset_id, status}`; text mode
  prints `Published: <url>` via `state.output.success()`.

### `cli/tests/test_publish_unit.py` (NEW, ~531 lines, 30 tests)

| Class | Tests | What it covers |
| ----- | ----- | -------------- |
| `TestGuessMime` | 9 | 7 known extensions + unknown fallback + no-extension |
| `TestConstructDatasetUrl` | 3 | dataset_id present, trailing-slash strip, no-id fallback |
| `TestBuildCommitRequest` | 3 | title-only, description→summary, summary stays UNSET |
| `TestHandleCommitAlreadyProcessed` | 1 | Exits EXIT_GENERIC + message contains job_id + "already committed" |
| `TestIsDuplicateCommitResponse` | 4 | 400 + matching, 409 + matching, 400 + unrelated detail, 202 |
| `TestUploadFile` | 1 | `client.get_httpx_client()` called; multipart payload includes name + MIME |
| `TestPublishCli` | 9 | no-instance, success, --no-wait, 409, 400-dup, non-TTY suppression, --json, name fallback, --name override |

### `cli/tests/test_exit_codes.py` (MODIFIED)

Removed `test_publish_stub_exits_2` per the Plan 02/03 handoff pattern.
Updated docstring to reflect that publish is now a real command (per-command
behavior asserted in `test_publish_unit.py::TestPublishCli`). Only
`test_export_stac_stub_exits_2` remains as a stub assertion until Plan 05.

## OCCLI-04 Closure Evidence

| Acceptance criterion | Evidence |
| -------------------- | -------- |
| 3-step ingest via SDK | `main.py publish` calls `_publish.upload_file` → `_preview.sync_detailed` → `_commit.sync_detailed` in sequence; verified by `test_publish_success_prints_dataset_url` |
| Dataset URL on success | `_publish.construct_dataset_url(instance, dataset_id=..., job_id=...)` produces `https://<instance>/datasets/<id>`; verified by `test_publish_success_prints_dataset_url` |
| Multipart workaround | `upload_file` uses `client.get_httpx_client().post(...)` with proper `files={...}` dict; verified by `TestUploadFile::test_upload_file_calls_sdk_get_httpx_client` |
| Duplicate-commit handling | `is_duplicate_commit_response` + `handle_commit_already_processed`; verified by `test_publish_409_exits_generic` AND `test_publish_400_already_processed_exits_generic` |
| Progress UI degrades on non-TTY | `Progress(..., disable=json_mode or not is_tty)`; verified by `test_progress_suppressed_non_tty` (no spinner frames in output) |
| Optional flags work | `--name`, `--description`, `--tags`, `--collection`, `--wait/--no-wait`; verified by `test_publish_uses_filename_stem_when_no_name`, `test_publish_name_overrides_title`, `test_publish_no_wait_emits_job_search_url` |

## OCCLI-06 Invariant Evidence

```bash
$ ! grep -rE '^(import|from) (httpx|requests)' cli/geolens_cli/
OCCLI-06 GLOBAL OK: zero direct httpx/requests imports across cli/geolens_cli/

$ ! grep -rE '^(import|from) httpx[^_]' cli/geolens_cli/publish.py cli/geolens_cli/main.py
OK: publish.py and main.py have no direct httpx imports

$ grep -E "client\.get_httpx_client" cli/geolens_cli/publish.py
``client.get_httpx_client()`` is the SDK's public surface for advanced
    OCCLI-06: ``client.get_httpx_client()`` is the SDK's public surface;
    httpx_client = client.get_httpx_client()
```

The httpx instance reaches `publish.py` exclusively via the SDK's public
`client.get_httpx_client()` accessor — no direct httpx dep, no
`httpx.Client(...)` construction. The Plan 06 CI grep gate will lock
this in across all of `cli/geolens_cli/` (the gate currently passes by
hand-verification at every plan boundary).

## Verification Evidence

| Check | Command | Result |
| ----- | ------- | ------ |
| Plan-04 unit slice | `cd cli && uv run --no-sync pytest tests/test_publish_unit.py -v` | 30/30 passed in 0.24s |
| Full unit suite | `cd cli && uv run --no-sync pytest -v` | 92/92 passed in 0.31s |
| Public surface smoke | `python -c "from geolens_cli.publish import guess_mime, upload_file, build_commit_request, construct_dataset_url, resolve_dataset_id, is_duplicate_commit_response, handle_commit_already_processed, ..."` | OK |
| OCCLI-06 grep gate (publish.py) | `! grep -rE '^(import\|from) httpx[^_]' cli/geolens_cli/publish.py` | no matches |
| OCCLI-06 grep gate (main.py) | `! grep -rE '^(import\|from) httpx[^_]' cli/geolens_cli/main.py` | no matches |
| OCCLI-06 grep gate (global) | `! grep -rE '^(import\|from) (httpx\|requests)' cli/geolens_cli/` | no matches |
| Decision-log artifacts | 4× `## Q[1-4]` headers + Q5 + Q6 + Q7 | OK |

## Public Interfaces Established for Plan 05+

```python
# Plan 05 (export stac) and Plan 06 (round-trip) may reuse:
from geolens_cli.publish import (
    guess_mime,                      # MIME map (potentially handy for export-by-mime)
    UPLOAD_OK_STATUS,                # Status code constants
    PREVIEW_OK_STATUS,
    COMMIT_OK_STATUS,
    JOB_STATUS_OK_STATUS,
)

# Plan 06's round-trip test will exercise the publish command
# end-to-end via CliRunner against the in-process ASGI app:
result = runner.invoke(app, ["publish", str(geojson_fixture)])
assert result.exit_code == 0
assert "/datasets/" in result.output
```

## Decisions Made

1. **Strategy (b) for the dataset URL.** `CommitResponse` is intentionally
   minimal (the worker hasn't created the dataset yet); polling
   `/jobs/{job_id}` is the documented resolution path. The `--no-wait`
   fallback URL keeps the user unblocked when ingestion is slow.
2. **Detect duplicate commits on 400 OR 409.** Backend currently uses 400
   ("Job already processed"), but the SDK parses both 400 and 409 as
   ProblemDetail. The `_DUPLICATE_DETAIL_NEEDLE` text match avoids false
   positives from validation 400s (e.g., bad CommitRequest body).
3. **`--tags` and `--collection` accepted but no-op.** Better UX than a
   "no such option" Typer error: users can paste a known recipe today
   and the flags become live in a future phase without breaking calls.
   Verbose-mode debug log + `# TODO(OCCLI-deferred)` markers ensure
   discoverability.
4. **`description` → `summary` mapping is silent.** `CommitRequest` has
   `summary`, not `description` — the planner anticipated the rename in
   Q2 of the spike. The CLI flag stays user-friendly; the SDK field
   alignment is invisible to users.
5. **`resolve_dataset_id` accepts injectable `sleep` + `monotonic`.**
   Future tests can run zero-real-time polls if they need to assert the
   loop semantics. Current tests skip this entirely by mocking the SDK
   function directly via `patch_sdk_for_publish`.
6. **publish stub test removed from `test_exit_codes.py`** rather than
   converted. Mirrors Plan 02 (login/logout/whoami stubs removed when
   real bodies landed) and Plan 03 (scan stub removed). The exit-code
   matrix file stays focused on testing matrix semantics, not per-command
   behavior; the latter lives in each command's dedicated test module.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Plan's pseudocode used `commit_response.dataset_id` for the URL — model has no such field**
- **Found during:** Task 0 spike (Q1)
- **Issue:** Plan 04's Task 1 pseudocode in the `<action>` block defaults to reading `dataset_id` from `commit_response`, with the fallback hint "if that field isn't present." The actual model exposes only `{job_id, message, status}` — strategy (a) is structurally impossible.
- **Fix:** Implemented strategy (b) — added `resolve_dataset_id(client, job_id, ...)` that polls `GET /jobs/{job_id}`. The `construct_dataset_url` signature changed from `(instance, commit_response, job_id)` to `(instance, *, dataset_id, job_id)` so the caller passes the resolved id directly. This is exactly the path Task 0 was budgeted to discover.
- **Files modified:** `cli/geolens_cli/publish.py`, `cli/geolens_cli/main.py`
- **Commits:** `8c9e6252` (Task 1 GREEN), `81118c05` (Task 2 GREEN)
- **Note:** This is the documented Open Question 1 outcome, not an unanticipated bug — the plan budgeted Task 0 specifically to resolve it. Logging here for traceability.

**2. [Rule 1 - Bug] Plan's Pitfall 6 message says 409 but backend returns 400**
- **Found during:** Task 0 spike (Q3)
- **Issue:** Plan body and Pitfall 6 both reference 409 for duplicate commits; actual code path in `backend/app/processing/ingest/router.py:593-597` raises HTTPException with `status_code=status.HTTP_400_BAD_REQUEST` and `detail="Job already processed"`.
- **Fix:** Implemented defensive detection on both 400 AND 409 with detail-text match (`is_duplicate_commit_response`). Two test cases (`test_publish_400_already_processed_exits_generic` and `test_publish_409_exits_generic`) cover both paths so a future backend migration to 409 doesn't require a CLI change.
- **Files modified:** `cli/geolens_cli/publish.py`, `cli/tests/test_publish_unit.py`
- **Commits:** `8c9e6252` (Task 1 GREEN includes test), `81118c05` (Task 2 wires it)

**3. [Rule 1 - Bug] Plan's pseudocode mapped `--description` to a `description` kwarg on CommitRequest — actual field is `summary`**
- **Found during:** Task 0 spike (Q2 inspection of `CommitRequest`)
- **Issue:** `CommitRequest` has `summary: None | str | Unset = UNSET`; no `description` field. The plan's Task 1 pseudocode used `kwargs["summary"] = description` with the placeholder note "field name per Task 0 finding" — Task 0 confirmed `summary` is correct.
- **Fix:** `build_commit_request(title, description)` maps `description` → `summary`. The CLI's user-facing flag stays `--description`; the SDK-level field alignment is internal. Tests `test_description_maps_to_summary` and `test_no_description_leaves_summary_unset` lock this in.
- **Files:** `cli/geolens_cli/publish.py`
- **Commit:** `8c9e6252`

**4. [Rule 2 - Missing critical functionality] `resolve_dataset_id` polling helper added**
- **Found during:** Task 1 design
- **Issue:** Strategy (b) requires polling `/jobs/{job_id}` until `dataset_id` materializes. The plan's `<action>` block left this as "Note for the executor #2 — if Task 0 Q1 chose strategy (b), add a `resolve_dataset_id(client, job_id) -> str` function."
- **Fix:** Implemented `resolve_dataset_id` with watchdog timeout (120s default) + injectable sleep/monotonic for testability. Returns `None` on terminal failure / timeout so the caller can fall back to the job-search URL.
- **Files:** `cli/geolens_cli/publish.py`
- **Commit:** `8c9e6252`

**5. [Rule 3 - Blocking] `cli/tests/test_exit_codes.py` `test_publish_stub_exits_2` would fail after Task 2**
- **Found during:** Task 2 wire-up
- **Issue:** Plan 01's exit-code matrix had `test_publish_stub_exits_2` asserting the stub exits 2. Once Task 2 wires the real publish command, the stub no longer exists and that test breaks.
- **Fix:** Removed the stub test (mirrors Plan 02 / Plan 03 handoff pattern — stubs are removed when their plan lands; per-command behavior lives in the command's dedicated test module). Updated the docstring to reflect that publish is no longer a stub.
- **Files:** `cli/tests/test_exit_codes.py`
- **Commit:** `81118c05`

### Auth Gates

None encountered — all three tasks executed autonomously. The publish command's auth surface (consumes `state.sdk()`) inherits Plan 02's keyring + refresh-retry logic; no new credentials are stored.

### Architectural Escalations

None.

## TDD Gate Compliance

Plan 04 had:
- Task 0: spike (no TDD applicable — produces a docs artifact only)
- Task 1: `tdd="true"`
- Task 2: `tdd="true"`

Tasks 1 and 2 share `cli/tests/test_publish_unit.py` (the test file
naturally covers both the unit-level publish.py surface AND the CLI
command body — they target related code under one test module). The
single RED commit `3811f5cf` covers both task surfaces.

| Task | RED commit (test) | GREEN commit (impl) | REFACTOR |
| ---- | ----------------- | ------------------- | -------- |
| 0 (spike) | n/a | `0edcbc6c` docs(216-04): record publish-command spike decisions | n/a |
| 1 (publish.py) + 2 (main.py wiring) | `3811f5cf` test(216-04): add failing tests for publish.py + publish CLI command | `8c9e6252` (Task 1 GREEN — publish.py) → `81118c05` (Task 2 GREEN — main.py wiring + test_exit_codes update) | not needed |

| RED gate | GREEN gate | REFACTOR gate |
| -------- | ---------- | ------------- |
| `test(216-04):` commit landed before any `feat(216-04):` | yes (`3811f5cf` → `8c9e6252` → `81118c05`) | not needed |

## Threat Flags

None — this plan implements the publish command exactly as the phase-level threat
model anticipated:

- **T-216-03 (file content-type spoofing):** `accept` per CONTEXT D-15.
  The CLI's MIME guess is informational; the backend's `upload_file()`
  re-validates via puremagic in `validate_file_content`. No CLI bypass.
- **T-216-04 (HTTP bypass):** `mitigate`. publish.py contains zero
  `^(import|from) httpx[^_]` lines. The httpx instance reaches it
  exclusively via `client.get_httpx_client()`. Verified at acceptance
  AND post-commit grep gates.
- **T-216-02 (token replay):** `mitigate (inherited)` from Plan 02. The
  publish command consumes `state.sdk()` which loads tokens via Plan 02's
  refresh-retry path; 401s are surfaced through `unwrap()` → `EXIT_AUTH`.
- **T-216-06 (commit storm via auto-retry):** `mitigate`. The
  `handle_commit_already_processed` helper exits cleanly with no retry;
  the duplicate detection covers both 400 and 409 by detail text.

## Commits

| Task | Hash | Description |
| ---- | ---- | ----------- |
| 0 | `0edcbc6c` | docs(216-04): record publish-command spike decisions (Task 0) |
| 1+2 RED | `3811f5cf` | test(216-04): add failing tests for publish.py + publish CLI command |
| 1 GREEN | `8c9e6252` | feat(216-04): implement publish.py — multipart workaround + 3-step orchestration |
| 2 GREEN | `81118c05` | feat(216-04): wire publish command + progress UI; mark publish stub retired |

## Next Plan Readiness

- Plan 05 (export stac) is the only remaining stub command — its TDD
  pattern mirrors Plans 02-04 directly. The `_publish.guess_mime` and
  status-code constants may or may not be reusable depending on whether
  STAC export needs MIME negotiation.
- Plan 06 (round-trip + CI + docs) inherits a clean OCCLI-06 invariant
  across all of `cli/geolens_cli/` — Plan 06's CI grep gate will lock
  it in. The round-trip test will exercise the publish flow end-to-end
  against the in-process ASGI app, validating the multipart workaround
  reaches the backend correctly.

## Self-Check: PASSED

- `cli/geolens_cli/publish.py` exists ✓
- `cli/tests/test_publish_unit.py` exists ✓
- `cli/geolens_cli/main.py` modified (publish wired) ✓
- `cli/tests/test_exit_codes.py` modified (publish stub removed) ✓
- `.planning/phases/216-geolens-cli-mvp/216-04-DECISION-LOG.md` exists ✓
- `.planning/phases/216-geolens-cli-mvp/216-04-SUMMARY.md` exists (this file) ✓
- Commit `0edcbc6c` exists ✓
- Commit `3811f5cf` exists ✓
- Commit `8c9e6252` exists ✓
- Commit `81118c05` exists ✓
- 30/30 publish unit tests passing ✓
- 92/92 full unit suite passing ✓
- OCCLI-06 invariant holds (zero `^(import|from) (httpx|requests)` in cli/geolens_cli/) ✓
- `client.get_httpx_client()` used in publish.py (no direct httpx dep) ✓
- Dataset URL strategy (b) implemented via `resolve_dataset_id` + fallback ✓
- Duplicate-commit detection covers both 400 and 409 ✓
- Decision log has all 4 mandatory `## Q[1-4]` sections + Q5/Q6/Q7 auxiliaries ✓

---
*Phase: 216-geolens-cli-mvp*
*Completed: 2026-04-27*
