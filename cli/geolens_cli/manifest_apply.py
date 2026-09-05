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
#
# fix(#1778 review round 21): that 60s figure is httpx's INACTIVITY (read)
# timeout on the download's streaming loop -- the time allowed between
# individual chunks arriving, reset on every chunk -- not a total download
# deadline. A large source served slowly but steadily (never idle long enough
# to trip the 60s inactivity bound on any single chunk) can legitimately run
# far longer than 60s in total while still actively succeeding. The formula
# below is therefore only ever a HEURISTIC LOWER BOUND, not a guarantee the
# apply finishes within it -- `--timeout`/`GEOLENS_MANIFEST_APPLY_TIMEOUT`
# (see `resolve_apply_timeout` and the `apply` command in main.py) let an
# operator override it outright, including removing the client-side timeout
# entirely (`--timeout 0`) to just wait for the server.

#: Mirrors the backend's own per-source HTTP download INACTIVITY (read)
#: timeout (see the module docstring above) — the dominant synchronous cost
#: per manifest entry, and only a HEURISTIC lower bound, not a deadline (round
#: 21: a steadily-but-slowly-served large source can legitimately exceed this
#: many times over while still actively succeeding). NOT OGRINFO_TIMEOUT_
#: SECONDS (300s): that bounds a DIFFERENT synchronous path, the ingest/
#: reupload PREVIEW probe, already covered by
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

#: fix(#1778 review round 19): the post-timeout dry-run status check
#: (``attempt_apply_timeout_status_check``) does not need the
#: entry-scaled budget above at all -- ``dry_run`` short-circuits
#: BEFORE any download/queue work (see
#: ``MANIFEST_SOURCE_DOWNLOAD_TIMEOUT_SECONDS``'s docstring), so its
#: own cost does not grow with entry count. A short, FIXED bound keeps
#: a stuck/overloaded server from making the status check itself hang
#: for as long as a maximum-sized ORIGINAL apply could legitimately
#: need (round 20: up to 7600s for a full 100-entry manifest, no
#: longer capped at an hour) -- this cheaper follow-up never should.
MANIFEST_APPLY_STATUS_CHECK_TIMEOUT_SECONDS: float = 30.0


def compute_manifest_apply_timeout(entry_count: int) -> float:
    """Batch-aware timeout budget, in seconds, for an apply POST sending
    ``entry_count`` dataset entries -- a HEURISTIC LOWER BOUND, not a
    guarantee the apply finishes within it (see below).

    ``budget = MANIFEST_APPLY_BASE_TIMEOUT_SECONDS + entry_count *
    (MANIFEST_SOURCE_DOWNLOAD_TIMEOUT_SECONDS +
    MANIFEST_ENTRY_PROCESSING_MARGIN_SECONDS)``. See the module-level
    comment above this constant block for the full rationale and the
    backend facts it mirrors.

    ``entry_count`` should be ``len(payload["datasets"])`` for the
    manifest THIS invocation is actually sending — not a guess. Linear
    in ``entry_count``, with NO separate ceiling: the backend's own
    hard cap of 100 datasets (ManifestApplyRequest.datasets,
    ``max_length=100`` — manifest_schemas.py) already bounds the
    worst case this formula ever has to produce, at
    ``MANIFEST_APPLY_BASE_TIMEOUT_SECONDS + 100 * 70 == 7600.0``.

    fix(#1778 review round 20): round 18 additionally clamped this to
    ``MANIFEST_APPLY_TIMEOUT_CEILING_SECONDS`` (3600s) — an ad hoc
    number smaller than the formula's own maximum (7600s), so the
    clamp started truncating the budget at ~43 entries, well inside
    the API's permitted 100. A valid, maximum-sized manifest of slow
    sources could still time out with earlier entries already queued.
    Removed: nothing downstream re-clamps the value this function
    returns (``long_request_timeout()`` assigns it straight to the
    httpx client's ``.timeout``; httpx does not impose its own ceiling
    on that assignment), so the bound this function computes is the
    bound the request actually gets.

    fix(#1778 review round 21): ``MANIFEST_SOURCE_DOWNLOAD_TIMEOUT_
    SECONDS`` (60s) is the backend's per-chunk INACTIVITY timeout on
    the download's streaming loop, not a total download deadline — a
    large source served slowly but steadily can legitimately take far
    longer than 70s (60 + the processing margin) per entry while never
    tripping that inactivity bound and never failing. This formula
    therefore cannot be a guarantee for every valid manifest, only a
    reasonable default for the common case; ``resolve_apply_timeout``
    (used by the ``apply`` command's ``--timeout``/
    ``GEOLENS_MANIFEST_APPLY_TIMEOUT``) lets an operator override it
    outright, including removing the client-side timeout entirely.

    If a caller somehow passes more than 100, the formula still
    computes linearly rather than pretending — the backend will reject
    the request on its own schema validation regardless; this
    function's job is only to not be the reason a VALID request times
    out sooner than it has to. Coerced to at least 1 so a malformed/
    empty count still returns the base budget rather than a smaller-
    than-intended one.
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
    malformed — schema validation (offline, before this ever POSTs)
    already rejects that; this is just a safe fallback, not a second
    validation pass."""
    datasets = payload.get("datasets")
    if isinstance(datasets, Sequence) and not isinstance(datasets, (str, bytes)):
        return max(1, len(datasets))
    return 1


class ManifestApplyTimeoutValueError(ValueError):
    """Raised by ``resolve_apply_timeout`` for an out-of-range
    ``--timeout``/``GEOLENS_MANIFEST_APPLY_TIMEOUT`` value (negative).
    A distinct type (not a bare ``ValueError``) so ``main.py`` can
    catch exactly this and map it to ``EXIT_USAGE`` without also
    swallowing an unrelated ``ValueError`` from somewhere else in the
    same ``try`` block."""


def resolve_apply_timeout(raw: float | None) -> float | None | Any:
    """Translate an already-parsed ``--timeout``/
    ``GEOLENS_MANIFEST_APPLY_TIMEOUT`` value into
    ``post_manifest_apply()``'s ``timeout=`` kwarg shape.

    fix(#1778 review round 21): ``raw`` is whatever ``typer``/``click``
    resolved from CLI flag vs. env var vs. "neither given" -- click's
    own ``envvar=`` precedence on the Option already implements "flag
    wins over env" and rejects a non-numeric value from EITHER source
    with its own usage error before this function ever runs (float
    type coercion on the Option). This function only handles the
    domain-specific translation:

    - ``raw is None``: neither the flag nor the env var was given —
      returns ``_UNSET`` so ``post_manifest_apply`` falls back to
      ``compute_manifest_apply_timeout``'s heuristic.
    - ``raw == 0``: an explicit operator request for NO client-side
      read timeout — returns ``None`` (forwarded to
      ``long_request_timeout()``, which keeps the connect phase
      bounded — see its docstring).
    - any other non-negative value: returned as-is, overriding the
      formula outright.
    - negative: raises ``ManifestApplyTimeoutValueError`` — a
      negative timeout has no meaning here, and click's own type
      coercion cannot express "float, but only the non-negative
      ones."
    """
    if raw is None:
        return _UNSET
    # fix(#1778 review round 24): click/typer's float coercion happily
    # parses "nan", "inf"/"-inf", and overflowing literals like "1e309"
    # (which rounds to inf) into real float values -- the `raw < 0`
    # check below lets nan through outright (every comparison against
    # NaN is False, including `< 0`), and lets +inf/1e309 all the way
    # through to `long_request_timeout()` as a real, silently-unbounded
    # timeout that never went through the documented `--timeout 0`
    # path. Rejected the same way analysis.py's require_finite() and
    # main.py's refresh/materialize `--timeout` checks already reject
    # their own non-finite input.
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


class _Unset:
    """Sentinel distinguishing "no timeout override given" (compute the
    heuristic formula) from an explicit ``None`` (fix(#1778 review
    round 21): --timeout 0 -- no client-side read timeout at all). A
    bare ``None`` default cannot carry that distinction since ``None``
    IS one of the two meaningful values here."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return "<unset>"


_UNSET = _Unset()


class ManifestApplyTimeout(Exception):
    """Raised when the apply POST itself times out — no response body
    ever arrived, unlike ``ManifestApplyRequestError`` (a response DID
    arrive and it was itself an error).

    fix(#1778 review round 18): carries ``entry_count``/``budget`` so
    the caller (``report_apply_timeout``) can build an informative
    message without recomputing them, and so a test can assert on the
    values without re-deriving the formula.

    fix(#1778 review round 21): ``budget`` may be ``None`` -- an
    operator explicitly asked for no client-side read timeout
    (``--timeout 0``) and a CONNECT-phase (or write/pool) timeout still
    fired; the message below says so instead of formatting ``None`` as
    a number.
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


def post_manifest_apply(
    client: Any,
    payload: Mapping[str, Any],
    *,
    timeout: float | None | _Unset = _UNSET,
) -> dict[str, Any]:
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

    fix(#1778 review round 19): ``timeout``, when given, OVERRIDES the
    batch-aware budget instead of computing it from ``payload``'s own
    entry count. Used by ``attempt_apply_timeout_status_check``'s
    post-timeout dry-run follow-up, which needs the short FIXED
    ``MANIFEST_APPLY_STATUS_CHECK_TIMEOUT_SECONDS`` bound regardless of
    how many entries the manifest has — dry_run does no download/queue
    work, so its cost does not scale with entry count the way the real
    apply's does.

    fix(#1778 review round 21): ``timeout`` is now three-state, not
    two -- the computed heuristic is only ever a LOWER BOUND (see
    ``compute_manifest_apply_timeout``'s docstring), so an operator
    override must be able to ask for something the formula itself
    cannot express: no timeout at all.

    - omitted (the default, ``_UNSET``): compute the batch-aware
      formula, as before.
    - ``None``: NO client-side read timeout (``--timeout 0`` /
      ``GEOLENS_MANIFEST_APPLY_TIMEOUT=0`` at the CLI layer) — forwarded
      to ``long_request_timeout()``, which keeps the connect phase
      bounded but waits indefinitely for the server's response.
    - a ``float``: exactly that many seconds, overriding the formula
      (an explicit operator value, or the status check's own fixed
      bound).
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

    fix(#1778, #1814): the CLI giving up does not stop the server, which
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
    """Best-effort dry-run follow-up after a ``ManifestApplyTimeout``,
    to report which entries the server had already reached. Returns
    ``None`` if the follow-up itself failed or timed out.

    ``dry_run=True`` on this same endpoint classifies every entry
    (create/update/skip_complete/skip_in_flight) without downloading or
    queuing anything, which makes it materially cheaper than the apply that
    just timed out and is exactly the "which entries did the server reach"
    answer.

    fix(#1814): an entry still being staged holds a reservation and classifies
    ``skip_in_flight``, so absence from the answer means the server had not
    reached that entry.

    Bounded by ``MANIFEST_APPLY_STATUS_CHECK_TIMEOUT_SECONDS``, a short fixed
    30s rather than the entry-scaled budget the real apply needed, because
    ``dry_run`` does no download or queue work. Best-effort: if the follow-up
    also fails or times out, the entry-by-entry answer was not available.

    Side-effect-free (no ``output`` printing) so a ``--json`` caller
    can build one clean structured payload from the result instead of
    inheriting rich-console/stderr writes meant for a human — see
    ``report_apply_timeout`` for that human-mode convenience wrapper.

    Catches every failure shape the follow-up can raise, including
    ``typer.Exit`` (which ``call_sdk`` raises for a plain network error, and
    which subclasses ``RuntimeError`` rather than ``Exception``). Any failure
    here must degrade to "status unavailable" rather than crash a command
    already in its error-reporting path.
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
    """Human-mode convenience: prints the round-18/19 timeout
    explanation, attempts the dry-run status follow-up
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
