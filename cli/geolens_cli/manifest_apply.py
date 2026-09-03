# SPDX-License-Identifier: Apache-2.0
"""Networked manifest apply helpers for `geolens apply`."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from rich.console import Console
from rich.table import Table

from ._sdk_helpers import (
    EXIT_AUTH,
    EXIT_GENERIC,
    EXIT_NETWORK,
    EXIT_SERVER,
    EXIT_USAGE,
    EXTENDED_REQUEST_TIMEOUT_SECONDS,
    call_sdk,
    long_request_timeout,
)

APPLY_ENDPOINT = "/ingest/manifest/apply"
_COUNT_KEYS = ("create", "update", "skip", "error")

# ---------------------------------------------------------------------------
# fix(#1778 review round 18): batch-aware apply timeout
# ---------------------------------------------------------------------------
#
# The FIXED 600s long-request bound (round 5, EXTENDED_REQUEST_TIMEOUT_SECONDS)
# can expire during a legitimately still-succeeding apply. ManifestApplyRequest
# allows up to 100 datasets (backend/app/processing/ingest/manifest_schemas.py,
# `datasets: list[ManifestDataset] = Field(min_length=1, max_length=100)`), and
# apply_manifest() processes them SEQUENTIALLY, one entry fully resolved before
# the next starts (backend/app/processing/ingest/manifest_service.py). Each
# entry's dominant SYNCHRONOUS cost is its own HTTP source download —
# `_download_http_source()` there uses `make_safe_client(timeout=60.0)` — after
# which the entry is written to the DB and its ingest job QUEUED (Procrastinate),
# not processed inline; the actual GDAL/ogrinfo conversion happens later in the
# background worker, off this request entirely. A manifest of many slow (near-
# 60s) sources can therefore legitimately take well past 600s even though every
# entry eventually succeeds — the bound must scale with how many entries THIS
# request is asking the server to resolve, not stay fixed.

#: Mirrors the backend's own per-source HTTP download timeout (see the module
#: docstring above) — the dominant synchronous cost per manifest entry. NOT
#: OGRINFO_TIMEOUT_SECONDS (300s): that bounds a DIFFERENT synchronous path,
#: the ingest/reupload PREVIEW probe, already covered by
#: `_sdk_helpers.LONG_RUNNING_SDK_FUNCTIONS`'s `ingest_preview`/
#: `reupload_preview` entries — manifest apply's own entries never run ogrinfo
#: inline.
MANIFEST_SOURCE_DOWNLOAD_TIMEOUT_SECONDS: float = 60.0

#: An estimated buffer per entry for the classification/authorization queries,
#: quota checks, and DB insert+commit that bracket the download — none
#: individually approaches the download's own bound, but a slow DB under load
#: can stack across many entries. Not tied to a specific backend constant
#: (there isn't one for this overhead); a round, conservative estimate.
MANIFEST_ENTRY_PROCESSING_MARGIN_SECONDS: float = 10.0

#: The base budget for a small manifest (a handful of entries) — reuses round
#: 5's original fixed bound so the common case (few entries, or entries that
#: return fast) is unaffected by this change.
MANIFEST_APPLY_BASE_TIMEOUT_SECONDS: float = EXTENDED_REQUEST_TIMEOUT_SECONDS

#: Ceiling on the batch-aware budget below. Mirrors OGR2OGR_FILE_TIMEOUT_SECONDS
#: (backend/app/processing/ingest/ogr.py) — this codebase's existing "a large
#: [operation] legitimately takes up to an hour" bound, reused here rather than
#: inventing a new number. A 100-entry manifest of maximally slow sources can
#: still exceed even this; see `ManifestApplyTimeout`/`report_apply_timeout`
#: below for what happens then — the cap bounds the CLI's own wait, not the
#: server's work, which continues regardless.
MANIFEST_APPLY_TIMEOUT_CEILING_SECONDS: float = 3600.0


def compute_manifest_apply_timeout(entry_count: int) -> float:
    """Batch-aware timeout budget, in seconds, for an apply POST sending
    ``entry_count`` dataset entries.

    ``budget = MANIFEST_APPLY_BASE_TIMEOUT_SECONDS + entry_count *
    (MANIFEST_SOURCE_DOWNLOAD_TIMEOUT_SECONDS +
    MANIFEST_ENTRY_PROCESSING_MARGIN_SECONDS)``, capped at
    ``MANIFEST_APPLY_TIMEOUT_CEILING_SECONDS``. See the module-level
    comment above this constant block for the full rationale and the
    backend facts it mirrors.

    ``entry_count`` should be ``len(payload["datasets"])`` for the
    manifest THIS invocation is actually sending — not a guess: the
    backend enforces a hard cap of 100 (ManifestApplyRequest.datasets),
    so the worst case this formula has to budget for is bounded too.
    Coerced to at least 1 so a malformed/empty count still returns the
    base budget rather than a smaller-than-intended one.
    """
    entry_count = max(1, entry_count)
    per_entry = (
        MANIFEST_SOURCE_DOWNLOAD_TIMEOUT_SECONDS
        + MANIFEST_ENTRY_PROCESSING_MARGIN_SECONDS
    )
    budget = MANIFEST_APPLY_BASE_TIMEOUT_SECONDS + entry_count * per_entry
    return min(budget, MANIFEST_APPLY_TIMEOUT_CEILING_SECONDS)


def _entry_count(payload: Mapping[str, Any]) -> int:
    """The number of dataset entries in an apply payload, for
    ``compute_manifest_apply_timeout``. 1 if ``datasets`` is missing or
    malformed — schema validation (offline, before this ever POSTs)
    already rejects that; this is just a safe fallback, not a second
    validation pass."""
    datasets = payload.get("datasets")
    if isinstance(datasets, Sequence) and not isinstance(datasets, (str, bytes)):
        return max(1, len(datasets))
    return 1

#: URI schemes the backend manifest-apply path fetches server-side. Anything
#: without one of these schemes is a LOCAL relative path that must already
#: exist under the server's upload_staging_dir — `apply` never transfers it.
_REMOTE_URI_SCHEMES = frozenset({"http", "https", "s3", "gs", "az", "abfs"})


def find_local_source_uris(document: Mapping[str, Any]) -> list[str]:
    """Return manifest source URIs that point at LOCAL (relative) paths.

    GAP-020: `geolens apply` only POSTs the manifest JSON — it never uploads
    the files those sources reference. The backend resolves a scheme-less
    ``uri`` against its own ``upload_staging_dir``, so a local path in the
    manifest is silently unresolved unless the operator pre-staged it. We
    surface these up front so the user is told to use ``geolens publish``
    instead of getting opaque backend skips/errors.

    A URI is treated as local when it has no recognized remote scheme
    (http/https/s3/gs/az/abfs). Matches the backend classifier in
    ``app.processing.ingest.manifest_sources.classify_manifest_source``.
    """
    local: list[str] = []
    datasets = document.get("datasets")
    if not isinstance(datasets, Sequence):
        return local
    for dataset in datasets:
        if not isinstance(dataset, Mapping):
            continue
        sources = dataset.get("sources")
        if not isinstance(sources, Sequence):
            continue
        for source in sources:
            if not isinstance(source, Mapping):
                continue
            uri = source.get("uri")
            if not isinstance(uri, str) or not uri:
                continue
            if urlsplit(uri).scheme.lower() not in _REMOTE_URI_SCHEMES:
                local.append(uri)
    return local


class ManifestApplyRequestError(Exception):
    """Raised when the backend apply request fails before a response body applies."""

    def __init__(self, message: str, *, exit_code: int) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code


class ManifestApplyTimeout(Exception):
    """Raised when the apply POST itself times out — no response body
    ever arrived, unlike ``ManifestApplyRequestError`` (a response DID
    arrive and it was itself an error).

    fix(#1778 review round 18): carries ``entry_count``/``budget`` so
    the caller (``report_apply_timeout``) can build an informative
    message without recomputing them, and so a test can assert on the
    values without re-deriving the formula."""

    def __init__(self, *, entry_count: int, budget: float) -> None:
        super().__init__(
            f"Manifest apply request timed out after {budget:.0f}s "
            f"({entry_count} dataset(s) submitted)."
        )
        self.entry_count = entry_count
        self.budget = budget
        # Same shape as ManifestApplyRequestError.exit_code -- lets
        # main.py's `apply` command handle both uniformly
        # (`raise typer.Exit(exc.exit_code)`) instead of hardcoding
        # EXIT_NETWORK a second time at the call site.
        self.exit_code = EXIT_NETWORK


def build_apply_payload(
    document: Mapping[str, Any], *, dry_run: bool
) -> dict[str, Any]:
    """Return the backend apply payload without mutating the loaded manifest."""

    payload = copy.deepcopy(dict(document))
    payload["dry_run"] = dry_run
    return payload


def _detail_from_response(response: Any) -> str:
    try:
        body = response.json()
    except ValueError:
        body = None

    if isinstance(body, Mapping):
        detail = body.get("detail") or body.get("message")
        if detail:
            if isinstance(detail, str):
                return detail
            return json.dumps(detail, sort_keys=True, default=str)

    text = getattr(response, "text", "")
    if isinstance(text, str) and text.strip():
        return text.strip()
    return "No response detail returned."


def _exit_code_for_status(status_code: int) -> int:
    if status_code in {401, 403}:
        return EXIT_AUTH
    if status_code == 422:
        return EXIT_USAGE
    if 500 <= status_code <= 599:
        return EXIT_SERVER
    return EXIT_GENERIC


def post_manifest_apply(client: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
    """POST a validated manifest through the SDK-owned HTTP client.

    fix(#1778 review round 5): the backend validates and applies the
    manifest (create/update/skip/error per dataset) before responding,
    which can outlast AppState.sdk()'s plain 30s bound for a manifest
    with many datasets. Wrapped in ``long_request_timeout()``.

    fix(#1778 review round 18): the timeout is now BATCH-AWARE
    (``compute_manifest_apply_timeout``) rather than the fixed round-5
    bound — see that function's docstring and the module-level comment
    above ``MANIFEST_SOURCE_DOWNLOAD_TIMEOUT_SECONDS`` for why a large
    manifest of slow sources can legitimately need more than 600s. A
    timeout now raises ``ManifestApplyTimeout`` (not a raw
    ``typer.Exit``) so the caller can report the round-18 part (b)/(c)
    guidance instead of a bare "Request timed out" — see
    ``report_apply_timeout``.
    """
    entry_count = _entry_count(payload)
    budget = compute_manifest_apply_timeout(entry_count)
    with long_request_timeout(client, timeout=budget) as httpx_client:
        response = call_sdk(
            httpx_client.post,
            url=APPLY_ENDPOINT,
            json=dict(payload),
            on_timeout=lambda: ManifestApplyTimeout(
                entry_count=entry_count, budget=budget
            ),
        )
    status_code = int(response.status_code)
    if status_code != 200:
        detail = _detail_from_response(response)
        raise ManifestApplyRequestError(
            f"Manifest apply request failed ({status_code}): {detail}",
            exit_code=_exit_code_for_status(status_code),
        )

    try:
        parsed = response.json()
    except ValueError as exc:
        raise ManifestApplyRequestError(
            "Manifest apply response was not valid JSON.",
            exit_code=EXIT_SERVER,
        ) from exc

    if not isinstance(parsed, Mapping):
        raise ManifestApplyRequestError(
            "Manifest apply response root was not a mapping.",
            exit_code=EXIT_SERVER,
        )
    return dict(parsed)


def build_apply_timeout_message(exc: ManifestApplyTimeout) -> str:
    """Human-readable explanation for a batch-aware apply timeout.

    fix(#1778 review round 18) part (b): the CLI giving up here does
    NOT mean the apply failed. ``apply_manifest()`` (backend/app/
    processing/ingest/manifest_service.py) keeps processing the
    manifest SEQUENTIALLY after this client stops waiting — a POST
    already accepted by the ASGI server runs to completion there
    regardless of whether the CLI is still listening, so entries
    already committed and queued stay committed and queued. Every
    entry is idempotent: the server fingerprints each dataset
    (``manifest_dataset_fingerprint``) and reports ``skip_complete``
    instead of reprocessing it once the SAME fingerprint is submitted
    again (``_classify_dataset`` in the same module). Re-running this
    exact ``geolens apply`` command is therefore always safe — entries
    the server already reached report ``skip_complete``/
    ``skip_in_flight``, and only entries it had not yet reached (or
    whose content actually changed) do real work.
    """
    return (
        f"Manifest apply timed out after {exc.budget:.0f}s "
        f"({exc.entry_count} dataset(s) submitted), but the server does "
        "NOT stop when this request does -- it continues applying the "
        "manifest sequentially in the background of that same request, "
        "and entries it already committed stay committed. Every entry "
        "is idempotent: the server fingerprints each dataset and "
        "reports skip_complete on a matching re-apply, so re-running "
        "this exact command is safe and resumes from wherever the "
        "server actually got to."
    )


def attempt_apply_timeout_status_check(
    client: Any, payload: Mapping[str, Any]
) -> dict[str, Any] | None:
    """Best-effort dry-run follow-up after a ``ManifestApplyTimeout``,
    to report which entries the server had already reached. Returns
    ``None`` if the follow-up itself failed or timed out.

    fix(#1778 review round 18) part (c): ``dry_run=True`` on this SAME
    endpoint already classifies every entry
    (create/update/skip_complete/skip_in_flight) WITHOUT downloading or
    queuing anything — ``_stage_source_if_needed`` (backend/app/
    processing/ingest/manifest_service.py) short-circuits before the
    network fetch when ``dry_run``. That makes it materially cheaper
    than the apply that just timed out, and it is EXACTLY the "which
    entries completed" answer: this PR does not add a separate status
    or job-listing endpoint (out of scope — no async job mode), because
    the existing dry-run classification on this same endpoint already
    covers the question. Best-effort: if the follow-up ALSO fails or
    times out, the entry-by-entry answer just was not available right
    now — the caller still knows re-running the ORIGINAL command is
    safe regardless (every entry is idempotent), which
    ``build_apply_timeout_message`` already said.

    Side-effect-free (no ``output`` printing) so a ``--json`` caller
    can build one clean structured payload from the result instead of
    inheriting rich-console/stderr writes meant for a human — see
    ``report_apply_timeout`` for that human-mode convenience wrapper.
    """
    status_payload = dict(payload)
    status_payload["dry_run"] = True
    try:
        return post_manifest_apply(client, status_payload)
    except (ManifestApplyTimeout, ManifestApplyRequestError):
        return None


def report_apply_timeout(
    client: Any,
    payload: Mapping[str, Any],
    exc: ManifestApplyTimeout,
    output: Any,
) -> dict[str, Any] | None:
    """Human-mode convenience: prints the round-18 timeout explanation,
    attempts the dry-run status follow-up
    (``attempt_apply_timeout_status_check``), and prints a warning if
    it could not be completed. Returns the status report (or ``None``).

    NOT for a ``--json`` caller: ``output.error()``/``output.warn()``
    write directly to stdout/stderr in a shape ``--json`` mode does not
    want duplicated alongside its own single structured payload —
    main.py's json branch calls ``attempt_apply_timeout_status_check``
    directly instead.
    """
    output.error(build_apply_timeout_message(exc))
    status = attempt_apply_timeout_status_check(client, payload)
    if status is None:
        output.warn(
            "Could not retrieve a completion status for this manifest "
            "right now (the status check itself failed or timed out). "
            "Re-running the command is still safe -- entries the "
            "server already reached will report skip_complete."
        )
    return status


def summarize_results(response: Mapping[str, Any]) -> dict[str, int]:
    """Count apply result actions in deterministic key order."""

    counts = dict.fromkeys(_COUNT_KEYS, 0)
    results = response.get("results")
    if not isinstance(results, list):
        return counts

    for result in results:
        if not isinstance(result, Mapping):
            continue
        action = result.get("action")
        if action in counts:
            counts[str(action)] += 1
    return counts


def apply_report_payload(path: Path, response: Mapping[str, Any]) -> dict[str, Any]:
    """Return deterministic JSON output for `geolens --json apply`."""

    return {
        "accepted": bool(response.get("accepted")),
        "counts": summarize_results(response),
        "dry_run": bool(response.get("dry_run")),
        "ok": bool(response.get("accepted")) and not has_apply_errors(response),
        "path": str(path),
        "results": response.get("results", []),
    }


def has_apply_errors(response: Mapping[str, Any]) -> bool:
    """Return True when the backend rejected or any result is an error."""

    if response.get("accepted") is False:
        return True
    results = response.get("results")
    if not isinstance(results, list):
        return False
    return any(
        isinstance(result, Mapping) and result.get("action") == "error"
        for result in results
    )


def _cell(result: Mapping[str, Any], key: str) -> str:
    value = result.get(key)
    if value is None:
        return "-"
    if isinstance(value, list):
        return "; ".join(str(item) for item in value) or "-"
    return str(value)


def render_apply_summary(
    console: Console,
    path: Path,
    response: Mapping[str, Any],
) -> None:
    """Render a human-readable apply result table."""

    counts = summarize_results(response)
    mode = "Dry run" if response.get("dry_run") else "Apply"
    console.print(
        (
            f"{mode}: {path} "
            f"(create={counts['create']}, update={counts['update']}, "
            f"skip={counts['skip']}, error={counts['error']})"
        ),
        soft_wrap=True,
    )

    table = Table(title="Manifest apply results")
    table.add_column("DATASET", overflow="fold")
    table.add_column("ACTION")
    table.add_column("DATASET ID", overflow="fold")
    table.add_column("JOB ID", overflow="fold")
    table.add_column("MESSAGE", overflow="fold")

    results = response.get("results", [])
    if isinstance(results, list):
        for result in results:
            if not isinstance(result, Mapping):
                continue
            table.add_row(
                _cell(result, "dataset_key"),
                _cell(result, "action"),
                _cell(result, "dataset_id"),
                _cell(result, "job_id"),
                _cell(result, "message"),
            )

    console.print(table)
