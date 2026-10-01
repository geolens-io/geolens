"""Settings reset and config import rebuild the vector column to the embedding width they carry.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid
from unittest.mock import AsyncMock

import anyio
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.persistent_config import EMBEDDING_DIMS, EMBEDDING_MODEL
from tests.test_settings_router import _column_dims
from tests.test_settings_router import (
    restore_embedding_settings as restore_embedding_settings,
)

_OLD_MODEL = "width-follows-old-model"
_NEW_MODEL = "width-follows-new-model"
_REBUILD = "app.processing.embeddings.service.rebuild_embedding_column"


def _width_other_than(*widths: int) -> int:
    return next(width for width in (512, 768, 384, 256) if width not in widths)


async def _publish_width(client, headers, session, width: int) -> None:
    """Commit an embedding_dims override through PUT, which also resizes the column."""
    resp = await client.put(
        "/settings/", json={"settings": {"embedding_dims": width}}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert await _column_dims(session) == width


async def _start_consistent(session) -> int:
    """Leave settings and storage agreeing on one width, and return it."""
    width = await _column_dims(session)
    assert width is not None and width > 0
    await EMBEDDING_DIMS.set(session, width)
    return width


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


async def _resend_width(client, headers, how: str, width: int):
    """Send ``width`` again through a reset (to the default) or a merge import."""
    if how == "reset":
        return await client.post(
            "/settings/reset/", json={"keys": ["embedding_dims"]}, headers=headers
        )
    return await client.post(
        "/config-ops/import/?mode=merge",
        json={"settings": {"embedding_dims": width}},
        headers=headers,
    )


@pytest.mark.anyio
@pytest.mark.parametrize("how", ["reset", "import"])
async def test_resending_the_width_repairs_a_column_left_at_another(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    restore_embedding_settings,
    how: str,
):
    """Re-sending the published width rebuilds a column a crash left at another width."""
    from app.processing.embeddings.service import rebuild_embedding_column

    width = EMBEDDING_DIMS.env_default
    await EMBEDDING_DIMS.set(test_db_session, width)
    stale = _width_other_than(width)
    await rebuild_embedding_column(test_db_session, stale)
    assert await _column_dims(test_db_session) == stale

    resp = await _resend_width(client, admin_auth_header, how, width)

    assert resp.status_code == 200, resp.text
    assert await EMBEDDING_DIMS.get_uncached(test_db_session) == width
    assert await _column_dims(test_db_session) == width


@pytest.mark.anyio
@pytest.mark.parametrize("how", ["reset", "import"])
async def test_resending_the_width_keeps_the_vectors_of_a_matching_column(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    restore_embedding_settings,
    how: str,
):
    """Re-sending the width the column already has deletes no vectors."""
    from app.processing.embeddings.models import RecordEmbedding
    from app.processing.embeddings.service import rebuild_embedding_column
    from tests.factories import create_dataset, get_user_id

    width = EMBEDDING_DIMS.env_default
    await EMBEDDING_DIMS.set(test_db_session, width)
    await rebuild_embedding_column(test_db_session, width)
    dataset = await create_dataset(
        test_db_session,
        created_by=await get_user_id(test_db_session, "admin"),
        name="width resend keeps vectors",
    )
    record_id = dataset.record_id
    test_db_session.add(
        RecordEmbedding(
            record_id=record_id,
            embedding=[1.0] + [0.0] * (width - 1),
            model_name=_OLD_MODEL,
            content_hash=uuid.uuid4().hex,
        )
    )
    await test_db_session.commit()

    resp = await _resend_width(client, admin_auth_header, how, width)

    assert resp.status_code == 200, resp.text
    kept = await test_db_session.scalar(
        select(func.count())
        .select_from(RecordEmbedding)
        .where(RecordEmbedding.record_id == record_id)
    )
    assert kept == 1


# ---------------------------------------------------------------------------
# Overlapping width changes
# ---------------------------------------------------------------------------


def _hold_first_rebuild(monkeypatch):
    """Hold the first column rebuild until released."""
    from app.processing.embeddings import service

    original = service.rebuild_embedding_column
    held, release = anyio.Event(), anyio.Event()
    calls: list[int] = []

    async def _held(db, new_dims):
        calls.append(new_dims)
        if len(calls) == 1:
            held.set()
            await release.wait()
        return await original(db, new_dims)

    monkeypatch.setattr(service, "rebuild_embedding_column", _held)
    return held, release


async def _change_embedding(client, headers, how: str, width: int):
    """Change the embedding settings through PUT, reset or a merge import.

    The ``-model`` variants change the model alone: an import that keeps
    ``width`` and a reset of the model.
    """
    if how == "put":
        return await client.put(
            "/settings/", json={"settings": {"embedding_dims": width}}, headers=headers
        )
    if how.startswith("reset"):
        key = "embedding_model" if how == "reset-model" else "embedding_dims"
        return await client.post(
            "/settings/reset/", json={"keys": [key]}, headers=headers
        )
    settings = {"embedding_dims": width}
    if how == "import-model":
        settings["embedding_model"] = _NEW_MODEL
    return await client.post(
        "/config-ops/import/?mode=merge",
        json={"settings": settings},
        headers=headers,
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("running", "second"),
    [
        ("put", "import"),
        ("reset", "import"),
        ("import", "import"),
        ("import", "put"),
        ("import", "reset"),
        ("reset", "import-model"),
        ("import", "reset-model"),
    ],
)
async def test_an_embedding_change_is_refused_while_another_is_running(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    monkeypatch,
    restore_embedding_settings,
    running: str,
    second: str,
):
    """A second model or width change answers 409 until the first has rebuilt the column."""
    default = EMBEDDING_DIMS.env_default
    await EMBEDDING_MODEL.set(test_db_session, _OLD_MODEL)
    if running == "reset":
        await _publish_width(
            client, admin_auth_header, test_db_session, _width_other_than(default)
        )
        target = default
    else:
        target = _width_other_than(await _column_dims(test_db_session), default)
    other = _width_other_than(await _column_dims(test_db_session), target, default)
    if second == "import-model":
        other = target
    held, release = _hold_first_rebuild(monkeypatch)
    responses = {}

    async def _first():
        responses["first"] = await _change_embedding(
            client, admin_auth_header, running, target
        )

    with anyio.fail_after(60):
        async with anyio.create_task_group() as tg:
            tg.start_soon(_first)
            await held.wait()
            responses["second"] = await _change_embedding(
                client, admin_auth_header, second, other
            )
            release.set()

    assert responses["first"].status_code == 200, responses["first"].text
    assert responses["second"].status_code == 409, responses["second"].text
    assert await EMBEDDING_DIMS.get_uncached(test_db_session) == target
    assert await _column_dims(test_db_session) == target

    retried = await _change_embedding(client, admin_auth_header, second, other)
    assert retried.status_code == 200, retried.text
    committed = await EMBEDDING_DIMS.get_uncached(test_db_session)
    assert await _column_dims(test_db_session) == committed


@pytest.mark.anyio
async def test_a_put_repeating_the_model_is_not_paired_with_a_new_width(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    monkeypatch,
    restore_embedding_settings,
):
    """A pair change made while a PUT repeats the current model answers 409."""
    from app.core.persistent_config import PersistentConfig

    width = await _start_consistent(test_db_session)
    await EMBEDDING_MODEL.set(test_db_session, _OLD_MODEL)
    real_get_uncached = PersistentConfig.get_uncached
    checked, release = anyio.Event(), anyio.Event()

    # Holds the repeating PUT just after it compares the model.
    async def _hold_after_the_model_check(self, db):
        value = await real_get_uncached(self, db)
        if self is EMBEDDING_MODEL and not checked.is_set():
            checked.set()
            await release.wait()
        return value

    monkeypatch.setattr(PersistentConfig, "get_uncached", _hold_after_the_model_check)
    new_pair = {
        "embedding_model": _NEW_MODEL,
        "embedding_dims": _width_other_than(width),
    }
    responses = {}

    async def _repeat_the_model():
        responses["repeat"] = await client.put(
            "/settings/",
            json={"settings": {"embedding_model": _OLD_MODEL}},
            headers=admin_auth_header,
        )

    with anyio.fail_after(60):
        async with anyio.create_task_group() as tg:
            tg.start_soon(_repeat_the_model)
            await checked.wait()
            responses["pair"] = await client.put(
                "/settings/", json={"settings": new_pair}, headers=admin_auth_header
            )
            release.set()

    assert responses["repeat"].status_code == 200, responses["repeat"].text
    assert responses["pair"].status_code == 409, responses["pair"].text
    assert await EMBEDDING_MODEL.get_uncached(test_db_session) == _OLD_MODEL
    assert await EMBEDDING_DIMS.get_uncached(test_db_session) == width
    assert await _column_dims(test_db_session) == width


@pytest.mark.anyio
async def test_pinning_the_default_model_is_refused_while_a_reset_rebuilds(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    monkeypatch,
    restore_embedding_settings,
):
    """An import that pins the default model during a reset's rebuild answers 409."""
    from app.processing.embeddings import service

    width = _width_other_than(EMBEDDING_DIMS.env_default)
    await _publish_width(client, admin_auth_header, test_db_session, width)
    await EMBEDDING_MODEL.set(test_db_session, _OLD_MODEL)
    rebuilding, release = anyio.Event(), anyio.Event()

    async def _fail_once_released(_db, _new_dims):
        rebuilding.set()
        await release.wait()
        raise RuntimeError("simulated DDL failure")

    monkeypatch.setattr(service, "rebuild_embedding_column", _fail_once_released)
    responses = {}

    async def _reset_both():
        responses["reset"] = await client.post(
            "/settings/reset/",
            json={"keys": ["embedding_model", "embedding_dims"]},
            headers=admin_auth_header,
        )

    with anyio.fail_after(60):
        async with anyio.create_task_group() as tg:
            tg.start_soon(_reset_both)
            await rebuilding.wait()
            responses["import"] = await client.post(
                "/config-ops/import/?mode=merge",
                json={"settings": {"embedding_model": EMBEDDING_MODEL.env_default}},
                headers=admin_auth_header,
            )
            release.set()

    assert responses["import"].status_code == 409, responses["import"].text
    assert responses["reset"].status_code == 503, responses["reset"].text
    assert await EMBEDDING_MODEL.get_uncached(test_db_session) == _OLD_MODEL
    assert await EMBEDDING_DIMS.get_uncached(test_db_session) == width
    assert await _column_dims(test_db_session) == width


class _RecordingSink:
    """An audit sink that keeps every event it is handed."""

    def __init__(self) -> None:
        self.events: list = []

    async def emit(self, session, event) -> None:
        self.events.append(event)


@pytest.mark.anyio
async def test_an_import_refused_by_the_embedding_lock_reaches_no_audit_sink(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    monkeypatch,
    restore_embedding_settings,
):
    """An import refused because another embedding change holds the lock hands no sink an event."""
    from app.platform.extensions import _extensions
    from app.processing.embeddings.service import embedding_change_lock

    width = await _start_consistent(test_db_session)
    await EMBEDDING_MODEL.set(test_db_session, _OLD_MODEL)
    sink = _RecordingSink()
    monkeypatch.setitem(_extensions, "audit_sinks", [sink])
    payload = {"settings": {"embedding_model": _NEW_MODEL, "embedding_dims": width}}

    def _import_events():
        return [
            event
            for event in sink.events
            if event.resource_type in ("setting", "config")
        ]

    async with embedding_change_lock():
        refused = await client.post(
            "/config-ops/import/?mode=merge", json=payload, headers=admin_auth_header
        )

    assert refused.status_code == 409, refused.text
    assert _import_events() == []
    assert await EMBEDDING_MODEL.get_uncached(test_db_session) == _OLD_MODEL

    # The sink is wired: the same import, once the lock is free, reaches it.
    applied = await client.post(
        "/config-ops/import/?mode=merge", json=payload, headers=admin_auth_header
    )
    assert applied.status_code == 200, applied.text
    assert {event.action for event in _import_events()} == {"update", "config_import"}


@pytest.mark.anyio
async def test_a_width_change_succeeds_on_a_one_connection_pool(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    monkeypatch,
    restore_embedding_settings,
):
    """The embedding change lock needs no second connection from the request pool."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    import app.core.db as db_module
    from app.api.main import app
    from app.core.config import settings
    from app.core.dependencies import get_db

    width = await _start_consistent(test_db_session)
    target = _width_other_than(width)
    one_connection = create_async_engine(
        settings.test_database_url, pool_size=1, max_overflow=0, pool_timeout=2
    )
    factory = async_sessionmaker(one_connection, expire_on_commit=False)

    async def _get_db_from_the_one_connection():
        async with factory() as session:
            yield session

    monkeypatch.setitem(
        app.dependency_overrides, get_db, _get_db_from_the_one_connection
    )
    monkeypatch.setattr(db_module, "engine", one_connection)
    monkeypatch.setattr(db_module, "async_session", factory)
    try:
        with anyio.fail_after(30):
            resp = await client.put(
                "/settings/",
                json={"settings": {"embedding_dims": target}},
                headers=admin_auth_header,
            )
    finally:
        await one_connection.dispose()

    assert resp.status_code == 200, resp.text
    assert await _column_dims(test_db_session) == target


@pytest.mark.anyio
@pytest.mark.parametrize("how", ["reset", "import"])
async def test_a_failed_rebuild_leaves_no_override_where_there_was_none(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    monkeypatch,
    restore_embedding_settings,
    how: str,
):
    """A failed rebuild removes the overrides the change wrote instead of pinning the defaults."""
    from app.core.db.models import AppSetting

    await EMBEDDING_DIMS.reset(test_db_session)
    await EMBEDDING_MODEL.reset(test_db_session)
    monkeypatch.setattr(
        _REBUILD, AsyncMock(side_effect=RuntimeError("simulated DDL failure"))
    )

    if how == "reset":
        resp = await client.post(
            "/settings/reset/",
            json={"keys": ["embedding_model", "embedding_dims"]},
            headers=admin_auth_header,
        )
    else:
        resp = await client.post(
            "/config-ops/import/?mode=merge",
            json={
                "settings": {
                    "embedding_model": _NEW_MODEL,
                    "embedding_dims": _width_other_than(EMBEDDING_DIMS.env_default),
                }
            },
            headers=admin_auth_header,
        )

    assert resp.status_code == 503, resp.text
    overrides = (
        await test_db_session.scalars(
            select(AppSetting.key).where(
                AppSetting.key.in_((EMBEDDING_DIMS.key, EMBEDDING_MODEL.key))
            )
        )
    ).all()
    assert overrides == []
    assert (
        await EMBEDDING_DIMS.get_uncached(test_db_session) == EMBEDDING_DIMS.env_default
    )
    assert (
        await EMBEDDING_MODEL.get_uncached(test_db_session)
        == EMBEDDING_MODEL.env_default
    )
