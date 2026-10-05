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


@pytest.mark.anyio
async def test_forced_bulk_redraw_writes_a_new_key_and_removes_the_old_image(
    monkeypatch,
):
    """Each draw gets its own key, so quicklook_version changes when the bytes do."""
    import sys
    from unittest.mock import AsyncMock

    from scripts import generate_vector_quicklooks as script

    dataset_id = "11111111-1111-1111-1111-111111111111"
    old_uri = f"vectors/{dataset_id}/quicklook_256.png"
    row = MagicMock(
        id=dataset_id,
        table_name="t",
        geometry_type="Point",
        quicklook_256_uri=old_uri,
    )
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(fetchall=lambda: [row]))
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=db)
    session.__aexit__ = AsyncMock(return_value=False)
    engine = MagicMock(dispose=AsyncMock())
    storage = MagicMock(put=AsyncMock(), delete=AsyncMock())
    monkeypatch.setattr(sys, "argv", ["generate_vector_quicklooks.py", "--force"])
    monkeypatch.setattr(script, "create_async_engine", MagicMock(return_value=engine))
    monkeypatch.setattr(script, "sessionmaker", MagicMock(return_value=lambda: session))
    monkeypatch.setattr("app.platform.storage.init_storage", MagicMock())
    monkeypatch.setattr("app.platform.storage.get_storage", lambda: storage)
    monkeypatch.setattr(
        "app.processing.vector.quicklook.generate_vector_quicklook_with_timeout",
        AsyncMock(return_value=b"x" * 600),
    )

    await script.main()

    new_key = storage.put.await_args.args[0]
    assert new_key != old_uri
    assert db.execute.await_args_list[-1].args[1]["uri"] == new_key
    storage.delete.assert_awaited_once_with(old_uri)
