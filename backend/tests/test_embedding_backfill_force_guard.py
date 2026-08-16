"""A force backfill must not destroy vectors it cannot regenerate (#1511).

`backfill_embeddings(force=True)` commits a DELETE of every visible
`record_embeddings` row before it generates anything. The rows it writes back
are stamped with the active embedding model, and `model_name` is NOT NULL, so
a run that starts while the model cannot be resolved deletes full coverage and
then fails every insert. The operator-visible shape is a "Regenerate All"
clicked during a persistent-config blip turning 100% coverage into 0%.

The guard belongs before the delete: resolve first, refuse loudly, leave the
vectors alone. That is the same fail-closed call `get_records_without_embeddings`
documents for the non-force path (#1506), moved to the one branch it could not
cover — force never consults the model, by design, because it runs *after* the
delete.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid

import pytest
from sqlalchemy import func, select

from app.processing.embeddings import backfill as backfill_module
from app.processing.embeddings import helpers
from app.processing.embeddings.models import RecordEmbedding

from tests.factories import create_dataset, get_user_id

_RESOLVABLE_MODEL = "force-guard-active-model"


async def _embedding_count(session) -> int:
    """Count every embedding row the force delete would clear."""
    result = await session.execute(select(func.count()).select_from(RecordEmbedding))
    return result.scalar_one()


async def _seed_embedding(session, name: str, model_name: str = _RESOLVABLE_MODEL):
    """Create one dataset with one embedding row under the given model."""
    user_id = await get_user_id(session, "admin")
    dataset = await create_dataset(session, created_by=user_id, name=name)
    session.add(
        RecordEmbedding(
            record_id=dataset.record_id,
            embedding=[1.0] + [0.0] * 1535,
            model_name=model_name,
            content_hash=uuid.uuid4().hex[:64],
        )
    )
    await session.commit()
    return dataset


async def _count_under(session, model_name: str) -> int:
    """Count embedding rows carrying a given model label."""
    result = await session.execute(
        select(func.count())
        .select_from(RecordEmbedding)
        .where(RecordEmbedding.model_name == model_name)
    )
    return result.scalar_one()


def _pin_model(monkeypatch, name: str) -> None:
    """Pin what the force guard resolves.

    `backfill_embeddings` imports the resolver inside the function body — the
    same call-site-reachable pattern `get_records_without_embeddings` uses — so
    patching the module attribute reaches it.
    """

    async def _resolve(_session):
        return name

    monkeypatch.setattr(helpers, "resolve_embedding_model_name", _resolve)


@pytest.mark.anyio
async def test_force_backfill_with_unresolvable_model_keeps_existing_vectors(
    test_db_session,
    monkeypatch,
):
    """An unknown active model aborts the run instead of emptying the table."""
    await _seed_embedding(test_db_session, "Force Guard Unresolvable")

    before = await _embedding_count(test_db_session)
    # Non-vacuity: with zero rows seeded, "the rows survived" asserts nothing.
    assert before > 0

    _pin_model(monkeypatch, helpers.UNKNOWN_EMBEDDING_MODEL)

    reported_failure = False
    try:
        await backfill_module.backfill_embeddings(test_db_session, force=True)
    except RuntimeError:
        reported_failure = True

    # Assertion order is deliberate. Survival is checked first so an unguarded
    # tree fails on the destruction itself rather than on a missing exception —
    # the lost vectors are the bug, the raise is only how it is reported.
    assert await _embedding_count(test_db_session) == before
    assert reported_failure


@pytest.mark.anyio
async def test_force_backfill_with_a_resolvable_model_still_clears(
    test_db_session,
    monkeypatch,
):
    """The guards must not turn Regenerate All into a no-op.

    Counterfactual for the test above: the surviving rows there are the
    sentinel's doing, not a force path that stopped deleting.

    fix(#1511 review r3): this used to assert that force clears even when the
    provider is unavailable. That is now the opposite of the contract — an
    unusable provider must abort before the delete, which is what the
    pre-flight is for — so the counterfactual has to run with a WORKING
    provider. The intent is unchanged: prove the delete still happens. The old
    setup asserted behavior the fix deliberately removed, so keeping it would
    have pinned the bug.
    """
    superseded = "force-guard-superseded-model"
    await _seed_embedding(test_db_session, "Force Guard Resolvable", superseded)
    assert await _count_under(test_db_session, superseded) > 0

    _pin_model(monkeypatch, _RESOLVABLE_MODEL)

    async def _vector(texts, *_args, **_kwargs):
        return [[1.0] + [0.0] * 1535 for _ in texts]

    monkeypatch.setattr(backfill_module, "generate_embeddings_batch", _vector)

    await backfill_module.backfill_embeddings(test_db_session, force=True)

    # The stale-labelled rows are gone, so the DELETE ran, and rows exist under
    # the active model, so the regenerate ran. Counting all rows could not tell
    # those apart now that the run actually writes vectors back.
    assert await _count_under(test_db_session, superseded) == 0
    assert await _count_under(test_db_session, _RESOLVABLE_MODEL) > 0
