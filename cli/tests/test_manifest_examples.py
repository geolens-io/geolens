"""Offline validation for public manifest examples."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from geolens_cli.manifest.schema import load_manifest, validate_manifest


REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_ROOT = REPO_ROOT / "examples" / "manifests"


def _example_paths() -> list[Path]:
    return sorted(EXAMPLE_ROOT.rglob("*.yaml"))


def _datasets(document: dict[str, Any]) -> list[dict[str, Any]]:
    return list(document.get("datasets", []))


def _sources(document: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        source
        for dataset in _datasets(document)
        for source in dataset.get("sources", [])
    ]


def test_public_manifest_examples_validate() -> None:
    paths = _example_paths()

    assert paths, "expected public manifest examples"
    for path in paths:
        errors = validate_manifest(load_manifest(path))
        assert errors == [], (path, errors)


def test_first_catalog_references_backend_local_sample_data() -> None:
    manifest = EXAMPLE_ROOT / "first-catalog" / "geolens.yaml"
    sample = EXAMPLE_ROOT / "first-catalog" / "city-parks.geojson"
    document = load_manifest(manifest)

    assert _sources(document)[0]["uri"] == "staging/city-parks.geojson"
    payload = json.loads(sample.read_text(encoding="utf-8"))
    assert payload["type"] == "FeatureCollection"
    assert payload["features"]


def test_examples_cover_http_s3_and_publication_intents() -> None:
    documents = [load_manifest(path) for path in _example_paths()]
    source_uris = [
        source["uri"] for document in documents for source in _sources(document)
    ]
    intents = {
        dataset["publication"]["intent"]
        for document in documents
        for dataset in _datasets(document)
    }

    assert any(uri.startswith(("http://", "https://")) for uri in source_uris)
    assert any(uri.startswith("s3://") for uri in source_uris)
    assert {"draft", "ready", "internal", "published"} <= intents
