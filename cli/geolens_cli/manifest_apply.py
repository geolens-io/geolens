# SPDX-License-Identifier: Apache-2.0
"""Networked manifest apply helpers for `geolens apply`."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from ._sdk_helpers import EXIT_AUTH, EXIT_GENERIC, EXIT_SERVER, EXIT_USAGE, call_sdk

APPLY_ENDPOINT = "/ingest/manifest/apply"
_COUNT_KEYS = ("create", "update", "skip", "error")


class ManifestApplyRequestError(Exception):
    """Raised when the backend apply request fails before a response body applies."""

    def __init__(self, message: str, *, exit_code: int) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code


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
    """POST a validated manifest through the SDK-owned HTTP client."""

    response = call_sdk(
        client.get_httpx_client().post,
        url=APPLY_ENDPOINT,
        json=dict(payload),
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
