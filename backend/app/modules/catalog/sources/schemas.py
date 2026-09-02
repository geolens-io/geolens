"""Pydantic request/response models for service probing endpoints."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

from app.core.url_redaction import has_url_credentials

# fix(#1746 B2b): the request-side auth schema lives in
# ``app.platform.service_auth`` and is imported back here, unmoved in the wire
# contract and unmoved for every existing importer. It had to leave this module
# because ``processing/`` may not import ``app.modules.catalog.*`` at any scope
# (test_layering PROCESS-02/04) and the import-commit door's request models are
# in ``processing/ingest/schemas.py``. One definition of what a credential
# looks like on the wire is the whole point of the object, so the model moved
# to the layer all three can reach rather than being restated in two.
from app.platform.service_auth import (
    DEPRECATED_TOKEN_SUFFIX,
    SERVICE_AUTH_BASIC_POLICY,
    SERVICE_AUTH_BEARER_POLICY,
    SERVICE_AUTH_CONFLICT_POLICY,
    SERVICE_AUTH_FIELD_DESCRIPTION,
    SERVICE_AUTH_HEADER_POLICY,
    SERVICE_AUTH_METHOD_DESCRIPTION,
    ServiceAuthRequest,
    _validate_safe_token,
    reject_service_auth_conflict,
    service_credential_from_request,
)

# Named re-exports, so a linter does not read the ones this module does not
# itself use as dead imports. Nothing does `import *` from here.
__all__ = [
    "DEPRECATED_TOKEN_SUFFIX",
    "SERVICE_AUTH_BASIC_POLICY",
    "SERVICE_AUTH_BEARER_POLICY",
    "SERVICE_AUTH_CONFLICT_POLICY",
    "SERVICE_AUTH_FIELD_DESCRIPTION",
    "SERVICE_AUTH_HEADER_POLICY",
    "SERVICE_AUTH_METHOD_DESCRIPTION",
    "ServiceAuthRequest",
    "reject_service_auth_conflict",
    "service_credential_from_request",
]

CONNECTOR_RESOURCE_HANDLE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._~-]{0,254}$"
CONNECTOR_RESOURCE_KIND_PATTERN = r"^[a-z][a-z0-9_-]{0,63}$"


class ConnectorDefinitionResponse(BaseModel):
    """Public, non-secret connector capabilities advertised by an overlay."""

    name: str
    display_name: str
    config_schema: dict[str, Any]
    supports_credentials: bool = False
    supports_scheduled_sync: bool = False


class ConnectorListResponse(BaseModel):
    connectors: list[ConnectorDefinitionResponse]


class ConnectorOperationRequest(BaseModel):
    """Configuration shared by connector discovery and ingest dispatch."""

    credential_id: str | None = Field(default=None, min_length=1, max_length=255)
    config: dict[str, Any] = Field(default_factory=dict)


class ConnectorDiscoverRequest(ConnectorOperationRequest):
    pass


class ConnectorResourceResponse(BaseModel):
    id: str = Field(
        min_length=1,
        max_length=255,
        pattern=CONNECTOR_RESOURCE_HANDLE_PATTERN,
        description=(
            "API-safe opaque resource handle. This is never a provider URL, "
            "signed locator, or credential."
        ),
    )
    name: str = Field(min_length=1, max_length=500)
    kind: str = Field(
        min_length=1,
        max_length=64,
        pattern=CONNECTOR_RESOURCE_KIND_PATTERN,
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConnectorDiscoverResponse(BaseModel):
    resources: list[ConnectorResourceResponse]


class ConnectorIngestRequest(ConnectorOperationRequest):
    resource_id: str = Field(
        min_length=1,
        max_length=255,
        pattern=CONNECTOR_RESOURCE_HANDLE_PATTERN,
        description="API-safe opaque handle returned by connector discovery.",
    )


class ConnectorIngestResponse(BaseModel):
    job_id: str = Field(
        min_length=1,
        max_length=255,
        pattern=CONNECTOR_RESOURCE_HANDLE_PATTERN,
        description="API-safe opaque handle for the dispatched ingest job.",
    )
    status: Literal["queued"] = "queued"


def _validate_http_url(v: str) -> str:
    """Validate HTTP/HTTPS URL format at the schema boundary.

    Returns the input string so downstream code keeps working with str. The
    SSRF guard runs separately after this format check.
    """
    HttpUrl(v)
    return v


def _validate_service_url(v: str) -> str:
    _validate_http_url(v)
    if has_url_credentials(v):
        raise ValueError(
            "url must not include credential query parameters; use the token field instead"
        )
    return v


class ProbeRequest(BaseModel):
    url: str = Field(
        min_length=1,
        max_length=2048,
        description="Service URL to probe. May be a WFS GetCapabilities URL or an ArcGIS service endpoint.",
    )
    _validate_url = field_validator("url")(_validate_service_url)
    token: str | None = Field(
        default=None,
        max_length=1000,
        description=(
            "Optional auth token for protected services (passed as query "
            "parameter or bearer token depending on service type)."
            + DEPRECATED_TOKEN_SUFFIX
        ),
    )
    _validate_token = field_validator("token")(_validate_safe_token)
    auth: ServiceAuthRequest | None = Field(
        default=None, description=SERVICE_AUTH_FIELD_DESCRIPTION
    )
    _reject_auth_conflict = model_validator(mode="after")(reject_service_auth_conflict)


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
    kind: Literal["vector", "raster"] = Field(
        default="vector",
        description=(
            "Backend-classified layer kind. 'vector' = point/line/polygon feature data. "
            "'raster' = imagery/coverage. Per Phase 1057 CLASS-07 D-09. "
            "Classification rule: raster IFF geometry_type contains 'raster', adapter is STAC, "
            "or layer has coverage_format/bands/mediaType:image/*. Everything else (including "
            "geometry_type=None after D-05 ogrinfo drop) defaults to 'vector'."
        ),
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


class ServicePreviewRequest(BaseModel):
    url: str = Field(
        min_length=1,
        max_length=2048,
        description="Normalized service URL from a previous probe response.",
    )
    _validate_url = field_validator("url")(_validate_service_url)
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
        description=(
            "Optional auth token for protected services." + DEPRECATED_TOKEN_SUFFIX
        ),
    )
    _validate_token = field_validator("token")(_validate_safe_token)
    object_id_field: str | None = Field(
        default=None,
        max_length=200,
        description="ArcGIS OID field name used for orderByFields during preview pagination.",
    )
    # fix(#1760 codex r2): LAST, like every other model that gained this field.
    # The generated Python SDK gives each model field a positional slot in
    # declaration order, so inserting `auth` ahead of `object_id_field` moved
    # that slot and an existing positional caller would have sent its OID
    # string as `auth` and collected a 422. Appending cannot move a slot that
    # already exists. Pinned by test_service_auth_contract_1746.
    auth: ServiceAuthRequest | None = Field(
        default=None, description=SERVICE_AUTH_FIELD_DESCRIPTION
    )
    _reject_auth_conflict = model_validator(mode="after")(reject_service_auth_conflict)


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


class ArcGISSignInRequest(BaseModel):
    """Portal address plus the credentials one generateToken call needs.

    No character policy on the two credential fields, deliberately. They are
    form-encoded into the outbound body, which percent-escapes every value,
    so neither a control character nor a separator can smuggle a second field
    into the request the way one can into a header line. The length bounds
    are here to keep an absurd body from reaching the portal at all.
    """

    portal_url: str = Field(
        min_length=1,
        max_length=2048,
        description=(
            "ArcGIS portal URL, for example https://your-org.maps.arcgis.com. "
            "The /sharing/rest base is accepted too."
        ),
    )
    _validate_portal_url = field_validator("portal_url")(_validate_service_url)
    username: str = Field(
        min_length=1,
        max_length=256,
        description="ArcGIS account name to sign in with.",
    )
    password: str = Field(
        min_length=1,
        max_length=1024,
        description="Password for that ArcGIS account.",
    )


class ArcGISSignInResponse(BaseModel):
    """The minted portal token and nothing else about the account."""

    token: str = Field(
        description=(
            "Short-lived ArcGIS portal token. Use it as the `token` field on "
            "probe, preview, commit and refresh."
        )
    )
    expires_at: datetime = Field(
        description="UTC instant at which the portal stops accepting the token."
    )
