"""OGC API Features Part 3 queryables, schema introspection, and CQL2 filtering."""

import json
from datetime import date, datetime
from typing import Any

from fastapi import HTTPException, status
from pydantic import BaseModel, Field

from app.datasets.models import Dataset, Record
from app.ogc.utils import build_url
from app.search.schemas import OGCRecordResponse


class DatasetQueryables(BaseModel):
    """Queryable properties for the datasets collection.

    Each field corresponds to a filterable property exposed via the
    /collections/datasets/queryables endpoint.
    """

    title: str = Field(description="Dataset title")
    description: str | None = Field(default=None, description="Dataset description")
    geometry_type: str | None = Field(default=None, description="Geometry type")
    srid: int | None = Field(
        default=None, description="Spatial Reference ID (EPSG code)"
    )
    source_organization: str | None = Field(
        default=None, description="Data source organization"
    )
    license: str | None = Field(default=None, description="Data license")
    created: datetime | None = Field(
        default=None, description="Record creation timestamp"
    )
    updated: datetime | None = Field(
        default=None, description="Record last update timestamp"
    )
    data_vintage_start: date | None = Field(
        default=None, description="Data vintage start date"
    )
    data_vintage_end: date | None = Field(
        default=None, description="Data vintage end date"
    )


# Maps OGC queryable property names to SQLAlchemy model columns.
# After records+datasets split, shared metadata fields are on Record.
FIELD_MAPPING = {
    "title": Record.title,
    "description": Record.summary,
    "geometry_type": Dataset.geometry_type,
    "srid": Dataset.srid,
    "source_organization": Record.source_organization,
    "license": Record.license,
    "created": Record.created_at,
    "updated": Record.updated_at,
    "data_vintage_start": Record.temporal_start,
    "data_vintage_end": Record.temporal_end,
    "geometry": Record.spatial_extent,  # spatial predicates
}


def parse_cql2_filter(filter_expr: str, filter_lang: str) -> Any:
    """Parse a CQL2 filter expression into an AST.

    Args:
        filter_expr: The CQL2 filter expression string.
        filter_lang: Either "cql2-text" or "cql2-json".

    Returns:
        Parsed AST from pygeofilter.

    Raises:
        HTTPException(400): On unsupported filter-lang or invalid expression.
    """
    from lark.exceptions import (
        UnexpectedCharacters,
        UnexpectedInput,
        UnexpectedToken,
    )

    if filter_lang == "cql2-text":
        from pygeofilter.parsers.cql2_text import parse

        try:
            return parse(filter_expr)
        except (
            UnexpectedToken,
            UnexpectedCharacters,
            UnexpectedInput,
            ValueError,
            KeyError,
        ) as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid CQL2 expression: {e}")
    elif filter_lang == "cql2-json":
        from pygeofilter.parsers.cql2_json import parse

        try:
            filter_dict = (
                json.loads(filter_expr) if isinstance(filter_expr, str) else filter_expr
            )
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid CQL2 expression: {e}")
        try:
            return parse(filter_dict)
        except (ValueError, KeyError, TypeError) as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid CQL2 expression: {e}")
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported filter-lang: {filter_lang}. Use cql2-text or cql2-json.",
        )


def apply_cql2_filter(stmt: Any, filter_expr: str, filter_lang: str = "cql2-text") -> Any:
    """Parse a CQL2 expression and apply it as a WHERE clause to a SQLAlchemy statement.

    Args:
        stmt: SQLAlchemy select statement to add the filter to.
        filter_expr: The CQL2 filter expression string.
        filter_lang: Either "cql2-text" or "cql2-json".

    Returns:
        The statement with the CQL2 filter applied.

    Raises:
        HTTPException(400): On invalid CQL2 expression or filter translation error.
    """
    from pygeofilter.backends.sqlalchemy import to_filter

    ast = parse_cql2_filter(filter_expr, filter_lang)
    try:
        sa_filter = to_filter(ast, FIELD_MAPPING)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid CQL2 expression: {e}")
    return stmt.where(sa_filter)


def build_queryables_response(public_api_url: str) -> dict:
    """Build a JSON Schema describing queryable properties (OGC Part 3)."""
    schema = DatasetQueryables.model_json_schema()
    schema["$id"] = build_url(
        "/collections/datasets/queryables", base_url=public_api_url
    )
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["type"] = "object"
    schema["additionalProperties"] = True

    # Add geometry property (not on the Pydantic model since it's spatial-only)
    props = schema.setdefault("properties", {})
    props["geometry"] = {
        "description": "Dataset spatial extent",
        "format": "geometry-polygon",
    }

    return schema


def build_record_schema_response(public_api_url: str) -> dict:
    """Build a JSON Schema describing the full OGC Record structure."""
    schema = OGCRecordResponse.model_json_schema()
    schema["$id"] = build_url("/collections/datasets/schema", base_url=public_api_url)
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    return schema
