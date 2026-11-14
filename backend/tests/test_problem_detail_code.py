"""ProblemDetail emits a top-level code only when one is set, and declares it in its schema."""

from __future__ import annotations

import json

from app.standards.ogc.errors import ProblemDetail


def test_unset_code_is_omitted_not_null() -> None:
    """A problem without a code dumps exactly the four members it always had, in both dump modes."""
    problem = ProblemDetail(title="Not Found", status=404, detail="Dataset not found")
    expected = {
        "type": "about:blank",
        "title": "Not Found",
        "status": 404,
        "detail": "Dataset not found",
    }
    assert problem.model_dump() == expected
    assert json.loads(problem.model_dump_json()) == expected


def test_set_code_is_emitted_beside_detail() -> None:
    """A problem with a code dumps it as a top-level member next to an unchanged detail."""
    problem = ProblemDetail(
        title="Conflict", status=409, detail="Busy.", code="catalog_lock_conflict"
    )
    assert problem.model_dump() == {
        "type": "about:blank",
        "title": "Conflict",
        "status": 409,
        "detail": "Busy.",
        "code": "catalog_lock_conflict",
    }


def test_schema_declares_an_optional_string_code() -> None:
    """The published schema lists code as an optional string with no default, never null."""
    schema = ProblemDetail.model_json_schema()
    assert schema["properties"]["code"]["type"] == "string"
    assert "default" not in schema["properties"]["code"]
    assert "code" not in schema["required"]


def test_set_action_and_shared_maps_are_emitted_beside_detail() -> None:
    """A refusal with an action and a map list dumps them as top-level members next to an unchanged detail."""
    problem = ProblemDetail(
        title="Validation Error",
        status=422,
        detail="Cannot restrict visibility: dataset is used in shared maps: Roads.",
        code="dataset_in_shared_maps",
        action="restrict_visibility",
        shared_maps=[{"id": "00000000-0000-0000-0000-0000000000b1", "name": "Roads"}],
    )
    assert problem.model_dump() == {
        "type": "about:blank",
        "title": "Validation Error",
        "status": 422,
        "detail": "Cannot restrict visibility: dataset is used in shared maps: Roads.",
        "code": "dataset_in_shared_maps",
        "action": "restrict_visibility",
        "shared_maps": [
            {"id": "00000000-0000-0000-0000-0000000000b1", "name": "Roads"}
        ],
    }


def test_unset_action_and_shared_maps_are_omitted_not_null() -> None:
    """A problem without an action or a map list dumps exactly the members it always had."""
    problem = ProblemDetail(title="Not Found", status=404, detail="Dataset not found")
    assert "action" not in problem.model_dump()
    assert "shared_maps" not in problem.model_dump()
    assert json.loads(problem.model_dump_json()) == {
        "type": "about:blank",
        "title": "Not Found",
        "status": 404,
        "detail": "Dataset not found",
    }


def test_schema_declares_optional_action_and_shared_maps() -> None:
    """The published schema lists action as an optional string and shared_maps as an optional array, neither with a default."""
    schema = ProblemDetail.model_json_schema()
    assert schema["properties"]["action"]["type"] == "string"
    assert "default" not in schema["properties"]["action"]
    assert "action" not in schema["required"]
    assert schema["properties"]["shared_maps"]["type"] == "array"
    assert "default" not in schema["properties"]["shared_maps"]
    assert "shared_maps" not in schema["required"]
