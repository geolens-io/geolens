"""fix(#1755 item 3): one rule for a service-credential token, on every door.

Item 3 asked whether ``_validate_safe_token`` (printable, no whitespace) could
be folded into the strict header-token policy. It cannot. ``credential_or_422``
reaches that policy only when ``requires_header_token_policy`` is true, so an
ArcGIS credential never meets it, and neither does a probe, which has no service
format yet. On that path the schema rule is the only rule.

What WAS duplicated is the schema rule itself. ``datasets/domain/schemas.py``
carried a byte-identical private copy under a second name, and while there were
two copies ``ReuploadCommitRequest.token`` and ``ServiceCommitRequest.token``
carried neither, so the deprecated flat spelling of a credential was laxer than
the ``auth`` object beside it on the same door.

These tests pin the consolidated state: every request model that accepts a
service credential judges its flat ``token`` by the one shared function, and
the strict header-token policy is unchanged in both directions.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.service_tokens import (
    ARCGIS_SERVICE_FORMAT,
    CredentialMethod,
    ServiceCredential,
)
from app.modules.catalog.datasets.domain.schemas import (
    DatasetRefreshRequest,
    ReuploadCommitRequest,
    ReuploadServicePreviewRequest,
)
from app.modules.catalog.sources.schemas import ProbeRequest, ServicePreviewRequest
from app.platform.service_auth import (
    ServiceAuthRequest,
    _validate_safe_token,
    credential_or_422,
)
from app.processing.ingest.schemas import ServiceCommitRequest

_URL = "https://services.example.test/geoserver/wfs"
_HEADER_AUTH_FORMAT = "wfs"

# Every request model whose `token` is a service credential, with the fields it
# requires. `CommitRequest` is absent because it is the flat wire union, and the
# route re-validates against `ServiceCommitRequest` before reading a credential.
_TOKEN_DOORS = {
    "probe": (ProbeRequest, {"url": _URL}),
    "service preview": (
        ServicePreviewRequest,
        {"url": _URL, "service_type": "WFS 2.0.0", "layer_name": "topp:parcels"},
    ),
    "reupload service preview": (
        ReuploadServicePreviewRequest,
        {"url": _URL, "service_type": "WFS 2.0.0", "layer_name": "topp:parcels"},
    ),
    "reupload commit": (ReuploadCommitRequest, {}),
    "refresh": (DatasetRefreshRequest, {}),
    "import commit": (ServiceCommitRequest, {"title": "Parcels"}),
    "structured auth": (ServiceAuthRequest, {"method": "bearer"}),
}

# The rule is printable and whitespace-free, so these are what it refuses. CR
# and LF are the header-smuggling primitive SEC-021 named.
# A token holding the two characters base64url refuses, so the schema layer's
# wider vocabulary is visible. Deliberately low-entropy and obviously synthetic.
_WIDE_VOCABULARY_TOKEN = "aaaa+bbbb/cccc="

_REFUSED_TOKENS = {
    "carriage return": "tok\rX-Injected: yes",
    "line feed": "tok\nX-Injected: yes",
    "embedded space": "tok en",
    "tab": "tok\ttab",
    "null": "tok\x00",
}


@pytest.mark.parametrize("door", sorted(_TOKEN_DOORS))
@pytest.mark.parametrize("kind", sorted(_REFUSED_TOKENS))
def test_every_service_credential_door_refuses_an_unsafe_token(door, kind):
    model, required = _TOKEN_DOORS[door]
    with pytest.raises(ValidationError) as exc_info:
        model(**required, token=_REFUSED_TOKENS[kind])

    fields = {error["loc"][0] for error in exc_info.value.errors()}
    assert "token" in fields, f"{door} refused the body, but not on the token field"


@pytest.mark.parametrize("door", sorted(_TOKEN_DOORS))
def test_every_service_credential_door_keeps_the_wider_vocabulary(door):
    """A token outside base64url passes the schema layer. Narrowing it is the
    door's job, and only where the credential becomes a header line."""
    model, required = _TOKEN_DOORS[door]
    model(**required, token=_WIDE_VOCABULARY_TOKEN)


@pytest.mark.parametrize("door", sorted(_TOKEN_DOORS))
def test_every_service_credential_door_uses_the_one_shared_rule(door):
    model, _ = _TOKEN_DOORS[door]
    validators = model.__pydantic_decorators__.field_validators
    on_token = [
        name
        for name, decorator in validators.items()
        if "token" in decorator.info.fields
    ]

    assert on_token, f"{door} has no validator on its token field"
    for name in on_token:
        assert validators[name].func is _validate_safe_token, (
            f"{door} judges its token by a second copy of the rule"
        )


class TestTheStrictHeaderTokenPolicyIsUnchanged:
    """The door-side half, which the schema rule neither replaces nor
    duplicates."""

    def test_a_header_auth_format_still_refuses_a_token_outside_base64url(self):
        credential = ServiceCredential(
            method=CredentialMethod.BEARER, token=_WIDE_VOCABULARY_TOKEN
        )
        with pytest.raises(HTTPException) as exc_info:
            credential_or_422(credential, service_format=_HEADER_AUTH_FORMAT)

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "invalid_service_token"

    def test_arcgis_still_accepts_a_token_outside_base64url(self):
        credential = ServiceCredential(
            method=CredentialMethod.BEARER, token=_WIDE_VOCABULARY_TOKEN
        )
        bound = credential_or_422(credential, service_format=ARCGIS_SERVICE_FORMAT)

        assert bound is not None and bound.token == _WIDE_VOCABULARY_TOKEN

    @pytest.mark.parametrize("service_format", [ARCGIS_SERVICE_FORMAT, None])
    def test_a_url_query_transport_never_reaches_the_strict_policy(
        self, service_format
    ):
        """A URL-query transport admits a control character, so the schema rule
        is the only one standing on this path."""
        credential = ServiceCredential(
            method=CredentialMethod.BEARER, token="tok\rX-Injected: yes"
        )
        bound = credential_or_422(credential, service_format=service_format)

        assert bound is not None
