"""Pydantic request/response models for service probing endpoints."""

import uuid

from pydantic import BaseModel, Field


class ProbeRequest(BaseModel):
    url: str = Field(min_length=1)
    token: str | None = None


class LayerInfo(BaseModel):
    name: str
    title: str | None = None
    geometry_type: str | None = None
    feature_count: int | None = None
    layer_type: str = "layer"  # "layer" or "table"
    layer_id: int | str | None = None
    object_id_field: str | None = None  # ArcGIS OID field name


class ProbeResponse(BaseModel):
    service_type: str  # e.g. "WFS 2.0", "ArcGIS FeatureServer"
    url: str  # normalized URL
    layers: list[LayerInfo]
    selected_layer_id: int | str | None = (
        None  # auto-selected if URL contained layer number
    )


class ProbeError(BaseModel):
    detail: str
    error_type: (
        str  # "ssrf_blocked", "timeout", "auth_required", "unrecognized", "unreachable"
    )


class ServicePreviewRequest(BaseModel):
    url: str = Field(min_length=1)  # Normalized service URL (from probe response)
    service_type: str  # "WFS 2.0.0" or "ArcGIS FeatureServer" (from probe)
    layer_name: str  # Layer name (from probe layers list)
    layer_title: str | None = (
        None  # Human-readable layer title (from probe LayerInfo.title)
    )
    layer_id: int | str | None = None  # Layer ID (for ArcGIS, from probe layers list)
    token: str | None = None  # Optional auth token for protected services
    object_id_field: str | None = None  # ArcGIS OID field name for orderByFields


class ServicePreviewResponse(BaseModel):
    job_id: uuid.UUID  # IngestJob ID for subsequent commit
    source_filename: str | None  # Layer name (matches file preview field name)
    columns: list[dict]  # [{"name": str, "type": str}, ...]
    crs: int | None  # EPSG code
    geometry_type: str | None
    feature_count: int | None
    sample_rows: list[dict]  # [{col: value, ...}, ...]
    layer_name: str  # Layer name from remote service
