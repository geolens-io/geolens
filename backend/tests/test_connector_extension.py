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
async def test_registered_connector_extension_can_return_opaque_credential_ref():
    import app.platform.extensions as ext_mod
    from app.platform.extensions import get_connector_extension
    from app.platform.extensions.protocols import (
        ConnectorCredentialRef,
        ConnectorDefinition,
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

    ext_mod._extensions["connectors"] = TestConnectorExtension()

    ext = get_connector_extension()
    assert ext.list_connectors()[0].supports_scheduled_sync is True
    credential = await ext.get_credential_ref(None, "arcgis", "cred-1")
    assert credential is not None
    assert credential.secret_ref.startswith("vault://")
