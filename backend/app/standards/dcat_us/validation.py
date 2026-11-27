"""DCAT-US 3.0 JSON Schema validation."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError
from referencing import Registry
from referencing.jsonschema import DRAFT202012

from app.standards.dcat_us.schemas import get_schema_definition, load_schema_definitions


def _format_checker() -> FormatChecker:
    """The stock checker, with ASCII IRIs settled by the fast URI check.

    The ``rfc3987_syntax`` IRI parser costs tens of milliseconds a value, which
    adds up to seconds across a catalog feed's distribution URLs. A string that
    passes the URI grammar is a valid IRI, so only the rest reach the parser.
    """
    checker = FormatChecker()
    for iri_format, uri_format in (("iri", "uri"), ("iri-reference", "uri-reference")):
        slow, fast = checker.checkers.get(iri_format), checker.checkers.get(uri_format)
        if slow is not None and fast is not None:
            checker.checks(iri_format, raises=slow[1])(
                _ascii_fast_path(fast[0], slow[0])
            )
    return checker


def _is_plain_ascii(value: str) -> bool:
    # The URI regex's `$` tolerates a trailing newline and its IPv6 literal
    # check is looser than the IRI parser's, so whitespace, control characters
    # and bracketed hosts take the stock path.
    return (
        value.isascii()
        and value.isprintable()
        and " " not in value
        and "[" not in value
    )


def _ascii_fast_path(fast, slow):
    def check(instance: object) -> bool:
        if isinstance(instance, str) and _is_plain_ascii(instance):
            try:
                if fast(instance):
                    return True
            except ValueError:
                pass
        return slow(instance)

    return check


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
        format_checker=_format_checker(),
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
