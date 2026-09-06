"""fix(#1755 item 3): one rule for a service-credential token, on every door.

Every request model accepting a service credential judges its flat ``token`` by
one shared function, and the door-side header-token policy is unchanged.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
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
from app.platform.jobs.models import IngestJob
from app.platform.service_auth import (
    ServiceAuthRequest,
    _validate_safe_token,
    credential_or_422,
)
from app.processing.ingest.schemas import ServiceCommitRequest
from tests.factories import create_dataset, get_user_id

# The dispatch harnesses #1676 built for these two doors, reused so this suite
# answers to the same model of a door that the door-policy suite does.
from tests.test_import_token_lease_1676 import (  # noqa: F401
    _import_harness,
    _reupload_harness,
)

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

# The two characters base64url refuses, as a low-entropy synthetic value.
_WIDE_VOCABULARY_TOKEN = "aaaa+bbbb/cccc="

_TOKEN_MAX_LENGTH = 1000

# The rule is printable and whitespace-free, so these are what it refuses.
# CR and LF are the header-smuggling primitive SEC-021 named.
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
def test_every_service_credential_door_caps_its_token(door):
    model, required = _TOKEN_DOORS[door]
    model(**required, token="a" * _TOKEN_MAX_LENGTH)

    with pytest.raises(ValidationError) as exc_info:
        model(**required, token="a" * (_TOKEN_MAX_LENGTH + 1))

    fields = {error["loc"][0] for error in exc_info.value.errors()}
    assert "token" in fields, f"{door} refused the body, but not on the token field"


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


# ---------------------------------------------------------------------------
# The same rule over HTTP, at the two doors this change converted
# ---------------------------------------------------------------------------

_ARCGIS_URL = "https://example.arcgis.test/rest/services/P/FeatureServer/0"

# Whitespace rather than a control character, so `secret not in resp.text` is a
# real assertion: JSON escapes a CR, and the raw byte would never appear anyway.
_UNSAFE_TOKEN_OVER_HTTP = "aaaa bbbb cccc"


async def _arcgis_job(session, *, created_by: uuid.UUID, dataset_id=None) -> IngestJob:
    """A pending ArcGIS service job, bound to a dataset when one is given."""
    metadata: dict = {"service_type": "ArcGIS FeatureServer", "layer_id": 0}
    if dataset_id is not None:
        metadata |= {
            "reupload": True,
            "dataset_id": str(dataset_id),
            "source_type": "service_url",
        }
    job = IngestJob(
        dataset_id=dataset_id,
        source_filename="Parcels",
        source_url=_ARCGIS_URL,
        source_layer="0",
        created_by=created_by,
        status="pending",
        user_metadata=metadata,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


def _assert_refused_without_the_token(resp, secret: str) -> None:
    """422 carrying the shared refusal code, and the credential absent."""
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    # fix(#1924): a schema-layer refusal publishes the same code a door-layer
    # one does — the frontend banner and the CLI sentence key on it.
    assert detail["code"] == "invalid_service_token"
    assert "whitespace" in detail["message"]
    # `ValidationError.errors()` carries the raw input; the handler in
    # standards/ogc/errors.py renders the code and policy and drops it.
    assert secret not in resp.text


class TestTheCommitDoorsRefuseOverHttp:
    """The refusal the schema rule newly performs, exercised end to end."""

    pytestmark = pytest.mark.anyio

    async def test_the_import_commit_door_refuses_and_never_echoes_the_token(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ) -> None:
        admin_id = await get_user_id(test_db_session, "admin")
        job = await _arcgis_job(test_db_session, created_by=admin_id)

        async with _import_harness() as task:
            resp = await client.post(
                f"/ingest/commit/{job.id}",
                json={"title": "Parcels", "token": _UNSAFE_TOKEN_OVER_HTTP},
                headers=admin_auth_header,
            )

        _assert_refused_without_the_token(resp, _UNSAFE_TOKEN_OVER_HTTP)
        task.defer_async.assert_not_awaited()

    async def test_the_import_commit_door_refuses_a_token_past_the_cap(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ) -> None:
        """The cap is not a coded refusal, so it answers with the field list."""
        admin_id = await get_user_id(test_db_session, "admin")
        job = await _arcgis_job(test_db_session, created_by=admin_id)
        over_cap = "a" * (_TOKEN_MAX_LENGTH + 1)

        async with _import_harness() as task:
            resp = await client.post(
                f"/ingest/commit/{job.id}",
                json={"title": "Parcels", "token": over_cap},
                headers=admin_auth_header,
            )

        assert resp.status_code == 422, resp.text
        detail = resp.json()["detail"]
        assert isinstance(detail, str)
        assert detail.startswith("token:")
        assert over_cap not in resp.text
        task.defer_async.assert_not_awaited()

    async def test_the_reupload_commit_door_refuses_and_never_echoes_the_token(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ) -> None:
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(
            test_db_session,
            created_by=admin_id,
            name="ArcGIS Reupload Dataset",
            visibility="public",
            feature_count=100,
            source_filename="original.geojson",
            source_url=_ARCGIS_URL,
        )
        job = await _arcgis_job(
            test_db_session, created_by=admin_id, dataset_id=dataset.id
        )

        async with _reupload_harness() as task:
            resp = await client.post(
                f"/datasets/{dataset.id}/reupload/{job.id}/commit",
                json={"token": _UNSAFE_TOKEN_OVER_HTTP},
                headers=admin_auth_header,
            )

        _assert_refused_without_the_token(resp, _UNSAFE_TOKEN_OVER_HTTP)
        task.defer_async.assert_not_awaited()

    async def test_a_second_field_error_keeps_the_flattened_list(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ) -> None:
        """fix(#1924): a second field error keeps the flattened list."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(
            test_db_session,
            created_by=admin_id,
            name="ArcGIS Reupload Dataset Two",
            visibility="public",
            feature_count=100,
            source_filename="original.geojson",
            source_url=_ARCGIS_URL,
        )
        job = await _arcgis_job(
            test_db_session, created_by=admin_id, dataset_id=dataset.id
        )

        async with _reupload_harness() as task:
            resp = await client.post(
                f"/datasets/{dataset.id}/reupload/{job.id}/commit",
                json={"token": _UNSAFE_TOKEN_OVER_HTTP, "srid_override": 0},
                headers=admin_auth_header,
            )

        assert resp.status_code == 422, resp.text
        detail = resp.json()["detail"]
        assert isinstance(detail, str)
        assert "body.token:" in detail and "body.srid_override:" in detail
        assert _UNSAFE_TOKEN_OVER_HTTP not in resp.text
        task.defer_async.assert_not_awaited()
