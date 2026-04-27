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


class RenameColumnRequest(BaseModel):
    new_name: str = Field(description="New column name (lowercase identifier).")

    @field_validator("new_name")
    @classmethod
    def validate_new_name(cls, v: str) -> str:
        if not COLUMN_NAME_RE.match(v):
            raise ValueError(
                f"Column name {v!r} must start with a lowercase letter "
                "and contain only lowercase letters, digits, and underscores "
                "(max 63 chars)."
            )
        if v in RESERVED_COLUMNS:
            raise ValueError(f"Column name {v!r} is reserved and cannot be used.")
        return v


class AlterColumnTypeRequest(BaseModel):
    new_type: str = Field(
        description="New column type: text/integer/real/boolean/date/timestamp."
    )

    @field_validator("new_type")
    @classmethod
    def validate_new_type(cls, v: str) -> str:
        if v not in ALLOWED_COLUMN_TYPES:
            raise ValueError(
                f"Column type {v!r} is not allowed. "
                f"Allowed types: {sorted(ALLOWED_COLUMN_TYPES.keys())}"
            )
        return v


class CreateLayerRequest(BaseModel):
    title: str = Field(
        min_length=1,
        max_length=500,
        description="Display name for the new layer",
        example="Survey Points",
    )
    geometry_type: str = Field(
        description="OGC geometry type: Point, MultiPoint, LineString, MultiLineString, Polygon, or MultiPolygon",
        example="Point",
    )
    summary: str | None = Field(
        default=None,
        max_length=5000,
        description="Optional text description of the layer",
    )
    columns: list[ColumnDef] | None = Field(
        default=None, description="Optional initial column definitions"
    )

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
    id: uuid.UUID = Field(description="Dataset ID of the created layer")
    title: str = Field(description="Display name")
    table_name: str = Field(description="PostGIS table name in the data schema")
    geometry_type: str = Field(description="OGC geometry type")
    feature_count: int = Field(description="Number of features (0 for new layers)")
    visibility: str = Field(
        description="Visibility level: private, internal, or public"
    )
    created_at: datetime = Field(description="Creation timestamp")
