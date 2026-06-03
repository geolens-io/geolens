# SPDX-License-Identifier: Apache-2.0
"""Load and validate `geolens.yaml` manifest documents."""

from __future__ import annotations

import json
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from .errors import ManifestValidationError, normalize_validation_errors

_SCHEMA_RESOURCE = "geolens-manifest-v1.schema.json"


def manifest_schema() -> dict[str, Any]:
    """Return the packaged manifest v1 JSON Schema."""

    schema_path = files("geolens_cli.manifest.schemas").joinpath(_SCHEMA_RESOURCE)
    return json.loads(schema_path.read_text(encoding="utf-8"))


def load_manifest(path: Path) -> dict[str, Any]:
    """Load a YAML manifest file into a mapping.

    Syntax and shape errors raise `ValueError`; schema validation errors are
    returned by `validate_manifest`.
    """

    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"Could not read manifest: {exc}") from exc

    if not isinstance(loaded, dict):
        raise ValueError("Manifest root must be a mapping")
    return loaded


def validate_manifest(document: Mapping[str, Any]) -> list[ManifestValidationError]:
    """Validate a manifest document and return stable validation errors."""

    validator = Draft202012Validator(manifest_schema())
    return normalize_validation_errors(validator.iter_errors(document))
