# SPDX-License-Identifier: Apache-2.0
"""Dataset refresh and source-status helpers.

Hand-maintained — NOT regenerated.  The request path deliberately stays on
the generated SDK surface: the only client-supplied refresh field is the
transient service ``token``.  Origin, layer, and trigger remain server-owned.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.parse import quote
from uuid import UUID

from rich.table import Table

from ._sdk_helpers import (
    EXIT_AUTH,
    EXIT_GENERIC,
    EXIT_SERVER,
    PollDeadlineExceeded,
    call_sdk,
    call_sdk_with_reauth,
    poll_until,
    unwrap,
)

REFRESH_ACCEPTED_STATUS = 202
DATASET_STATUS_OK = 200
JOB_STATUS_OK = 200
DEFAULT_POLL_INTERVAL_SECONDS = 1.0


@dataclass(frozen=True)
class RefreshRequestError(Exception):
    """A refresh refusal translated into a stable CLI message and exit code."""

    message: str
    exit_code: int = EXIT_GENERIC
    code: str | None = None


@dataclass(frozen=True)
class RefreshPollResult:
    """Terminal (or timed-out) state observed through ``GET /jobs/{id}``."""

    status: str
    error_message: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == "complete"


_REFUSAL_MESSAGES: dict[str, str] = {
    "refresh_not_applicable": (
        "This dataset's origin does not support refresh. Replace its data "
        "through re-upload, or re-run 'geolens apply' with an updated "
        "manifest."
    ),
    # fix(#1266): kind-agnostic for the same reason #1319 made its sibling so.
    # This code now answers for three origins — a service binding with no base
    # URL or layer, a registered table with no table name, a STAC dataset with
    # no item href — and naming one of them was already stale for the other
    # two. The recovery is the same sentence in every case: import it again
    # through the flow it came from.
    "origin_unavailable": (
        "This dataset's stored source binding is incomplete, so GeoLens "
        "cannot tell what to refresh from. Import it again through the flow "
        "it came from to record a complete one."
    ),
    "dataset_busy": (
        "A refresh or re-upload is already running for this dataset. Wait for "
        "it to finish, then try again."
    ),
    "origin_changed": (
        "The dataset's source changed while the refresh was being queued. "
        "Check its current status, then try again."
    ),
    "credential_store_unavailable": (
        "GeoLens cannot securely hand the service credential to a worker. "
        "Ask an operator to check the shared credential store, then try again."
    ),
    "invalid_service_token": (
        "GeoLens rejected the service token. Supply a token that meets the "
        "service's credential policy and try again."
    ),
}


def start_refresh(client: Any, dataset_id: UUID, token: str | None = None) -> Any:
    """Dispatch a refresh through the generated SDK.

    With no credential, the optional request body is omitted.  With a
    credential, ``DatasetRefreshRequest`` guarantees that the serialized body
    contains only ``token``; notably, there is no client-supplied trigger or
    source pointer.
    """
    from geolens.api.datasets_refresh import (
        refresh_dataset_datasets_dataset_id_refresh_post as refresh_endpoint,
    )

    kwargs: dict[str, Any] = {"dataset_id": dataset_id, "client": client}
    if token is not None:
        from geolens.models.dataset_refresh_request import DatasetRefreshRequest

        kwargs["body"] = DatasetRefreshRequest(token=token)

    response = call_sdk(refresh_endpoint.sync_detailed, **kwargs)
    if int(response.status_code) != REFRESH_ACCEPTED_STATUS:
        raise _refresh_request_error(response, token=token)
    return unwrap(response, expected=REFRESH_ACCEPTED_STATUS)


def _refresh_request_error(
    response: Any, *, token: str | None = None
) -> RefreshRequestError:
    status_code = int(response.status_code)
    code, server_message = _problem_detail(response.parsed)

    if status_code in {401, 403}:
        return RefreshRequestError(
            "Authentication or edit permission is required to refresh this dataset.",
            exit_code=EXIT_AUTH,
            code=code,
        )
    if status_code == 400:
        # Stored URLs are revalidated for SSRF at dispatch time.  Do not repeat
        # the rejected URL (or provider text) into terminal history.
        return RefreshRequestError(
            "GeoLens refused the stored source URL because it failed network-safety "
            "checks. Review or re-import the dataset's source before retrying.",
            code=code,
        )
    if code in _REFUSAL_MESSAGES:
        return RefreshRequestError(
            _REFUSAL_MESSAGES[code],
            exit_code=EXIT_SERVER if status_code >= 500 else EXIT_GENERIC,
            code=code,
        )
    if status_code >= 500:
        return RefreshRequestError(
            _redact_secret(server_message, token)
            if server_message
            else f"GeoLens could not queue the refresh ({status_code}).",
            exit_code=EXIT_SERVER,
            code=code,
        )
    return RefreshRequestError(
        _redact_secret(server_message, token)
        if server_message
        else f"Refresh request failed ({status_code}).",
        code=code,
    )


def _problem_detail(parsed: Any) -> tuple[str | None, str | None]:
    """Return a ProblemDetail's structured ``(code, message)`` defensively."""
    from geolens.models.problem_detail import ProblemDetail

    if not isinstance(parsed, ProblemDetail):
        return None, None
    detail = parsed.detail
    if isinstance(detail, str):
        return None, detail
    if isinstance(detail, Mapping):
        payload = detail
    else:
        to_dict = getattr(detail, "to_dict", None)
        payload = to_dict() if callable(to_dict) else {}
    code = payload.get("code")
    message = payload.get("message")
    return (
        str(code) if code is not None else None,
        str(message) if message is not None else None,
    )


def wait_for_refresh(
    client: Any,
    job_id: str | UUID,
    *,
    token: str | None = None,
    interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
    timeout: float | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> RefreshPollResult:
    """Poll until terminal, or until an explicitly supplied timeout expires.

    fix(#1778 review round 8): a per-request httpx.TimeoutException is
    retried via poll_until() (logged at debug, slept past) instead of
    being treated as immediately fatal. Previously this called plain
    call_sdk() with no ``reraise_timeout`` — call_sdk's own
    deadline_expired/DeadlineTimeout path only distinguishes "the
    request timed out AND the deadline has already passed" from a hard
    exit; there was no third option to retry a timeout that happens
    BEFORE the deadline. That meant one slow status GET exited
    EXIT_NETWORK immediately even with the deadline nowhere near (or,
    for the default unbounded ``--wait``, with no deadline at all).
    """
    from geolens.api.admin import get_job_status_jobs_job_id_get

    uuid_arg = job_id if isinstance(job_id, UUID) else UUID(str(job_id))
    deadline = monotonic() + timeout if timeout is not None else None
    transport = client.get_httpx_client() if deadline is not None else None
    original_timeout = transport.timeout if transport is not None else None
    # poll_until() needs a concrete deadline to retry against; the
    # unbounded default --wait (deadline=None here) has no operation
    # deadline to give up at, so a per-request timeout is retried
    # forever — same "no bound" convention as analysis.POLL_FOREVER.
    poll_deadline = deadline if deadline is not None else float("inf")
    status = "pending"
    try:
        while True:
            if deadline is not None:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return RefreshPollResult(
                        status="timed_out",
                        error_message=(
                            f"Refresh job {job_id} is still {status}; "
                            "check its status later."
                        ),
                    )
                transport.timeout = remaining
            try:
                response = poll_until(
                    lambda: call_sdk(
                        get_job_status_jobs_job_id_get.sync_detailed,
                        job_id=uuid_arg,
                        client=client,
                        reraise_timeout=True,
                    ),
                    deadline=poll_deadline,
                    interval=interval,
                    sleep=sleep,
                    monotonic=monotonic,
                )
            except PollDeadlineExceeded:
                return RefreshPollResult(
                    status="timed_out",
                    error_message=(
                        f"Refresh job {job_id} is still {status}; "
                        "check its status later."
                    ),
                )
            if int(response.status_code) != JOB_STATUS_OK:
                # ``unwrap`` preserves the CLI's standard auth/server exit mapping.
                unwrap(response, expected=JOB_STATUS_OK)
            job = unwrap(response, expected=JOB_STATUS_OK)
            status = str(getattr(job, "status", "unknown"))
            if status == "complete":
                return RefreshPollResult(status=status)
            if status in {"failed", "cancelled"}:
                error = getattr(job, "error_message", None)
                return RefreshPollResult(
                    status=status,
                    error_message=_redact_secret(str(error), token) if error else None,
                )
            if deadline is None:
                sleep(interval)
                continue
            remaining = deadline - monotonic()
            if remaining <= 0:
                return RefreshPollResult(
                    status="timed_out",
                    error_message=(
                        f"Refresh job {job_id} is still {status}; "
                        "check its status later."
                    ),
                )
            sleep(min(interval, remaining))
    finally:
        if transport is not None:
            transport.timeout = original_timeout


def _redact_secret(message: str, secret: str | None) -> str:
    """Keep a supplied token out of an upstream failure message."""
    if not secret:
        return message
    redacted = message.replace(secret, "[REDACTED]")
    encoded = quote(secret, safe="")
    if encoded != secret:
        redacted = redacted.replace(encoded, "[REDACTED]")
    return redacted


def refresh_payload(response: Any, poll: RefreshPollResult | None = None) -> dict:
    """Serialize the 202 response, optionally replacing status with job status."""
    to_dict = getattr(response, "to_dict", None)
    payload = (
        to_dict()
        if callable(to_dict)
        else {
            key: getattr(response, key, None)
            for key in (
                "run_id",
                "job_id",
                "dataset_id",
                "origin_kind",
                "trigger",
                "status",
                "message",
            )
        }
    )
    if poll is not None:
        payload["status"] = poll.status
        if poll.error_message:
            payload["error_message"] = poll.error_message
    return payload


def fetch_dataset_status(
    client: Any,
    dataset_id: UUID,
    *,
    instance: str | None = None,
    credential_kind: str | None = None,
    credential_provenance: str | None = None,
) -> Any:
    """Read the generated dataset detail model used by ``geolens status``.

    fix(#1778): ``instance`` is optional so existing callers are
    unaffected — pass it to refresh-retry once on 401 instead of
    hard-failing on an access token that expired since login (D-13;
    previously only ``whoami`` spent the stored refresh token).

    fix(#1778 review round 3): ``credential_kind`` (from the
    ``GeolensClient`` returned by ``AppState.sdk()`` / ``make_client()``)
    is required alongside ``instance`` to enable the retry — it gates
    the refresh attempt to a bearer-token client. See
    ``_sdk_helpers.call_sdk_with_reauth``.

    fix(#1778 review round 26): ``credential_provenance`` is forwarded
    the same way — see ``call_sdk_with_reauth``'s own docstring for why
    "bearer" alone is not enough to justify spending a stored refresh
    token.
    """
    from geolens.api.datasets import get_single_dataset_datasets_dataset_id_get

    if instance is not None and credential_kind is not None:
        response = call_sdk_with_reauth(
            get_single_dataset_datasets_dataset_id_get.sync_detailed,
            instance=instance,
            credential_kind=credential_kind,
            credential_provenance=credential_provenance,
            dataset_id=dataset_id,
            client=client,
        )
    else:
        response = call_sdk(
            get_single_dataset_datasets_dataset_id_get.sync_detailed,
            dataset_id=dataset_id,
            client=client,
        )
    return unwrap(response, expected=DATASET_STATUS_OK)


def dataset_status_payload(dataset: Any) -> dict[str, Any]:
    """Select stable source-status fields from ``DatasetResponse``."""
    return {
        "dataset_id": str(dataset.id),
        "title": dataset.title,
        "status": _value(getattr(dataset, "record_status", None)),
        "origin": _value(getattr(dataset, "origin", None)),
        "source_freshness": _value(getattr(dataset, "source_freshness", None)),
        "source_health": _value(getattr(dataset, "source_health", None)),
        "source_health_detail": _value(getattr(dataset, "source_health_detail", None)),
        "last_refreshed_at": _value(getattr(dataset, "last_refreshed_at", None)),
        "last_checked_at": _value(getattr(dataset, "last_checked_at", None)),
        "update_frequency": _value(getattr(dataset, "update_frequency", None)),
    }


def _value(value: Any) -> Any:
    from geolens.types import Unset

    return None if isinstance(value, Unset) else value


def render_dataset_status(console: Any, payload: Mapping[str, Any]) -> None:
    """Render one dataset as a terminal-width-safe source-status table."""
    table = Table(title="Dataset status", show_header=False)
    table.add_column("FIELD", style="bold")
    table.add_column("VALUE", overflow="fold")

    health = _display(payload.get("source_health"))
    if payload.get("source_health_detail"):
        health = f"{health} ({payload['source_health_detail']})"
    rows = (
        (
            "Dataset",
            f"{payload.get('title') or '(untitled)'} ({payload['dataset_id']})",
        ),
        ("Status", _display(payload.get("status"))),
        ("Origin", _display(payload.get("origin"))),
        ("Freshness", _display(payload.get("source_freshness"))),
        ("Health", health),
        ("Last refreshed", _display(payload.get("last_refreshed_at"))),
        ("Last checked", _display(payload.get("last_checked_at"))),
        ("Update frequency", _display(payload.get("update_frequency"))),
    )
    for label, value in rows:
        table.add_row(label, value)
    console.print(table)


def _display(value: Any) -> str:
    if value is None or value == "":
        return "—"
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else str(value)
