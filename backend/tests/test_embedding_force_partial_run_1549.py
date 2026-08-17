"""A force backfill must not destroy vectors before it knows it can finish (#1549).

`backfill_embeddings(force=True)` used to commit `DELETE FROM
catalog.record_embeddings` before generating anything, so every abort after
that point ended the run with the old vectors gone and few or none written: a
provider outage, a configuration change detected mid-run, a worker restart.
The guards from #1519, #1525 and #1539 all sit correctly BEFORE that commit for
the conditions they can see at the start; none of them can see a change that
lands after it.

The delete now happens per batch, inside the transaction that writes that
batch's replacements. An aborted run leaves a mix: replaced records hold rows
from the run's pinned configuration, untouched records hold exactly what they
held before it started. #1546's stamp is what makes that mix readable instead
of ambiguous, which is why it had to land first.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.persistent_config import EMBEDDING_DIMS, EMBEDDING_MODEL
from app.modules.admin.service import AdminService
from app.modules.catalog.datasets.domain.models import Record
from app.processing.embeddings import backfill as backfill_module
from app.processing.embeddings import service as service_module
from app.processing.embeddings.models import RecordEmbedding

from tests.factories import create_dataset, get_user_id

_DIMS = 1536
_MODEL = "partial-run-model"
# What an operator changes to mid-run, which is one of the abort sources #1549
# lists and the one the drift guard turns into a stop.
_MODEL_AFTER = "partial-run-model-after"
# The label on the vectors a force run is replacing.
_MODEL_BEFORE = "partial-run-superseded-model"


@pytest.fixture
async def restore_embedding_config(test_db_session):
    """Put the AI config back; the worker database is shared across tests."""
    before = (
        await EMBEDDING_MODEL.get(test_db_session),
        await EMBEDDING_DIMS.get(test_db_session),
    )
    yield
    await EMBEDDING_MODEL.set(test_db_session, before[0])
    await EMBEDDING_DIMS.set(test_db_session, before[1])


async def _seed(
    session: AsyncSession, name: str, *, model_name: str = _MODEL_BEFORE
) -> uuid.UUID:
    """A dataset carrying one embedding row; returns its record id.

    The seeded `content_hash` is the record's NAME, which no generated row can
    ever carry — a written row hashes its content text. That is the
    discriminator every assertion below leans on to tell "this row was
    replaced" apart from "this row was never touched", now that a completed
    force run ends with a populated table rather than an empty one.

    A plain UUID rather than the ORM object, deliberately: several of these
    tests assert AFTER a run that rolled back, and a rollback expires every
    instance in the session, so touching `dataset.record_id` there would
    trigger a lazy load and raise MissingGreenlet.
    """
    user_id = await get_user_id(session, "admin")
    dataset = await create_dataset(session, created_by=user_id, name=name)
    record_id = dataset.record_id
    session.add(
        RecordEmbedding(
            record_id=record_id,
            embedding=[1.0] + [0.0] * (_DIMS - 1),
            model_name=model_name,
            content_hash=name,
        )
    )
    await session.commit()
    return record_id


def _as_record(record_id: uuid.UUID, *, title: str | None):
    """What the run reads off a record; `title=None` makes its content empty."""
    return SimpleNamespace(
        id=record_id,
        title=title,
        summary=None,
        keywords=[],
        lineage_summary=None,
        translations=[],
    )


async def _rows_for(
    session: AsyncSession, record_id: uuid.UUID
) -> list[tuple[str, str]]:
    """Every (model_name, content_hash) this record currently holds."""
    result = await session.execute(
        select(RecordEmbedding.model_name, RecordEmbedding.content_hash).where(
            RecordEmbedding.record_id == record_id
        )
    )
    return sorted((row[0], row[1]) for row in result.all())


async def _assert_replaced(session, record_id: uuid.UUID, *, marker: str) -> None:
    """The record holds exactly one row, written by the run under the pin."""
    rows = await _rows_for(session, record_id)
    assert len(rows) == 1, rows
    model_name, content_hash = rows[0]
    assert model_name == _MODEL
    assert content_hash != marker, "the row still carries the seeded marker"


async def _assert_untouched(session, record_id: uuid.UUID, *, marker: str) -> None:
    """The record holds exactly the row it was seeded with."""
    assert await _rows_for(session, record_id) == [(_MODEL_BEFORE, marker)]


def _pin_run(monkeypatch, records, *, batch_size: int = 1):
    """Point the run at exactly `records`, one per batch."""
    monkeypatch.setattr(backfill_module, "_BATCH_SIZE", batch_size)
    port = SimpleNamespace(
        get_record_orm_class=lambda: Record,
        get_records_without_embeddings=AsyncMock(return_value=records),
    )
    monkeypatch.setattr(backfill_module, "get_processing_port", lambda: port)
    monkeypatch.setattr(
        service_module, "settings", SimpleNamespace(openai_api_key="partial-run-key")
    )
    return port


@pytest.mark.anyio
async def test_a_force_run_that_aborts_partway_does_not_empty_the_catalog(
    test_db_session,
    restore_embedding_config,
    monkeypatch,
):
    """The defect: an abort after the bulk delete left the catalog with nothing.

    The run replaces the first record, then an admin changes the embedding model
    while the second batch is in flight. #1539's drift guard stops the run, which
    is correct and stays. What must not happen any more is that the records the
    run never reached have lost their vectors too.
    """
    session = test_db_session
    await EMBEDDING_MODEL.set(session, _MODEL)
    await EMBEDDING_DIMS.set(session, _DIMS)

    first = await _seed(session, "Partial Run First")
    second = await _seed(session, "Partial Run Second")
    _pin_run(
        monkeypatch,
        [_as_record(first, title="First"), _as_record(second, title="Second")],
    )

    batches = {"n": 0}

    async def _fake_batch(texts, sess, *, model, dimensions, base_url):
        # The force path's pre-flight embedding is a provider call too, and it
        # comes FIRST. Counting it as a batch would land the edit during batch
        # one and abort the run before it had written anything, which would
        # test the drift guard rather than what an abort leaves behind.
        if texts != [backfill_module._PREFLIGHT_TEXT]:
            batches["n"] += 1
            if batches["n"] == 2:
                # Lands the admin's edit while the SECOND batch is being
                # generated, through the real setter, so the drift check after
                # the call sees it.
                await EMBEDDING_MODEL.set(sess, _MODEL_AFTER)
        return [[1.0] + [0.0] * (_DIMS - 1) for _ in texts]

    monkeypatch.setattr(backfill_module, "generate_embeddings_batch", _fake_batch)

    with pytest.raises(RuntimeError):
        await backfill_module.backfill_embeddings(session, force=True)

    # Non-vacuity: the run really did reach the second batch and really did stop.
    assert batches["n"] == 2

    # The record it reached was replaced, once, under the pinned model.
    await _assert_replaced(session, first, marker="Partial Run First")
    # The record it did not reach still holds exactly what it held before. This
    # is the assertion the bulk delete made impossible: there, both rows were
    # already gone by the time the run started generating.
    await _assert_untouched(session, second, marker="Partial Run Second")


@pytest.mark.anyio
async def test_a_batch_whose_write_fails_keeps_the_vector_it_was_replacing(
    test_db_session,
    restore_embedding_config,
    monkeypatch,
):
    """Delete and replacement are one transaction, so neither half lands alone.

    The provider answers with a vector of the wrong width, which the column
    rejects. The batch write fails, the per-record retry fails the same way, and
    the record must come out of it holding the vector it started with rather
    than nothing.
    """
    session = test_db_session
    await EMBEDDING_MODEL.set(session, _MODEL)
    await EMBEDDING_DIMS.set(session, _DIMS)

    dataset = await _seed(session, "Failed Write")
    _pin_run(monkeypatch, [_as_record(dataset, title="Failed Write")])

    async def _fake_batch(texts, sess, *, model, dimensions, base_url):
        # The pre-flight gets a storable vector, so the run reaches the batch
        # loop; the batch itself gets one the column will refuse.
        width = _DIMS if texts == [backfill_module._PREFLIGHT_TEXT] else 8
        return [[1.0] + [0.0] * (width - 1) for _ in texts]

    monkeypatch.setattr(backfill_module, "generate_embeddings_batch", _fake_batch)

    result = await backfill_module.backfill_embeddings(session, force=True)

    # Non-vacuity: the write really was attempted and really did fail.
    assert result["created"] == 0
    assert result["errors"] == 1
    await _assert_untouched(session, dataset, marker="Failed Write")


@pytest.mark.anyio
async def test_a_completed_force_run_still_replaces_a_superseded_model_row(
    test_db_session,
    restore_embedding_config,
    monkeypatch,
):
    """Per-batch replacement kept the breadth the bulk delete had.

    The upsert on its own cannot reach a row under a different model name, since
    it is keyed `(record_id, model_name)`. Force means "replace what is there",
    so the delete inside the batch clears every row the record holds.

    Counterfactual: drop the delete from `_replace_embeddings` and the record
    ends the run holding two rows instead of one.
    """
    session = test_db_session
    await EMBEDDING_MODEL.set(session, _MODEL)
    await EMBEDDING_DIMS.set(session, _DIMS)

    dataset = await _seed(session, "Superseded Row")
    _pin_run(monkeypatch, [_as_record(dataset, title="Superseded Row")])

    async def _fake_batch(texts, sess, *, model, dimensions, base_url):
        return [[1.0] + [0.0] * (_DIMS - 1) for _ in texts]

    monkeypatch.setattr(backfill_module, "generate_embeddings_batch", _fake_batch)

    result = await backfill_module.backfill_embeddings(session, force=True)

    assert result["created"] == 1
    await _assert_replaced(session, dataset, marker="Superseded Row")


@pytest.mark.anyio
async def test_a_completed_force_run_drops_a_vector_it_cannot_regenerate(
    test_db_session,
    restore_embedding_config,
    monkeypatch,
):
    """A record with no embeddable content left has a stale vector and no batch.

    These records never reach a batch, so per-batch replacement cannot reclaim
    them the way the bulk delete did. They are cleaned up at the END of the run,
    which is what keeps an ABORTED run from touching them while a completed one
    still honours what force means.

    Counterfactual: drop that final delete and the stale row survives a
    completed regenerate.
    """
    session = test_db_session
    await EMBEDDING_MODEL.set(session, _MODEL)
    await EMBEDDING_DIMS.set(session, _DIMS)

    embeddable = await _seed(session, "Still Embeddable")
    emptied = await _seed(session, "Content Emptied")
    _pin_run(
        monkeypatch,
        [
            _as_record(embeddable, title="Still Embeddable"),
            # No title, no summary, no keywords: `build_content_text` returns
            # "" and the run counts it as skipped rather than embedding it.
            _as_record(emptied, title=None),
        ],
    )

    async def _fake_batch(texts, sess, *, model, dimensions, base_url):
        return [[1.0] + [0.0] * (_DIMS - 1) for _ in texts]

    monkeypatch.setattr(backfill_module, "generate_embeddings_batch", _fake_batch)

    result = await backfill_module.backfill_embeddings(session, force=True)

    assert result["created"] == 1
    assert result["skipped"] == 1
    await _assert_replaced(session, embeddable, marker="Still Embeddable")
    assert await _rows_for(session, emptied) == []


@pytest.mark.anyio
async def test_coverage_after_an_aborted_force_run_reports_what_search_can_use(
    test_db_session,
    restore_embedding_config,
    monkeypatch,
):
    """The panel has to describe the mix, not round it to full or empty.

    An aborted force run leaves records in two states, and the operator's next
    decision depends on telling them apart. Coverage counts rows usable by the
    LIVE configuration, so it answers differently before and after the operator
    undoes the change that stopped the run. Both answers are the truth about
    what semantic search can retrieve at that moment.
    """
    session = test_db_session
    await EMBEDDING_MODEL.set(session, _MODEL)
    await EMBEDDING_DIMS.set(session, _DIMS)

    service = AdminService(session)
    baseline = await service.get_embedding_stats()

    first = await _seed(session, "Coverage First")
    second = await _seed(session, "Coverage Second")
    _pin_run(
        monkeypatch,
        [_as_record(first, title="First"), _as_record(second, title="Second")],
    )

    # Both records start covered by NOTHING the active model can use: their
    # rows carry the superseded label.
    seeded = await service.get_embedding_stats()
    assert seeded.total_records == baseline.total_records + 2
    assert seeded.embedded_records == baseline.embedded_records

    batches = {"n": 0}

    async def _fake_batch(texts, sess, *, model, dimensions, base_url):
        # Skipping the pre-flight call, as above.
        if texts != [backfill_module._PREFLIGHT_TEXT]:
            batches["n"] += 1
            if batches["n"] == 2:
                await EMBEDDING_MODEL.set(sess, _MODEL_AFTER)
        return [[1.0] + [0.0] * (_DIMS - 1) for _ in texts]

    monkeypatch.setattr(backfill_module, "generate_embeddings_batch", _fake_batch)

    with pytest.raises(RuntimeError):
        await backfill_module.backfill_embeddings(session, force=True)

    # The operator puts the model back to what the run pinned, which is the
    # state in which the question "how much of this survived?" has an answer.
    # Every reading here is taken under that same live model, so the deltas
    # describe these two records rather than whatever else the shared worker
    # database is carrying.
    await EMBEDDING_MODEL.set(session, _MODEL)
    after = await service.get_embedding_stats()

    # ONE of the two counts as covered: the record the run reached. Not two,
    # which is what crediting an aborted run would look like, and not zero,
    # which is what the bulk delete used to leave behind.
    assert after.total_records == seeded.total_records
    assert after.embedded_records == seeded.embedded_records + 1
    # The record the run never reached still holds a vector, just not one this
    # configuration can use, so it reads as stale rather than missing. That is
    # the distinction that tells an operator to re-run rather than to worry.
    assert after.stale_records == seeded.stale_records - 1
    assert after.missing_records == seeded.missing_records - 1


@pytest.mark.anyio
async def test_a_non_force_run_deletes_nothing(
    test_db_session,
    restore_embedding_config,
    monkeypatch,
):
    """Generate Missing fills gaps; it must not have acquired a delete.

    `record_orm` is what carries the force flag into `_replace_embeddings`, and
    a non-force run passes None. If that ever stopped being true, a run the
    operator believes is additive would start replacing rows, including the ones
    under other models that force exists to clear.
    """
    session = test_db_session
    await EMBEDDING_MODEL.set(session, _MODEL)
    await EMBEDDING_DIMS.set(session, _DIMS)

    dataset = await _seed(session, "Non Force Keeps Rows")
    # Its only row is under a superseded model, so the record reads as missing
    # under the active one and the run does regenerate it.
    _pin_run(monkeypatch, [_as_record(dataset, title="Non Force Keeps Rows")])

    async def _fake_batch(texts, sess, *, model, dimensions, base_url):
        return [[1.0] + [0.0] * (_DIMS - 1) for _ in texts]

    monkeypatch.setattr(backfill_module, "generate_embeddings_batch", _fake_batch)

    result = await backfill_module.backfill_embeddings(session, force=False)

    assert result["created"] == 1
    # Both rows: the superseded one it was not asked to remove, and the new one.
    rows = await _rows_for(session, dataset)
    assert len(rows) == 2, rows
    assert (_MODEL_BEFORE, "Non Force Keeps Rows") in rows
    assert [model for model, _ in rows].count(_MODEL) == 1


@pytest.mark.anyio
async def test_a_run_over_no_records_deletes_nothing(
    test_db_session,
    restore_embedding_config,
    monkeypatch,
):
    """The empty case, which is where the old bulk delete was at its worst.

    A force run that finds nothing to regenerate used to clear the table anyway
    if the emptiness check did not catch it first. There is no delete without a
    replacement now, so an empty selection is a no-op.
    """
    session = test_db_session
    await EMBEDDING_MODEL.set(session, _MODEL)
    await EMBEDDING_DIMS.set(session, _DIMS)

    untouched = await _seed(session, "Untouched By Empty Run")
    _pin_run(monkeypatch, [])

    async def _fake_batch(texts, sess, *, model, dimensions, base_url):
        return [[1.0] + [0.0] * (_DIMS - 1) for _ in texts]

    monkeypatch.setattr(backfill_module, "generate_embeddings_batch", _fake_batch)

    result = await backfill_module.backfill_embeddings(session, force=True)

    assert result == {"processed": 0, "created": 0, "skipped": 0, "errors": 0}
    await _assert_untouched(session, untouched, marker="Untouched By Empty Run")
