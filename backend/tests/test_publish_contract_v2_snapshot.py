"""The v2 contract snapshot, and the hand-written wire schema held to the model.

``fixtures/publish_manifest_v2.schema.json`` is the connector subset that
clients vendor, so it is written by hand and stays stricter than the request
model in places the model serves other callers (version 1, other source
schemes). Two checks keep the two from drifting apart: the file may never be
looser than the model, and it may not leave out a field the model accepts.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from app.processing.ingest.manifest_schemas import (
    ManifestApplyRequest,
    ManifestApplyResponse,
)
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

# Patterns the connector schema may not share with the model. Every other
# pattern must be the model's, with the end anchor `(?![\\s\\S])` read as `$`
# (the schema's form refuses a trailing newline, which `$` lets through).
# A hand-file pattern where the model has none, such as the uuid pattern for
# `format: uuid`, is stricter and needs no entry.
APPROVED_PATTERN_DIFFERENCES = {
    "datasets[].sources[].uri": "Connectors send only the upload: subset of the model's schemes.",
    "maps[].thumbnail": "The schema requires well-formed padded base64; the model decodes it.",
}


def test_the_snapshot_matches_the_models_and_codes():
    stored = snapshot.SNAPSHOT_PATH.read_text(encoding="utf-8")
    assert stored == snapshot.render(), (
        "The publish contract v2 snapshot is out of date. If the change to the "
        "manifest models, message codes or job kinds is intended, regenerate "
        f"it with: {snapshot.REGENERATE}"
    )


# -- the hand-written schema against the model ---------------------------------

_END = r"(?![\s\S])"


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


def _element(node: dict[str, Any], index: int | None) -> dict[str, Any]:
    """The schema of one array position; `{}` accepts anything."""
    if index is not None and index < len(node.get("prefixItems", [])):
        return node["prefixItems"][index]
    return node.get("items", {})


def _join(path: str, name: str) -> str:
    return f"{path}.{name}" if path else name


_LOWER = ("minLength", "minItems", "minimum")
_UPPER = ("maxLength", "maxItems", "maximum")


class Audit:
    """Compares a hand-written schema with the request model's schema."""

    def __init__(self, hand: dict[str, Any], model: dict[str, Any]) -> None:
        self.hand, self.model = hand, model
        self.approved_used: set[str] = set()

    def looser(self) -> list[str]:
        """Places the hand-written schema accepts more than the model."""
        return self._compare(self.hand, self.model, "")

    def missing(self) -> list[str]:
        """Model fields, at any depth, that no hand-written branch lists."""
        return self._missing(self.hand, self.model, "")

    def _pattern_problem(self, hand, model, path) -> str | None:
        if "pattern" not in model:
            return None
        if "pattern" not in hand:
            return "no pattern where the model has one"
        if hand["pattern"].replace(_END, "$") == model["pattern"].replace(_END, "$"):
            return None
        if path in APPROVED_PATTERN_DIFFERENCES:
            self.approved_used.add(path)
            return None
        return "pattern differs from the model's"

    def _keyword_problems(self, hand, model, path) -> list[str]:
        problems = []
        for key in _LOWER:
            if key in model and hand.get(key, float("-inf")) < model[key]:
                problems.append(f"{key} {hand.get(key)} below the model's {model[key]}")
        for key in _UPPER:
            if key in model and hand.get(key, float("inf")) > model[key]:
                problems.append(f"{key} {hand.get(key)} above the model's {model[key]}")
        if problem := self._pattern_problem(hand, model, path):
            problems.append(problem)
        allowed = set(model["enum"]) if "enum" in model else None
        if "const" in model:
            allowed = {model["const"]}
        if allowed is not None:
            mine = {hand["const"]} if "const" in hand else set(hand.get("enum", []))
            if not mine or not mine <= allowed:
                problems.append(
                    f"values {sorted(mine)} outside the model's {sorted(allowed)}"
                )
        if _types(model):
            unrestricted = (
                not _types(hand) and "enum" not in hand and "const" not in hand
            )
            if unrestricted:
                problems.append("no type where the model has one")
            elif not _types(hand) <= _types(model):
                problems.append(f"type {sorted(_types(hand))} wider than the model's")
        if (
            model.get("additionalProperties") is False
            and hand.get("additionalProperties") is not False
        ):
            problems.append("allows unknown properties where the model forbids them")
        return problems

    def _one_branch(self, hand, model, path) -> list[str]:
        problems = [
            f"{path or '<root>'}: {p}"
            for p in self._keyword_problems(hand, model, path)
        ]
        hand_props = hand.get("properties", {})
        model_props = model.get("properties", {})
        if model.get("additionalProperties") is False:
            for name in sorted(hand_props.keys() - model_props.keys()):
                problems.append(f"{_join(path, name)}: the model has no such field")
        for name in sorted(
            set(model.get("required", [])) - set(hand.get("required", []))
        ):
            problems.append(
                f"{_join(path, name)}: required by the model, optional here"
            )
        for name in sorted(hand_props.keys() & model_props.keys()):
            problems += self._compare(
                hand_props[name], model_props[name], _join(path, name)
            )
        if "items" in model or "prefixItems" in model:
            count = max(
                len(model.get("prefixItems", [])), len(hand.get("prefixItems", []))
            )
            for index in range(count):
                problems += self._compare(
                    _element(hand, index), _element(model, index), f"{path}[{index}]"
                )
            closed = hand.get("maxItems", float("inf")) <= len(
                hand.get("prefixItems", [])
            )
            if "items" in model and not closed:
                problems += self._compare(
                    _element(hand, None), _element(model, None), f"{path}[]"
                )
        extra = model.get("additionalProperties")
        if isinstance(extra, dict):
            mine = hand.get("additionalProperties")
            problems += self._compare(
                mine if isinstance(mine, dict) else {}, extra, f"{path}.*"
            )
        return problems

    def _compare(self, hand, model, path) -> list[str]:
        hand_branches, hand_null = _branches(self.hand, hand)
        model_branches, model_null = _branches(self.model, model)
        problems = []
        if hand_null and not model_null:
            problems.append(f"{path}: accepts null where the model does not")
        for branch in hand_branches:
            trials = [self._one_branch(branch, m, path) for m in model_branches]
            if trials and all(trials):
                problems += min(trials, key=len)
        return problems

    def _missing(self, hand, model, path) -> list[str]:
        hand_branches, _ = _branches(self.hand, hand)
        found = []
        for candidate in _branches(self.model, model)[0]:
            for name, child in candidate.get("properties", {}).items():
                mine = [
                    b["properties"][name]
                    for b in hand_branches
                    if name in b.get("properties", {})
                ]
                for node in mine or [{}]:
                    if not mine:
                        found.append(_join(path, name))
                        break
                    found += self._missing(node, child, _join(path, name))
            if "items" in candidate:
                items = [b["items"] for b in hand_branches if "items" in b] or [{}]
                for node in items:
                    found += self._missing(node, candidate["items"], f"{path}[]")
        return found


AUDIT = Audit(SCHEMA, MODEL)


def test_the_hand_written_schema_is_no_looser_than_the_model():
    assert AUDIT.looser() == [], (
        "publish_manifest_v2.schema.json accepts something the request model "
        "refuses. Tighten the schema to the model's bounds, patterns, enums "
        "and required members, or add an approved pattern difference here."
    )


def test_the_hand_written_schema_lists_every_model_field():
    absent = sorted(set(AUDIT.missing()) - NOT_IN_CONNECTOR_SCHEMA.keys())
    assert absent == [], (
        "The request model accepts fields that publish_manifest_v2.schema.json "
        "does not list: add each to the schema with the model's bounds, or to "
        "NOT_IN_CONNECTOR_SCHEMA in this test with a reason."
    )


def test_the_exclusions_still_name_real_model_fields():
    assert set(NOT_IN_CONNECTOR_SCHEMA) <= set(AUDIT.missing())


def test_the_approved_pattern_differences_are_still_differences():
    AUDIT.looser()
    assert set(APPROVED_PATTERN_DIFFERENCES) == AUDIT.approved_used


# -- each guard catches the change it exists for --------------------------------


def _edited_hand(edit) -> Audit:
    hand = copy.deepcopy(SCHEMA)
    edit(hand["$defs"])
    return Audit(hand, MODEL)


def _edited_model(edit) -> Audit:
    model = copy.deepcopy(MODEL)
    edit(model["$defs"])
    return Audit(SCHEMA, model)


def test_a_tighter_model_longitude_is_caught_positionally():
    def edit(defs):
        defs["ManifestMapView"]["properties"]["center"]["prefixItems"][0]["maximum"] = (
            90
        )

    assert any("center[0]" in p for p in _edited_model(edit).looser())


def test_a_hand_array_without_items_is_unconstrained():
    def edit(defs):
        del defs["lossReport"]["properties"]["items"]["items"]

    audit = _edited_hand(edit)
    assert any("maps[].loss_report.items[]" in p for p in audit.looser())
    assert "maps[].loss_report.items[].path" in audit.missing()


def test_a_hand_schema_without_a_type_is_unrestricted():
    def edit(defs):
        del defs["attribute"]["properties"]["source_name"]["type"]

    assert any("source_name" in p for p in _edited_hand(edit).looser())


def test_a_changed_pattern_is_caught_and_anchor_spelling_is_not():
    def edit(defs):
        defs["key"]["pattern"] = defs["key"]["pattern"].replace("._-", "._~-")

    assert any("pattern differs" in p for p in _edited_hand(edit).looser())
    assert AUDIT.looser() == []


def test_the_snapshot_records_the_response_roots_and_array_positions():
    schema = ManifestApplyResponse.model_json_schema()
    frozen = snapshot.build()["models"]["ManifestApplyResponse"]
    assert (
        snapshot._models("ManifestApplyResponse", schema)["ManifestApplyResponse"]
        == frozen
    )

    dropped = copy.deepcopy(schema)
    del dropped["properties"]["accepted"]
    dropped["required"].remove("accepted")
    retyped = copy.deepcopy(schema)
    retyped["properties"]["dry_run"] = {"type": "string"}
    for changed in (dropped, retyped):
        models = snapshot._models("ManifestApplyResponse", changed)
        assert models["ManifestApplyResponse"] != frozen
    assert snapshot.build()["models"]["ManifestMapView"]["center"]["type"] == (
        "tuple<number,number>"
    )
