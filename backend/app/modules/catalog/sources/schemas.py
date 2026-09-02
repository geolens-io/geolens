"""Pydantic request/response models for service probing endpoints."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

from app.core.service_tokens import CredentialMethod, ServiceCredential
from app.core.url_redaction import has_url_credentials

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


def _validate_safe_token(v: str | None) -> str | None:
    """Reject control characters / whitespace in auth tokens (SEC-021).

    Tokens flow into a GDAL_HTTP_HEADER_FILE (WFS/OAPIF bearer) and into service
    query URLs (ArcGIS). A CR/LF or other control character could smuggle
    additional outbound HTTP headers through the libcurl pipeline. Legitimate
    JWT / base64url / ArcGIS tokens never contain control characters or
    whitespace, so reject them at the API boundary (422).
    """
    if v is None:
        return v
    if not v.isprintable():
        raise ValueError(
            "token contains control characters (possible header injection)"
        )
    if any(c.isspace() for c in v):
        raise ValueError("token contains whitespace")
    return v


# ---------------------------------------------------------------------------
# feat(#1746): the structured `auth` object every service door accepts, and the
# deprecated flat `token` that means the same thing for a bearer credential.
#
# One model, imported by the re-upload and refresh request models as well, so
# the four doors cannot describe the same credential four ways. The pydantic
# layer judges SHAPE only: which fields belong to which method, and that a
# request does not say the same thing twice. What a username or a header value
# may CONTAIN is `core/service_tokens.py`'s rule, applied at the door once the
# method has been accepted, because those rules exist to protect a composed
# header line and no line is composed here.
# ---------------------------------------------------------------------------

SERVICE_AUTH_METHOD_DESCRIPTION = (
    "How the credential is presented to the remote service. Omit the whole "
    "auth object for a public service."
)

# Every message below describes the policy and never the input. A validator
# whose ValueError interpolated a value would defeat the 422 flattener in
# standards/ogc/errors.py, which drops pydantic's `input` and keeps the
# message.
SERVICE_AUTH_BEARER_POLICY = (
    "A bearer credential is described by the token field alone. Remove the "
    "username, password, header name and header value."
)

SERVICE_AUTH_BASIC_POLICY = (
    "A username-and-password credential is described by the username and "
    "password fields, and needs both. Remove the token, header name and "
    "header value."
)

SERVICE_AUTH_HEADER_POLICY = (
    "An API-key credential is described by the header name and header value "
    "fields, and needs both. Remove the token, username and password."
)

SERVICE_AUTH_CONFLICT_POLICY = (
    "Set either the auth object or the deprecated token field, not both. The "
    "token field means the same as an auth object with method bearer."
)

SERVICE_AUTH_FIELD_DESCRIPTION = (
    "Structured credential for a protected service. Mutually exclusive with "
    "the token field."
)

DEPRECATED_TOKEN_SUFFIX = " Deprecated: use the auth object with method bearer."

_SERVICE_AUTH_CREDENTIAL_FIELDS = (
    "token",
    "username",
    "password",
    "header_name",
    "header_value",
)

# What each method is described by, exactly. The comparison in the validator is
# equality rather than a subset test, so a body that also sets a field
# belonging to another method is refused instead of having that field silently
# discarded.
_SERVICE_AUTH_SHAPES: dict[str, tuple[frozenset[str], str]] = {
    "bearer": (frozenset({"token"}), SERVICE_AUTH_BEARER_POLICY),
    "basic": (frozenset({"username", "password"}), SERVICE_AUTH_BASIC_POLICY),
    "header": (
        frozenset({"header_name", "header_value"}),
        SERVICE_AUTH_HEADER_POLICY,
    ),
}


def _names_a_credential(value: str | None) -> bool:
    """Whether *value* is a credential the caller actually supplied.

    fix(#1760 codex r1): an empty or whitespace-only string is not one. It used
    to count as supplied, so ``{"method": "bearer", "token": ""}`` passed the
    shape check, and every downstream test is a truthiness test, so the door
    then contacted the origin with no credential at all. The caller had named a
    method, which makes an anonymous request the one outcome they did not ask
    for: a public service needs no ``auth`` object, and a protected one answers
    401 in a way that reads like a broken service rather than a blank field.

    Whitespace as well as empty, because none of these values may contain
    whitespace anywhere: a blank-looking one is a typo, never a credential.
    """
    return value is not None and value.strip() != ""


class ServiceAuthRequest(BaseModel):
    """How one request authenticates to the remote service it names."""

    method: Literal["bearer", "basic", "header"] = Field(
        description=SERVICE_AUTH_METHOD_DESCRIPTION
    )
    token: str | None = Field(
        default=None,
        max_length=1000,
        description="Bearer token or API key, for method bearer.",
    )
    _validate_token = field_validator("token")(_validate_safe_token)
    username: str | None = Field(
        default=None, max_length=255, description="Username, for method basic."
    )
    password: str | None = Field(
        default=None, max_length=1000, description="Password, for method basic."
    )
    header_name: str | None = Field(
        default=None,
        max_length=255,
        description="Name of the header the key is sent under, for method header.",
    )
    header_value: str | None = Field(
        default=None,
        max_length=1000,
        description="Value of the header the key is sent under, for method header.",
    )

    @model_validator(mode="after")
    def _fields_must_match_the_method(self) -> "ServiceAuthRequest":
        required, policy = _SERVICE_AUTH_SHAPES[self.method]
        supplied = {
            name
            for name in _SERVICE_AUTH_CREDENTIAL_FIELDS
            if _names_a_credential(getattr(self, name))
        }
        if supplied != required:
            raise ValueError(policy)
        return self

    def to_credential(self, service_format: str | None = None) -> ServiceCredential:
        """The layer-neutral credential this request describes."""
        return ServiceCredential(
            method=CredentialMethod(self.method),
            service_format=service_format,
            token=self.token,
            username=self.username,
            password=self.password,
            header_name=self.header_name,
            header_value=self.header_value,
        )


def reject_service_auth_conflict(model: Any) -> Any:
    """Refuse a body that describes its credential twice.

    Used as an ``@model_validator(mode="after")`` on every request model that
    carries both spellings. Honouring one and dropping the other would make
    which credential was actually sent depend on an ordering nobody wrote down.
    """
    if model.auth is not None and model.token is not None:
        raise ValueError(SERVICE_AUTH_CONFLICT_POLICY)
    return model


def service_credential_from_request(
    auth: ServiceAuthRequest | None,
    token: str | None,
    *,
    service_format: str | None = None,
) -> ServiceCredential | None:
    """The credential a request carries, from either spelling.

    ``None`` when the request named no credential at all, so a caller can tell
    a public service from a credentialed one without inspecting a method.
    """
    if auth is not None:
        return auth.to_credential(service_format)
    if token:
        return ServiceCredential(
            method=CredentialMethod.BEARER,
            service_format=service_format,
            token=token,
        )
    return None


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
