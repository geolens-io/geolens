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
from http import HTTPStatus
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

import typer

from ._sdk_helpers import EXIT_GENERIC, call_sdk

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

    httpx_client = client.get_httpx_client()
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


def resolve_dataset_id(
    client: Any,
    job_id: str | UUID,
    *,
    interval: float = _DEFAULT_POLL_INTERVAL_SECONDS,
    timeout: float = _DEFAULT_POLL_TIMEOUT_SECONDS,
    sleep: Any = time.sleep,
    monotonic: Any = time.monotonic,
) -> Optional[str]:
    """Poll ``GET /jobs/{job_id}`` until the dataset_id materializes.

    Returns the dataset_id as a string when ingestion completes successfully,
    or ``None`` on terminal failure / timeout (caller falls back to the
    job-search URL form).

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
            return None
    else:
        uuid_arg = job_id

    deadline = monotonic() + timeout
    while monotonic() < deadline:
        # BUG-034: route the poll through call_sdk so a network failure during
        # post-commit polling maps to EXIT_NETWORK (4) per D-32 rather than a
        # raw httpx traceback + exit 1.
        resp = call_sdk(
            get_job_status_jobs_job_id_get.sync_detailed,
            job_id=uuid_arg,
            client=client,
        )
        if int(resp.status_code) != JOB_STATUS_OK_STATUS:
            # Non-200 (auth error, server error, 404) — give up and let the
            # caller surface a fallback URL.
            return None
        if isinstance(resp.parsed, ProblemDetail):
            return None
        parsed = resp.parsed
        status = getattr(parsed, "status", None)
        dataset_id = getattr(parsed, "dataset_id", None)
        # Terminal success: dataset_id materialized.
        if dataset_id:
            return str(dataset_id)
        # Terminal failure: the worker explicitly marked the job failed.
        if status == "failed":
            return None
        sleep(interval)
    return None  # timeout — fall back to job-search URL


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
