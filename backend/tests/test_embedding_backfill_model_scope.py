"""The non-force backfill must select on the ACTIVE embedding model (#1506).

`catalog.record_embeddings` is keyed `(record_id, model_name)` and semantic
search reads only rows matching the active model. While "missing" meant "has no
row at all", every record kept its superseded row through a model swap, so
Generate Missing was a no-op on exactly the catalog state where coverage was
broken — the one #1505's `stale_records` surfaces.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid

import pytest

from app.platform.extensions.defaults_processing_port import DefaultProcessingPort
from app.processing.embeddings import helpers
from app.processing.embeddings.models import RecordEmbedding

from tests.factories import create_dataset, get_user_id

_ACTIVE_MODEL = "backfill-scope-active-model"
_PREVIOUS_MODEL = "backfill-scope-previous-model"

# What `resolve_embedding_model_name` returns when the active model cannot be
# resolved. That the real resolver produces it on failure is pinned by
# test_phase_274_caches_and_pool; here it is the input to a decision.
_UNKNOWN_MODEL = helpers.UNKNOWN_EMBEDDING_MODEL


@pytest.fixture
def pinned_model(monkeypatch):
    """Pin the model the non-force predicate scopes itself to.

    `get_records_without_embeddings` imports the resolver inside the function
    body, so patching the module attribute reaches the call site.
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


async def _missing_ids(session, *, force: bool = False) -> set[uuid.UUID]:
    records = await DefaultProcessingPort().get_records_without_embeddings(
        session, force=force
    )
    return {record.id for record in records}


@pytest.mark.anyio
async def test_record_with_only_a_superseded_vector_reads_missing(
    test_db_session,
    pinned_model,
):
    """A vector from a previous model does not satisfy the active model."""
    user_id = await get_user_id(test_db_session, "admin")
    stale = await create_dataset(
        test_db_session, created_by=user_id, name="Backfill Scope Stale"
    )
    covered = await create_dataset(
        test_db_session, created_by=user_id, name="Backfill Scope Covered"
    )
    await _add_embedding(test_db_session, stale.record_id, _PREVIOUS_MODEL)
    await _add_embedding(test_db_session, covered.record_id, _ACTIVE_MODEL)

    selected = await _missing_ids(test_db_session)

    # The honest assertion: before #1506 this record had a row, so the
    # `RecordEmbedding.id IS NULL` predicate skipped it and the backfill left
    # the catalog with no vector any live search could use.
    assert stale.record_id in selected
    # And the fix must not turn Generate Missing into Regenerate All — a
    # record the active model already covers costs provider tokens to redo.
    assert covered.record_id not in selected


@pytest.mark.anyio
async def test_a_swap_moves_a_covered_record_back_into_the_selection(
    test_db_session,
    pinned_model,
):
    """The operator action this bug hides: switching models in admin Settings."""
    user_id = await get_user_id(test_db_session, "admin")
    dataset = await create_dataset(
        test_db_session, created_by=user_id, name="Backfill Scope Swap"
    )
    await _add_embedding(test_db_session, dataset.record_id, _ACTIVE_MODEL)

    assert dataset.record_id not in await _missing_ids(test_db_session)

    pinned_model["name"] = "backfill-scope-newly-selected-model"

    assert dataset.record_id in await _missing_ids(test_db_session)


@pytest.mark.anyio
async def test_force_still_selects_records_the_active_model_covers(
    test_db_session,
    pinned_model,
):
    """force=True means "every record" and never consults the model."""
    user_id = await get_user_id(test_db_session, "admin")
    dataset = await create_dataset(
        test_db_session, created_by=user_id, name="Backfill Scope Force"
    )
    await _add_embedding(test_db_session, dataset.record_id, _ACTIVE_MODEL)

    assert dataset.record_id in await _missing_ids(test_db_session, force=True)

    # Force is the post-delete regenerate path, so it must keep answering
    # even when the model cannot be resolved — the rows are already gone.
    pinned_model["name"] = _UNKNOWN_MODEL
    assert dataset.record_id in await _missing_ids(test_db_session, force=True)


@pytest.mark.anyio
async def test_unresolvable_model_selects_nothing(
    test_db_session,
    pinned_model,
):
    """An unknown active model stops the run instead of selecting everything.

    The sentinel matches no stored row, so scoping by it would mark the whole
    catalog missing. `backfill.py` stamps its rows from a separate
    `EMBEDDING_MODEL.get()` and `model_name` is NOT NULL, so that run would
    embed every record at provider-token cost and then fail every insert.
    """
    user_id = await get_user_id(test_db_session, "admin")
    dataset = await create_dataset(
        test_db_session, created_by=user_id, name="Backfill Scope Unknown"
    )

    # Counterfactual guard: with a resolvable model this record IS selected,
    # so the empty result below is the sentinel's doing and not an empty
    # catalog or a broken fixture.
    assert dataset.record_id in await _missing_ids(test_db_session)

    pinned_model["name"] = _UNKNOWN_MODEL

    assert await _missing_ids(test_db_session) == set()
