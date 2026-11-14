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
