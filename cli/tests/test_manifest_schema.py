"""Manifest schema and validation contract tests."""

from __future__ import annotations

import ast
from pathlib import Path

from geolens_cli.manifest import (
    ManifestValidationError,
    manifest_schema,
    validate_manifest,
)


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
