"""Admin embedding-coverage stats must count only active-model vectors (#1503).

`catalog.record_embeddings` is keyed `(record_id, model_name)` because vectors
from different models are incomparable, and semantic search reads only the rows
matching the active model. Counting every row regardless of model reported full
coverage after a model swap while search's vector arm matched nothing.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid

import pytest
from sqlalchemy import update

from app.modules.admin.service import AdminService
from app.processing.embeddings import helpers
from app.processing.embeddings.models import RecordEmbedding

from tests.factories import create_dataset, get_user_id

_ACTIVE_MODEL = "stats-scope-active-model"
_PREVIOUS_MODEL = "stats-scope-previous-model"

# The sentinel `resolve_embedding_model_name` returns when the active model
# cannot be resolved. Matches no stored row by construction; that the real
# resolver produces it on failure is pinned by test_phase_274_caches_and_pool.
_UNKNOWN_MODEL = "__model_unknown__"


@pytest.fixture
def pinned_model(monkeypatch):
    """Pin the active embedding model the stats query scopes itself to.

    Returns a mutable holder so a test can swap the model mid-flight, which is
    the operator action (`Settings -> AI -> Embedding Model`) this bug hides.
    """
    state = {"name": _ACTIVE_MODEL}

    async def _resolve(_session):
        return state["name"]

    monkeypatch.setattr(helpers, "resolve_embedding_model_name", _resolve)
    return state


async def _add_embedding(session, record_id: uuid.UUID, model_name: str) -> None:
    """Insert one RecordEmbedding row under the given model name."""
    session.add(
        RecordEmbedding(
            record_id=record_id,
            embedding=[1.0] + [0.0] * 1535,
            model_name=model_name,
            content_hash=uuid.uuid4().hex[:64],
        )
    )
    await session.commit()


@pytest.mark.anyio
async def test_stats_count_only_active_model_embeddings(
    test_db_session,
    pinned_model,
):
    """A vector stored under a superseded model is stale, not covered."""
    service = AdminService(test_db_session)
    baseline = await service.get_embedding_stats()

    user_id = await get_user_id(test_db_session, "admin")
    dataset = await create_dataset(
        test_db_session, created_by=user_id, name="Stats Scope DS"
    )
    await _add_embedding(test_db_session, dataset.record_id, _ACTIVE_MODEL)

    covered = await service.get_embedding_stats()
    assert covered.total_records == baseline.total_records + 1
    assert covered.embedded_records == baseline.embedded_records + 1
    assert covered.missing_records == baseline.missing_records
    assert covered.stale_records == baseline.stale_records

    # The operator swaps models. Every stored vector keeps its old model_name,
    # so search can no longer use any of them. Before #1503 the stats query
    # joined on record_id alone and kept reporting this record as covered.
    await test_db_session.execute(
        update(RecordEmbedding)
        .where(RecordEmbedding.record_id == dataset.record_id)
        .values(model_name=_PREVIOUS_MODEL)
    )
    await test_db_session.commit()

    swapped = await service.get_embedding_stats()
    assert swapped.total_records == baseline.total_records + 1
    assert swapped.embedded_records == baseline.embedded_records
    assert swapped.missing_records == baseline.missing_records + 1
    assert swapped.stale_records == baseline.stale_records + 1
    assert swapped.coverage_percent < covered.coverage_percent


@pytest.mark.anyio
async def test_unresolvable_model_reports_zero_coverage(
    test_db_session,
    pinned_model,
):
    """An unknown active model reports no coverage rather than false coverage."""
    user_id = await get_user_id(test_db_session, "admin")
    dataset = await create_dataset(
        test_db_session, created_by=user_id, name="Stats Unknown Model DS"
    )
    await _add_embedding(test_db_session, dataset.record_id, _ACTIVE_MODEL)

    pinned_model["name"] = _UNKNOWN_MODEL

    stats = await AdminService(test_db_session).get_embedding_stats()
    assert stats.embedded_records == 0
    assert stats.coverage_percent == 0.0
    assert stats.missing_records == stats.total_records
    assert stats.stale_records >= 1
