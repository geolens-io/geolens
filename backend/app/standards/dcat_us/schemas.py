"""Vendored DCAT-US 3.0 JSON Schema helpers."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any

DCAT_US_SCHEMA_VERSION = "3.0.0"
DCAT_US_SCHEMA_COMMIT = "98408dc000f0b71131a03920e2dec6247a84abff"
DCAT_US_SCHEMA_REPOSITORY = "https://github.com/GSA/dcat-us"
DCAT_US_SCHEMA_BASE_URI = "https://resources.data.gov/dcat-us/3.0.0/definitions"


@lru_cache(maxsize=1)
def load_schema_definitions() -> dict[str, dict[str, Any]]:
    """Load vendored official DCAT-US 3.0 schema definitions by lowercase name."""
    definitions_dir = files("app.standards.dcat_us").joinpath(
        "jsonschema", "definitions"
    )
    definitions: dict[str, dict[str, Any]] = {}
    for path in definitions_dir.iterdir():
        if path.name.endswith(".json"):
            with path.open("r", encoding="utf-8") as fh:
                schema = json.load(fh)
            definitions[path.stem.lower()] = schema
    return definitions


def get_schema_definition(name: str) -> dict[str, Any]:
    """Return a single vendored schema definition by case-insensitive name."""
    key = name.lower()
    try:
        return load_schema_definitions()[key]
    except KeyError as exc:
        available = ", ".join(sorted(load_schema_definitions()))
        raise ValueError(f"Unknown DCAT-US schema '{name}'. Available: {available}") from exc
