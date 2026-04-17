"""Pydantic schemas for layer creation."""

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

ALLOWED_GEOMETRY_TYPES = {
    "Point",
    "MultiPoint",
    "LineString",
    "MultiLineString",
    "Polygon",
    "MultiPolygon",
}

ALLOWED_COLUMN_TYPES = {
    "text": "TEXT",
    "integer": "INTEGER",
    "real": "DOUBLE PRECISION",
    "boolean": "BOOLEAN",
    "date": "DATE",
    "timestamp": "TIMESTAMP WITH TIME ZONE",
}

COLUMN_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")

RESERVED_COLUMNS = {"gid", "geom", "geom_4326", "id", "fid", "ogc_fid"}


class ColumnDef(BaseModel):
    name: str
    type: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not COLUMN_NAME_RE.match(v):
            raise ValueError(
                f"Column name {v!r} must start with a lowercase letter "
                "and contain only lowercase letters, digits, and underscores "
                "(max 63 chars)."
            )
        if v in RESERVED_COLUMNS:
            raise ValueError(f"Column name {v!r} is reserved and cannot be used.")
        return v

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in ALLOWED_COLUMN_TYPES:
            raise ValueError(
                f"Column type {v!r} is not allowed. "
                f"Allowed types: {sorted(ALLOWED_COLUMN_TYPES.keys())}"
            )
        return v


class AddColumnRequest(BaseModel):
    column: ColumnDef


class ColumnListResponse(BaseModel):
    columns: list[dict]


class CreateLayerRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    geometry_type: str
    summary: str | None = Field(default=None, max_length=5000)
    columns: list[ColumnDef] | None = None

    @field_validator("geometry_type")
    @classmethod
    def validate_geometry_type(cls, v: str) -> str:
        if v not in ALLOWED_GEOMETRY_TYPES:
            raise ValueError(
                f"Geometry type {v!r} is not allowed. "
                f"Allowed types: {sorted(ALLOWED_GEOMETRY_TYPES)}"
            )
        return v


class CreateLayerResponse(BaseModel):
    id: uuid.UUID
    title: str
    table_name: str
    geometry_type: str
    feature_count: int
    visibility: str
    created_at: datetime
