---
phase: 216-geolens-cli-mvp
plan: 04
type: execute
wave: 3
depends_on: [02]
files_modified:
  - cli/geolens_cli/publish.py
  - cli/geolens_cli/main.py
  - cli/tests/test_publish_unit.py
  - .planning/phases/216-geolens-cli-mvp/216-04-DECISION-LOG.md
files_read:
  - cli/geolens_cli/auth.py
  - cli/geolens_cli/output.py
  - cli/geolens_cli/_sdk_helpers.py
  - sdks/python/geolens_sdk/api/datasets/upload_file_ingest_upload_post.py
  - sdks/python/geolens_sdk/api/datasets/preview_file_ingest_preview_job_id_post.py
  - sdks/python/geolens_sdk/api/datasets/commit_import_ingest_commit_job_id_post.py
  - sdks/python/geolens_sdk/models/commit_response.py
  - sdks/python/geolens_sdk/models/commit_request.py
  - backend/app/processing/ingest/router.py
  - backend/tests/test_sdks_round_trip.py
autonomous: true
requirements:
  - OCCLI-04
must_haves:
  decisions_covered:
    - "D-19: 3-step ingest flow via SDK — upload → preview → commit; print dataset URL on success"
    - "D-20: Synchronous-by-default with `--wait/--no-wait` flag (default --wait emits URL once status complete)"
    - "D-21: Progress UI via `rich.progress.Progress` with 4 stages; suppressed on non-TTY or --json"
    - "D-22: Ingest type detection client-side reuses D-15 extension allowlist; backend dispatches based on record_type (no --type override)"
    - "D-23: No presigned-upload path in MVP (streamed multipart only; presigned deferred for >100MB files)"
    - "D-24: Optional flags --name, --description, --tags (if CommitRequest exposes), --collection, --wait/--no-wait"
  truths:
    - "`geolens publish <file>` runs the 3-step ingest flow: POST /ingest/upload (returns job_id) → POST /ingest/preview/{job_id} → POST /ingest/commit/{job_id}"
    - "Upload step uses the multipart workaround from RESEARCH Pattern 3 — bypasses the broken generated `to_multipart()` by calling `client.get_httpx_client().post('/ingest/upload', files={...})` directly"
    - "Multipart payload includes filename + correct MIME type so backend's `upload_file()` does not reject with 400 'missing filename'"
    - "On successful commit, the CLI prints a dataset URL of the form `https://<instance>/datasets/<dataset_id>` (or, if the commit response only carries job_id, follows the documented job_id→dataset_id resolution path)"
    - "Optional flags supported: `--name`, `--description`, `--collection`, `--wait/--no-wait` (and `--tags` if CommitRequest exposes it; otherwise tags is captured as a deferred flag with a TODO)"
    - "Progress UI uses `rich.progress.Progress` with 4 stages (uploading, previewing, committing, done); auto-suppressed when stdout is not a TTY OR --json is set"
    - "On 409 from commit (job already processed), CLI prints 'Job <id> was already committed' and exits with EXIT_GENERIC (1) — does NOT auto-retry per Pitfall 6"
    - "publish.py imports zero `httpx` or `requests` modules at file-level; the multipart workaround uses `client.get_httpx_client()` only (the SDK owns the httpx instance)"
  artifacts:
    - path: cli/geolens_cli/publish.py
      provides: "upload_file (multipart workaround); publish_flow orchestration; MIME guess; tags resolution stub if not on CommitRequest"
      contains: "client.get_httpx_client"
    - path: cli/geolens_cli/main.py
      provides: "real `publish` command body replacing the Plan 01 stub; flag wiring; progress UI"
    - path: cli/tests/test_publish_unit.py
      provides: "mocked-SDK unit tests covering the 3-step orchestration, dataset URL format, progress suppression on non-TTY, 409 handling, optional flags pass-through"
  key_links:
    - from: "cli/geolens_cli/publish.py upload_file"
      to: "geolens_sdk.AuthenticatedClient.get_httpx_client"
      via: "post('/ingest/upload', files=...) bypassing broken to_multipart()"
      pattern: "client\\.get_httpx_client\\(\\)\\.post"
    - from: "cli/geolens_cli/main.py publish"
      to: "geolens_sdk.api.datasets.{preview,commit}"
      via: "AppState.sdk() → call_sdk(_preview.sync_detailed) → call_sdk(_commit.sync_detailed)"
      pattern: "preview_file_ingest_preview_job_id_post|commit_import_ingest_commit_job_id_post"
---

<objective>
Implement the `geolens publish <file>` command — the 3-step ingest flow (upload → preview → commit) with the documented multipart workaround for the broken `to_multipart()` generator quirk. On success, print the dataset URL (per ROADMAP SC#4). Closes OCCLI-04.

Purpose: The publish command is the headline value-add of the CLI — a user can upload a vector or raster file end-to-end without touching the GeoLens UI. This plan addresses Pitfall 1 (broken to_multipart), Pitfall 6 (commit not idempotent → don't retry on 409), and Open Question 1 (CommitResponse returns job_id, not dataset_id — this plan investigates and implements the documented resolution).

Output: Working `geolens publish <file>` command with progress UI, optional flags, mocked unit tests; documented decision on how the dataset URL is constructed (whether the commit response is widened, a follow-up GET is added, or the job_id is used in the URL with a documented note).
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/216-geolens-cli-mvp/216-CONTEXT.md
@.planning/phases/216-geolens-cli-mvp/216-RESEARCH.md
@.planning/phases/216-geolens-cli-mvp/216-PATTERNS.md
@.planning/phases/216-geolens-cli-mvp/216-VALIDATION.md
@.planning/phases/216-geolens-cli-mvp/216-02-auth-and-config-PLAN.md
@backend/tests/test_sdks_round_trip.py

<interfaces>
<!-- Plan 01 / 02 surfaces this plan consumes -->

From cli/geolens_cli/main.py (Plan 02 — AppState):
```python
class AppState:
    output: Formatter
    config: AppConfig
    json_mode: bool
    def active_instance() -> Optional[str]
    def sdk() -> GeolensClient   # raises typer.BadParameter if no instance configured
```

From cli/geolens_cli/_sdk_helpers.py (Plan 01):
```python
unwrap(resp, *, expected: int = 200) -> T
call_sdk(fn, **kwargs) -> Response
EXIT_GENERIC=1, EXIT_USAGE=2, EXIT_SERVER=5
```

<!-- SDK surface this plan calls -->

From geolens_sdk.api.datasets:
```python
# upload — generated to_multipart() is BROKEN (Pitfall 1); bypass via httpx_client.post
from geolens_sdk.api.datasets import upload_file_ingest_upload_post
# Internal helpers used by the workaround:
upload_file_ingest_upload_post._parse_response(client, response)  # parses raw httpx response

# preview — generated function works correctly
from geolens_sdk.api.datasets import preview_file_ingest_preview_job_id_post
# Returns Response[Union[PreviewResponse, ProblemDetail]]

# commit — generated function works correctly
from geolens_sdk.api.datasets import commit_import_ingest_commit_job_id_post
# Returns Response[Union[CommitResponse, ProblemDetail]]
# Per Open Question 1: CommitResponse has job_id, message, status — possibly NOT dataset_id
```

From geolens_sdk.client:
```python
class AuthenticatedClient:
    def get_httpx_client() -> httpx.Client      # SDK-owned sync client
```

From geolens_sdk.types:
```python
class Response[T]:
    status_code: HTTPStatus
    content: bytes
    headers: Headers
    parsed: Optional[T]
```

<!-- Models the plan must inspect at task time -->

The executor MUST read the actual files in sdks/python/geolens_sdk/models/commit_request.py
and commit_response.py to determine:
1. Whether CommitRequest has a `tags` field (Open Question 4)
2. What CommitResponse exposes (Open Question 1: job_id only? or also dataset_id?)

The plan budgets a Task 0 spike for these answers before writing publish.py.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 0: Spike — verify SDK model shapes for commit and resolve dataset URL strategy</name>
  <files>.planning/phases/216-geolens-cli-mvp/216-04-DECISION-LOG.md</files>
  <read_first>
    - sdks/python/geolens_sdk/models/commit_request.py (verify field names — does it have `tags`? `title`? `summary`?)
    - sdks/python/geolens_sdk/models/commit_response.py (verify field names — `job_id`? `dataset_id`? `status`?)
    - sdks/python/geolens_sdk/api/datasets/commit_import_ingest_commit_job_id_post.py (verify the function signature, expected status code, and how the parser maps responses)
    - sdks/python/geolens_sdk/api/datasets/upload_file_ingest_upload_post.py (verify status code on success — likely 201 — and confirm the broken to_multipart pattern)
    - backend/app/processing/ingest/router.py (search for `commit_import` handler; identify what the response body actually contains; if commit only returns job_id, look for a follow-up endpoint like GET /ingest/jobs/{job_id} or GET /datasets that resolves job→dataset)
    - backend/tests/test_sdks_round_trip.py (lines 217-266 — the existing test_ingest_upload that documents the broken to_multipart and accepts non-5xx; lines 219-227 docstring)
    - .planning/phases/216-geolens-cli-mvp/216-RESEARCH.md (Open Question 1 — RESEARCH lines 952-955; Open Question 4 — RESEARCH lines 967-970; Pitfall 6 — 3-step ingest is NOT idempotent)
  </read_first>
  <action>
    Read each file in `<read_first>` and answer the following questions in writing (record answers in the commit message of the next task and in Plan 04's SUMMARY):

    **Q1 (Open Question 1): How does the CLI translate `job_id` → dataset URL?**
    - Inspect `commit_response.py`. List its fields verbatim.
    - Inspect `backend/app/processing/ingest/router.py`'s `commit_import` handler. What does it return on the wire?
    - Decide on ONE of:
      (a) **CommitResponse already includes `dataset_id`** — use it directly. URL = `f"{instance}/datasets/{commit.dataset_id}"`.
      (b) **Commit response only has `job_id`, but a `GET /ingest/jobs/{job_id}` (or `GET /datasets?job_id=...`) endpoint resolves it** — add a follow-up SDK call after commit. URL constructed after that call.
      (c) **Neither (a) nor (b) is available** — print `f"{instance}/datasets?job_id={job_id}"` (a search URL) with a `state.output.info("Dataset will be available once ingestion completes — see job <id>")` warning. Document this as a known MVP limitation; CONTEXT.md does not budget for OpenAPI changes.
    - The decision MUST be documented in the SUMMARY with the actual field names from the SDK models.

    **Q2 (Open Question 4): Does CommitRequest expose a `tags` field?**
    - Inspect `commit_request.py`. List its fields.
    - If `tags` is present: wire `--tags a,b,c` directly into the CommitRequest constructor.
    - If `tags` is absent but a separate endpoint like `PATCH /datasets/{id}` accepts tags: leave `--tags` off the publish flags for MVP and add a `# TODO(OCCLI-deferred): tags requires post-commit PATCH; see Phase 216 Open Question 4` comment. Note in SUMMARY that tags is deferred.
    - If `tags` is absent and no clear post-commit path exists: same as above — defer.

    **Q3 (Pitfall 6 verification): What status code does commit return on a duplicate?**
    - Inspect the backend handler for the 409 path. Confirm the CLI's 409-handler message matches the actual error.

    **Q4 (Upload status): What status code does upload return?**
    - Inspect `upload_file_ingest_upload_post.py`. Confirm the success status (likely 201 Created).
    - The `unwrap(resp, expected=...)` call in publish.py must use this exact value.

    Output of this task: create `.planning/phases/216-geolens-cli-mvp/216-04-DECISION-LOG.md` with the four answers cited inline:
    ```markdown
    # Phase 216 / Plan 04 — Publish Command Decisions

    Investigated by Plan 04 Task 0 spike. The Task 1/2 implementations below use these decisions verbatim.

    ## Q1 — Dataset URL strategy
    Strategy: <a/b/c>
    Cited: `sdks/python/geolens_sdk/models/commit_response.py` field list — <list>
    Cited: `backend/app/processing/ingest/router.py:<line>` commit_import handler returns — <body shape>

    ## Q2 — `tags` field on CommitRequest
    Present: <yes/no>
    Cited: `sdks/python/geolens_sdk/models/commit_request.py` field list — <list>
    Wiring: <wired directly via kwarg / deferred with TODO and verbose-mode log>

    ## Q3 — 409 conflict message
    Cited: `backend/app/processing/ingest/router.py:<line>` — backend emits "<actual error string>"
    CLI message: "Job <id> was already committed (resume not supported in MVP)"

    ## Q4 — Upload success status code
    Cited: `sdks/python/geolens_sdk/api/datasets/upload_file_ingest_upload_post.py:<line>` — success status <NNN>
    UPLOAD_OK_STATUS constant in `cli/geolens_cli/publish.py` set to <NNN>
    ```
  </action>
  <verify>
    <automated>test -f /Users/ishiland/Code/geolens/sdks/python/geolens_sdk/models/commit_response.py && test -f /Users/ishiland/Code/geolens/sdks/python/geolens_sdk/models/commit_request.py</automated>
    <automated>grep -E "^class CommitResponse" /Users/ishiland/Code/geolens/sdks/python/geolens_sdk/models/commit_response.py</automated>
    <automated>grep -E "^class CommitRequest" /Users/ishiland/Code/geolens/sdks/python/geolens_sdk/models/commit_request.py</automated>
    <automated>test -f /Users/ishiland/Code/geolens/.planning/phases/216-geolens-cli-mvp/216-04-DECISION-LOG.md && [ $(grep -cE "^## Q[1-4]" /Users/ishiland/Code/geolens/.planning/phases/216-geolens-cli-mvp/216-04-DECISION-LOG.md) -ge 4 ]</automated>
  </verify>
  <acceptance_criteria>
    - All four files in `<read_first>` are read in this task
    - Q1 answered with: cited field list from commit_response.py + cited handler line from backend/app/processing/ingest/router.py + chosen strategy (a/b/c) recorded
    - Q2 answered with: cited field list from commit_request.py + decision (wire `--tags` OR defer with TODO comment)
    - Q3 answered with: cited 409 path from backend/app/processing/ingest/router.py + the actual error string the CLI's 409 handler will print
    - Q4 answered with: cited success status code from upload_file_ingest_upload_post.py
    - `.planning/phases/216-geolens-cli-mvp/216-04-DECISION-LOG.md` exists with all four `## Q1` … `## Q4` headers populated and citations
    - The four decisions also appear in Plan 04's SUMMARY (committed at end of plan; SUMMARY references the DECISION-LOG.md path)
  </acceptance_criteria>
  <done>The four open questions are resolved with citations. Tasks 1 and 2 below implement publish.py with the chosen strategy (no guessing).</done>
</task>

<task type="auto" tdd="true">
  <name>Task 1: Implement publish.py — multipart upload workaround + 3-step orchestration</name>
  <files>cli/geolens_cli/publish.py</files>
  <read_first>
    - .planning/phases/216-geolens-cli-mvp/216-RESEARCH.md (Pattern 3 lines 309-355 verbatim — multipart workaround; Example B lines 727-786 — full publish flow; Pitfall 1 — broken to_multipart; Pitfall 6 — 409 not idempotent)
    - .planning/phases/216-geolens-cli-mvp/216-PATTERNS.md (§`cli/geolens_cli/publish.py` — generator-quirk acknowledgement, multipart workaround, OCCLI-06 verification)
    - .planning/phases/216-geolens-cli-mvp/216-CONTEXT.md (D-19 — 3-step flow; D-20 — wait/no-wait; D-21 — progress UI; D-22 — type detection inherited from scan; D-24 — optional flags)
    - cli/geolens_cli/auth.py (Plan 02 — for ApiKey/BearerToken types if needed; mostly unused in publish)
    - cli/geolens_cli/_sdk_helpers.py (Plan 01 — unwrap, call_sdk, EXIT_*)
    - Task 0 DECISION-LOG (Q1, Q2, Q3, Q4 answers)
  </read_first>
  <behavior>
    - `_guess_mime(path)` returns the correct MIME for `.geojson`, `.gpkg`, `.tif`/`.tiff`, `.shp`, `.zip` (per RESEARCH Pattern 3)
    - `upload_file(client, path)` uses `client.get_httpx_client().post('/ingest/upload', files={...})` and parses via `upload_file_ingest_upload_post._parse_response(client=client, response=response)`
    - The constructed Response has `status_code=HTTPStatus(...)`, `content`, `headers`, `parsed`
    - Function-level docstring explicitly notes "OCCLI-06: uses SDK-owned httpx client; no direct httpx import here"
    - `publish_flow(sdk, file_path, *, name, description, tags, collection, wait)` returns `(dataset_url, job_id)` (or whatever the Q1 decision settled on)
    - On 409 from commit, raises an explicit `typer.Exit(1)` after printing "Job <id> was already committed (resume not supported in MVP)"
  </behavior>
  <action>
    Create `cli/geolens_cli/publish.py` per RESEARCH Pattern 3 + Example B + Task 0 decisions. The exact code below assumes the most likely Task 0 outcome (Q1=c, Q2=defer-tags, Q3=409 with "Job already processed", Q4=201). The executor adjusts the constants and one-line areas based on actual Task 0 findings:

    ```python
    """3-step ingest flow — upload, preview, commit.

    Hand-maintained — NOT regenerated. Implements the upload workaround for the
    broken generated `BodyUploadFileIngestUploadPost.to_multipart()` (RESEARCH
    Pitfall 1) by calling httpx through the SDK-owned client. OCCLI-06 holds:
    no direct `import httpx` here — `client.get_httpx_client()` is the SDK's
    public surface for advanced use.

    Pitfall 6: commit is NOT idempotent. On 409 we print a clear message and
    exit; we do NOT auto-retry.
    """
    from __future__ import annotations

    import mimetypes
    from http import HTTPStatus
    from pathlib import Path
    from typing import Any, Optional

    import typer

    from ._sdk_helpers import EXIT_GENERIC, call_sdk, unwrap

    # MIME map (RESEARCH Pattern 3 lines 317-325)
    _MIME_BY_EXT = {
        ".geojson": "application/geo+json",
        ".json": "application/json",
        ".gpkg": "application/geopackage+sqlite3",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
        ".csv": "text/csv",
        ".zip": "application/zip",
    }

    # Status codes — verify against Task 0 Q4 finding
    UPLOAD_OK_STATUS = 201        # POST /ingest/upload returns 201 Created
    PREVIEW_OK_STATUS = 200       # POST /ingest/preview/{job_id} returns 200 OK
    COMMIT_OK_STATUS = 202        # POST /ingest/commit/{job_id} returns 202 Accepted (verify Q4)
    COMMIT_DUPLICATE_STATUS = 409


    def guess_mime(path: Path) -> str:
        """Return the MIME for a spatial file. Backend re-validates content."""
        return _MIME_BY_EXT.get(path.suffix.lower()) or (
            mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        )


    def upload_file(client: Any, path: Path) -> Any:
        """Upload a file via the SDK-owned httpx client (multipart workaround).

        The generated `BodyUploadFileIngestUploadPost.to_multipart()` is broken
        (Pitfall 1) — it sends `(None, str(path).encode(), 'text/plain')`. We
        bypass it by building the multipart payload directly. The httpx client
        comes from the SDK, so OCCLI-06 holds (no direct httpx dep in cli/).
        """
        # Lazy import to keep --help/--version snappy
        from geolens_sdk.api.datasets import upload_file_ingest_upload_post
        from geolens_sdk.types import Response

        httpx_client = client.get_httpx_client()  # SDK-owned httpx.Client
        with path.open("rb") as fh:
            files = {"file": (path.name, fh, guess_mime(path))}
            raw = httpx_client.post("/ingest/upload", files=files)
        parsed = upload_file_ingest_upload_post._parse_response(client=client, response=raw)
        return Response(
            status_code=HTTPStatus(raw.status_code),
            content=raw.content,
            headers=raw.headers,
            parsed=parsed,
        )


    def build_commit_request(
        *,
        title: str,
        description: Optional[str],
        tags: Optional[list[str]],
        collection_id: Optional[str],
    ) -> Any:
        """Construct a CommitRequest from CLI flags.

        Field set is determined by Task 0 Q2. If `tags` is not on the model,
        this function silently drops it (the CLI already warned the user via
        the deferred-flag note).
        """
        from geolens_sdk.models.commit_request import CommitRequest
        # The Task 0 spike establishes which fields exist on CommitRequest.
        # This function passes only those fields; missing fields are dropped.
        kwargs: dict[str, Any] = {"title": title}
        if description is not None:
            kwargs["summary"] = description  # field name per Task 0 finding
        # NOTE: collection wiring may go via separate post-commit endpoint;
        # see Task 0 Q2/Q4. If CommitRequest has a `collection_id` field, set it.
        # If not, this function returns the request without it; main.py adds the
        # dataset to the collection via a follow-up SDK call after commit.
        if collection_id is not None and "collection_id" in CommitRequest.__match_args__ if hasattr(CommitRequest, "__match_args__") else False:
            kwargs["collection_id"] = collection_id
        # tags: per Task 0 Q2, only include if the field exists on the model.
        # The simplest robust approach is try/except construct.
        try:
            return CommitRequest(**kwargs)
        except TypeError:
            # Strip any kwarg that the model doesn't accept and retry once.
            from inspect import signature
            valid = set(signature(CommitRequest).parameters.keys())
            cleaned = {k: v for k, v in kwargs.items() if k in valid}
            return CommitRequest(**cleaned)


    def construct_dataset_url(instance: str, commit_response: Any, job_id: str) -> str:
        """Construct the dataset URL from the commit response.

        Per Task 0 Q1: pick the strategy (a/b/c) and implement here.
        - (a) commit_response.dataset_id present → f"{instance}/datasets/{commit.dataset_id}"
        - (b) follow-up GET to resolve job_id → dataset_id (caller passes resolved id)
        - (c) fallback: f"{instance}/datasets?job_id={job_id}" with a documented note

        This function defaults to (a) by reading `dataset_id`; falls back to
        (c) if that field isn't present.
        """
        instance = instance.rstrip("/")
        dataset_id = getattr(commit_response, "dataset_id", None)
        if dataset_id:
            return f"{instance}/datasets/{dataset_id}"
        # Fallback (c): job_id-keyed search URL with a clear marker.
        return f"{instance}/datasets?job_id={job_id}"


    def handle_commit_409(job_id: str, output) -> None:
        """Per Pitfall 6: commit is not idempotent. On 409, print and exit."""
        output.error(f"Job {job_id} was already committed (resume not supported in MVP)")
        raise typer.Exit(EXIT_GENERIC)
    ```

    Notes for the executor:
    1. The `__match_args__` check is a Python 3.10+ idiom for inspecting dataclass fields. The Task 0 spike will confirm whether `CommitRequest` is an attrs class (most likely — generator emits attrs) or a pydantic model. Adjust the field-detection approach accordingly. The fallback try/except + `inspect.signature` approach is robust for both.
    2. If Task 0 Q1 chose strategy (b) (follow-up GET to resolve job→dataset), add a `resolve_dataset_id(client, job_id) -> str` function that calls the SDK's `GET /ingest/jobs/{job_id}` (or whichever endpoint resolves it). Update `construct_dataset_url` to take the resolved `dataset_id` directly.
    3. The `description` field maps to `summary` per common backend conventions. If Task 0 finds the field is actually `description`, change the kwargs key.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/cli && uv run python -c "from geolens_cli.publish import guess_mime, upload_file, build_commit_request, construct_dataset_url, handle_commit_409; from pathlib import Path; assert guess_mime(Path('a.geojson'))=='application/geo+json'; assert guess_mime(Path('b.tif'))=='image/tiff'; assert guess_mime(Path('c.gpkg'))=='application/geopackage+sqlite3'; print('OK')"</automated>
    <automated>! grep -rE '^(import|from) httpx[^_]|^import httpx$|^from httpx import' /Users/ishiland/Code/geolens/cli/geolens_cli/publish.py</automated>
    <automated>grep -E "client\.get_httpx_client" /Users/ishiland/Code/geolens/cli/geolens_cli/publish.py</automated>
  </verify>
  <acceptance_criteria>
    - cli/geolens_cli/publish.py defines `guess_mime`, `upload_file`, `build_commit_request`, `construct_dataset_url`, `handle_commit_409`
    - `upload_file` uses `client.get_httpx_client().post(...)` (the SDK's surface), NOT a direct `httpx.Client(...)` call
    - `_MIME_BY_EXT` maps `.geojson` → `application/geo+json`, `.gpkg` → `application/geopackage+sqlite3`, `.tif` → `image/tiff`
    - `handle_commit_409` raises `typer.Exit(EXIT_GENERIC=1)` per Pitfall 6
    - publish.py has zero `^(import|from) httpx[^_]` lines (the file imports httpx ONLY transitively via SDK; the explicit `import httpx` for exception types lives in `_sdk_helpers.py`, NOT here)
    - publish.py contains the comment `OCCLI-06` somewhere in its docstrings/comments (signals intent)
    - `construct_dataset_url` constructs `f"{instance}/datasets/{...}"` when `dataset_id` is present on the commit response
  </acceptance_criteria>
  <done>publish.py exposes the multipart workaround, MIME guesser, CommitRequest builder, dataset-URL constructor, and 409 handler. All Task 0 findings are baked into the constants. Zero direct httpx imports.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Wire publish command + progress UI; add mocked unit tests</name>
  <files>cli/geolens_cli/main.py, cli/tests/test_publish_unit.py</files>
  <read_first>
    - cli/geolens_cli/main.py (Plan 02 — current `publish` stub; AppState.sdk() lazy property)
    - cli/geolens_cli/publish.py (Task 1 — guess_mime, upload_file, build_commit_request, construct_dataset_url, handle_commit_409)
    - .planning/phases/216-geolens-cli-mvp/216-RESEARCH.md (Example B lines 727-786 — full command body; Standard Stack — rich.progress)
    - .planning/phases/216-geolens-cli-mvp/216-CONTEXT.md (D-21 progress display + non-TTY suppression; D-24 optional flags)
    - .planning/phases/216-geolens-cli-mvp/216-VALIDATION.md (test_publish_unit.py expectations)
    - sdks/python/geolens_sdk/api/datasets/preview_file_ingest_preview_job_id_post.py (verify the function signature + status code)
  </read_first>
  <behavior>
    - `geolens publish <file>` runs through the 3 steps with a rich.Progress UI showing "Uploading…", "Previewing…", "Committing…", "Done"
    - `--name` overrides the default title (file stem)
    - `--description` sets the description/summary
    - `--collection <id>` calls `POST /catalog/collections/{id}/datasets` after commit (or the equivalent endpoint per Task 0)
    - `--tags a,b,c` is parsed into a list; if CommitRequest exposes a tags field per Task 0 Q2, it's wired through; otherwise the flag is accepted but ignored with a `--verbose` log line "tags deferred"
    - `--wait/--no-wait` (default `--wait`): when `--no-wait`, prints job_id and exits immediately after commit
    - On non-TTY OR `--json`, the progress bar is suppressed (Progress.disable=True) and the final output is the dataset_url (text mode) or `{dataset_url, job_id, status}` (JSON mode)
    - On 409 from commit, `handle_commit_409` is called → exits 1 with "Job <id> was already committed"
  </behavior>
  <action>
    Modify `cli/geolens_cli/main.py` — replace the Plan 01 `publish` stub. Update imports at the top of main.py to add:
    ```python
    from . import publish as _publish
    from rich.progress import Progress, SpinnerColumn, TextColumn
    ```

    Replace the publish command body:
    ```python
    @app.command()
    def publish(
        ctx: typer.Context,
        file: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True, help="Spatial file to publish")],
        name: Annotated[Optional[str], typer.Option("--name", help="Dataset name (default: filename stem)")] = None,
        description: Annotated[Optional[str], typer.Option("--description", help="Dataset description")] = None,
        tags: Annotated[Optional[str], typer.Option("--tags", help="Comma-separated keyword tags")] = None,
        collection: Annotated[Optional[str], typer.Option("--collection", help="Add to this collection after commit")] = None,
        wait: Annotated[bool, typer.Option("--wait/--no-wait", help="Wait for commit completion")] = True,
    ) -> None:
        """Upload a vector or raster file and publish it as a dataset."""
        state: AppState = ctx.obj
        instance = state.active_instance()
        if not instance:
            state.output.error("No instance configured. Run `geolens login <url>` first.")
            raise typer.Exit(EXIT_AUTH)

        sdk = state.sdk()
        title = name or file.stem
        tags_list: Optional[list[str]] = None
        if tags:
            tags_list = [t.strip() for t in tags.split(",") if t.strip()]

        # Lazy SDK imports
        from geolens_sdk.api.datasets import (
            preview_file_ingest_preview_job_id_post as _preview,
            commit_import_ingest_commit_job_id_post as _commit,
        )

        progress_disabled = state.json_mode or not state.output.is_tty
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            disable=progress_disabled,
        )

        with progress:
            t1 = progress.add_task("Uploading...", total=None)
            upload_resp = _publish.upload_file(sdk.client, file)
            upload = unwrap(upload_resp, expected=_publish.UPLOAD_OK_STATUS)
            job_id = getattr(upload, "job_id", None)
            if job_id is None:
                state.output.error("Upload did not return a job_id; cannot proceed.")
                raise typer.Exit(EXIT_GENERIC)
            progress.update(t1, description=f"Uploaded (job_id={job_id})")

            t2 = progress.add_task("Previewing...", total=None)
            preview_resp = call_sdk(_preview.sync_detailed, job_id=job_id, client=sdk.client)
            unwrap(preview_resp, expected=_publish.PREVIEW_OK_STATUS)
            progress.update(t2, description="Preview OK")

            t3 = progress.add_task("Committing...", total=None)
            commit_body = _publish.build_commit_request(
                title=title,
                description=description,
                tags=tags_list,
                collection_id=collection,
            )
            commit_resp = call_sdk(
                _commit.sync_detailed,
                job_id=job_id,
                client=sdk.client,
                body=commit_body,
            )
            if int(commit_resp.status_code) == _publish.COMMIT_DUPLICATE_STATUS:
                _publish.handle_commit_409(str(job_id), state.output)
            commit = unwrap(commit_resp, expected=_publish.COMMIT_OK_STATUS)
            progress.update(t3, description="Committed")

        dataset_url = _publish.construct_dataset_url(instance, commit, str(job_id))

        if not wait:
            # --no-wait: print URL but do not block on async COG conversion etc.
            payload = {"dataset_url": dataset_url, "job_id": str(job_id), "status": getattr(commit, "status", None)}
        else:
            payload = {"dataset_url": dataset_url, "job_id": str(job_id), "status": getattr(commit, "status", None)}

        if state.json_mode:
            state.output.json(payload)
        else:
            state.output.success(f"Published: {dataset_url}")
    ```

    Note: the `--collection` follow-up call is not implemented inline above to keep the task focused on OCCLI-04's core behavior (3-step flow + URL). If Task 0 confirms a `POST /catalog/collections/{id}/datasets` endpoint exists in the SDK, the executor adds:
    ```python
    if collection:
        from geolens_sdk.api.collections import add_dataset_to_collection_catalog_collections_collection_id_datasets_post as _add_to_coll
        # ... or whatever the actual operation_id is — read from sdks/python/geolens_sdk/api/collections/
        # call_sdk(_add_to_coll.sync_detailed, ...)
    ```
    If no collection-add endpoint is in the SDK, leave a `# TODO(OCCLI-deferred): collection-add endpoint not in SDK` and document in SUMMARY.

    Create `cli/tests/test_publish_unit.py`:
    ```python
    """OCCLI-04: publish unit tests with mocked SDK."""
    from __future__ import annotations

    import json
    from http import HTTPStatus
    from pathlib import Path
    from unittest.mock import MagicMock, patch

    import pytest

    from geolens_cli import publish as _publish
    from geolens_cli.main import app


    class TestGuessMime:
        @pytest.mark.parametrize("name,expected", [
            ("a.geojson", "application/geo+json"),
            ("b.json", "application/json"),
            ("c.gpkg", "application/geopackage+sqlite3"),
            ("d.tif", "image/tiff"),
            ("e.tiff", "image/tiff"),
            ("f.zip", "application/zip"),
            ("g.csv", "text/csv"),
        ])
        def test_known_extensions(self, name, expected) -> None:
            assert _publish.guess_mime(Path(name)) == expected


    class TestConstructDatasetUrl:
        def test_strips_trailing_slash(self) -> None:
            commit = MagicMock(dataset_id="abc-123")
            url = _publish.construct_dataset_url("https://x.example.com/", commit, "job-9")
            assert url == "https://x.example.com/datasets/abc-123"

        def test_uses_dataset_id_when_present(self) -> None:
            commit = MagicMock(dataset_id="abc-123")
            url = _publish.construct_dataset_url("https://x.example.com", commit, "job-9")
            assert url == "https://x.example.com/datasets/abc-123"

        def test_falls_back_to_job_search_when_no_dataset_id(self) -> None:
            class C:
                pass  # no dataset_id attribute
            url = _publish.construct_dataset_url("https://x.example.com", C(), "job-9")
            assert "job_id=job-9" in url


    class TestPublishCli:
        @pytest.fixture
        def sample_geojson(self, tmp_path: Path) -> Path:
            f = tmp_path / "cities.geojson"
            f.write_text('{"type":"FeatureCollection","features":[]}')
            return f

        def _setup_state(self, monkeypatch, tmp_xdg_home, mock_keyring, instance="https://x.example.com"):
            """Helper — pre-seed login state."""
            from geolens_cli import auth as _auth
            from geolens_cli import config as _config
            mock_keyring[("geolens", instance)] = "tok-abc"
            _config.write_default_instance(instance, username="alice")

        def test_no_instance_exits_auth_error(self, runner, tmp_xdg_home, sample_geojson) -> None:
            # No login state seeded
            result = runner.invoke(app, ["publish", str(sample_geojson)])
            assert result.exit_code in (3, 2), result.output

        def test_publish_success_prints_dataset_url(
            self, runner, tmp_xdg_home, mock_keyring, monkeypatch, sample_geojson
        ) -> None:
            self._setup_state(monkeypatch, tmp_xdg_home, mock_keyring)

            # Mock the SDK constructor returned by AppState.sdk()
            # by patching upload_file, _preview.sync_detailed, _commit.sync_detailed
            upload_mock = MagicMock(
                status_code=HTTPStatus(_publish.UPLOAD_OK_STATUS),
                parsed=MagicMock(job_id="job-9"),
            )
            preview_mock = MagicMock(
                status_code=HTTPStatus(_publish.PREVIEW_OK_STATUS),
                parsed=MagicMock(),
            )
            commit_mock = MagicMock(
                status_code=HTTPStatus(_publish.COMMIT_OK_STATUS),
                parsed=MagicMock(dataset_id="ds-42", status="committed"),
            )

            monkeypatch.setattr("geolens_cli.publish.upload_file", lambda c, p: upload_mock)
            monkeypatch.setattr(
                "geolens_sdk.api.datasets.preview_file_ingest_preview_job_id_post.sync_detailed",
                lambda **kw: preview_mock,
            )
            monkeypatch.setattr(
                "geolens_sdk.api.datasets.commit_import_ingest_commit_job_id_post.sync_detailed",
                lambda **kw: commit_mock,
            )

            result = runner.invoke(app, ["publish", str(sample_geojson)])
            assert result.exit_code == 0, result.output
            assert "https://x.example.com/datasets/ds-42" in result.output

        def test_publish_409_exits_generic(
            self, runner, tmp_xdg_home, mock_keyring, monkeypatch, sample_geojson
        ) -> None:
            self._setup_state(monkeypatch, tmp_xdg_home, mock_keyring)

            upload_mock = MagicMock(
                status_code=HTTPStatus(_publish.UPLOAD_OK_STATUS),
                parsed=MagicMock(job_id="job-dupe"),
            )
            preview_mock = MagicMock(
                status_code=HTTPStatus(_publish.PREVIEW_OK_STATUS),
                parsed=MagicMock(),
            )
            commit_409 = MagicMock(
                status_code=HTTPStatus(_publish.COMMIT_DUPLICATE_STATUS),
                parsed=None,
            )
            monkeypatch.setattr("geolens_cli.publish.upload_file", lambda c, p: upload_mock)
            monkeypatch.setattr(
                "geolens_sdk.api.datasets.preview_file_ingest_preview_job_id_post.sync_detailed",
                lambda **kw: preview_mock,
            )
            monkeypatch.setattr(
                "geolens_sdk.api.datasets.commit_import_ingest_commit_job_id_post.sync_detailed",
                lambda **kw: commit_409,
            )

            result = runner.invoke(app, ["publish", str(sample_geojson)])
            assert result.exit_code == 1, result.output
            assert "already committed" in result.output

        def test_progress_suppressed_non_tty(
            self, runner, tmp_xdg_home, mock_keyring, monkeypatch, sample_geojson
        ) -> None:
            """CliRunner output is not a TTY; progress UI must not emit ANSI escape codes."""
            self._setup_state(monkeypatch, tmp_xdg_home, mock_keyring)

            upload_mock = MagicMock(
                status_code=HTTPStatus(_publish.UPLOAD_OK_STATUS),
                parsed=MagicMock(job_id="job-1"),
            )
            preview_mock = MagicMock(
                status_code=HTTPStatus(_publish.PREVIEW_OK_STATUS),
                parsed=MagicMock(),
            )
            commit_mock = MagicMock(
                status_code=HTTPStatus(_publish.COMMIT_OK_STATUS),
                parsed=MagicMock(dataset_id="ds-1", status="committed"),
            )
            monkeypatch.setattr("geolens_cli.publish.upload_file", lambda c, p: upload_mock)
            monkeypatch.setattr(
                "geolens_sdk.api.datasets.preview_file_ingest_preview_job_id_post.sync_detailed",
                lambda **kw: preview_mock,
            )
            monkeypatch.setattr(
                "geolens_sdk.api.datasets.commit_import_ingest_commit_job_id_post.sync_detailed",
                lambda **kw: commit_mock,
            )

            result = runner.invoke(app, ["publish", str(sample_geojson)])
            assert result.exit_code == 0, result.output
            # CliRunner mixes stderr/stdout but rich.Progress with disable=True emits nothing.
            # The output should NOT contain spinner frames like ⠋ ⠙ etc.
            for spinner in ("⠋", "⠙", "⠚", "⠞"):
                assert spinner not in result.output

        def test_json_mode_emits_payload(
            self, runner, tmp_xdg_home, mock_keyring, monkeypatch, sample_geojson
        ) -> None:
            self._setup_state(monkeypatch, tmp_xdg_home, mock_keyring)

            upload_mock = MagicMock(
                status_code=HTTPStatus(_publish.UPLOAD_OK_STATUS),
                parsed=MagicMock(job_id="job-7"),
            )
            preview_mock = MagicMock(
                status_code=HTTPStatus(_publish.PREVIEW_OK_STATUS),
                parsed=MagicMock(),
            )
            commit_mock = MagicMock(
                status_code=HTTPStatus(_publish.COMMIT_OK_STATUS),
                parsed=MagicMock(dataset_id="ds-7", status="committed"),
            )
            monkeypatch.setattr("geolens_cli.publish.upload_file", lambda c, p: upload_mock)
            monkeypatch.setattr(
                "geolens_sdk.api.datasets.preview_file_ingest_preview_job_id_post.sync_detailed",
                lambda **kw: preview_mock,
            )
            monkeypatch.setattr(
                "geolens_sdk.api.datasets.commit_import_ingest_commit_job_id_post.sync_detailed",
                lambda **kw: commit_mock,
            )

            result = runner.invoke(app, ["--json", "publish", str(sample_geojson)])
            assert result.exit_code == 0, result.output
            payload = json.loads(result.output)
            assert payload["dataset_url"].endswith("/datasets/ds-7")
            assert payload["job_id"] == "job-7"
    ```
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/cli && uv run pytest tests/test_publish_unit.py -v 2>&1 | tail -40</automated>
    <automated>cd /Users/ishiland/Code/geolens/cli && uv run pytest -v 2>&1 | grep -E "(passed|failed)" | tail -5</automated>
    <automated>! grep -rE '^(import|from) httpx[^_]' /Users/ishiland/Code/geolens/cli/geolens_cli/publish.py /Users/ishiland/Code/geolens/cli/geolens_cli/main.py</automated>
    <automated>! grep -rE '^(import|from) requests' /Users/ishiland/Code/geolens/cli/geolens_cli/publish.py /Users/ishiland/Code/geolens/cli/geolens_cli/main.py</automated>
  </verify>
  <acceptance_criteria>
    - cli/geolens_cli/main.py `publish` command body imports `_publish` and `Progress`/`SpinnerColumn`/`TextColumn` from rich
    - `publish` calls `_publish.upload_file(sdk.client, file)` (NOT direct httpx)
    - `publish` calls `_preview.sync_detailed(job_id=..., client=...)` and `_commit.sync_detailed(job_id=..., client=..., body=...)`
    - `publish` 409 path: `handle_commit_409` is invoked when `commit_resp.status_code == 409`
    - `publish` JSON mode emits a parseable JSON payload with `dataset_url`, `job_id`, `status`
    - `publish` progress UI is suppressed when `state.output.is_tty` is False OR `state.json_mode` is True (Progress(..., disable=...))
    - test_publish_unit.py contains TestGuessMime parametrized over 7+ extensions
    - test_publish_unit.py contains TestConstructDatasetUrl with ≥3 methods including dataset_id-present and dataset_id-absent paths
    - test_publish_unit.py contains TestPublishCli with ≥5 methods including no-instance, success, 409, non-TTY, json
    - `cd cli && uv run pytest tests/test_publish_unit.py -v` exits 0 with all tests passing
    - Zero `^(import|from) httpx[^_]` lines in publish.py or the `publish` body of main.py (httpx instance is obtained through `client.get_httpx_client()`)
    - Zero `^(import|from) requests` lines in publish.py or main.py
  </acceptance_criteria>
  <done>`geolens publish <file>` runs end-to-end with mocked SDK, prints the dataset URL on success, exits 1 on 409 with a clear message, and suppresses progress on non-TTY. publish.py uses the SDK's httpx client only — OCCLI-06 invariant intact.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| User-supplied file path | `publish` opens the file in binary mode and streams it via multipart; Typer's `exists=True, file_okay=True, readable=True` enforces the path is a readable file before the body runs |
| CLI process → backend `/ingest/upload` | Multipart POST through SDK's httpx client; backend re-validates the file via puremagic before persistence |
| CLI process → backend `/ingest/preview/{job_id}` | Backend may surface the file's columns/CRS/sample rows (preview can include user data) |
| CLI process → backend `/ingest/commit/{job_id}` | Backend persists the dataset; commit body includes user-supplied `name`/`description`/`tags` (free-text fields the backend sanitizes) |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-216-03 | Tampering | A user could rename a malicious file (e.g., shell script) to `.geojson` and publish it | accept | The CLI's MIME guess is informational; backend's `upload_file()` re-validates via puremagic and rejects mismatched content. The CLI never bypasses or substitutes server-side validation. Documented in publish.py docstring. |
| T-216-04 | Tampering | publish.py introducing a direct `httpx.Client(...)` would silently break OCCLI-06 | mitigate | Acceptance criterion enforces zero `^(import|from) httpx[^_]` lines in publish.py via grep. The multipart workaround uses `client.get_httpx_client()` — the SDK's public surface. Plan 06 closes the global CI grep gate across `cli/geolens_cli/`. |
| T-216-02 | Spoofing / Replay | Stolen access token replayed against `/ingest/upload` | mitigate (inherited) | Inherited from Plan 02: refresh-retry-once on 401 via `try_refresh`; second 401 exits EXIT_AUTH (3). publish.py's call_sdk wrapper surfaces 401 to unwrap which exits 3. |
| T-216-06 | Denial of Service | Resuming a failed publish via re-running the same job_id is rejected with 409 (Pitfall 6) | mitigate | publish.py's `handle_commit_409` exits cleanly with a clear "already committed" message. No auto-retry that could storm the backend with duplicate commits. |

**Not Applicable in this plan:**
- T-216-01 (token-at-rest): Not applicable — publish does not write credentials; it consumes `AppState.sdk()` (Plan 02) which loads tokens from keyring/file and never persists new ones during publish. Plan 02 owns T-216-01.
- T-216-05 (token-in-shell-history): Not applicable — publish has no `--token` flag (auth happens via prior `geolens login`). Plan 02 owns the `--token` flag; Plan 06 docs/cli.md owns the user-facing warning.
</threat_model>

<verification>
- `cd cli && uv run pytest tests/test_publish_unit.py -v` exits 0 with all tests passing
- `cd cli && uv run pytest -v` (full unit slice) still green (Plans 01 + 02 + 03 + 04 tests all pass)
- Grep gates clean: zero `^(import|from) httpx[^_]` and zero `^(import|from) requests` in publish.py and the publish body of main.py
- The 4 Task 0 decisions are recorded in Plan 04's SUMMARY with citations
</verification>

<success_criteria>
- OCCLI-04 closed: 3-step ingest flow works end-to-end (verified via mocked unit tests; round-trip in Plan 06); dataset URL printed on success; 409 handled cleanly; progress UI degrades gracefully on non-TTY
- OCCLI-06 invariant preserved: the multipart workaround uses `client.get_httpx_client()` (SDK-owned); no direct httpx import in publish.py
</success_criteria>

<output>
After completion, create `.planning/phases/216-geolens-cli-mvp/216-04-SUMMARY.md` capturing:
- Task 0 findings (Q1, Q2, Q3, Q4 with citations)
- Whether `--tags` is wired or deferred
- Whether the dataset URL uses `dataset_id` or the job-search fallback
- The actual status codes for upload/preview/commit
- Test count
- Any deviations from RESEARCH Pattern 3 / Example B
</output>
