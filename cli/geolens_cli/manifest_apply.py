# SPDX-License-Identifier: Apache-2.0
"""Networked manifest apply helpers for `geolens apply`."""

from __future__ import annotations

import copy
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from ._sdk_helpers import (
    EXIT_AUTH,
    EXIT_BLOCKED,
    EXIT_GENERIC,
    EXIT_NETWORK,
    EXIT_SERVER,
    EXIT_USAGE,
    EXTENDED_REQUEST_TIMEOUT_SECONDS,
    call_sdk,
    long_request_timeout,
)

APPLY_ENDPOINT = "/ingest/manifest/apply"
_COUNT_KEYS = ("create", "update", "skip", "blocked", "error")

# The fixed 600s long-request bound (EXTENDED_REQUEST_TIMEOUT_SECONDS) can
# expire during an apply that is still succeeding. ManifestApplyRequest allows
# up to 100 datasets (backend/app/processing/ingest/manifest_schemas.py) and
# apply_manifest() resolves them sequentially (manifest_service.py). Each
# entry's dominant synchronous cost is its HTTP source download
# (`_download_http_source()` uses `make_safe_client(timeout=60.0)`); the entry
# is then written to the DB and its ingest job queued, with the GDAL/ogrinfo
# conversion left to the background worker. A manifest of many slow sources can
# therefore take well past 600s while every entry succeeds, so the bound scales
# with the entry count.
#
# That 60s is httpx's inactivity (read) timeout between chunks, not a total
# download deadline: a large source served slowly but steadily can run far
# longer. The formula below is a heuristic lower bound, not a guarantee;
# `--timeout`/`GEOLENS_MANIFEST_APPLY_TIMEOUT` (see `resolve_apply_timeout` and
# the `apply` command in main.py) override it, and `--timeout 0` removes the
# client-side timeout.

#: The backend's per-source HTTP download inactivity (read) timeout (see the
#: comment above): the dominant synchronous cost per manifest entry, and only a
#: heuristic lower bound. Not OGRINFO_TIMEOUT_SECONDS (300s), which bounds the
#: ingest/reupload preview probe already covered by
#: `_sdk_helpers.LONG_RUNNING_SDK_FUNCTIONS`; manifest apply never runs ogrinfo
#: inline.
MANIFEST_SOURCE_DOWNLOAD_TIMEOUT_SECONDS: float = 60.0

#: A per-entry buffer for the classification/authorization queries, quota
#: checks and DB insert+commit around the download. No backend constant exists
#: for this overhead; it is a round, conservative estimate.
MANIFEST_ENTRY_PROCESSING_MARGIN_SECONDS: float = 10.0

#: The base budget for a small manifest; reuses the fixed long-request bound so
#: few or fast entries are unaffected by the per-entry scaling.
MANIFEST_APPLY_BASE_TIMEOUT_SECONDS: float = EXTENDED_REQUEST_TIMEOUT_SECONDS

#: The post-timeout dry-run status check (``attempt_apply_timeout_status_check``)
#: does not need the entry-scaled budget: ``dry_run`` short-circuits before any
#: download/queue work (see ``MANIFEST_SOURCE_DOWNLOAD_TIMEOUT_SECONDS``), so
#: its cost does not grow with entry count. A short fixed bound keeps a stuck
#: server from making the check hang as long as a maximum-sized apply could
#: legitimately need (up to 7600s for 100 entries).
MANIFEST_APPLY_STATUS_CHECK_TIMEOUT_SECONDS: float = 30.0


def compute_manifest_apply_timeout(entry_count: int) -> float:
    """Batch-aware timeout budget, in seconds, for an apply POST sending
    ``entry_count`` dataset entries: a heuristic lower bound, not a guarantee
    the apply finishes within it.

    ``budget = MANIFEST_APPLY_BASE_TIMEOUT_SECONDS + entry_count *
    (MANIFEST_SOURCE_DOWNLOAD_TIMEOUT_SECONDS +
    MANIFEST_ENTRY_PROCESSING_MARGIN_SECONDS)``; see the comment above the
    constants for the rationale and the backend facts it mirrors.

    ``entry_count`` should be ``len(payload["datasets"])`` for the manifest
    being sent. It is linear with no separate ceiling: the backend's cap of 100
    datasets already bounds the worst case at
    ``MANIFEST_APPLY_BASE_TIMEOUT_SECONDS + 100 * 70 == 7600.0``, and a smaller
    ceiling would let a valid maximum-sized manifest of slow sources time out
    with earlier entries already queued. Nothing downstream re-clamps the
    value: ``long_request_timeout()`` assigns it straight to the httpx client.

    ``MANIFEST_SOURCE_DOWNLOAD_TIMEOUT_SECONDS`` (60s) is a per-chunk
    inactivity timeout, so a large source served slowly but steadily can take
    far longer than 70s per entry without failing. The formula is therefore a
    default for the common case; ``resolve_apply_timeout`` (the ``apply``
    command's ``--timeout``/``GEOLENS_MANIFEST_APPLY_TIMEOUT``) overrides it.

    A count above 100 still computes linearly; the backend rejects it on its own
    schema validation. A count below 1 is coerced to 1 so a malformed count
    still returns at least the base budget.
    """
    entry_count = max(1, entry_count)
    per_entry = (
        MANIFEST_SOURCE_DOWNLOAD_TIMEOUT_SECONDS
        + MANIFEST_ENTRY_PROCESSING_MARGIN_SECONDS
    )
    return MANIFEST_APPLY_BASE_TIMEOUT_SECONDS + entry_count * per_entry


def _entry_count(payload: Mapping[str, Any]) -> int:
    """The number of dataset entries in an apply payload, for
    ``compute_manifest_apply_timeout``. 1 if ``datasets`` is missing or
    malformed; schema validation already rejects that before this POSTs."""
    datasets = payload.get("datasets")
    if isinstance(datasets, Sequence) and not isinstance(datasets, (str, bytes)):
        return max(1, len(datasets))
    return 1


class ManifestApplyTimeoutValueError(ValueError):
    """Raised by ``resolve_apply_timeout`` for a negative
    ``--timeout``/``GEOLENS_MANIFEST_APPLY_TIMEOUT`` value. A distinct type so
    ``main.py`` can map exactly this to ``EXIT_USAGE`` without swallowing an
    unrelated ``ValueError`` from the same ``try`` block."""


def resolve_apply_timeout(raw: float | None) -> float | None | Any:
    """Translate an already-parsed ``--timeout``/
    ``GEOLENS_MANIFEST_APPLY_TIMEOUT`` value into ``post_manifest_apply()``'s
    ``timeout=`` kwarg shape.

    ``raw`` is whatever click resolved: its ``envvar=`` precedence already makes
    the flag win over the env var, and its float coercion rejects a non-numeric
    value from either source. This function only does the domain translation:

    - ``raw is None``: neither was given; returns ``_UNSET`` so
      ``post_manifest_apply`` falls back to ``compute_manifest_apply_timeout``.
    - ``raw == 0``: an explicit request for no client-side read timeout;
      returns ``None`` (forwarded to ``long_request_timeout()``, which keeps the
      connect phase bounded).
    - any other non-negative value: returned as-is, overriding the formula.
    - negative: raises ``ManifestApplyTimeoutValueError``; click's float
      coercion cannot express "non-negative only".
    """
    if raw is None:
        return _UNSET
    # click's float coercion parses "nan", "inf" and overflowing literals like
    # "1e309" (which rounds to inf). `raw < 0` lets nan through (every NaN
    # comparison is False), and inf would reach `long_request_timeout()` as a
    # silently unbounded timeout that bypassed the documented `--timeout 0`
    # path. Rejected like analysis.py's require_finite() and main.py's other
    # `--timeout` checks.
    if not math.isfinite(raw):
        raise ManifestApplyTimeoutValueError(
            f"--timeout must be 0 or a positive, finite number of seconds, got {raw!r}."
        )
    if raw < 0:
        raise ManifestApplyTimeoutValueError(
            f"--timeout must be 0 or a positive number of seconds, got {raw!r}."
        )
    if raw == 0:
        return None
    return raw

#: URI schemes the backend manifest-apply path fetches server-side. Anything
#: without one of these schemes is a LOCAL relative path that must already
#: exist under the server's upload_staging_dir — `apply` never transfers it.
_REMOTE_URI_SCHEMES = frozenset({"http", "https", "s3"})


def find_local_source_uris(document: Mapping[str, Any]) -> list[str]:
    """Return manifest source URIs that point at LOCAL (relative) paths.

    `geolens apply` only POSTs the manifest JSON — it never uploads
    the files those sources reference. The backend resolves a scheme-less
    ``uri`` against its own ``upload_staging_dir``, so a local path in the
    manifest is silently unresolved unless the operator pre-staged it. We
    surface these up front so the user is told to use ``geolens publish``
    instead of getting opaque backend skips/errors.

    A URI is treated as local when it has no recognized remote scheme
    (http/https/s3). Matches the backend classifier in
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


class _Unset:
    """Sentinel distinguishing "no timeout override given" (compute the
    heuristic formula) from an explicit ``None`` (--timeout 0 -- no
    client-side read timeout at all). A
    bare ``None`` default cannot carry that distinction since ``None``
    IS one of the two meaningful values here."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return "<unset>"


_UNSET = _Unset()


class ManifestApplyTimeout(Exception):
    """Raised when the apply POST itself times out and no response body ever
    arrived, unlike ``ManifestApplyRequestError`` (a response arrived and was
    an error).

    Carries ``entry_count``/``budget`` so ``report_apply_timeout`` can build its
    message without recomputing them.

    ``budget`` is ``None`` when the operator asked for no client-side read
    timeout (``--timeout 0``) and a connect, write or pool timeout still fired.
    """

    def __init__(self, *, entry_count: int, budget: float | None) -> None:
        if budget is None:
            budget_text = "with no client-side read timeout (--timeout 0)"
        else:
            budget_text = f"after {budget:.0f}s"
        super().__init__(
            f"Manifest apply request timed out {budget_text} "
            f"({entry_count} dataset(s) submitted)."
        )
        self.entry_count = entry_count
        self.budget = budget
        # Same shape as ManifestApplyRequestError.exit_code, so main.py's
        # `apply` handles both uniformly.
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


def post_manifest_apply(
    client: Any,
    payload: Mapping[str, Any],
    *,
    timeout: float | None | _Unset = _UNSET,
) -> dict[str, Any]:
    """POST a validated manifest through the SDK-owned HTTP client.

    The backend validates and applies the manifest (create/update/skip/error
    per dataset) before responding, which can outlast AppState.sdk()'s plain
    30s bound for a manifest with many datasets. Wrapped in
    ``long_request_timeout()``.

    The default timeout is batch-aware (``compute_manifest_apply_timeout``; see
    the comment above ``MANIFEST_SOURCE_DOWNLOAD_TIMEOUT_SECONDS``). A timeout
    raises ``ManifestApplyTimeout``, not a raw ``typer.Exit``, so the caller can
    report the batch size and that the server keeps applying
    (``report_apply_timeout``).

    ``timeout`` overrides the batch-aware budget. Three states, since the
    computed heuristic is only a lower bound and an operator must be able to ask
    for no timeout at all:

    - omitted (``_UNSET``): compute the batch-aware formula.
    - ``None``: no client-side read timeout (``--timeout 0``), forwarded to
      ``long_request_timeout()``, which keeps the connect phase bounded.
    - a ``float``: exactly that many seconds. The post-timeout dry-run status
      check uses a short fixed ``MANIFEST_APPLY_STATUS_CHECK_TIMEOUT_SECONDS``
      because dry_run does no download/queue work.
    """
    entry_count = _entry_count(payload)
    if timeout is _UNSET:
        budget: float | None = compute_manifest_apply_timeout(entry_count)
    else:
        budget = timeout
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

    The CLI giving up does not stop the server, which
    reserves each entry before fetching, so a re-apply attaches or skips.
    """
    budget_phrase = (
        "with no client-side timeout"
        if exc.budget is None
        else f"after {exc.budget:.0f}s"
    )
    return (
        f"Manifest apply timed out {budget_phrase} "
        f"({exc.entry_count} dataset(s) submitted). The server does "
        "NOT stop applying when this request does -- it keeps "
        "processing the manifest sequentially. Every entry it has "
        "reached is recorded before its source is downloaded, so "
        "re-running this exact command attaches to an entry still "
        "being staged and skips one already queued or completed. Run "
        "`geolens apply --dry-run <path>` to see which entries the "
        "server has already settled. Or re-run with `--timeout 0` to "
        "wait for the server, or a larger value, if the manifest's own "
        "sources are just legitimately slow."
    )


def attempt_apply_timeout_status_check(
    client: Any, payload: Mapping[str, Any]
) -> dict[str, Any] | None:
    """Best-effort dry-run follow-up after a ``ManifestApplyTimeout``, to
    report which entries the server had already reached. Returns ``None`` if
    the follow-up itself failed or timed out.

    ``dry_run=True`` on this endpoint classifies every entry
    (create/update/skip_complete/skip_in_flight) without downloading or queuing
    anything. An entry still being staged holds a reservation and classifies
    ``skip_in_flight``, so absence from the answer means the server had not
    reached it. Bounded by ``MANIFEST_APPLY_STATUS_CHECK_TIMEOUT_SECONDS``.

    Side-effect-free (no ``output`` printing) so a ``--json`` caller can build
    one structured payload; ``report_apply_timeout`` is the human-mode wrapper.

    Catches every failure shape, including the ``typer.Exit`` that ``call_sdk``
    raises for a plain network error: a failure here must degrade to "status
    unavailable" rather than crash a command already reporting an error.
    """
    status_payload = dict(payload)
    status_payload["dry_run"] = True
    try:
        return post_manifest_apply(
            client,
            status_payload,
            timeout=MANIFEST_APPLY_STATUS_CHECK_TIMEOUT_SECONDS,
        )
    except (ManifestApplyTimeout, ManifestApplyRequestError, typer.Exit, Exception):
        return None


def report_apply_timeout(
    client: Any,
    payload: Mapping[str, Any],
    exc: ManifestApplyTimeout,
    output: Any,
) -> dict[str, Any] | None:
    """Human-mode wrapper: prints the timeout explanation, attempts the dry-run
    status follow-up (``attempt_apply_timeout_status_check``) and warns if it
    could not be completed. Returns the status report (or ``None``).

    Not for ``--json``, whose single structured payload would be duplicated by
    ``output.error()``/``output.warn()``; main.py's json branch calls
    ``attempt_apply_timeout_status_check`` directly.
    """
    output.error(build_apply_timeout_message(exc))
    status = attempt_apply_timeout_status_check(client, payload)
    if status is None:
        output.warn(
            "Could not retrieve a completion status for this manifest "
            "right now (the status check itself failed or timed out "
            f"after {MANIFEST_APPLY_STATUS_CHECK_TIMEOUT_SECONDS:.0f}s). "
            "Re-running the same command is still the way forward: the "
            "server records each entry before downloading its source, "
            "so a re-apply attaches to one still being staged rather "
            "than queueing it again."
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
        "ok": bool(response.get("accepted"))
        and not has_apply_errors(response)
        and not has_blocked_results(response),
        "path": str(path),
        "results": response.get("results", []),
    }


def wait_for_apply_jobs(
    client: Any,
    response: Mapping[str, Any],
    *,
    instance: str,
    credential_kind: str,
    credential_provenance: str | None,
) -> dict[str, Any]:
    """Follow every queued job to its end and stamp each result with the outcome.

    A skip that names a job is an identical manifest already queued or finished,
    so its job is followed too. An update runs under a refresh run, found through
    the job that queued it. A job with no run (a first import) is followed through the job itself.
    ``final_status`` is one of complete, failed, blocked or cancelled.
    """
    from uuid import UUID

    from . import refresh as _refresh

    active_client = client

    def replace_client(replacement: Any) -> None:
        nonlocal active_client
        active_client = replacement

    waited = copy.deepcopy(dict(response))
    results = waited.get("results")
    if not isinstance(results, list):
        return waited
    for result in results:
        if not (
            isinstance(result, dict)
            and result.get("action") in {"create", "update", "skip"}
            and result.get("job_id")
        ):
            continue
        job_id = UUID(str(result["job_id"]))
        def follow_run(job_id=job_id, result=result):
            if not result.get("dataset_id"):
                return None
            try:
                return _refresh.wait_for_refresh_run(
                    active_client,
                    UUID(str(result["dataset_id"])),
                    None,
                    ingest_job_id=job_id,
                    instance=instance,
                    credential_kind=credential_kind,
                    credential_provenance=credential_provenance,
                    on_reauthenticated=replace_client,
                )
            except _refresh.RefreshRequestError:
                return None

        poll = follow_run()
        if poll is None:
            poll = _refresh.wait_for_refresh(
                active_client,
                job_id,
                instance=instance,
                credential_kind=credential_kind,
                credential_provenance=credential_provenance,
                on_reauthenticated=replace_client,
            )
            # The job can end before its run exists (a retry racing the original
            # request); a review hold shows only on the run, so look again.
            poll = follow_run() or poll
        result["final_status"] = "complete" if poll.succeeded else poll.status
        result["run_id"] = poll.run_id
        if poll.error_message:
            result["error_message"] = poll.error_message
        if poll.status == "blocked":
            result["review_reasons"] = _refresh.blocked_review_reasons(poll)
    return waited


def apply_exit_code(response: Mapping[str, Any]) -> int:
    """1 if anything errored or failed, else 6 if anything is blocked, else 0."""
    if has_apply_errors(response):
        return EXIT_GENERIC
    return EXIT_BLOCKED if has_blocked_results(response) else 0


def is_blocked(result: Any) -> bool:
    """True for an entry held for review: reported blocked, or followed to a hold."""
    return isinstance(result, Mapping) and "blocked" in (
        result.get("action"),
        result.get("final_status"),
    )


def has_blocked_results(response: Mapping[str, Any]) -> bool:
    """True when any entry is held for review."""
    results = response.get("results")
    return isinstance(results, list) and any(is_blocked(result) for result in results)


def has_apply_errors(response: Mapping[str, Any]) -> bool:
    """Return True when the backend rejected or any result is an error."""

    if response.get("accepted") is False:
        return True
    results = response.get("results")
    if not isinstance(results, list):
        return False
    return any(
        isinstance(result, Mapping)
        and (
            result.get("action") == "error"
            or result.get("final_status") in {"failed", "cancelled", "timed_out"}
        )
        for result in results
    )


def _cell(result: Mapping[str, Any], key: str) -> str:
    value = result.get(key)
    if value is None:
        return "-"
    if isinstance(value, list):
        return "; ".join(str(item) for item in value) or "-"
    return str(value)


def _message_key(result: Mapping[str, Any]) -> str:
    """A failed or cancelled follow-up shows why in place of the queued message."""
    failed = result.get("final_status") in {"failed", "cancelled"}
    return "error_message" if failed and result.get("error_message") else "message"


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
            f"skip={counts['skip']}, blocked={counts['blocked']}, "
            f"error={counts['error']})"
        ),
        soft_wrap=True,
        markup=False,
    )

    table = Table(title="Manifest apply results")
    table.add_column("DATASET", overflow="fold")
    table.add_column("ACTION")
    table.add_column("DATASET ID", overflow="fold")
    table.add_column("JOB ID", overflow="fold")
    results = response.get("results", [])
    waited = isinstance(results, list) and any(
        isinstance(result, Mapping) and "final_status" in result for result in results
    )
    if waited:
        table.add_column("STATUS")
    with_run = isinstance(results, list) and any(
        isinstance(result, Mapping) and result.get("run_id") for result in results
    )
    if with_run:
        table.add_column("RUN ID", overflow="fold")
    table.add_column("MESSAGE", overflow="fold")

    if isinstance(results, list):
        for result in results:
            if not isinstance(result, Mapping):
                continue
            table.add_row(
                *(
                    Text(_cell(result, key))
                    for key in (
                        "dataset_key",
                        "action",
                        "dataset_id",
                        "job_id",
                        *(("final_status",) if waited else ()),
                        *(("run_id",) if with_run else ()),
                        _message_key(result),
                    )
                )
            )

    console.print(table)
