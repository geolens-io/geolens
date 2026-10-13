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


def _too_many_datasets() -> dict:
    manifest = copy.deepcopy(_valid("create"))
    base = manifest["datasets"][0]
    manifest["datasets"] = [{**base, "key": f"k{i}"} for i in range(101)]
    return manifest


def _too_many_attributes() -> dict:
    manifest = copy.deepcopy(_valid("create"))
    manifest["datasets"][0]["attributes"] = [
        {"source_name": f"c{i}"} for i in range(501)
    ]
    return manifest


def _thumbnail_too_long() -> dict:
    manifest = copy.deepcopy(_valid("create"))
    manifest["maps"][0]["thumbnail"] = "data:image/png;base64," + "A" * 100_000
    return manifest


@pytest.mark.parametrize(
    "build", [_too_many_datasets, _too_many_attributes, _thumbnail_too_long]
)
def test_size_limits_are_enforced(build):
    assert not VALIDATOR.is_valid(build())


def test_hundred_datasets_is_accepted():
    boundary = copy.deepcopy(_valid("create"))
    boundary["datasets"] = [
        {**boundary["datasets"][0], "key": f"k{i}"} for i in range(100)
    ]
    assert VALIDATOR.is_valid(boundary)
