"""An embedding write lands only for the content its record still holds.

Every writer reads a record, spends a provider call, then stores the vector.
An edit that commits during that call queues its own re-embed, and the fresh
vector can be stored before the slower writer resumes. The slower writer must
then drop its result rather than overwrite the newer one with superseded text.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.persistent_config import EMBEDDING_DIMS, EMBEDDING_MODEL
from app.modules.catalog.datasets.domain.models import Record, RecordTranslation
from app.platform.extensions.defaults_processing_port import DefaultProcessingPort
from app.processing.embeddings import backfill as backfill_module
from app.processing.embeddings import service as service_module
from app.processing.embeddings.models import RecordEmbedding
from app.processing.embeddings.tasks import embed_record

from tests.factories import create_dataset, create_raster_dataset, get_user_id

_DIMS = 1536
_MODEL = "freshness-model"
_STALE_VECTOR = [1.0] + [0.0] * (_DIMS - 1)
_FRESH_VECTOR = [0.0, 1.0] + [0.0] * (_DIMS - 2)


@pytest.fixture
async def embedding_config(test_db_session, monkeypatch):
    """Activate a test model, and put the AI config back afterwards."""
    before = (
        await EMBEDDING_MODEL.get(test_db_session),
        await EMBEDDING_DIMS.get(test_db_session),
    )
    await EMBEDDING_MODEL.set(test_db_session, _MODEL)
    await EMBEDDING_DIMS.set(test_db_session, _DIMS)
    monkeypatch.setattr(
        service_module, "settings", SimpleNamespace(openai_api_key="freshness-key")
    )
    yield
    await EMBEDDING_MODEL.set(test_db_session, before[0])
    await EMBEDDING_DIMS.set(test_db_session, before[1])


@pytest.fixture
async def other_sessions():
    """Sessions on their own connections, standing in for an editor and a worker."""
    engine = create_async_engine(settings.test_database_url)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _seed(session: AsyncSession, name: str) -> uuid.UUID:
    """A record with several keywords and a translation; returns its id."""
    user_id = await get_user_id(session, "admin")
    dataset = await create_dataset(
        session,
        created_by=user_id,
        name=name,
        keywords=["rivers", "hydrology", "basins"],
    )
    session.add(
        RecordTranslation(
            record_id=dataset.record_id,
            language="fr",
            title=f"{name} (fr)",
            summary="Résumé",
        )
    )
    await session.commit()
    return dataset.record_id


async def _seed_raster(session: AsyncSession, name: str) -> uuid.UUID:
    """A raster record whose asset facts are part of its embedded text."""
    user_id = await get_user_id(session, "admin")
    dataset = await create_raster_dataset(
        session,
        created_by=user_id,
        name=name,
        create_raster_asset=True,
        raster_asset_kwargs={
            "band_count": 1,
            "dtype": "float32",
            "epsg": 4326,
            "res_x": 0.5,
            "compression": "deflate",
            "size_bytes": 4 * 1024 * 1024,
        },
    )
    return dataset.record_id


async def _with_row(session: AsyncSession, record_id: uuid.UUID) -> None:
    """An existing row, so a stale write is an UPDATE that would replace it."""
    session.add(
        RecordEmbedding(
            record_id=record_id,
            embedding=_STALE_VECTOR,
            model_name=_MODEL,
            content_hash="before the worker",
        )
    )
    await session.commit()


# A raster publish's catalog writes, in its lock order: the raster row, the
# dataset, then the record.
_RASTER_PUBLISH = (
    "SELECT 1 FROM catalog.raster_assets WHERE dataset_id IN "
    "(SELECT id FROM catalog.datasets WHERE record_id = :rid) FOR UPDATE",
    "SELECT 1 FROM catalog.datasets WHERE record_id = :rid FOR UPDATE",
    "SELECT 1 FROM catalog.records WHERE id = :rid FOR UPDATE",
    "UPDATE catalog.raster_assets SET band_count = 3, dtype = 'uint8' "
    "WHERE dataset_id IN (SELECT id FROM catalog.datasets WHERE record_id = :rid)",
)


async def _hold_until_waited_on(
    sessions, statements, record_id: uuid.UUID, holding: asyncio.Event
) -> bool:
    """Run an edit, keep it open until something waits on it, then commit.

    Returns whether anything was waiting on the edit when it committed.
    """
    async with sessions() as editor:
        editor_pid = await editor.scalar(text("SELECT pg_backend_pid()"))
        for statement in statements:
            await editor.execute(text(statement), {"rid": record_id})
        holding.set()
        waited = False
        for _ in range(100):
            async with sessions() as probe:
                waited = bool(
                    await probe.scalar(
                        text(
                            "SELECT count(*) FROM pg_stat_activity "
                            "WHERE :pid = ANY(pg_blocking_pids(pid))"
                        ),
                        {"pid": editor_pid},
                    )
                )
            if waited:
                break
            await asyncio.sleep(0.05)
        await editor.commit()
        return waited


async def _embed_during_edit(
    sessions, monkeypatch, record_id: uuid.UUID, statements
) -> bool:
    """Run ``embed_record`` with an edit in flight when its provider call returns."""
    holding = asyncio.Event()
    edit: list[asyncio.Task] = []

    async def _provider(texts, _sess, *, model, dimensions, base_url):
        edit.append(
            asyncio.create_task(
                _hold_until_waited_on(sessions, statements, record_id, holding)
            )
        )
        await holding.wait()
        return [_STALE_VECTOR for _ in texts]

    monkeypatch.setattr(service_module, "generate_embeddings_batch", _provider)
    await embed_record.func(record_id=str(record_id))
    return await asyncio.wait_for(edit[0], timeout=30)


async def _stored(session: AsyncSession, record_id: uuid.UUID) -> list[str]:
    result = await session.execute(
        select(RecordEmbedding.content_hash).where(
            RecordEmbedding.record_id == record_id,
            RecordEmbedding.model_name == _MODEL,
        )
    )
    return list(result.scalars().all())


def _pin_backfill(monkeypatch, records) -> None:
    """Run the backfill over exactly these records, as the real loader read them."""
    port = SimpleNamespace(
        get_record_orm_class=lambda: Record,
        get_records_without_embeddings=AsyncMock(return_value=records),
        get_record=DefaultProcessingPort().get_record,
    )
    monkeypatch.setattr(backfill_module, "get_processing_port", lambda: port)


async def _fresh_worker(texts, _session, *, model, dimensions, base_url):
    return [_FRESH_VECTOR for _ in texts]


_RECORD_EDIT = (
    "UPDATE catalog.records SET summary = 'Edited while embedding' WHERE id = :rid",
)


@pytest.mark.anyio
@pytest.mark.parametrize("force", [False, True])
@pytest.mark.parametrize(
    ("seed", "edit"),
    [(_seed, _RECORD_EDIT), (_seed_raster, _RASTER_PUBLISH)],
    ids=["record", "raster"],
)
async def test_backfill_keeps_the_vector_of_an_edit_made_during_its_provider_call(
    test_db_session, embedding_config, other_sessions, monkeypatch, force, seed, edit
):
    session = test_db_session
    record_id = await seed(session, f"Backfill Freshness {seed.__name__} {force}")
    record = await DefaultProcessingPort().get_record(session, record_id)
    _pin_backfill(monkeypatch, [record])
    monkeypatch.setattr(service_module, "generate_embeddings_batch", _fresh_worker)

    fresh: list[str] = []

    async def _provider(texts, _sess, *, model, dimensions, base_url):
        if texts != [backfill_module._PREFLIGHT_TEXT]:
            async with other_sessions() as editor:
                for statement in edit:
                    await editor.execute(text(statement), {"rid": record_id})
                await editor.commit()
                # The edit's own re-embed lands while the backfill still waits.
                await embed_record.func(record_id=str(record_id))
                fresh.extend(await _stored(editor, record_id))
        return [_STALE_VECTOR for _ in texts]

    monkeypatch.setattr(backfill_module, "generate_embeddings_batch", _provider)

    result = await backfill_module.backfill_embeddings(session, force=force)

    assert len(fresh) == 1, "the edit's re-embed stored nothing"
    assert await _stored(session, record_id) == fresh
    assert result["created"] == 0
    assert result["skipped"] == 1


@pytest.mark.anyio
@pytest.mark.parametrize("seed", [_seed, _seed_raster], ids=["record", "raster"])
async def test_backfill_writes_a_record_nobody_edited(
    test_db_session, embedding_config, monkeypatch, seed
):
    """Positive control: the freshness check passes an unchanged record."""
    session = test_db_session
    record_id = await seed(session, f"Backfill Freshness Untouched {seed.__name__}")
    record = await DefaultProcessingPort().get_record(session, record_id)
    _pin_backfill(monkeypatch, [record])

    async def _provider(texts, _sess, *, model, dimensions, base_url):
        return [_STALE_VECTOR for _ in texts]

    monkeypatch.setattr(backfill_module, "generate_embeddings_batch", _provider)

    result = await backfill_module.backfill_embeddings(session, force=True)

    assert result["created"] == 1
    assert len(await _stored(session, record_id)) == 1


@pytest.mark.anyio
async def test_embed_record_keeps_the_vector_of_an_edit_made_during_its_provider_call(
    test_db_session, embedding_config, other_sessions, monkeypatch
):
    """Two queued re-embeds of one record: the one that read older text loses."""
    session = test_db_session
    record_id = await _seed(session, "Worker Freshness")
    # An existing row, so the slower worker's write is an UPDATE that would
    # replace the newer vector instead of failing on the unique key.
    session.add(
        RecordEmbedding(
            record_id=record_id,
            embedding=_STALE_VECTOR,
            model_name=_MODEL,
            content_hash="before either worker",
        )
    )
    await session.commit()

    calls = {"n": 0}
    fresh: list[str] = []

    async def _provider(texts, _sess, *, model, dimensions, base_url):
        calls["n"] += 1
        if calls["n"] > 1:
            return [_FRESH_VECTOR for _ in texts]
        async with other_sessions() as editor:
            await editor.execute(
                text(
                    "UPDATE catalog.record_translations SET title = :t "
                    "WHERE record_id = :rid"
                ),
                {"t": "Titre modifié", "rid": record_id},
            )
            await editor.commit()
            await embed_record.func(record_id=str(record_id))
            fresh.extend(await _stored(editor, record_id))
        return [_STALE_VECTOR for _ in texts]

    monkeypatch.setattr(service_module, "generate_embeddings_batch", _provider)

    await embed_record.func(record_id=str(record_id))

    assert calls["n"] == 2
    assert fresh != ["before either worker"], "the edit's re-embed stored nothing"
    assert await _stored(session, record_id) == fresh


@pytest.mark.anyio
async def test_embed_record_sees_a_keyword_edit_that_held_the_record_during_its_check(
    test_db_session, embedding_config, other_sessions, monkeypatch
):
    """The check waits for an edit holding the record, then reads what it wrote.

    The records API stamps the record before it touches keywords, so an edit
    in flight holds the record row. A check that started waiting on it must
    still see the keyword it added once it commits.
    """
    session = test_db_session
    record_id = await _seed(session, "Worker Freshness In Flight")
    await _with_row(session, record_id)

    waited = await _embed_during_edit(
        other_sessions,
        monkeypatch,
        record_id,
        (
            "UPDATE catalog.records SET updated_at = now() WHERE id = :rid",
            "INSERT INTO catalog.record_keywords (record_id, keyword, keyword_type) "
            "VALUES (:rid, 'estuaries', 'theme')",
        ),
    )

    assert waited, "the worker's check never waited on the edit in flight"
    assert await _stored(session, record_id) == ["before the worker"]


@pytest.mark.anyio
async def test_embed_record_keeps_the_vector_of_a_raster_publish_made_during_its_provider_call(
    test_db_session, embedding_config, other_sessions, monkeypatch
):
    """A raster's asset facts are embedded text, so a new raster is new content."""
    session = test_db_session
    record_id = await _seed_raster(session, "Raster Freshness")
    await _with_row(session, record_id)

    calls = {"n": 0}
    fresh: list[str] = []

    async def _provider(texts, _sess, *, model, dimensions, base_url):
        calls["n"] += 1
        if calls["n"] > 1:
            return [_FRESH_VECTOR for _ in texts]
        async with other_sessions() as publisher:
            for statement in _RASTER_PUBLISH:
                await publisher.execute(text(statement), {"rid": record_id})
            await publisher.commit()
            # The publish's own re-embed lands while this worker still waits.
            await embed_record.func(record_id=str(record_id))
            fresh.extend(await _stored(publisher, record_id))
        return [_STALE_VECTOR for _ in texts]

    monkeypatch.setattr(service_module, "generate_embeddings_batch", _provider)

    await embed_record.func(record_id=str(record_id))

    assert calls["n"] == 2
    assert fresh != ["before the worker"], "the publish's re-embed stored nothing"
    assert await _stored(session, record_id) == fresh


@pytest.mark.anyio
async def test_embed_record_sees_a_raster_publish_that_held_the_record_during_its_check(
    test_db_session, embedding_config, other_sessions, monkeypatch
):
    """Raster publishes lock the record row, which orders them with the check."""
    session = test_db_session
    record_id = await _seed_raster(session, "Raster Freshness In Flight")
    await _with_row(session, record_id)

    waited = await _embed_during_edit(
        other_sessions, monkeypatch, record_id, _RASTER_PUBLISH
    )

    assert waited, "the worker's check never waited on the publish in flight"
    assert await _stored(session, record_id) == ["before the worker"]
