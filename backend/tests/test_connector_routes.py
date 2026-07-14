"""Application wiring for the persistent connector extension."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.catalog.sources.schemas import (
    ConnectorDiscoverRequest,
    ConnectorIngestRequest,
)
from app.platform.extensions import (
    ConnectorCredentialRef,
    ConnectorDefinition,
    ConnectorResource,
)


class FakeConnectorExtension:
    def __init__(self, *, secret_metadata: bool = False) -> None:
        self.secret_metadata = secret_metadata
        self.validate_config = AsyncMock(
            side_effect=lambda _name, config: {**config, "ok": True}
        )
        self.get_credential_ref = AsyncMock(
            return_value=ConnectorCredentialRef(
                id="credential-1",
                connector_name="warehouse",
                display_name="Production",
                secret_ref="vault://private/path",
            )
        )
        metadata = {"secret_ref": "must-not-leak"} if secret_metadata else {"rows": 4}
        self.discover_resources = AsyncMock(
            return_value=[
                ConnectorResource(
                    id="roads",
                    name="Roads",
                    kind="vector",
                    metadata=metadata,
                )
            ]
        )
        self.dispatch_ingest = AsyncMock(return_value="overlay-job-42")

    def list_connectors(self):
        return [
            ConnectorDefinition(
                name="warehouse",
                display_name="Warehouse",
                config_schema={"type": "object"},
                supports_credentials=True,
                supports_scheduled_sync=True,
            )
        ]


def test_connector_openapi_declares_provider_failures():
    from app.api.main import app

    schema = app.openapi()
    for path in (
        "/services/connectors/{connector_name}/discover/",
        "/services/connectors/{connector_name}/ingest/",
    ):
        responses = schema["paths"][path]["post"]["responses"]
        assert {"502", "504"} <= responses.keys()


@pytest.fixture
def connector_context(monkeypatch):
    from app.modules.catalog.sources import router as router_module

    extension = FakeConnectorExtension()
    db = AsyncMock()
    audit = AsyncMock()
    monkeypatch.setattr(router_module, "get_connector_extension", lambda: extension)
    monkeypatch.setattr(router_module, "audit_emit", audit)
    return router_module, extension, db, audit


@pytest.mark.asyncio
async def test_connector_discovery_validates_config_and_keeps_secret_ref_opaque(
    connector_context,
):
    router_module, extension, db, audit = connector_context
    user = SimpleNamespace(id=uuid.uuid4())

    response = await router_module.discover_connector_resources_endpoint(
        "warehouse",
        ConnectorDiscoverRequest(
            credential_id="credential-1", config={"database": "catalog"}
        ),
        user,
        db,
    )

    assert response.resources[0].metadata == {"rows": 4}
    assert "secret" not in response.model_dump_json()
    extension.validate_config.assert_awaited_once()
    extension.get_credential_ref.assert_awaited_once_with(
        db, "warehouse", "credential-1"
    )
    credential = extension.discover_resources.await_args.args[2]
    assert credential.secret_ref == "vault://private/path"
    audit.assert_awaited_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_community_connector_listing_is_empty(monkeypatch):
    from app.modules.catalog.sources import router as router_module
    from app.platform.extensions.defaults import DefaultConnectorExtension

    monkeypatch.setattr(
        router_module,
        "get_connector_extension",
        lambda: DefaultConnectorExtension(),
    )

    response = await router_module.list_connectors_endpoint(
        SimpleNamespace(id=uuid.uuid4())
    )

    assert response.connectors == []


@pytest.mark.asyncio
async def test_connector_discovery_rejects_secret_shaped_metadata(
    connector_context, monkeypatch
):
    router_module, _extension, db, _audit = connector_context
    secret_extension = FakeConnectorExtension(secret_metadata=True)
    monkeypatch.setattr(
        router_module, "get_connector_extension", lambda: secret_extension
    )

    with pytest.raises(HTTPException) as exc_info:
        await router_module.discover_connector_resources_endpoint(
            "warehouse",
            ConnectorDiscoverRequest(config={}),
            SimpleNamespace(id=uuid.uuid4()),
            db,
        )

    assert exc_info.value.status_code == 502
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", "https://provider.example/roads?X-Amz-Signature=private"),
        ("name", "https://provider.example/roads?access_token=private"),
        ("kind", "https://user:private@provider.example/vector"),
    ],
)
async def test_connector_discovery_rejects_secret_bearing_public_fields(
    connector_context, field, value
):
    router_module, extension, db, audit = connector_context
    resource_values = {
        "id": "roads",
        "name": "Roads",
        "kind": "vector",
        "metadata": {"rows": 4},
    }
    resource_values[field] = value
    extension.discover_resources.return_value = [ConnectorResource(**resource_values)]

    with pytest.raises(HTTPException) as exc_info:
        await router_module.discover_connector_resources_endpoint(
            "warehouse",
            ConnectorDiscoverRequest(config={}),
            SimpleNamespace(id=uuid.uuid4()),
            db,
        )

    assert exc_info.value.status_code == 502
    assert "private" not in str(exc_info.value.detail)
    audit.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_connector_discovery_rejects_non_api_safe_resource_handle(
    connector_context,
):
    router_module, extension, db, audit = connector_context
    extension.discover_resources.return_value = [
        ConnectorResource(
            id="provider/folder/roads",
            name="Roads",
            kind="vector",
            metadata={"rows": 4},
        )
    ]

    with pytest.raises(HTTPException) as exc_info:
        await router_module.discover_connector_resources_endpoint(
            "warehouse",
            ConnectorDiscoverRequest(config={}),
            SimpleNamespace(id=uuid.uuid4()),
            db,
        )

    assert exc_info.value.status_code == 502
    audit.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.parametrize(
    "resource_id",
    [
        "provider/folder/roads",
        "https://provider.example/roads?token=private",
        " leading-space",
    ],
)
def test_connector_ingest_requires_discovery_handle(resource_id):
    with pytest.raises(ValidationError):
        ConnectorIngestRequest(resource_id=resource_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "inline_config",
    [
        {"oauth": {"client-secret": "do-not-log-this-value"}},
        {"database": {"db_password": "do-not-log-this-value"}},
        {"oauth": {"clientSecretValue": "do-not-log-this-value"}},
        {"credentials": {"value": "do-not-log-this-value"}},
        {"credential": "do-not-log-this-value"},
        {"access_key": "do-not-log-this-value"},
        {"auth": {"header": "do-not-log-this-value"}},
        {"authHeader": "do-not-log-this-value"},
        {"bearer": "do-not-log-this-value"},
        {"connectionString": "do-not-log-this-value"},
        {"warehouse_dsn": "do-not-log-this-value"},
        {"endpoint": "https://user:do-not-log-this-value@example.com/data"},
    ],
)
async def test_connector_routes_reject_nested_inline_secrets_before_validation(
    connector_context, inline_config
):
    router_module, extension, db, _audit = connector_context
    user = SimpleNamespace(id=uuid.uuid4())
    with pytest.raises(HTTPException) as discover_error:
        await router_module.discover_connector_resources_endpoint(
            "warehouse",
            ConnectorDiscoverRequest(config=inline_config),
            user,
            db,
        )
    with pytest.raises(HTTPException) as ingest_error:
        await router_module.dispatch_connector_ingest_endpoint(
            "warehouse",
            ConnectorIngestRequest(config=inline_config, resource_id="roads"),
            user,
            db,
        )

    assert discover_error.value.status_code == 400
    assert ingest_error.value.status_code == 400
    assert "do-not-log-this-value" not in str(discover_error.value.detail)
    extension.validate_config.assert_not_awaited()


@pytest.mark.asyncio
async def test_connector_ingest_dispatches_through_overlay(connector_context):
    router_module, extension, db, audit = connector_context
    user = SimpleNamespace(id=uuid.uuid4())

    response = await router_module.dispatch_connector_ingest_endpoint(
        "warehouse",
        ConnectorIngestRequest(
            credential_id="credential-1",
            config={"database": "catalog"},
            resource_id="roads",
        ),
        user,
        db,
    )

    assert response.job_id == "overlay-job-42"
    assert response.status == "queued"
    args = extension.dispatch_ingest.await_args.args
    assert args[0:2] == (db, "warehouse")
    assert args[2].secret_ref == "vault://private/path"
    assert args[3] == "roads"
    assert args[4] == {"database": "catalog", "ok": True}
    audit_details = audit.await_args.args[1].details
    assert "resource_id" not in audit_details
    assert audit_details["resource_id_sha256"] == (
        "846bb37c041492f4748c75cf4f86033ea1f009e2c939c794be7d93c072391ce6"
    )
    assert args[5] == str(user.id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "job_id",
    [
        "provider/jobs/42",
        "https://provider.example/jobs/42?signature=do-not-log-this-value",
    ],
)
async def test_connector_ingest_rejects_invalid_provider_job_handle_before_audit(
    connector_context, job_id
):
    router_module, extension, db, audit = connector_context
    extension.dispatch_ingest.return_value = job_id

    with pytest.raises(HTTPException) as exc_info:
        await router_module.dispatch_connector_ingest_endpoint(
            "warehouse",
            ConnectorIngestRequest(config={}, resource_id="roads"),
            SimpleNamespace(id=uuid.uuid4()),
            db,
        )

    assert exc_info.value.status_code == 502
    assert "do-not-log-this-value" not in str(exc_info.value.detail)
    audit.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_connector_validation_errors_do_not_echo_extension_details(
    connector_context,
):
    router_module, extension, db, _audit = connector_context
    extension.validate_config.side_effect = ValueError(
        "provider rejected do-not-log-this-value"
    )

    with pytest.raises(HTTPException) as exc_info:
        await router_module.discover_connector_resources_endpoint(
            "warehouse",
            ConnectorDiscoverRequest(config={"database": "catalog"}),
            SimpleNamespace(id=uuid.uuid4()),
            db,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid connector configuration"
    assert "do-not-log-this-value" not in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_connector_credential_must_belong_to_requested_connector(
    connector_context,
):
    router_module, extension, db, _audit = connector_context
    extension.get_credential_ref.return_value = ConnectorCredentialRef(
        id="credential-1",
        connector_name="different",
        display_name="Wrong connector",
        secret_ref="vault://private/path",
    )

    with pytest.raises(HTTPException) as exc_info:
        await router_module.discover_connector_resources_endpoint(
            "warehouse",
            ConnectorDiscoverRequest(credential_id="credential-1", config={}),
            SimpleNamespace(id=uuid.uuid4()),
            db,
        )

    assert exc_info.value.status_code == 404
