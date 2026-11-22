"""The coded messages a manifest map's check and apply answer with."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

NO_MAP_PERMISSION = "A003"
PUBLIC_REFUSED = "A020"
TABLE_LAYER = "A032"
STYLING_KEPT = "A070"
KEY_NOT_WRITABLE = "A050"
DATASET_NOT_READY = "A052"
LAYER_REMOVED = "A059"
STYLE_KEY_DROPPED = "A062"
COLUMN_MISSING = "A063"
OTHER_REFUSAL = "A099"

MAX_REPORTED_ERRORS = 5
# Names in a message come from the caller, so a message lists only so many.
_MAX_LISTED_NAMES = 20
_MAX_LISTED_NAME_LENGTH = 64
# A schema error may quote the caller's keys too.
MAX_ERROR_LENGTH = 300


def short(name: object, limit: int = _MAX_LISTED_NAME_LENGTH) -> str:
    value = str(name)
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def problem(error: Mapping[str, Any]) -> str:
    where = ".".join(short(part) for part in error["loc"]) or "layer"
    return f"{where}: {short(error['msg'], MAX_ERROR_LENGTH)}"


def listed(names: Sequence[str]) -> str:
    shown = ", ".join(short(name) for name in names[:_MAX_LISTED_NAMES])
    rest = len(names) - _MAX_LISTED_NAMES
    return f"{shown} and {rest} more" if rest > 0 else shown


def message(
    code: str,
    severity: str,
    message: str,
    *,
    fix: str | None = None,
    layer: str | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "fix": fix,
        "layer": layer,
    }


def error_result(key: str, text: str) -> dict[str, Any]:
    return {
        "map_key": key,
        "action": "error",
        "map_id": None,
        "messages": [message(OTHER_REFUSAL, "error", text)],
    }
