"""DCAT-US 3.0 JSON Schema validation."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError
from referencing import Registry
from referencing.jsonschema import DRAFT202012

from app.standards.dcat_us.schemas import get_schema_definition, load_schema_definitions


@lru_cache(maxsize=1)
def _schema_registry() -> Registry:
    resources = [
        (schema["$id"], DRAFT202012.create_resource(schema))
        for schema in load_schema_definitions().values()
    ]
    return Registry().with_resources(resources)


@lru_cache(maxsize=None)
def _validator(schema_name: str) -> Draft202012Validator:
    schema = get_schema_definition(schema_name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(
        schema,
        registry=_schema_registry(),
        format_checker=FormatChecker(),
    )


def validate_dcat_us3(payload: Any, schema_name: str = "Catalog") -> dict:
    """Validate a payload against a vendored DCAT-US 3.0 schema definition."""
    errors = sorted(
        _validator(schema_name).iter_errors(payload),
        key=lambda error: list(error.absolute_path),
    )
    return {
        "schema": schema_name,
        "valid": not errors,
        "error_count": len(errors),
        "errors": [_validation_error_to_dict(error) for error in errors],
    }


def _validation_error_to_dict(error: ValidationError) -> dict:
    return {
        "path": _json_path(error.absolute_path),
        "schema_path": _json_path(error.absolute_schema_path),
        "validator": error.validator,
        "message": error.message,
    }


def _json_path(parts) -> str:
    path = "$"
    for part in parts:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}"
    return path
