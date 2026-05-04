"""Manifest schema and validation contract tests."""

from __future__ import annotations

import ast
from pathlib import Path

from geolens_cli.manifest import (
    ManifestValidationError,
    load_manifest,
    manifest_schema,
    validate_manifest,
)


FIXTURE_ROOT = (
    Path(__file__).resolve().parents[1] / "geolens_cli" / "manifest" / "fixtures"
)

INVALID_FIXTURE_ERRORS = {
    "bad-bbox.yaml": {("$.datasets[0].metadata.bbox", "minItems")},
    "bad-publication-intent.yaml": {
        ("$.datasets[0].publication.intent", "enum"),
    },
    "bad-source-type.yaml": {("$.datasets[0].sources[0].type", "enum")},
    "bad-source-uri.yaml": {("$.datasets[0].sources[0].uri", "pattern")},
    "bad-version.yaml": {("$.manifest_version", "const")},
    "empty-datasets.yaml": {("$.datasets", "minItems")},
    "missing-dataset-key.yaml": {("$.datasets[0].key", "required")},
}


def _minimal_manifest() -> dict:
    return {
        "manifest_version": "1",
        "catalog": {"title": "Example catalog"},
        "datasets": [
            {
                "key": "roads",
                "title": "Road centerlines",
                "sources": [{"type": "vector", "uri": "./data/roads.geojson"}],
                "publication": {"intent": "draft"},
            }
        ],
    }


def _error_pairs(document: dict) -> set[tuple[str, str]]:
    return {(error.path, error.code) for error in validate_manifest(document)}


def test_schema_resource_loads() -> None:
    schema = manifest_schema()

    assert schema["title"] == "GeoLens Manifest v1"
    assert schema["properties"]["manifest_version"]["const"] == "1"


def test_minimal_manifest_validates() -> None:
    assert validate_manifest(_minimal_manifest()) == []


def test_valid_manifest_fixtures_pass() -> None:
    valid_fixtures = sorted((FIXTURE_ROOT / "valid").glob("*.yaml"))

    assert {path.name for path in valid_fixtures} == {
        "raster-cog-storage.yaml",
        "vector-relative.yaml",
        "vector-url.yaml",
        "vrt-relative.yaml",
    }
    for path in valid_fixtures:
        assert validate_manifest(load_manifest(path)) == [], path.name


def test_invalid_manifest_fixtures_report_expected_errors() -> None:
    invalid_fixtures = sorted((FIXTURE_ROOT / "invalid").glob("*.yaml"))

    assert {path.name for path in invalid_fixtures} == set(INVALID_FIXTURE_ERRORS)
    for path in invalid_fixtures:
        assert INVALID_FIXTURE_ERRORS[path.name].issubset(
            _error_pairs(load_manifest(path))
        ), path.name


def test_required_field_errors_are_path_specific() -> None:
    document = _minimal_manifest()
    del document["datasets"][0]["key"]

    errors = validate_manifest(document)

    assert (
        ManifestValidationError(
            path="$.datasets[0].key",
            code="required",
            message="Missing required field: key",
        )
        in errors
    )


def test_version_and_enum_errors_are_stable() -> None:
    document = _minimal_manifest()
    document["manifest_version"] = "2"
    document["datasets"][0]["publication"]["intent"] = "approval_required"

    assert {
        ("$.manifest_version", "const"),
        ("$.datasets[0].publication.intent", "enum"),
    }.issubset(_error_pairs(document))


def test_manifest_v1_version_compatibility_is_locked() -> None:
    assert validate_manifest(_minimal_manifest()) == []

    future_version = _minimal_manifest()
    future_version["manifest_version"] = "2"
    numeric_version = _minimal_manifest()
    numeric_version["manifest_version"] = 1

    assert ("$.manifest_version", "const") in _error_pairs(future_version)
    assert ("$.manifest_version", "type") in _error_pairs(numeric_version)


def test_unknown_top_level_fields_are_rejected() -> None:
    document = _minimal_manifest()
    document["tenant_id"] = "enterprise-only"

    assert ("$.tenant_id", "additionalProperties") in _error_pairs(document)


def test_enterprise_only_manifest_fields_are_rejected() -> None:
    document = _minimal_manifest()
    document["datasets"][0]["connector_schedule"] = "0 * * * *"
    document["datasets"][0]["stored_credentials"] = {"secret_ref": "vault/path"}
    document["datasets"][0]["publication"]["approval_workflow"] = "manager-review"

    assert {
        ("$.datasets[0].connector_schedule", "additionalProperties"),
        ("$.datasets[0].stored_credentials", "additionalProperties"),
        ("$.datasets[0].publication.approval_workflow", "additionalProperties"),
    }.issubset(_error_pairs(document))


def test_invalid_fixture_validation_output_is_repeatable() -> None:
    path = FIXTURE_ROOT / "invalid" / "bad-source-uri.yaml"
    document = load_manifest(path)

    first = validate_manifest(document)
    second = validate_manifest(document)

    assert first == second
    assert [(error.path, error.code) for error in first] == [
        ("$.datasets[0].sources[0].uri", "pattern")
    ]


def test_validation_error_order_is_deterministic() -> None:
    document = {
        "catalog": {},
        "datasets": [
            {
                "sources": [{"type": "database", "uri": "ftp://example.com/file.gpkg"}],
                "publication": {},
            }
        ],
    }

    first = validate_manifest(document)
    second = validate_manifest(document)

    assert first == second
    assert [(error.path, error.code) for error in first] == sorted(
        (error.path, error.code) for error in first
    )


def test_manifest_modules_do_not_import_backend_app() -> None:
    root = Path(__file__).resolve().parents[1] / "geolens_cli" / "manifest"
    offenders: list[str] = []

    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            imported: str | None = None
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported = alias.name
                    if imported.startswith(("app.", "backend.app.")):
                        offenders.append(f"{path}:{node.lineno}:{imported}")
            elif isinstance(node, ast.ImportFrom):
                imported = node.module
                if imported and imported.startswith(("app.", "backend.app.")):
                    offenders.append(f"{path}:{node.lineno}:{imported}")

    assert offenders == []
