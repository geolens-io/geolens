"""The v2 contract snapshot, and the hand-written wire schema held to the model.

``fixtures/publish_manifest_v2.schema.json`` is the connector subset that
clients vendor, so it is written by hand and stays stricter than the request
model in places the model serves other callers (version 1, other source
schemes). Two checks keep the two from drifting apart: the file may never be
looser than the model, and it may not leave out a field the model accepts.
"""

from __future__ import annotations

import json
from typing import Any

from app.processing.ingest.manifest_schemas import ManifestApplyRequest
from tests import publish_contract_v2_snapshot as snapshot

SCHEMA = json.loads((snapshot.FIXTURES / "publish_manifest_v2.schema.json").read_text())
MODEL = ManifestApplyRequest.model_json_schema()

# Model fields the connector schema deliberately leaves out. Each path is
# written as the schema is walked: `[]` is an array item.
NOT_IN_CONNECTOR_SCHEMA = {
    "catalog.contact": "Connectors publish no catalog contact.",
    "datasets[].sources[].title": "The dataset entry carries the title.",
    "datasets[].sources[].description": "The dataset entry carries the description.",
    "datasets[].sources[].format": "The server reads the format from the uploaded file.",
    "datasets[].sources[].layer": "A connector uploads one layer per file.",
}


def test_the_snapshot_matches_the_models_and_codes():
    stored = snapshot.SNAPSHOT_PATH.read_text(encoding="utf-8")
    assert stored == snapshot.render(), (
        "The publish contract v2 snapshot is out of date. If the change to the "
        "manifest models, message codes or job kinds is intended, regenerate "
        f"it with: {snapshot.REGENERATE}"
    )


# -- the hand-written schema against the model ---------------------------------


def _ref(root: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in node:
        extra = {k: v for k, v in node.items() if k != "$ref"}
        node = {**root["$defs"][node["$ref"].rsplit("/", 1)[1]], **extra}
    return node


def _branches(root: dict[str, Any], node: dict[str, Any]) -> tuple[list, bool]:
    """Flatten a node's unions into non-null branches, and whether null is allowed."""
    node = _ref(root, node)
    nullable = node.get("type") == "null" or (
        isinstance(node.get("type"), list) and "null" in node["type"]
    )
    for key in ("anyOf", "oneOf"):
        # A union beside `properties` only adds constraints to that object.
        if key in node and "properties" not in node:
            out: list = []
            for option in node[key]:
                inner, null = _branches(root, option)
                out += inner
                nullable = nullable or null
            return out, nullable
    if node.get("type") == "null":
        return [], True
    if isinstance(node.get("type"), list):
        types = [t for t in node["type"] if t != "null"]
        node = {**node, "type": types[0] if len(types) == 1 else types}
    return [node], nullable


def _types(node: dict[str, Any]) -> set[str]:
    kind = node.get("type")
    if kind is None:
        return set()
    return set(kind) if isinstance(kind, list) else {kind}


_LOWER = ("minLength", "minItems", "minimum")
_UPPER = ("maxLength", "maxItems", "maximum")


def _keyword_problems(hand: dict[str, Any], model: dict[str, Any]) -> list[str]:
    problems = []
    for key in _LOWER:
        if key in model and hand.get(key, float("-inf")) < model[key]:
            problems.append(f"{key} {hand.get(key)} below the model's {model[key]}")
    for key in _UPPER:
        if key in model and hand.get(key, float("inf")) > model[key]:
            problems.append(f"{key} {hand.get(key)} above the model's {model[key]}")
    if "pattern" in model and "pattern" not in hand:
        problems.append("no pattern where the model has one")
    allowed = set(model["enum"]) if "enum" in model else None
    if "const" in model:
        allowed = {model["const"]}
    if allowed is not None:
        mine = {hand["const"]} if "const" in hand else set(hand.get("enum", []))
        if not mine or not mine <= allowed:
            problems.append(
                f"values {sorted(mine)} outside the model's {sorted(allowed)}"
            )
    if _types(model) and not _types(hand) <= _types(model):
        problems.append(f"type {sorted(_types(hand))} wider than the model's")
    if (
        model.get("additionalProperties") is False
        and hand.get("additionalProperties") is not False
    ):
        problems.append("allows unknown properties where the model forbids them")
    return problems


def _looser(hand: dict[str, Any], model: dict[str, Any], path: str) -> list[str]:
    """Where one hand-written branch accepts more than one model branch."""
    problems = [f"{path or '<root>'}: {p}" for p in _keyword_problems(hand, model)]
    hand_props = hand.get("properties", {})
    model_props = model.get("properties", {})
    for name in hand_props.keys() - model_props.keys():
        if model.get("additionalProperties") is False:
            problems.append(f"{path}.{name}: the model has no such field")
    missing_required = set(model.get("required", [])) - set(hand.get("required", []))
    for name in sorted(missing_required):
        problems.append(f"{path}.{name}: required by the model, optional here")
    for name in hand_props.keys() & model_props.keys():
        problems += _compare(hand_props[name], model_props[name], f"{path}.{name}")
    if "items" in model:
        items = hand.get("prefixItems", []) or (
            [hand["items"]] if "items" in hand else []
        )
        for index, mine in enumerate(items):
            problems += _compare(mine, model["items"], f"{path}[{index}]")
    extra = model.get("additionalProperties")
    if isinstance(extra, dict) and isinstance(hand.get("additionalProperties"), dict):
        problems += _compare(hand["additionalProperties"], extra, f"{path}.*")
    return problems


def _compare(hand: dict[str, Any], model: dict[str, Any], path: str) -> list[str]:
    hand_branches, hand_null = _branches(SCHEMA, hand)
    model_branches, model_null = _branches(MODEL, model)
    problems = []
    if hand_null and not model_null:
        problems.append(f"{path}: accepts null where the model does not")
    for branch in hand_branches:
        trials = [_looser(branch, candidate, path) for candidate in model_branches]
        if trials and all(trials):
            problems += min(trials, key=len)
    return problems


def _missing(hand: dict[str, Any], model: dict[str, Any], path: str) -> list[str]:
    """Model fields, at any depth, that no hand-written branch lists."""
    hand_branches, _ = _branches(SCHEMA, hand)
    found = []
    for candidate in _branches(MODEL, model)[0]:
        for name, child in candidate.get("properties", {}).items():
            where = f"{path}.{name}" if path else name
            mine = [
                b["properties"][name]
                for b in hand_branches
                if name in b.get("properties", {})
            ]
            if not mine:
                found.append(where)
                continue
            for node in mine:
                found += _missing(node, child, where)
        if "items" in candidate:
            for branch in hand_branches:
                if "items" in branch:
                    found += _missing(branch["items"], candidate["items"], f"{path}[]")
    return found


def test_the_hand_written_schema_is_no_looser_than_the_model():
    problems = _compare(SCHEMA, MODEL, "")
    assert problems == [], (
        "publish_manifest_v2.schema.json accepts something the request model "
        "refuses. Tighten the schema to the model's bounds, patterns, enums "
        "and required members."
    )


def test_the_hand_written_schema_lists_every_model_field():
    absent = sorted(set(_missing(SCHEMA, MODEL, "")) - NOT_IN_CONNECTOR_SCHEMA.keys())
    assert absent == [], (
        "The request model accepts fields that publish_manifest_v2.schema.json "
        "does not list: add each to the schema with the model's bounds, or to "
        "NOT_IN_CONNECTOR_SCHEMA in this test with a reason."
    )


def test_the_exclusions_still_name_real_model_fields():
    assert set(NOT_IN_CONNECTOR_SCHEMA) <= set(_missing(SCHEMA, MODEL, ""))
