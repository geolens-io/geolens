# SPDX-License-Identifier: Apache-2.0
"""Rendering helpers for manifest validation reports."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .errors import ManifestValidationError

_REMEDIATIONS = {
    "additionalProperties": "Remove the unsupported field or move it to a supported manifest property.",
    "const": 'Use manifest_version "1" for the current GeoLens manifest schema.',
    "enum": "Use one of the supported values documented by the manifest schema.",
    "maxItems": "Remove extra values so the list matches the schema limit.",
    "maxLength": "Shorten the value at this manifest path.",
    "minItems": "Add the required number of list entries at this manifest path.",
    "minLength": "Provide a non-empty value at this manifest path.",
    "pattern": "Update the value so it matches the expected manifest format.",
    "required": "Add the missing required field at this manifest path.",
    "type": "Change the value type to match the manifest schema.",
}


def remediation_for_error(code: str) -> str:
    """Return human-readable remediation text for a stable error code."""

    return _REMEDIATIONS.get(
        code,
        "Update this manifest value so it satisfies the GeoLens manifest schema.",
    )


def validation_report_payload(
    path: Path,
    errors: Sequence[ManifestValidationError],
) -> dict[str, Any]:
    """Return a deterministic JSON-serializable validation report."""

    return {
        "errors": [
            {
                "code": error.code,
                "message": error.message,
                "path": error.path,
                "remediation": remediation_for_error(error.code),
            }
            for error in errors
        ],
        "ok": not errors,
        "path": str(path),
    }


def format_validation_error_lines(
    path: Path,
    errors: Sequence[ManifestValidationError],
) -> list[str]:
    """Return deterministic human-readable error lines."""

    return [
        (
            f"{path} {error.path} [{error.code}]: {error.message}. "
            f"Remediation: {remediation_for_error(error.code)}"
        )
        for error in errors
    ]
