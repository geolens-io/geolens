# SPDX-License-Identifier: Apache-2.0
"""Load and validate `geolens.yaml` manifest documents."""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from .errors import ManifestValidationError, normalize_validation_errors

SUPPORTED_VERSIONS = ("1", "2")

_SCHEMA_RESOURCES = {
    version: f"geolens-manifest-v{version}.schema.json" for version in SUPPORTED_VERSIONS
}

# Validation runs before anything is uploaded, so a v2 source that names a file
# or URL is checked as if it already were an upload.
_PLACEHOLDER_UPLOAD_URI = "upload:00000000-0000-0000-0000-000000000000"
_PLACEHOLDER_CHECKSUM = "sha256:" + "0" * 64
UPLOAD_URI_PREFIX = "upload:"


def manifest_schema(version: str = "1") -> dict[str, Any]:
    """Return the packaged manifest JSON Schema for ``version``."""

    schema_path = files("geolens_cli.manifest.schemas").joinpath(
        _SCHEMA_RESOURCES[version]
    )
    return json.loads(schema_path.read_text(encoding="utf-8"))


_AUTHORING_URI_PATTERN = (
    r"^(?:(?:\./)?[^\s:/][^\s:]*|https?://[^\s]+|s3://[^\s]+|"
    r"upload:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?![\s\S])"
)


def authoring_schema() -> dict[str, Any]:
    """The v2 schema for files people write, built from the bundled wire schema.

    The wire schema only takes `upload:<job_id>` sources with a checksum, which
    is what `geolens apply` sends. A file the CLI reads may name a local path or
    a URL and leave the checksum to the CLI; `upload:` still needs one.
    """

    schema = manifest_schema("2")
    schema["$id"] = schema["$id"].replace(
        "publish_manifest_v2", "publish_manifest_v2_authoring"
    )
    schema["title"] = f"{schema.get('title', 'GeoLens Manifest v2')} (authoring)"
    schema["$comment"] = (
        "Derived from the wire schema by geolens-cli: a source uri may be a local "
        "path, http(s), s3 or upload:, and checksum is optional except for upload:."
    )
    source = schema["$defs"]["source"]
    source["required"] = ["type", "uri"]
    source["properties"]["uri"] = {
        "type": "string",
        "minLength": 1,
        "maxLength": 2000,
        "pattern": _AUTHORING_URI_PATTERN,
    }
    source["if"] = {
        "required": ["uri"],
        "properties": {"uri": {"pattern": "^upload:"}},
    }
    source["then"] = {"required": ["checksum"]}
    return schema


def document_version(document: Mapping[str, Any]) -> str:
    """The schema version a document is validated against.

    Anything that isn't "2" validates as v1, so a wrong version reports the v1
    schema's own `const` error.
    """

    return "2" if document.get("manifest_version") == "2" else "1"


def source_dicts(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every source mapping of every dataset, in manifest order."""

    datasets = document.get("datasets")
    if not isinstance(datasets, list):
        return []
    return [
        source
        for dataset in datasets
        if isinstance(dataset, dict) and isinstance(dataset.get("sources"), list)
        for source in dataset["sources"]
        if isinstance(source, dict)
    ]


def names_unuploaded_source(source: Mapping[str, Any]) -> bool:
    """True for a source whose non-empty `uri` isn't an `upload:` reference."""

    uri = source.get("uri")
    return isinstance(uri, str) and bool(uri) and not uri.startswith(UPLOAD_URI_PREFIX)


def _authoring_uri_ok(uri: str) -> bool:
    return len(uri) <= 2000 and re.fullmatch(_AUTHORING_URI_PATTERN, uri) is not None


def _validation_view(document: Mapping[str, Any]) -> dict[str, Any]:
    view = copy.deepcopy(dict(document))
    for source in source_dicts(view):
        # A uri the authoring rules refuse stays as written, so the schema
        # reports it.
        if names_unuploaded_source(source) and _authoring_uri_ok(source["uri"]):
            source["uri"] = _PLACEHOLDER_UPLOAD_URI
            source.setdefault("checksum", _PLACEHOLDER_CHECKSUM)
    return view


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

    version = document_version(document)
    checked = _validation_view(document) if version == "2" else document
    validator = Draft202012Validator(manifest_schema(version))
    return normalize_validation_errors(validator.iter_errors(checked))
