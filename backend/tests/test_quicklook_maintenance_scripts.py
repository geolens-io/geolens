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
    db.scalar = AsyncMock(return_value=row.quicklook_256_uri)
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


@pytest.mark.anyio
async def test_forced_bulk_redraw_removes_its_upload_when_the_write_fails(monkeypatch):
    """An image whose pointer never landed is not left under the dataset prefix."""
    import sys
    from unittest.mock import AsyncMock

    from scripts import generate_vector_quicklooks as script

    row = MagicMock(
        id="22222222-2222-2222-2222-222222222222",
        table_name="t",
        geometry_type="Point",
        quicklook_256_uri=None,
    )
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[MagicMock(fetchall=lambda: [row]), RuntimeError("write failed")]
    )
    db.scalar = AsyncMock(return_value=None)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=db)
    session.__aexit__ = AsyncMock(return_value=False)
    storage = MagicMock(put=AsyncMock(), delete=AsyncMock())
    monkeypatch.setattr(sys, "argv", ["generate_vector_quicklooks.py", "--force"])
    monkeypatch.setattr(
        script,
        "create_async_engine",
        MagicMock(return_value=MagicMock(dispose=AsyncMock())),
    )
    monkeypatch.setattr(script, "sessionmaker", MagicMock(return_value=lambda: session))
    monkeypatch.setattr("app.platform.storage.init_storage", MagicMock())
    monkeypatch.setattr("app.platform.storage.get_storage", lambda: storage)
    monkeypatch.setattr(
        "app.processing.vector.quicklook.generate_vector_quicklook_with_timeout",
        AsyncMock(return_value=b"x" * 600),
    )

    await script.main()

    storage.delete.assert_awaited_once_with(storage.put.await_args.args[0])


@pytest.mark.anyio
async def test_forced_bulk_redraw_counts_a_failed_old_image_removal_as_done(
    monkeypatch, capsys
):
    """The pointer is already committed, so a cleanup failure is not a failed redraw."""
    import sys
    from unittest.mock import AsyncMock

    from scripts import generate_vector_quicklooks as script

    row = MagicMock(
        id="33333333-3333-3333-3333-333333333333",
        table_name="t",
        geometry_type="Point",
        quicklook_256_uri="vectors/33333333/quicklook_256.png",
    )
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(fetchall=lambda: [row]))
    db.scalar = AsyncMock(return_value=row.quicklook_256_uri)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=db)
    session.__aexit__ = AsyncMock(return_value=False)
    storage = MagicMock(
        put=AsyncMock(), delete=AsyncMock(side_effect=OSError("delete failed"))
    )
    monkeypatch.setattr(sys, "argv", ["generate_vector_quicklooks.py", "--force"])
    monkeypatch.setattr(
        script,
        "create_async_engine",
        MagicMock(return_value=MagicMock(dispose=AsyncMock())),
    )
    monkeypatch.setattr(script, "sessionmaker", MagicMock(return_value=lambda: session))
    monkeypatch.setattr("app.platform.storage.init_storage", MagicMock())
    monkeypatch.setattr("app.platform.storage.get_storage", lambda: storage)
    monkeypatch.setattr(
        "app.processing.vector.quicklook.generate_vector_quicklook_with_timeout",
        AsyncMock(return_value=b"x" * 600),
    )

    await script.main()

    assert "Done: 1 generated, 0 skipped." in capsys.readouterr().out


@pytest.mark.anyio
async def test_forced_bulk_redraw_removes_the_pointer_its_update_replaced(monkeypatch):
    """A pointer that moved while the image rendered is the one to reap, not the batch's copy."""
    import sys
    from unittest.mock import AsyncMock

    from scripts import generate_vector_quicklooks as script

    row = MagicMock(
        id="44444444-4444-4444-4444-444444444444",
        table_name="t",
        geometry_type="Point",
        quicklook_256_uri="vectors/44444444/quicklook_256_aaaa.png",
    )
    moved_to = "vectors/44444444/quicklook_256_bbbb.png"
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(fetchall=lambda: [row]))
    db.scalar = AsyncMock(return_value=moved_to)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=db)
    session.__aexit__ = AsyncMock(return_value=False)
    storage = MagicMock(put=AsyncMock(), delete=AsyncMock())
    monkeypatch.setattr(sys, "argv", ["generate_vector_quicklooks.py", "--force"])
    monkeypatch.setattr(
        script,
        "create_async_engine",
        MagicMock(return_value=MagicMock(dispose=AsyncMock())),
    )
    monkeypatch.setattr(script, "sessionmaker", MagicMock(return_value=lambda: session))
    monkeypatch.setattr("app.platform.storage.init_storage", MagicMock())
    monkeypatch.setattr("app.platform.storage.get_storage", lambda: storage)
    monkeypatch.setattr(
        "app.processing.vector.quicklook.generate_vector_quicklook_with_timeout",
        AsyncMock(return_value=b"x" * 600),
    )

    await script.main()

    storage.delete.assert_awaited_once_with(moved_to)


@pytest.mark.anyio
async def test_forced_bulk_redraw_removes_its_upload_when_cancelled(monkeypatch):
    """An interrupt after the upload leaves no unreferenced image and still propagates."""
    import asyncio
    import sys
    from unittest.mock import AsyncMock

    from scripts import generate_vector_quicklooks as script

    row = MagicMock(
        id="55555555-5555-5555-5555-555555555555",
        table_name="t",
        geometry_type="Point",
        quicklook_256_uri=None,
    )
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(fetchall=lambda: [row]))
    db.scalar = AsyncMock(side_effect=[asyncio.CancelledError(), None])
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=db)
    session.__aexit__ = AsyncMock(return_value=False)
    storage = MagicMock(put=AsyncMock(), delete=AsyncMock())
    monkeypatch.setattr(sys, "argv", ["generate_vector_quicklooks.py", "--force"])
    monkeypatch.setattr(
        script,
        "create_async_engine",
        MagicMock(return_value=MagicMock(dispose=AsyncMock())),
    )
    monkeypatch.setattr(script, "sessionmaker", MagicMock(return_value=lambda: session))
    monkeypatch.setattr("app.platform.storage.init_storage", MagicMock())
    monkeypatch.setattr("app.platform.storage.get_storage", lambda: storage)
    monkeypatch.setattr(
        "app.processing.vector.quicklook.generate_vector_quicklook_with_timeout",
        AsyncMock(return_value=b"x" * 600),
    )

    with pytest.raises(asyncio.CancelledError):
        await script.main()

    storage.delete.assert_awaited_once_with(storage.put.await_args.args[0])


@pytest.mark.anyio
async def test_forced_bulk_redraw_removes_its_upload_when_the_dataset_is_gone(
    monkeypatch, capsys
):
    """A pointer update that matches no row must not leave the upload behind."""
    import sys
    from unittest.mock import AsyncMock

    from scripts import generate_vector_quicklooks as script

    row = MagicMock(
        id="66666666-6666-6666-6666-666666666666",
        table_name="t",
        geometry_type="Point",
        quicklook_256_uri=None,
    )
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[MagicMock(fetchall=lambda: [row]), MagicMock(rowcount=0)]
    )
    db.scalar = AsyncMock(return_value=None)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=db)
    session.__aexit__ = AsyncMock(return_value=False)
    storage = MagicMock(put=AsyncMock(), delete=AsyncMock())
    monkeypatch.setattr(sys, "argv", ["generate_vector_quicklooks.py", "--force"])
    monkeypatch.setattr(
        script,
        "create_async_engine",
        MagicMock(return_value=MagicMock(dispose=AsyncMock())),
    )
    monkeypatch.setattr(script, "sessionmaker", MagicMock(return_value=lambda: session))
    monkeypatch.setattr("app.platform.storage.init_storage", MagicMock())
    monkeypatch.setattr("app.platform.storage.get_storage", lambda: storage)
    monkeypatch.setattr(
        "app.processing.vector.quicklook.generate_vector_quicklook_with_timeout",
        AsyncMock(return_value=b"x" * 600),
    )

    await script.main()

    storage.delete.assert_awaited_once_with(storage.put.await_args.args[0])
    assert "Done: 0 generated, 1 skipped." in capsys.readouterr().out
