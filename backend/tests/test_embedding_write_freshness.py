"""An embedding write lands only for the content its record still holds.

Every writer reads a record, spends a provider call, then stores the vector.
An edit that commits during that call queues its own re-embed, and the fresh
vector can be stored before the slower writer resumes. The slower writer must
then drop its result rather than overwrite the newer one with superseded text.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

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

from tests.factories import create_dataset, get_user_id

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


@pytest.mark.anyio
@pytest.mark.parametrize("force", [False, True])
async def test_backfill_keeps_the_vector_of_an_edit_made_during_its_provider_call(
    test_db_session, embedding_config, other_sessions, monkeypatch, force
):
    session = test_db_session
    record_id = await _seed(session, f"Backfill Freshness {force}")
    record = await DefaultProcessingPort().get_record(session, record_id)
    _pin_backfill(monkeypatch, [record])
    monkeypatch.setattr(service_module, "generate_embeddings_batch", _fresh_worker)

    fresh: list[str] = []

    async def _provider(texts, _sess, *, model, dimensions, base_url):
        if texts != [backfill_module._PREFLIGHT_TEXT]:
            async with other_sessions() as editor:
                await editor.execute(
                    text("UPDATE catalog.records SET summary = :s WHERE id = :rid"),
                    {"s": "Edited during the backfill", "rid": record_id},
                )
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
async def test_backfill_writes_a_record_nobody_edited(
    test_db_session, embedding_config, monkeypatch
):
    """Positive control: the freshness check passes an unchanged record."""
    session = test_db_session
    record_id = await _seed(session, "Backfill Freshness Untouched")
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
    import asyncio

    session = test_db_session
    record_id = await _seed(session, "Worker Freshness In Flight")
    session.add(
        RecordEmbedding(
            record_id=record_id,
            embedding=_STALE_VECTOR,
            model_name=_MODEL,
            content_hash="before the worker",
        )
    )
    await session.commit()

    holding = asyncio.Event()
    waited: list[bool] = []

    async def _someone_waits_on(editor_pid: int) -> bool:
        async with other_sessions() as probe:
            return bool(
                await probe.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE :pid = ANY(pg_blocking_pids(pid))"
                    ),
                    {"pid": editor_pid},
                )
            )

    async def _editor() -> None:
        async with other_sessions() as editor:
            editor_pid = await editor.scalar(text("SELECT pg_backend_pid()"))
            await editor.execute(
                text("UPDATE catalog.records SET updated_at = now() WHERE id = :rid"),
                {"rid": record_id},
            )
            await editor.execute(
                text(
                    "INSERT INTO catalog.record_keywords "
                    "(record_id, keyword, keyword_type) "
                    "VALUES (:rid, 'estuaries', 'theme')"
                ),
                {"rid": record_id},
            )
            holding.set()
            for _ in range(100):
                if await _someone_waits_on(editor_pid):
                    waited.append(True)
                    break
                await asyncio.sleep(0.05)
            await editor.commit()

    editor_task: list[asyncio.Task] = []

    async def _provider(texts, _sess, *, model, dimensions, base_url):
        editor_task.append(asyncio.create_task(_editor()))
        await holding.wait()
        return [_STALE_VECTOR for _ in texts]

    monkeypatch.setattr(service_module, "generate_embeddings_batch", _provider)

    await embed_record.func(record_id=str(record_id))
    await asyncio.wait_for(editor_task[0], timeout=30)

    assert waited, "the worker's check never waited on the edit in flight"
    assert await _stored(session, record_id) == ["before the worker"]
