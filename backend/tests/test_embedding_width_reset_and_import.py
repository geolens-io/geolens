"""Settings reset and config import resize the vector column whenever they change the embedding width.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.persistent_config import EMBEDDING_DIMS, EMBEDDING_MODEL
from tests.test_settings_router import _column_dims
from tests.test_settings_router import (
    restore_embedding_settings as restore_embedding_settings,
)

_OLD_MODEL = "width-follows-old-model"
_NEW_MODEL = "width-follows-new-model"
_REBUILD = "app.processing.embeddings.service.rebuild_embedding_column"


def _width_other_than(*widths: int) -> int:
    return next(width for width in (512, 768, 384) if width not in widths)


async def _publish_width(client, headers, session, width: int) -> None:
    """Commit an embedding_dims override through PUT, which also resizes the column."""
    resp = await client.put(
        "/settings/", json={"settings": {"embedding_dims": width}}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert await _column_dims(session) == width


async def _stored_overrides(session) -> dict:
    """Every registry key that has a database override, as an import payload."""
    from app.core.db.models import AppSetting
    from app.core.persistent_config import _registry

    keys = {cfg.key for cfg in _registry}
    rows = (await session.execute(select(AppSetting.key, AppSetting.value))).all()
    await session.rollback()
    return {
        key: value["v"] if isinstance(value, dict) and "v" in value else value
        for key, value in rows
        if key in keys
    }


async def _import_default_width(client, headers, session, mode: str, extra: dict):
    """Import a configuration that moves embedding_dims to its runtime default.

    Merge names the default; overwrite keeps every other override and omits
    embedding_dims, so the import resets it.
    """
    if mode == "merge":
        payload = {**extra, "embedding_dims": EMBEDDING_DIMS.env_default}
        return await client.post(
            "/config-ops/import/?mode=merge",
            json={"settings": payload},
            headers=headers,
        )
    payload = {**(await _stored_overrides(session)), **extra}
    payload.pop("embedding_dims", None)
    preview = await client.post(
        "/config-ops/dry-run/?mode=overwrite",
        json={"settings": payload},
        headers=headers,
    )
    assert preview.status_code == 200, preview.text
    return await client.post(
        "/config-ops/import/?mode=overwrite",
        json={"settings": payload},
        headers={
            **headers,
            "X-Config-Preview-Token": preview.json()["preview_token"],
        },
    )


async def _assert_regeneration_fits_storage(session, monkeypatch) -> None:
    """The backfill preflight accepts a vector of the published width."""
    from app.processing.embeddings import backfill

    async def _embed_at_requested_width(texts, _session, *, dimensions, **_kwargs):
        return [[0.0] * dimensions for _ in texts]

    monkeypatch.setattr(
        backfill, "generate_embeddings_batch", _embed_at_requested_width
    )
    dims = await EMBEDDING_DIMS.get_uncached(session)
    await backfill._preflight_embedding(
        session,
        (_NEW_MODEL, dims, None),
        await backfill._live_column_dims(session),
    )
    await session.rollback()


@pytest.mark.anyio
async def test_reset_resizes_the_column_to_the_default_width(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    monkeypatch,
    restore_embedding_settings,
):
    """Resetting an overridden width rebuilds storage to the runtime default."""
    default = EMBEDDING_DIMS.env_default
    await _publish_width(
        client, admin_auth_header, test_db_session, _width_other_than(default)
    )

    resp = await client.post(
        "/settings/reset/", json={"keys": ["embedding_dims"]}, headers=admin_auth_header
    )

    assert resp.status_code == 200, resp.text
    assert await EMBEDDING_DIMS.get_uncached(test_db_session) == default
    assert await _column_dims(test_db_session) == default
    await _assert_regeneration_fits_storage(test_db_session, monkeypatch)


@pytest.mark.anyio
async def test_a_failed_rebuild_on_reset_puts_the_embedding_pair_back(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    monkeypatch,
    restore_embedding_settings,
):
    """A reset whose rebuild fails answers 503 and leaves settings matching storage."""
    width = _width_other_than(EMBEDDING_DIMS.env_default)
    await _publish_width(client, admin_auth_header, test_db_session, width)
    await EMBEDDING_MODEL.set(test_db_session, _OLD_MODEL)
    monkeypatch.setattr(
        _REBUILD, AsyncMock(side_effect=RuntimeError("simulated DDL failure"))
    )

    resp = await client.post(
        "/settings/reset/",
        json={"keys": ["embedding_model", "embedding_dims"]},
        headers=admin_auth_header,
    )

    assert resp.status_code == 503
    assert await EMBEDDING_DIMS.get_uncached(test_db_session) == width
    assert await EMBEDDING_MODEL.get_uncached(test_db_session) == _OLD_MODEL
    assert await _column_dims(test_db_session) == width


@pytest.mark.anyio
async def test_a_reset_that_keeps_the_width_does_not_rebuild(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    monkeypatch,
    restore_embedding_settings,
):
    """Resetting a width that already equals the default leaves storage alone."""
    await EMBEDDING_DIMS.set(test_db_session, EMBEDDING_DIMS.env_default)
    rebuild = AsyncMock(return_value=True)
    monkeypatch.setattr(_REBUILD, rebuild)

    resp = await client.post(
        "/settings/reset/", json={"keys": ["embedding_dims"]}, headers=admin_auth_header
    )

    assert resp.status_code == 200, resp.text
    rebuild.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["merge", "overwrite"])
async def test_an_import_that_changes_the_width_resizes_the_column(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    monkeypatch,
    restore_embedding_settings,
    mode: str,
):
    """Merge and overwrite imports rebuild storage to the width they publish."""
    default = EMBEDDING_DIMS.env_default
    await _publish_width(
        client, admin_auth_header, test_db_session, _width_other_than(default)
    )

    resp = await _import_default_width(
        client, admin_auth_header, test_db_session, mode, {}
    )

    assert resp.status_code == 200, resp.text
    assert await EMBEDDING_DIMS.get_uncached(test_db_session) == default
    assert await _column_dims(test_db_session) == default
    await _assert_regeneration_fits_storage(test_db_session, monkeypatch)


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["merge", "overwrite"])
async def test_a_failed_rebuild_on_import_puts_the_embedding_pair_back(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    monkeypatch,
    restore_embedding_settings,
    mode: str,
):
    """An import whose rebuild fails answers 503 and leaves settings matching storage."""
    width = _width_other_than(EMBEDDING_DIMS.env_default)
    await _publish_width(client, admin_auth_header, test_db_session, width)
    await EMBEDDING_MODEL.set(test_db_session, _OLD_MODEL)
    monkeypatch.setattr(
        _REBUILD, AsyncMock(side_effect=RuntimeError("simulated DDL failure"))
    )

    resp = await _import_default_width(
        client,
        admin_auth_header,
        test_db_session,
        mode,
        {"embedding_model": _NEW_MODEL},
    )

    assert resp.status_code == 503
    assert await EMBEDDING_DIMS.get_uncached(test_db_session) == width
    assert await EMBEDDING_MODEL.get_uncached(test_db_session) == _OLD_MODEL
    assert await _column_dims(test_db_session) == width


@pytest.mark.anyio
async def test_an_import_that_keeps_the_width_does_not_rebuild(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    monkeypatch,
    restore_embedding_settings,
):
    """A model change, or pinning the width already in effect, leaves storage alone."""
    from app.core.db.models import AppSetting

    # No override, so the import writes the default width as one.
    await EMBEDDING_DIMS.reset(test_db_session)
    await EMBEDDING_MODEL.set(test_db_session, _OLD_MODEL)
    rebuild = AsyncMock(return_value=True)
    monkeypatch.setattr(_REBUILD, rebuild)

    resp = await client.post(
        "/config-ops/import/?mode=merge",
        json={
            "settings": {
                "embedding_model": _NEW_MODEL,
                "embedding_dims": EMBEDDING_DIMS.env_default,
            }
        },
        headers=admin_auth_header,
    )

    assert resp.status_code == 200, resp.text
    assert await EMBEDDING_MODEL.get_uncached(test_db_session) == _NEW_MODEL
    pinned = await test_db_session.scalar(
        select(AppSetting.value).where(AppSetting.key == EMBEDDING_DIMS.key)
    )
    assert pinned == {"v": EMBEDDING_DIMS.env_default}
    rebuild.assert_not_awaited()
