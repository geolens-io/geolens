"""The quicklook maintenance scripts refuse to run in multi-tenant mode."""

from unittest.mock import MagicMock

import pytest

from app.core.config import settings


@pytest.fixture
def multi_tenant(monkeypatch):
    monkeypatch.setattr(settings, "geolens_tenancy_mode", "multi_tenant")


@pytest.mark.anyio
@pytest.mark.parametrize(
    "module_name", ["reconcile_quicklook_uris", "generate_vector_quicklooks"]
)
async def test_script_refuses_multi_tenant_mode(
    module_name, multi_tenant, monkeypatch, capsys
):
    import importlib

    module = importlib.import_module(f"scripts.{module_name}")
    engine_factory = MagicMock()
    storage_init = MagicMock()
    monkeypatch.setattr(module, "create_async_engine", engine_factory)
    monkeypatch.setattr("app.platform.storage.init_storage", storage_init)

    with pytest.raises(SystemExit) as excinfo:
        await module.main()

    assert excinfo.value.code == 2
    assert "multi-tenant mode is not supported" in capsys.readouterr().err
    engine_factory.assert_not_called()
    storage_init.assert_not_called()
