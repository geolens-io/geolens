"""Pydantic request/response models for service probing endpoints."""

import uuid

from pydantic import BaseModel, Field, HttpUrl, field_validator


def _validate_http_url(v: str) -> str:
    """Validate HTTP/HTTPS URL format at the schema boundary.

    Returns the input string so downstream code keeps working with str. The
    SSRF guard runs separately after this format check.
    """
    HttpUrl(v)
    return v


class ProbeRequest(BaseModel):
    url: str = Field(
        min_length=1,
        max_length=2048,
        description="Service URL to probe. May be a WFS GetCapabilities URL or an ArcGIS service endpoint.",
    )
    _validate_url = field_validator("url")(_validate_http_url)
    token: str | None = Field(
        default=None,
        max_length=1000,
        description="Optional auth token for protected services (passed as query parameter or bearer token depending on service type).",
    )


class LayerInfo(BaseModel):
    name: str = Field(
        description="Internal layer identifier used by the source service."
    )
    title: str | None = Field(
        default=None,
        description="Human-readable layer title from the service capabilities.",
    )
    geometry_type: str | None = Field(
        default=None, description="Detected geometry type for the layer."
    )
    feature_count: int | None = Field(
        default=None, description="Total feature count if reported by the service."
    )
    layer_type: str = Field(
        default="layer",
        description="Layer kind: 'layer' (spatial) or 'table' (non-spatial attribute table).",
    )
    layer_id: int | str | None = Field(
        default=None, description="Numeric or string layer ID used by ArcGIS services."
    )
    object_id_field: str | None = Field(
        default=None,
        description="ArcGIS object ID field name, used for stable pagination.",
    )


class ProbeResponse(BaseModel):
    service_type: str = Field(
        description="Detected service type, e.g. 'WFS 2.0' or 'ArcGIS FeatureServer'."
    )
    url: str = Field(description="Normalized service URL after probing.")
    layers: list[LayerInfo] = Field(description="Layers exposed by the probed service.")
    selected_layer_id: int | str | None = Field(
        default=None,
        description="Auto-selected layer ID when the input URL contained a specific layer number.",
    )


class ProbeError(BaseModel):
    detail: str = Field(description="Human-readable error message.")
    error_type: str = Field(
        description="Machine-parseable error type: 'ssrf_blocked', 'timeout', 'auth_required', 'unrecognized', or 'unreachable'."
    )


class ServicePreviewRequest(BaseModel):
    url: str = Field(
        min_length=1,
        max_length=2048,
        description="Normalized service URL from a previous probe response.",
    )
    _validate_url = field_validator("url")(_validate_http_url)
    service_type: str = Field(
        min_length=1,
        max_length=100,
        description="Service type from the probe response, e.g. 'WFS 2.0.0' or 'ArcGIS FeatureServer'.",
    )
    layer_name: str = Field(
        min_length=1,
        max_length=500,
        description="Name of the specific layer to preview, from the probe layers list.",
    )
    layer_title: str | None = Field(
        default=None,
        max_length=500,
        description="Human-readable layer title from the probe LayerInfo.",
    )
    layer_id: int | str | None = Field(
        default=None, description="ArcGIS layer ID, when applicable."
    )
    token: str | None = Field(
        default=None,
        max_length=1000,
        description="Optional auth token for protected services.",
    )
    object_id_field: str | None = Field(
        default=None,
        max_length=200,
        description="ArcGIS OID field name used for orderByFields during preview pagination.",
    )


class ServicePreviewResponse(BaseModel):
    job_id: uuid.UUID = Field(
        description="IngestJob ID for the preview. Use this to commit the import."
    )
    source_filename: str | None = Field(
        description="Layer name acting as a source filename for downstream ingestion logic."
    )
    columns: list[dict[str, str]] = Field(
        description="Detected attribute columns: [{'name': str, 'type': str}, ...]."
    )
    crs: int | None = Field(description="Detected EPSG code for the layer's CRS.")
    geometry_type: str | None = Field(description="Detected geometry type.")
    feature_count: int | None = Field(
        description="Total feature count if reported by the source service."
    )
    sample_rows: list[dict] = Field(
        description="Up to 5 sample rows for preview display."
    )
    layer_name: str = Field(
        description="Layer name as it appears in the remote service."
    )
