"""Fixtures put shared state back when their own setup raises before yielding."""

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.core.db as db_module
import app.platform.storage.provider as storage_provider_module
import tests.conftest as conftest
import tests.fixtures.multi_tenant_harness as harness
from app.api.main import app
from app.core.config import settings
from app.core.dependencies import get_db

pytestmark = pytest.mark.anyio


async def test_client_fixture_restores_shared_state_when_admin_seeding_fails(
    tmp_path, monkeypatch
):
    original_staging = settings.upload_staging_dir
    original_tempdir = tempfile.tempdir
    original_engine = db_module.engine
    original_session = db_module.async_session
    original_storage = storage_provider_module._storage
    original_overrides = dict(app.dependency_overrides)
    # monkeypatch restores these even if the fixture under test leaks them.
    monkeypatch.setattr(settings, "upload_staging_dir", original_staging)
    monkeypatch.setattr(tempfile, "tempdir", original_tempdir)
    monkeypatch.setattr(db_module, "engine", original_engine)
    monkeypatch.setattr(db_module, "async_session", original_session)
    monkeypatch.setattr(storage_provider_module, "_storage", original_storage)
    monkeypatch.setattr(conftest, "_client_session_factory", None)

    test_engine = MagicMock()
    test_engine.dispose = AsyncMock()
    monkeypatch.setattr(conftest, "_make_test_async_engine", lambda url: test_engine)
    monkeypatch.setattr(
        conftest, "_ensure_roles_and_admin", AsyncMock(side_effect=RuntimeError("seed"))
    )

    fixture = conftest.client.__wrapped__(tmp_path)
    try:
        with pytest.raises(RuntimeError, match="seed"):
            await fixture.__anext__()
        restored = (
            settings.upload_staging_dir,
            tempfile.tempdir,
            db_module.engine,
            db_module.async_session,
            storage_provider_module._storage,
            conftest._client_session_factory,
            dict(app.dependency_overrides),
        )
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)

    assert restored == (
        original_staging,
        original_tempdir,
        original_engine,
        original_session,
        original_storage,
        None,
        original_overrides,
    )
    assert get_db not in restored[-1]
    test_engine.dispose.assert_awaited_once()


@pytest.fixture
def harness_steps(monkeypatch):
    steps = MagicMock()
    steps.seed = AsyncMock(return_value=("user-a", "user-b"))
    steps.enable = AsyncMock()
    steps.disable = AsyncMock()
    steps.delete = AsyncMock()
    monkeypatch.setattr(harness, "_reload_settings", MagicMock())
    monkeypatch.setattr(harness, "_seed_users", steps.seed)
    monkeypatch.setattr(harness, "_enable_rls_autocommit", steps.enable)
    monkeypatch.setattr(harness, "_disable_rls_autocommit", steps.disable)
    monkeypatch.setattr(harness, "_delete_seeded_users", steps.delete)
    monkeypatch.setenv("GEOLENS_TENANCY_MODE", "single_tenant")
    return steps


async def test_harness_undoes_a_partial_rls_enable(harness_steps, monkeypatch):
    harness_steps.enable.side_effect = RuntimeError("enable")

    fixture = harness.multi_tenant_rls.__wrapped__(monkeypatch)
    with pytest.raises(RuntimeError, match="enable"):
        await fixture.__anext__()

    harness_steps.disable.assert_awaited_once()
    harness_steps.delete.assert_awaited_once()
    assert harness_steps.delete.await_args.args[1:] == ("user-a", "user-b")
    assert os.environ["GEOLENS_TENANCY_MODE"] == "single_tenant"


async def test_harness_restores_the_tenancy_mode_when_seeding_fails(
    harness_steps, monkeypatch
):
    harness_steps.seed.side_effect = RuntimeError("seed")

    fixture = harness.multi_tenant_rls.__wrapped__(monkeypatch)
    with pytest.raises(RuntimeError, match="seed"):
        await fixture.__anext__()

    assert os.environ["GEOLENS_TENANCY_MODE"] == "single_tenant"
    harness_steps.enable.assert_not_called()
