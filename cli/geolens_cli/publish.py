# SPDX-License-Identifier: Apache-2.0
"""3-step ingest flow — upload → preview → commit.

Hand-maintained — NOT regenerated. Implements the upload workaround for
the broken generated ``BodyUploadFileIngestUploadPost.to_multipart()``
(Phase 216 RESEARCH Pitfall 1) by calling httpx through the SDK-owned
client. OCCLI-06 holds: no direct ``import httpx`` here —
``client.get_httpx_client()`` is the SDK's public surface for advanced
use, and the dep list (`cli/pyproject.toml`) declares no httpx direct
dependency (only transitive via the geolens SDK).

Pitfall 6: commit is NOT idempotent. On a duplicate-commit response we
print a clear "already committed" message and exit cleanly; we do NOT
auto-retry. The backend currently returns 400 for this case (per the
Plan 04 Task 0 spike, recorded in 216-04-DECISION-LOG.md), but the SDK
parses both 400 and 409 as ``ProblemDetail`` so the CLI handles both
defensively by matching on the detail text.

Open Question 1 (CommitResponse → dataset URL) — resolved by Task 0 Q1:
``CommitResponse`` only carries ``{job_id, message, status}``, so the
dataset URL is constructed via a follow-up ``GET /jobs/{job_id}`` poll
that resolves ``job_id`` to ``dataset_id``. With ``--no-wait``, the URL
falls back to a job-search form ``<instance>/datasets?job_id=<id>``.

Open Question 4 (--tags wiring) — RESOLVED, fix(#569): ``CommitRequest``
still has no ``tags`` field, so ``--tags`` and ``--collection`` are
applied AFTER the commit resolves a dataset id (see
``apply_publish_extras``): tags become record keywords, and the
collection is resolved by id or exact name. Both need ``--wait``.
"""

from __future__ import annotations

import mimetypes
import time
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

import typer

from ._sdk_helpers import (
    EXIT_GENERIC,
    EXIT_NETWORK,
    EXIT_SERVER,
    PollDeadlineExceeded,
    call_sdk,
    long_request_timeout,
    poll_until,
)

# ---------------------------------------------------------------------------
# Status-code constants — verified by Plan 04 Task 0 Q4 spike.
# ---------------------------------------------------------------------------

#: Upload returns 201 Created (UploadResponse). Cited:
#: sdks/python/geolens/api/datasets/upload_file_ingest_upload_post.py:35
UPLOAD_OK_STATUS = 201

#: Preview returns 200 OK (PreviewResponse | RasterPreviewResponse). Cited:
#: sdks/python/geolens/api/datasets/preview_file_ingest_preview_job_id_post.py:49
PREVIEW_OK_STATUS = 200

#: Commit returns 202 Accepted (CommitResponse with status="pending"). Cited:
#: sdks/python/geolens/api/datasets/commit_import_ingest_commit_job_id_post.py:42
#: backend/app/processing/ingest/router.py:578
COMMIT_OK_STATUS = 202

#: GET /jobs/{job_id} returns 200 OK (JobStatusResponse with optional
#: dataset_id). Cited:
#: sdks/python/geolens/api/admin/get_job_status_jobs_job_id_get.py:33
JOB_STATUS_OK_STATUS = 200

#: Backend emits 400 for duplicate commits (Task 0 Q3); 409 is also
#: documented in the SDK's ``_parse_response``, so we accept either.
COMMIT_DUPLICATE_STATUSES: tuple[int, ...] = (400, 409)

#: Detail-text marker the backend uses for the duplicate-commit path:
#: "Job already processed" (router.py:596).
_DUPLICATE_DETAIL_NEEDLE = "already processed"

# ---------------------------------------------------------------------------
# Polling configuration — Claude judgment, see DECISION-LOG.md Q1.
# ---------------------------------------------------------------------------

_DEFAULT_POLL_INTERVAL_SECONDS: float = 1.0
_DEFAULT_POLL_TIMEOUT_SECONDS: float = 120.0

#: fix(#1778, codex round 5): bound for the ONE-SHOT follow-up read a
#: caller makes after a "timeout" or "poll_failed" PollOutcome, to check
#: for a dataset_id that resolved a moment too late (fix(#685 review)) or
#: a status that has since gone terminal (fix(#1778) round 4). The SDK
#: client's generated transport defaults to timeout=None — unbounded — so
#: without this, a stalled connection on that read would hang the command
#: forever instead of reporting the outcome it already has. A few seconds
#: is enough for a status lookup; this is a diagnostic extra, not worth
#: waiting long for.
_SNAPSHOT_REQUEST_TIMEOUT_SECONDS: float = 5.0

#: fix(#1778): job statuses that mean "this job will never produce a
#: dataset_id through this endpoint". Previously only "failed" was terminal
#: here, so --wait polled a cancelled job for the full timeout. "cancelled"
#: matches refresh.wait_for_refresh's terminal set ({"failed", "cancelled"});
#: "fanned_out" is added too because the parent of a multi-layer commit is
#: marked fanned_out and never gets its own dataset_id (commit_fan_out,
#: backend/app/processing/ingest/router.py).
_TERMINAL_NO_DATASET_STATUSES = frozenset({"failed", "cancelled", "fanned_out"})

# ---------------------------------------------------------------------------
# MIME map (RESEARCH Pattern 3 lines 317-325) — informational; the backend
# re-validates content via puremagic. T-216-03 (file content-type spoofing)
# is `accept` for the CLI because the server is the authoritative gate.
# ---------------------------------------------------------------------------

_MIME_BY_EXT: dict[str, str] = {
    ".geojson": "application/geo+json",
    ".json": "application/json",
    ".gpkg": "application/geopackage+sqlite3",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".csv": "text/csv",
    ".zip": "application/zip",
    # KML/KMZ are IANA-registered; FlatGeobuf has no registered type, so the
    # vendor tree name the FlatGeobuf project uses stands in.
    ".kml": "application/vnd.google-earth.kml+xml",
    ".kmz": "application/vnd.google-earth.kmz",
    ".fgb": "application/vnd.flatgeobuf",
}


def guess_mime(path: Path) -> str:
    """Return the MIME for a spatial file. Backend re-validates content."""
    by_ext = _MIME_BY_EXT.get(path.suffix.lower())
    if by_ext:
        return by_ext
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


# ---------------------------------------------------------------------------
# Multipart upload workaround (RESEARCH Pattern 3 / Pitfall 1)
# ---------------------------------------------------------------------------


def upload_file(client: Any, path: Path) -> Any:
    """Upload a file via the SDK-owned httpx client (multipart workaround).

    The generated ``BodyUploadFileIngestUploadPost.to_multipart()`` packs
    ``(None, str(self.file).encode(), 'text/plain')`` instead of a real
    multipart file — backend rejects with 400 "Upload missing filename"
    (Pitfall 1). We bypass it by building the multipart payload directly
    on the SDK's httpx client.

    OCCLI-06: ``client.get_httpx_client()`` is the SDK's public surface;
    the CLI never imports httpx directly to construct a Client. The dep
    list in ``cli/pyproject.toml`` enforces this structurally.
    """
    # Lazy SDK imports to keep ``geolens --help`` snappy.
    from geolens.api.datasets import upload_file_ingest_upload_post
    from geolens.types import Response

    # fix(#1778, review round 5): a large geospatial file upload can
    # easily outlast AppState.sdk()'s 30s default — long_request_timeout()
    # raises the bound for the transfer itself and restores it
    # afterward, so a later request on this same client (preview/
    # commit/poll) isn't left with the upload's longer timeout.
    with long_request_timeout(client) as httpx_client:
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


# ---------------------------------------------------------------------------
# Commit request builder
# ---------------------------------------------------------------------------


def build_commit_request(
    *,
    title: str,
    description: Optional[str],
) -> Any:
    """Construct a ``CommitRequest`` from the publish CLI flags.

    Field set is constrained by Task 0 Q2 — the SDK-generated
    ``CommitRequest`` model has no ``tags`` field, so ``--tags`` rides the
    post-commit path (``apply_publish_extras``) rather than this body.
    ``description`` maps to the model's ``summary`` attribute.
    """
    from geolens.models.commit_request import CommitRequest
    from geolens.types import UNSET

    summary: Any = description if description is not None else UNSET
    # CommitRequest also exposes title, visibility, x_column/y_column,
    # temporal_*, srid_override, etc. — those are out of scope for the MVP
    # publish command. Future flags can be added here without wider changes.
    return CommitRequest(title=title, summary=summary)


# ---------------------------------------------------------------------------
# Dataset URL construction (Task 0 Q1)
# ---------------------------------------------------------------------------


def construct_dataset_url(
    instance: str,
    *,
    dataset_id: Optional[str | UUID],
    job_id: str | UUID,
) -> str:
    """Build the user-facing URL for the freshly published dataset.

    Strategy (b) per Task 0 Q1:
      - If ``dataset_id`` was resolved (via ``GET /jobs/{job_id}`` poll),
        emit the canonical ``<instance>/datasets/<dataset_id>`` URL.
      - Otherwise, fall back to ``<instance>/datasets?job_id=<job_id>``
        which the GeoLens record list can filter on. The user can also
        re-resolve manually via ``GET /jobs/<job_id>`` later.

    fix(#588): the stored instance is always ``/api``-suffixed
    (``normalize_instance_url`` canonicalizes it that way for credential
    lookup), so this printed a JSON API endpoint instead of the browser
    page. Drop that one trailing PATH segment — parsed, not string-
    trimmed, so a host literally named ``api`` is untouched.
    """
    base = _web_origin(instance)
    if dataset_id:
        return f"{base}/datasets/{dataset_id}"
    return f"{base}/datasets?job_id={job_id}"


def _web_origin(instance: str) -> str:
    """Strip the canonical trailing ``/api`` path segment for display URLs."""
    parts = urlsplit(instance.rstrip("/"))
    if not parts.scheme or not parts.netloc:
        # Not a parseable absolute URL — leave it alone rather than mangle it.
        return instance.rstrip("/")
    path = parts.path.rstrip("/")
    if path.endswith("/api"):
        path = path[: -len("/api")]
    elif path == "/api":
        path = ""
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


# ---------------------------------------------------------------------------
# Job-status poll (job_id → dataset_id resolution)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PollOutcome:
    """Result of a ``resolve_dataset_id`` poll.

    fix(#1778, codex round 3): the old ``Optional[str]`` return collapsed a
    real 120s timeout, a terminal job status, a transient poll failure and
    an expired token into the same bare ``None`` — a caller could only
    guess which one happened by making a SECOND, independent request
    (``analysis.job_snapshot``) and trusting ITS status, which can legally
    disagree with what actually stopped the original poll (a transient 500
    followed by a lucky ``pending`` re-read read as "still running after
    120s", which was never true). This return type carries the real reason
    instead, so callers never have to guess.

    ``dataset_id`` is set only on success, in which case every other field
    is None. Otherwise ``stopped_because`` explains why there is no
    dataset_id:

    - ``"terminal"``: the job reached a status in
      ``_TERMINAL_NO_DATASET_STATUSES`` (failed/cancelled/fanned_out) —
      ``status`` carries which one.
    - ``"timeout"``: the deadline was reached while the job was still
      pending/running — ``status`` carries the last status read.
    - ``"token_expired"``: a job-status request came back 401/403.
    - ``"poll_failed"``: a job-status request failed some other way (a
      non-200/401/403 status, or a response body that could not be parsed)
      — ``detail`` names the failure (an HTTP status or error text), and
      ``http_status`` carries the numeric status when the failure was a
      real HTTP response (fix(#1778, codex round 7): a caller must be able
      to tell a 5xx from a 404 to select the CLI's own EXIT_SERVER vs
      EXIT_GENERIC per the matrix in ``_sdk_helpers.unwrap()`` — collapsing
      every poll_failed into EXIT_GENERIC hid a server outage from scripts
      that check the exit code). ``None`` when there was no real response
      to classify (an invalid job id, or a 200 with an unparseable body).
    """

    dataset_id: Optional[str] = None
    status: Optional[str] = None
    stopped_because: Optional[str] = None
    detail: Optional[str] = None
    http_status: Optional[int] = None


def poll_failed_exit_code(http_status: Optional[int]) -> int:
    """Exit code for a "poll_failed" PollOutcome (fix(#1778, codex round 7)).

    Mirrors the status-to-exit-code matrix ``_sdk_helpers.unwrap()`` already
    uses for every other SDK response in this CLI: 5xx maps to EXIT_SERVER,
    anything else to EXIT_GENERIC. 401/403 never reach here — the poll
    reports those as "token_expired", not "poll_failed" — and a missing
    ``http_status`` (an invalid job id, or a 200 with an unparseable body)
    has no server-error signal to preserve, so it falls back to generic.
    """
    if http_status is not None and 500 <= http_status <= 599:
        return EXIT_SERVER
    return EXIT_GENERIC


def resolve_dataset_id(
    client: Any,
    job_id: str | UUID,
    *,
    interval: float = _DEFAULT_POLL_INTERVAL_SECONDS,
    timeout: float = _DEFAULT_POLL_TIMEOUT_SECONDS,
    sleep: Any = time.sleep,
    monotonic: Any = time.monotonic,
) -> PollOutcome:
    """Poll ``GET /jobs/{job_id}`` until the dataset_id materializes.

    Returns a ``PollOutcome`` — see its docstring for the full shape. A
    caller that must tell a real timeout apart from a transient read
    failure or an expired token no longer has to make a second request and
    guess: ``stopped_because`` says which one happened, from THIS poll, not
    a possibly-contradictory follow-up read.

    fix(#1778 review round 7): a single poll REQUEST timing out (the 5s
    per-request bound) is retried — logged at debug and slept past —
    rather than aborting the whole operation immediately; a busy DB
    pool making one ``GET /jobs/{job_id}`` slow doesn't mean the
    operation itself is unhealthy, and the caller's own ``timeout``
    deadline still has the final say. Only once that deadline is
    reached WHILE a request is timing out does this exit
    ``typer.Exit(EXIT_NETWORK)`` (naming the deadline in the message) —
    a real network failure (connection refused/reset, as opposed to a
    slow response) still exits immediately, unchanged.

    ``sleep`` and ``monotonic`` are injectable so tests can run with zero
    real-time delay.
    """
    from geolens.api.admin import get_job_status_jobs_job_id_get
    from geolens.models.problem_detail import ProblemDetail

    # The SDK's job-status function accepts a UUID; coerce string → UUID
    # so callers can pass either type.
    if not isinstance(job_id, UUID):
        try:
            uuid_arg = UUID(str(job_id))
        except ValueError:
            return PollOutcome(
                stopped_because="poll_failed", detail=f"invalid job id: {job_id!r}"
            )
    else:
        uuid_arg = job_id

    last_status: Optional[str] = None
    transport = client.get_httpx_client()
    original_timeout = transport.timeout
    # fix(#1778, #1787): AppState.sdk() bounds every request to a default
    # 30s now, but a caller-supplied `timeout` (or analysis materialize's
    # POLL_FOREVER) can be far longer than that — bind each INDIVIDUAL
    # poll request to the same short bound already used for the one-shot
    # follow-up read of this identical endpoint
    # (_SNAPSHOT_REQUEST_TIMEOUT_SECONDS), so a single stalled connection
    # can't outlive the whole --wait the way it previously could (the
    # deadline below is only checked BETWEEN polls). Restored
    # unconditionally: publish()'s Stage 5 (--tags/--collection) and
    # materialize's own follow-up read both reuse this same client
    # afterward (fix(#1778, codex round 6) regression shape).
    transport.timeout = min(timeout, _SNAPSHOT_REQUEST_TIMEOUT_SECONDS)
    try:
        deadline = monotonic() + timeout
        while monotonic() < deadline:
            # BUG-034: route the poll through call_sdk so a network failure during
            # post-commit polling maps to EXIT_NETWORK (4) per D-32 rather than a
            # raw httpx traceback + exit 1.
            #
            # fix(#1778 review round 7, shared via round 8's poll_until):
            # a per-request timeout (the 5s snapshot bound above) is
            # routine under load — a busy DB pool can make one
            # GET /jobs/{job_id} slow without the overall operation
            # being unhealthy. poll_until() retries it (logged at
            # debug, slept past) as long as THIS loop's own deadline
            # (not call_sdk's) hasn't passed yet. A genuine network
            # failure (connection refused/reset) still exits
            # immediately via call_sdk, unchanged from before.
            try:
                resp = poll_until(
                    lambda: call_sdk(
                        get_job_status_jobs_job_id_get.sync_detailed,
                        job_id=uuid_arg,
                        client=client,
                        reraise_timeout=True,
                    ),
                    deadline=deadline,
                    interval=interval,
                    sleep=sleep,
                    monotonic=monotonic,
                )
            except PollDeadlineExceeded:
                typer.secho(
                    f"Request timed out repeatedly; giving up after the "
                    f"{timeout:.0f}s deadline.",
                    fg="red",
                    err=True,
                )
                raise typer.Exit(EXIT_NETWORK) from None
            code = int(resp.status_code)
            if code in (401, 403):
                return PollOutcome(status=last_status, stopped_because="token_expired")
            if code != JOB_STATUS_OK_STATUS:
                # Some other non-200 (server error, 404, ...) — give up rather
                # than spend the whole deadline retrying a status the caller
                # should decide how to handle. http_status is carried so the
                # caller can select EXIT_SERVER for a 5xx rather than the
                # generic exit code (fix(#1778, codex round 7)).
                return PollOutcome(
                    status=last_status,
                    stopped_because="poll_failed",
                    detail=f"HTTP {code}",
                    http_status=code,
                )
            if isinstance(resp.parsed, ProblemDetail):
                return PollOutcome(
                    status=last_status,
                    stopped_because="poll_failed",
                    detail=resp.parsed.detail or "unexpected response body",
                )
            parsed = resp.parsed
            status = getattr(parsed, "status", None)
            dataset_id = getattr(parsed, "dataset_id", None)
            last_status = status
            # Terminal success: dataset_id materialized.
            if dataset_id:
                return PollOutcome(dataset_id=str(dataset_id), status=status)
            # fix(#1778): "cancelled" and "fanned_out" were missing from the
            # terminal set, so --wait kept polling until timeout instead of
            # stopping as soon as the job's fate was known.
            if status in _TERMINAL_NO_DATASET_STATUSES:
                return PollOutcome(status=status, stopped_because="terminal")
            # fix(#1778 review round 16): capped to the time actually
            # remaining, matching wait_for_refresh's own outer sleep and
            # poll_until's fixed inner one -- a bare sleep(interval) here
            # was harmless for correctness (the `while monotonic() <
            # deadline:` guard at the top already stops a late fetch),
            # but could oversleep well past the deadline before this
            # loop noticed, for no reason once `interval` exceeds the
            # time actually left.
            remaining = deadline - monotonic()
            if remaining <= 0:
                break
            sleep(min(interval, remaining))
        return PollOutcome(status=last_status, stopped_because="timeout")
    finally:
        transport.timeout = original_timeout


# ---------------------------------------------------------------------------
# Duplicate-commit detection + handler (Pitfall 6)
# ---------------------------------------------------------------------------


def is_duplicate_commit_response(resp: Any) -> bool:
    """Return True iff the commit response is the "already processed" path.

    Defensive on both 400 and 409 because the backend currently uses 400
    (router.py:593-597) but the SDK parses both. Detail-text matching
    avoids false positives from other 400s (e.g., body validation).
    """
    from geolens.models.problem_detail import ProblemDetail

    sc = int(resp.status_code)
    if sc not in COMMIT_DUPLICATE_STATUSES:
        return False
    parsed = resp.parsed
    if not isinstance(parsed, ProblemDetail):
        return False
    detail = (parsed.detail or "").lower()
    return _DUPLICATE_DETAIL_NEEDLE in detail


def handle_commit_already_processed(job_id: str, output: Any) -> None:
    """Per Pitfall 6: commit is not idempotent. Print + exit cleanly."""
    output.error(f"Job {job_id} was already committed (resume not supported in MVP)")
    raise typer.Exit(EXIT_GENERIC)


# ---------------------------------------------------------------------------
# Post-commit extras — --tags / --collection wiring (fix(#569))
# ---------------------------------------------------------------------------


def _split_tags(tags_csv: str) -> list[str]:
    """Split a comma-separated tag list, trimming blanks and duplicates."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in tags_csv.split(","):
        tag = raw.strip()
        key = tag.lower()
        if not tag or key in seen:
            continue
        seen.add(key)
        out.append(tag)
    return out


def _resolve_record_id(client: Any, dataset_id: str) -> UUID | str:
    """Fetch the dataset's parent catalog record id.

    The keyword API is record-scoped and ``Dataset.id != Dataset.record_id``
    — fix(#588): posting the dataset id returns 404 "Record not found" on
    every tagged publish. Returns a UUID, or a failure description string.
    """
    from geolens.api.datasets import (
        get_single_dataset_datasets_dataset_id_get as _get,
    )

    resp = call_sdk(_get.sync_detailed, dataset_id=UUID(dataset_id), client=client)
    record_id = getattr(resp.parsed, "record_id", None)
    if int(resp.status_code) != 200 or record_id is None:
        return f"record lookup failed: HTTP {int(resp.status_code)}"
    return record_id


def _apply_tags(client: Any, dataset_id: str, tags_csv: str) -> list[str]:
    """POST each tag as a record keyword. Returns failure descriptions."""
    from geolens.api.records import (
        create_keyword_endpoint_records_record_id_keywords_post as _kw,
    )
    from geolens.models.keyword_create import KeywordCreate

    record_id = _resolve_record_id(client, dataset_id)
    if isinstance(record_id, str):
        return [record_id]

    failures: list[str] = []
    for tag in _split_tags(tags_csv):
        resp = call_sdk(
            _kw.sync_detailed,
            record_id=record_id,
            client=client,
            body=KeywordCreate(keyword=tag),
        )
        if int(resp.status_code) != 201:
            failures.append(f"tag {tag!r}: HTTP {int(resp.status_code)}")
    return failures


def _resolve_collection_id(client: Any, collection_ref: str) -> UUID | str:
    """Resolve --collection to a collection id.

    Accepts a UUID directly; otherwise matches the collection NAME
    (case-insensitive, exact). Returns a UUID on success or a failure
    description string.
    """
    try:
        return UUID(collection_ref)
    except ValueError:
        pass

    from geolens.api.datasets import (
        list_collections_endpoint_catalog_collections_get as _list,
    )

    wanted = collection_ref.strip().lower()
    matches: list[UUID] = []
    skip = 0
    page = 100
    while True:
        resp = call_sdk(_list.sync_detailed, client=client, skip=skip, limit=page)
        if int(resp.status_code) != 200 or resp.parsed is None:
            return f"collection lookup failed: HTTP {int(resp.status_code)}"
        collections = getattr(resp.parsed, "collections", []) or []
        matches.extend(c.id for c in collections if c.name.strip().lower() == wanted)
        if len(collections) < page:
            break
        skip += page
    if not matches:
        return f"collection {collection_ref!r} not found (pass its id or exact name)"
    if len(matches) > 1:
        return f"collection name {collection_ref!r} is ambiguous ({len(matches)} matches) — pass its id"
    return matches[0]


def _apply_collection(client: Any, dataset_id: str, collection_ref: str) -> list[str]:
    """Add the dataset to the referenced collection. Returns failures."""
    from geolens.api.datasets import (
        add_datasets_endpoint_catalog_collections_collection_id_datasets_post as _add,
    )
    from geolens.models.collection_add_datasets_request import (
        CollectionAddDatasetsRequest,
    )

    resolved = _resolve_collection_id(client, collection_ref)
    if isinstance(resolved, str):
        return [resolved]
    resp = call_sdk(
        _add.sync_detailed,
        collection_id=resolved,
        client=client,
        body=CollectionAddDatasetsRequest(dataset_ids=[UUID(dataset_id)]),
    )
    if int(resp.status_code) != 200:
        return [f"collection add: HTTP {int(resp.status_code)}"]
    return []


def _guard(label: str, run: Any) -> list[str]:
    """Run one post-commit extra, converting ANY raise into a failure line.

    fix(#588): ``call_sdk`` maps httpx timeouts/network errors to
    ``typer.Exit(EXIT_NETWORK)``. Propagating that from here would abort
    the command before the dataset URL and job id are printed — losing the
    recovery info for a dataset that WAS created. Every failure becomes
    data instead, so ``apply_publish_extras`` never raises.
    """
    try:
        return run()
    except Exception as exc:  # noqa: BLE001 — see docstring: nothing may escape
        if isinstance(exc, typer.Exit):
            # call_sdk already printed the cause (e.g. "Network error: ...").
            return [f"{label}: request failed (exit code {exc.exit_code})"]
        return [f"{label}: {type(exc).__name__}: {exc}"]


def apply_publish_extras(
    client: Any,
    dataset_id: str,
    tags_csv: Optional[str],
    collection_ref: Optional[str],
) -> list[str]:
    """Apply post-commit --tags / --collection. Returns failure descriptions.

    Never raises. The dataset already exists by the time this runs — callers
    must report failures WITHOUT implying the publish itself failed, then
    exit non-zero so scripts notice the partial result.

    The caller's non-zero exit is deliberately EXIT_GENERIC even for
    transport failures: re-running `publish` would upload the file again
    and create a DUPLICATE dataset, so this must not look retryable the
    way EXIT_NETWORK does.
    """
    failures: list[str] = []
    if tags_csv:
        failures.extend(
            _guard("tags", lambda: _apply_tags(client, dataset_id, tags_csv))
        )
    if collection_ref:
        failures.extend(
            _guard(
                "collection",
                lambda: _apply_collection(client, dataset_id, collection_ref),
            )
        )
    return failures
