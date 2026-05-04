# SPDX-License-Identifier: Apache-2.0
"""Stable manifest validation error normalization."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, order=True)
class ManifestValidationError:
    """A CLI-safe validation error with a deterministic path and code."""

    path: str
    code: str
    message: str


_REQUIRED_RE = re.compile(r"'([^']+)' is a required property")
_ADDITIONAL_RE = re.compile(r"'([^']+)' was unexpected")


def normalize_validation_errors(errors: Iterable[Any]) -> list[ManifestValidationError]:
    """Convert jsonschema errors into a deterministic CLI-facing shape."""

    return sorted(_normalize_one(error) for error in _sort_jsonschema_errors(errors))


def _sort_jsonschema_errors(errors: Iterable[Any]) -> list[Any]:
    return sorted(
        errors,
        key=lambda error: (
            _json_path(error.path),
            str(error.validator),
            _schema_path(error.schema_path),
        ),
    )


def _normalize_one(error: Any) -> ManifestValidationError:
    code = _code(error)
    path = _json_path(error.path)
    message = str(error.message)

    if error.validator == "required":
        missing = _match(_REQUIRED_RE, message)
        if missing:
            path = _append_path(path, missing)
            message = f"Missing required field: {missing}"
    elif error.validator == "additionalProperties":
        extra = _match(_ADDITIONAL_RE, message)
        if extra:
            path = _append_path(path, extra)
            message = f"Unexpected field: {extra}"

    return ManifestValidationError(path=path, code=code, message=message)


def _code(error: Any) -> str:
    validator = str(error.validator)
    if validator in {
        "additionalProperties",
        "const",
        "enum",
        "maxItems",
        "maxLength",
        "minItems",
        "minLength",
        "pattern",
        "required",
        "type",
    }:
        return validator
    return "schema"


def _json_path(parts: Sequence[Any]) -> str:
    path = "$"
    for part in parts:
        if isinstance(part, int):
            path += f"[{part}]"
        elif _is_identifier(str(part)):
            path += f".{part}"
        else:
            escaped = str(part).replace("\\", "\\\\").replace('"', '\\"')
            path += f'["{escaped}"]'
    return path


def _append_path(path: str, part: str) -> str:
    if _is_identifier(part):
        return f"{path}.{part}"
    escaped = part.replace("\\", "\\\\").replace('"', '\\"')
    return f'{path}["{escaped}"]'


def _schema_path(parts: Sequence[Any]) -> str:
    return "/".join(str(part) for part in parts)


def _is_identifier(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value))


def _match(pattern: re.Pattern[str], value: str) -> str | None:
    match = pattern.search(value)
    if match is None:
        return None
    return match.group(1)
