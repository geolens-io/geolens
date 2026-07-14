"""Tests for the persistent connector extension contract."""

from __future__ import annotations

import pytest


def _reset_registry():
    import app.platform.extensions as ext_mod

    ext_mod._extensions.clear()
    ext_mod._loaded = False


@pytest.fixture(autouse=True)
def _clean_registry():
    _reset_registry()
    yield
    _reset_registry()


def test_default_connector_extension_has_no_community_connectors():
    from app.platform.extensions import get_connector_extension
    from app.platform.extensions.protocols import ConnectorExtension

    ext = get_connector_extension()

    assert isinstance(ext, ConnectorExtension)
    assert ext.list_connectors() == []


@pytest.mark.asyncio
async def test_default_connector_extension_rejects_unknown_config():
    from app.platform.extensions import get_connector_extension

    with pytest.raises(ValueError, match=r"^Unknown connector: arcgis$"):
        await get_connector_extension().validate_config(
            "arcgis", {"url": "https://example.com"}
        )


@pytest.mark.asyncio
async def test_default_connector_extension_rejects_discovery_and_dispatch():
    from app.platform.extensions import get_connector_extension

    extension = get_connector_extension()
    with pytest.raises(ValueError, match=r"^Unknown connector: arcgis$"):
        await extension.discover_resources(
            None,
            "arcgis",
            None,
            {"url": "https://example.com"},
        )
    with pytest.raises(ValueError, match=r"^Unknown connector: arcgis$"):
        await extension.dispatch_ingest(
            None,
            "arcgis",
            None,
            "resource-1",
            {"url": "https://example.com"},
            "user-1",
        )


@pytest.mark.asyncio
async def test_registered_connector_extension_can_return_opaque_credential_ref():
    import app.platform.extensions as ext_mod
    from app.platform.extensions import get_connector_extension
    from app.platform.extensions.protocols import (
        ConnectorCredentialRef,
        ConnectorDefinition,
        ConnectorResource,
    )

    class TestConnectorExtension:
        def list_connectors(self):
            return [
                ConnectorDefinition(
                    name="arcgis",
                    display_name="ArcGIS Online",
                    config_schema={"type": "object"},
                    supports_credentials=True,
                    supports_scheduled_sync=True,
                )
            ]

        async def validate_config(self, connector_name, config):
            return {"connector": connector_name, **config}

        async def get_credential_ref(self, db, connector_name, credential_id):
            del db
            return ConnectorCredentialRef(
                id=credential_id,
                connector_name=connector_name,
                display_name="Production",
                secret_ref="vault://geolens/connectors/arcgis/prod",
            )

        async def discover_resources(self, db, connector_name, credential_ref, config):
            del db, credential_ref, config
            return [
                ConnectorResource(
                    id="resource-1",
                    name=f"{connector_name} roads",
                    kind="feature_layer",
                    metadata={"spatialReference": 4326},
                )
            ]

        async def dispatch_ingest(
            self,
            db,
            connector_name,
            credential_ref,
            resource_id,
            config,
            user_id,
        ):
            del db, connector_name, credential_ref, config, user_id
            return f"job:{resource_id}"

    ext_mod._extensions["connectors"] = TestConnectorExtension()

    ext = get_connector_extension()
    assert ext.list_connectors()[0].supports_scheduled_sync is True
    credential = await ext.get_credential_ref(None, "arcgis", "cred-1")
    assert credential is not None
    assert credential.secret_ref.startswith("vault://")
    resources = await ext.discover_resources(None, "arcgis", credential, {})
    assert resources == [
        ConnectorResource(
            id="resource-1",
            name="arcgis roads",
            kind="feature_layer",
            metadata={"spatialReference": 4326},
        )
    ]
    assert (
        await ext.dispatch_ingest(
            None,
            "arcgis",
            credential,
            resources[0].id,
            {},
            "user-1",
        )
        == "job:resource-1"
    )


def test_connector_dtos_are_exported_from_extension_package():
    from app.platform.extensions import (
        ConnectorCredentialRef,
        ConnectorDefinition,
        ConnectorResource,
    )

    assert ConnectorDefinition.__name__ == "ConnectorDefinition"
    assert ConnectorCredentialRef.__name__ == "ConnectorCredentialRef"
    assert ConnectorResource.__name__ == "ConnectorResource"
