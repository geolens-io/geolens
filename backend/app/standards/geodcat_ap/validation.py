"""GeoDCAT-AP 2.0.0 structural validation.

The GeoDCAT-AP specification does not publish an official JSON Schema for its
JSON-LD serialization (its normative artifacts are SHACL shapes), so this
module applies structural / required-field validation that mirrors the
mandatory-class cardinalities of the specification. The report shape matches
``app.standards.dcat_us.validation.validate_dcat_us3`` so the two profiles
share a consistent validation contract.
"""

from __future__ import annotations

from typing import Any

from app.standards.geodcat_ap.schemas import (
    CATALOG_REQUIRED_PROPERTIES,
    CATALOG_TYPE,
    DATASET_REQUIRED_PROPERTIES,
    DATASET_TYPE,
)


def validate_geodcat_ap(payload: Any, schema_name: str = "Catalog") -> dict:
    """Validate a payload against the GeoDCAT-AP 2.0.0 structural expectations.

    Args:
        payload: The serialized JSON-LD dict (Catalog or Dataset).
        schema_name: ``"Catalog"`` or ``"Dataset"``.

    Returns:
        A report dict identical in shape to the DCAT-US validator:
        ``{"schema", "valid", "error_count", "errors"}`` where each error has
        ``path``, ``schema_path``, ``validator`` and ``message``.
    """
    if schema_name == "Catalog":
        errors = _validate_catalog(payload)
    elif schema_name == "Dataset":
        errors = _validate_dataset(payload, "$")
    else:
        errors = [
            _error(
                "$",
                "schema",
                f"Unknown GeoDCAT-AP schema '{schema_name}'. "
                "Available: Catalog, Dataset",
            )
        ]

    return {
        "schema": schema_name,
        "valid": not errors,
        "error_count": len(errors),
        "errors": errors,
    }


def _validate_catalog(payload: Any) -> list[dict]:
    errors: list[dict] = []
    if not isinstance(payload, dict):
        return [_error("$", "type", "Catalog must be a JSON object")]

    if payload.get("@type") != CATALOG_TYPE:
        errors.append(
            _error(
                "$.@type",
                "const",
                f"Catalog @type must be '{CATALOG_TYPE}'",
            )
        )

    for prop in CATALOG_REQUIRED_PROPERTIES:
        if not _has_value(payload, prop):
            errors.append(_error("$", "required", f"'{prop}' is a required property"))

    datasets = payload.get("dcat:dataset")
    if isinstance(datasets, list):
        for index, entry in enumerate(datasets):
            errors.extend(_validate_dataset(entry, f"$.dcat:dataset[{index}]"))

    return errors


def _validate_dataset(payload: Any, path: str) -> list[dict]:
    errors: list[dict] = []
    if not isinstance(payload, dict):
        return [_error(path, "type", "Dataset must be a JSON object")]

    if payload.get("@type") != DATASET_TYPE:
        errors.append(
            _error(
                f"{path}.@type",
                "const",
                f"Dataset @type must be '{DATASET_TYPE}'",
            )
        )

    for prop in DATASET_REQUIRED_PROPERTIES:
        if not _has_value(payload, prop):
            errors.append(_error(path, "required", f"'{prop}' is a required property"))

    return errors


def _has_value(payload: dict, key: str) -> bool:
    value = payload.get(key)
    return value is not None and value != [] and value != {} and value != ""


def _error(path: str, validator: str, message: str) -> dict:
    return {
        "path": path,
        "schema_path": f"{path}/{validator}",
        "validator": validator,
        "message": message,
    }
