"""The publish manifest v2 schema accepts every valid example and rejects every invalid one."""

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

FIXTURES = Path(__file__).parent / "fixtures"
SCHEMA = json.loads((FIXTURES / "publish_manifest_v2.schema.json").read_text())
EXAMPLES = json.loads((FIXTURES / "publish_contract_v2.json").read_text())
VALIDATOR = Draft202012Validator(SCHEMA)


def _valid(name: str) -> dict:
    return next(e["manifest"] for e in EXAMPLES["valid"] if e["name"] == name)


def test_schema_is_a_valid_draft_2020_12_schema():
    Draft202012Validator.check_schema(SCHEMA)
    assert "Apache-2.0 OR MIT" in SCHEMA["$comment"]


@pytest.mark.parametrize("example", EXAMPLES["valid"], ids=lambda e: e["name"])
def test_valid_example_passes(example):
    errors = [e.message for e in VALIDATOR.iter_errors(example["manifest"])]
    assert errors == []


@pytest.mark.parametrize("example", EXAMPLES["invalid"], ids=lambda e: e["name"])
def test_invalid_example_is_rejected(example):
    assert example["breaks"]
    assert not VALIDATOR.is_valid(example["manifest"])


def _datasets(count: int) -> dict:
    manifest = copy.deepcopy(_valid("create"))
    base = manifest["datasets"][0]
    manifest["datasets"] = [{**base, "key": f"k{i}"} for i in range(count)]
    return manifest


def _attributes(count: int) -> dict:
    manifest = copy.deepcopy(_valid("create"))
    manifest["datasets"][0]["attributes"] = [
        {"source_name": f"c{i}"} for i in range(count)
    ]
    return manifest


def _thumbnail(payload_chars: int) -> dict:
    manifest = copy.deepcopy(_valid("create"))
    manifest["maps"][0]["thumbnail"] = "data:image/png;base64," + "A" * payload_chars
    return manifest


@pytest.mark.parametrize(
    ("build", "largest_valid", "smallest_invalid"),
    [
        (_datasets, 100, 101),
        (_attributes, 500, 501),
        # The prefix is 22 characters and the payload grows in groups of four,
        # so no thumbnail is exactly 100,000 characters long.
        (_thumbnail, 99_976, 99_980),
    ],
)
def test_size_limits_are_enforced(build, largest_valid, smallest_invalid):
    assert VALIDATOR.is_valid(build(largest_valid))
    assert not VALIDATOR.is_valid(build(smallest_invalid))


def test_a_jpeg_thumbnail_is_accepted():
    manifest = copy.deepcopy(_valid("create"))
    manifest["maps"][0]["thumbnail"] = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQ=="
    assert VALIDATOR.is_valid(manifest)


def _layers(count: int) -> dict:
    manifest = copy.deepcopy(_valid("create"))
    layer = manifest["maps"][0]["layers"][0]
    manifest["maps"][0]["layers"] = [{**layer, "key": f"l{i}"} for i in range(count)]
    return manifest


def test_a_map_holds_at_most_200_layers():
    assert VALIDATOR.is_valid(_layers(200))
    assert not VALIDATOR.is_valid(_layers(201))


@pytest.mark.parametrize(
    ("path", "limit"),
    [
        (("maps", 0, "name"), 255),
        (("maps", 0, "description"), 2000),
        (("maps", 0, "basemap_style"), 2000),
        (("maps", 0, "layers", 0, "display_name"), 255),
    ],
)
def test_map_text_fields_stop_at_their_storage_limit(path, limit):
    manifest = copy.deepcopy(_valid("create"))
    target = manifest
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = "x" * limit
    assert VALIDATOR.is_valid(manifest)
    target[path[-1]] = "x" * (limit + 1)
    assert not VALIDATOR.is_valid(manifest)


def test_a_request_holds_at_most_100_maps():
    manifest = copy.deepcopy(_valid("create"))
    map_entry = manifest["maps"][0]
    manifest["maps"] = [{**map_entry, "key": f"m{i}"} for i in range(100)]
    assert VALIDATOR.is_valid(manifest)
    manifest["maps"].append({**map_entry, "key": "m100"})
    assert not VALIDATOR.is_valid(manifest)


@pytest.mark.parametrize(
    ("path", "limit"),
    [
        (("datasets", 0, "collection", "name"), 255),
        (("datasets", 0, "attributes", 0, "title"), 500),
        (("datasets", 0, "attributes", 0, "description"), 2000),
        (("datasets", 0, "attributes", 0, "units"), 50),
    ],
)
def test_dataset_text_fields_stop_at_their_storage_limit(path, limit):
    manifest = copy.deepcopy(_valid("create"))
    target = manifest
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = "x" * limit
    assert VALIDATOR.is_valid(manifest)
    target[path[-1]] = "x" * (limit + 1)
    assert not VALIDATOR.is_valid(manifest)


@pytest.mark.parametrize(
    ("path", "limit"),
    [
        (("catalog", "title"), 500),
        (("catalog", "description"), 5000),
        (("catalog", "organization"), 500),
        (("datasets", 0, "title"), 500),
        (("datasets", 0, "description"), 5000),
        (("datasets", 0, "metadata", "organization"), 500),
        (("datasets", 0, "metadata", "license"), 500),
        (("datasets", 0, "metadata", "attribution"), 5000),
        (("datasets", 0, "publication", "intent"), 20),
    ],
)
def test_catalog_and_dataset_text_fields_stop_at_their_limit(path, limit):
    manifest = copy.deepcopy(_valid("create"))
    target = manifest
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = "x" * limit
    assert VALIDATOR.is_valid(manifest)
    target[path[-1]] = "x" * (limit + 1)
    assert not VALIDATOR.is_valid(manifest)
