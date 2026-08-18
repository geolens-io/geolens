"""A backfill must stop when the column moves under it, by ANY route (#1533).

#1539 made the run notice that the configuration it pinned had stopped being
the active one, by re-reading `EMBEDDING_MODEL`, `EMBEDDING_DIMS` and the
endpoint at every batch boundary. That closes the settings route: `update_settings`
commits `embedding_dims` and only then calls `rebuild_embedding_column`, so the
dimensions comparison sees the change within one batch. Measured on the real
`backfill_embeddings` over 1,000 records with the rebuild landing during the
first batch: 2 provider calls, run aborted, cause named.

It closes nothing else. The declared width of `catalog.record_embeddings.embedding`
moves with no settings write at all in an `ENV_ONLY_CONFIG` deployment (no
settings row, no rebuild ever fires), after a hand `ALTER TABLE`, after a
restored dump, and after a rebuild that failed partway. The same measurement
with the width moved by hand and the settings row untouched: 1,009 provider
calls, 1,000 errors, and a result an operator cannot tell apart from a broken
provider.

So the drift check reads the live width off `pg_attribute` and compares it with
the width the run pinned at the start. The tests below hold that:

  - a hand `ALTER` stops the run after one batch, and names the column;
  - it stops the RETRY path too, which is where the amplification lives: a batch
    that fails for a reason of its own re-embeds every record individually, one
    provider call each, and a check that only runs at batch boundaries never
    sees them;
  - a healthy run is not disturbed by the new check;
  - the settings route still reports itself as a settings change, because both
    comparisons fire there and the one naming the admin's action is the more
    useful message.

What none of this buys is data. The force path's DELETE commits before any of
these checks can run, so the vectors are gone either way. What is bought is the
work not done and a failure an operator can read.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid

import pytest
from sqlalchemy import func, select

from app.core.persistent_config import EMBEDDING_DIMS
from app.processing.embeddings import backfill as backfill_module
from app.processing.embeddings import helpers
from app.processing.embeddings.models import RecordEmbedding

from tests.alembic_helpers import fresh_query
from tests.factories import create_dataset, get_user_id

_MODEL = "column-drift-active-model"

# Enough records that the run's one batch carries several of them, so "the batch
# ran and nothing after it" is distinguishable from "one record was retried".
_SEEDED = 3


async def _column_dims() -> int:
    """The declared width of the embedding column, read outside the test session."""
    rows = await fresh_query(
        "SELECT atttypmod FROM pg_attribute "
        "WHERE attrelid = 'catalog.record_embeddings'::regclass "
        "AND attname = 'embedding' AND NOT attisdropped"
    )
    return rows[0][0]


async def _set_column_dims(session, new_dims: int) -> None:
    """Move the column width the way anything but the settings route moves it.

    The statements are `rebuild_embedding_column`'s, minus the settings write:
    the rows go (a `vector` column cannot be retyped under them), the index goes
    and comes back, and `app_settings` is never touched. That is what an
    `ENV_ONLY_CONFIG` deployment, a hand `ALTER`, and a restored dump all look
    like from the column's side.

    The session is released first because this needs `ACCESS EXCLUSIVE` and the
    test session holds `ACCESS SHARE` for as long as its transaction is open —
    one bare SELECT is enough to open one, and this test file counts rows. The
    `lock_timeout` is the backstop: a missed release fails the test in ten
    seconds instead of hanging the worker on a lock nothing will release.
    """
    from sqlalchemy import text as sa_text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings as app_settings

    await session.rollback()
    engine = create_async_engine(
        app_settings.test_database_url, isolation_level="AUTOCOMMIT"
    )
    try:
        async with engine.connect() as conn:
            await conn.execute(sa_text("SET lock_timeout = '10s'"))
            await conn.execute(sa_text("DELETE FROM catalog.record_embeddings"))
            await conn.execute(
                sa_text("DROP INDEX IF EXISTS catalog.ix_record_embeddings_hnsw")
            )
            await conn.execute(
                sa_text(
                    f"ALTER TABLE catalog.record_embeddings "
                    f"ALTER COLUMN embedding TYPE vector({new_dims}) "
                    f"USING embedding::vector({new_dims})"
                )
            )
            await conn.execute(
                sa_text(
                    "CREATE INDEX ix_record_embeddings_hnsw "
                    "ON catalog.record_embeddings USING hnsw "
                    "(embedding vector_cosine_ops) WITH (m=16, ef_construction=64)"
                )
            )
    finally:
        await engine.dispose()


async def _embedding_count(session) -> int:
    result = await session.execute(select(func.count()).select_from(RecordEmbedding))
    return result.scalar_one()


async def _seed(session, name: str, width: int) -> None:
    """`_SEEDED` datasets, each with an embedding, so the force DELETE has work."""
    user_id = await get_user_id(session, "admin")
    for index in range(_SEEDED):
        dataset = await create_dataset(
            session, created_by=user_id, name=f"{name} {index}"
        )
        session.add(
            RecordEmbedding(
                record_id=dataset.record_id,
                embedding=[1.0] + [0.0] * (width - 1),
                model_name=_MODEL,
                content_hash=uuid.uuid4().hex[:64],
            )
        )
    await session.commit()


def _pin_model(monkeypatch) -> None:
    """Pin what the snapshot and the drift check resolve, as the sibling suite does."""

    async def _resolve(_session, **_kwargs):
        return _MODEL

    monkeypatch.setattr(helpers, "resolve_embedding_model_name", _resolve)


def _provider(calls: list[int], width: int, *, on_first_batch=None, fail_batch=False):
    """A stub that records its call sizes and can move the column mid-call.

    The hook fires DURING the first real batch's provider call, which is the
    window the issue's measurement identified: the force DELETE has committed
    and no batch has been inserted yet.

    "First real batch" is the SECOND call, by position. Not by input count: the
    force path's pre-flight is always call one and a batch can legitimately hold
    a single record, so sizing the calls would leave the hook unfired on a small
    catalog and the test passing for the wrong reason.
    """

    async def _embed(texts, _session, **_kwargs):
        calls.append(len(texts))
        first_real_batch = len(calls) == 2
        if first_real_batch and on_first_batch is not None:
            await on_first_batch()
        if first_real_batch and fail_batch:
            raise RuntimeError("provider rejected this batch")
        return [[0.1] * width for _ in texts]

    return _embed


@pytest.mark.anyio
async def test_hand_altered_column_stops_the_run_after_one_batch(
    test_db_session, monkeypatch
):
    """The route #1539's guard cannot see: the column moves, the settings do not."""
    start_width = await _column_dims()
    moved_width = 768 if start_width != 768 else 384
    await _seed(test_db_session, "Column Drift Batch Path", start_width)
    assert await _embedding_count(test_db_session) > 0

    _pin_model(monkeypatch)
    calls: list[int] = []

    async def _move_column():
        # The backfill's session holds an open read transaction at this point,
        # and ALTER TABLE needs ACCESS EXCLUSIVE. Committing first is what lets
        # the DDL through, and is what happens in production anyway, where the
        # two run in different processes.
        await test_db_session.commit()
        await _set_column_dims(test_db_session, moved_width)

    monkeypatch.setattr(
        backfill_module,
        "generate_embeddings_batch",
        _provider(calls, start_width, on_first_batch=_move_column),
    )

    try:
        with pytest.raises(RuntimeError, match="embedding column width changed"):
            await backfill_module.backfill_embeddings(test_db_session, force=True)

        # Pre-flight, then the one batch that discovers the move. Nothing after.
        assert len(calls) == 2, calls
        assert calls[0] == 1, "the first call is the force path's pre-flight"
        assert calls[1] >= _SEEDED, (
            "the second call carried the whole batch, so no per-record retry ran"
        )
        assert await _embedding_count(test_db_session) == 0
    finally:
        await _set_column_dims(test_db_session, start_width)

    # The settings row was never in play. Without this the test would also pass
    # against a guard that only reads settings, which is the thing it exists to
    # rule out.
    assert await EMBEDDING_DIMS.get_uncached(test_db_session) != moved_width


@pytest.mark.anyio
async def test_hand_altered_column_stops_the_per_record_retry_path(
    test_db_session, monkeypatch
):
    """The batch fails for its own reason, and the retry loop must not run on.

    This is where the cost is. A per-batch check alone is nearly useless here:
    the width moves during the first batch's provider call, that batch fails
    into the retry loop, and every record then makes its own provider call
    before dying on the same typmod. Measured without the bracketing: 1,009
    provider calls for 1,000 records.
    """
    start_width = await _column_dims()
    moved_width = 768 if start_width != 768 else 384
    await _seed(test_db_session, "Column Drift Retry Path", start_width)

    _pin_model(monkeypatch)
    calls: list[int] = []

    async def _move_column():
        await test_db_session.commit()
        await _set_column_dims(test_db_session, moved_width)

    monkeypatch.setattr(
        backfill_module,
        "generate_embeddings_batch",
        _provider(calls, start_width, on_first_batch=_move_column, fail_batch=True),
    )

    try:
        with pytest.raises(RuntimeError, match="embedding column width changed"):
            await backfill_module.backfill_embeddings(test_db_session, force=True)

        # Pre-flight, then the batch that failed. The retry loop stopped on its
        # FIRST record, before spending a call on it.
        assert len(calls) == 2, calls
        assert await _embedding_count(test_db_session) == 0
    finally:
        await _set_column_dims(test_db_session, start_width)


@pytest.mark.anyio
async def test_a_healthy_force_run_is_not_stopped_by_the_new_check(
    test_db_session, monkeypatch
):
    """Counterfactual: the aborts above are the moved column's doing.

    A check that read the width wrong, or compared it against `EMBEDDING_DIMS`
    rather than against what the run observed, would abort here too — an
    `ENV_ONLY_CONFIG` deployment whose setting and column disagree at rest is a
    normal state, not drift.
    """
    start_width = await _column_dims()
    await _seed(test_db_session, "Column Drift Healthy Run", start_width)

    _pin_model(monkeypatch)
    calls: list[int] = []
    monkeypatch.setattr(
        backfill_module, "generate_embeddings_batch", _provider(calls, start_width)
    )

    result = await backfill_module.backfill_embeddings(test_db_session, force=True)

    assert result["errors"] == 0, result
    assert result["created"] > 0, result
    assert await _embedding_count(test_db_session) == result["created"]


@pytest.mark.anyio
async def test_the_settings_route_still_reports_itself_as_a_settings_change(
    test_db_session, monkeypatch
):
    """Both comparisons fire on the settings route; the useful one wins.

    `update_settings` publishes `embedding_dims` and then rebuilds the column,
    so by the time a run notices, both have moved. The message that names the
    admin's action is worth more than the one that names its consequence, which
    is why the settings comparisons stay ahead of the column read.
    """
    start_width = await _column_dims()
    await _seed(test_db_session, "Column Drift Settings Route", start_width)

    _pin_model(monkeypatch)
    pinned_dims = await EMBEDDING_DIMS.get_uncached(test_db_session)
    calls: list[int] = []

    async def _publish_new_dims():
        await test_db_session.commit()
        await EMBEDDING_DIMS.set(test_db_session, (pinned_dims or 1536) + 8)

    monkeypatch.setattr(
        backfill_module,
        "generate_embeddings_batch",
        _provider(calls, start_width, on_first_batch=_publish_new_dims),
    )

    try:
        with pytest.raises(RuntimeError, match="embedding dimensions changed"):
            await backfill_module.backfill_embeddings(test_db_session, force=True)
        assert len(calls) == 2, calls
    finally:
        await EMBEDDING_DIMS.set(test_db_session, pinned_dims)
        await test_db_session.commit()


@pytest.mark.anyio
async def test_a_non_force_run_stops_instead_of_retrying_a_width_it_cannot_store(
    test_db_session, monkeypatch
):
    """The sibling class: the column is already wrong when the run starts.

    Not drift. Nothing moves during this run, so every check above is silent and
    correct to be. The force path catches this state in its pre-flight, before
    the DELETE. The non-force path has no pre-flight, so the first batch insert
    fails the typmod, every record is retried individually, and each retry
    spends a provider call before dying on the same error.

    A pre-flight here would cost a provider call per run and would abort a run
    that a single transient provider failure could otherwise survive, which is
    the #449 contract two tests in `test_embedding_backfill.py` pin. Comparing
    the width the provider actually produced against the width the run pinned
    costs no call at all and stops before the first insert.
    """
    start_width = await _column_dims()
    moved_width = 768 if start_width != 768 else 384

    # Records with NO embedding, so the non-force path selects them.
    user_id = await get_user_id(test_db_session, "admin")
    for index in range(_SEEDED):
        await create_dataset(
            test_db_session, created_by=user_id, name=f"Non-force Width {index}"
        )
    await test_db_session.commit()

    await _set_column_dims(test_db_session, moved_width)

    _pin_model(monkeypatch)
    calls: list[int] = []
    monkeypatch.setattr(
        backfill_module, "generate_embeddings_batch", _provider(calls, start_width)
    )

    try:
        with pytest.raises(
            RuntimeError, match="catalog.record_embeddings.embedding is vector"
        ):
            await backfill_module.backfill_embeddings(test_db_session)

        # One batch call, and no per-record retry after it.
        assert calls == [len(calls) and calls[0]], calls
        assert len(calls) == 1, calls
    finally:
        await _set_column_dims(test_db_session, start_width)


@pytest.mark.anyio
async def test_one_anomalous_vector_width_costs_one_record_not_the_run(
    test_db_session, monkeypatch
):
    """Isolated is not structural (#1579 review, codex P2).

    The width guards exist to stop a run that cannot store ANY of its vectors.
    A provider handing back one anomalous width while the column sits exactly
    where the run pinned it is a different thing: one bad record among good
    ones, which #449 says costs one error and nothing else.

    An earlier revision could not tell them apart. Every mismatch raised
    `_PinDrift`, the per-record handler rethrew it, and one odd vector abandoned
    the rest of the catalog — a regression of the isolation this file's own
    docstring defends.

    The batch here holds mixed widths, so it is not structural and must not stop
    at the batch check. It fails its insert on the odd row, drops into the
    per-record retry, and each vector is judged alone against a column that has
    not moved.
    """
    start_width = await _column_dims()
    odd_width = 768 if start_width != 768 else 384
    odd_marker = "Anomalous Width Record"

    user_id = await get_user_id(test_db_session, "admin")
    for index in range(_SEEDED):
        await create_dataset(
            test_db_session, created_by=user_id, name=f"Isolation Good {index}"
        )
    await create_dataset(test_db_session, created_by=user_id, name=odd_marker)
    await test_db_session.commit()

    _pin_model(monkeypatch)
    seen: list[list[str]] = []

    async def _embed(texts, _session, **_kwargs):
        # Keyed on content, not call order: the force path's pre-flight is its
        # own single-text call and must come back at the column's width, or the
        # run aborts before the batch this test is about.
        seen.append(list(texts))
        return [
            [0.1] * (odd_width if odd_marker in text else start_width) for text in texts
        ]

    monkeypatch.setattr(backfill_module, "generate_embeddings_batch", _embed)

    result = await backfill_module.backfill_embeddings(test_db_session, force=True)
    calls = [len(texts) for texts in seen]

    assert result["errors"] == 1, result
    assert result["created"] >= _SEEDED, result
    assert await _embedding_count(test_db_session) == result["created"]

    # Non-vacuity: the batch really did fail and retry per record, so the
    # per-record judgement is what produced that single error rather than the
    # batch check having quietly let everything through.
    #
    # Anchored on the anomalous record's TEXT rather than on a call position or
    # a batch size: on a busy xdist worker the database already holds records
    # earlier tests committed, so the odd record lands in whichever batch the
    # accumulated count puts it (seen at batch_start=256 in CI), and at 127 mod
    # `_BATCH_SIZE` prior records it is a batch of one all by itself. Whatever
    # the batch, the odd record is embedded exactly twice: once in that batch,
    # once alone in the retry, and every record of the failed batch is
    # re-embedded alone right after it.
    assert calls[0] == 1, "the pre-flight"
    marker_calls = [
        i for i, texts in enumerate(seen) if any(odd_marker in t for t in texts)
    ]
    assert len(marker_calls) == 2, (
        "expected the anomalous record to be embedded in its batch and once more "
        f"alone in the retry; it appeared in calls {marker_calls} of sizes {calls}"
    )
    failed_batch, retry = marker_calls
    size = calls[failed_batch]
    assert calls[failed_batch + 1 : failed_batch + 1 + size] == [1] * size, (
        f"expected the failed batch of {size} to be retried record by record; "
        f"call sizes were {calls}"
    )
    assert calls[retry] == 1, calls

    # And the column never moved, which is what made it isolated.
    assert await _column_dims() == start_width


@pytest.mark.anyio
async def test_a_one_record_batch_does_not_read_as_structural(
    test_db_session, monkeypatch
):
    """One input agrees with itself, which is no evidence at all (#1579 review r2).

    The batch rule calls a width mismatch structural when every vector in the
    batch shares it. With a single-record batch that test is vacuous: one
    anomalous vector satisfies it, and the run stopped over one bad record —
    the same isolation bug as the retry path had, surviving at the one batch
    size where the batch path has no more evidence than the retry path does.

    A catalog sized 1 mod `_BATCH_SIZE` produces exactly that batch as its last.
    `_BATCH_SIZE` is patched to 1 rather than seeding 129 records: it makes
    EVERY batch a singleton, so the anomalous record lands in one whatever order
    the run selects records in, and it does not depend on how many records other
    tests left on this worker's database.
    """
    start_width = await _column_dims()
    odd_width = 768 if start_width != 768 else 384
    odd_marker = "Singleton Batch Anomaly"

    user_id = await get_user_id(test_db_session, "admin")
    for index in range(_SEEDED):
        await create_dataset(
            test_db_session, created_by=user_id, name=f"Singleton Good {index}"
        )
    await create_dataset(test_db_session, created_by=user_id, name=odd_marker)
    await test_db_session.commit()

    _pin_model(monkeypatch)
    monkeypatch.setattr(backfill_module, "_BATCH_SIZE", 1)

    async def _embed(texts, _session, **_kwargs):
        return [
            [0.1] * (odd_width if odd_marker in text else start_width) for text in texts
        ]

    monkeypatch.setattr(backfill_module, "generate_embeddings_batch", _embed)

    result = await backfill_module.backfill_embeddings(test_db_session, force=True)

    assert result["errors"] == 1, result
    assert result["created"] >= _SEEDED, result
    assert await _embedding_count(test_db_session) == result["created"]
    # The column never moved, which is what made the one mismatch isolated.
    assert await _column_dims() == start_width


@pytest.mark.anyio
async def test_the_pre_commit_check_holds_the_relation_lock(
    test_db_session, monkeypatch
):
    """Check-then-act is only sound while the thing checked cannot move.

    fix(#1579 review r3, codex P2): the pre-commit drift check reads
    `pg_attribute`, which locks nothing. Running it before the rows were sent
    left a window in which an `ALTER TABLE` could take ACCESS EXCLUSIVE, commit,
    and be missed entirely — and when that ALTER widens the column to an
    unconstrained `vector`, the old-width inserts then SUCCEED and the run
    reports success over a column that moved under it. That is exactly the
    outcome `_pinned_config_drift` says a widening change must not produce.

    Flushing first takes RowExclusiveLock on the relation, which ACCESS
    EXCLUSIVE conflicts with, so the check reads a width that cannot change
    until this transaction ends.

    The ALTER is fired deterministically, the instant the check returns, rather
    than raced: the window is a known one and constructing it beats hoping to
    hit it. What proves the two sides genuinely contended is not the ordering
    but the outcome — Postgres reports `lock_not_available`, which it can only
    do if something else was holding a conflicting lock at that moment.
    """
    from sqlalchemy import text as sa_text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings as app_settings

    start_width = await _column_dims()
    await _seed(test_db_session, "Lock Window", start_width)

    outcome: list[str] = []

    async def _widen_column_from_another_connection() -> None:
        """What a hand `ALTER` does, from a connection this run does not own."""
        engine = create_async_engine(
            app_settings.test_database_url, isolation_level="AUTOCOMMIT"
        )
        try:
            async with engine.connect() as conn:
                await conn.execute(sa_text("SET lock_timeout = '750ms'"))
                await conn.execute(
                    sa_text(
                        "ALTER TABLE catalog.record_embeddings "
                        "ALTER COLUMN embedding TYPE vector USING embedding::vector"
                    )
                )
            outcome.append("committed")
        except Exception as exc:  # noqa: BLE001 - the outcome IS the assertion
            # Matched on the message rather than the exception class: the
            # asyncpg dialect wraps every driver error in one adapter type, so
            # the class name alone cannot tell a lock timeout from anything else.
            message = str(getattr(exc, "orig", exc))
            outcome.append(
                "blocked" if "lock timeout" in message else f"other: {message[:160]}"
            )
        finally:
            await engine.dispose()

    original_check = backfill_module._raise_on_pin_drift

    async def _check_then_widen(*args, **kwargs):
        await original_check(*args, **kwargs)
        # The SECOND call is the pre-commit one on either ordering: the first is
        # the batch loop's own pre-flight check, before any provider call.
        if len(outcome) == 0 and getattr(_check_then_widen, "seen", 0) == 1:
            await _widen_column_from_another_connection()
        _check_then_widen.seen = getattr(_check_then_widen, "seen", 0) + 1

    _check_then_widen.seen = 0
    monkeypatch.setattr(backfill_module, "_raise_on_pin_drift", _check_then_widen)

    _pin_model(monkeypatch)
    monkeypatch.setattr(
        backfill_module,
        "generate_embeddings_batch",
        _provider([], start_width),
    )

    try:
        result = await backfill_module.backfill_embeddings(test_db_session, force=True)

        # Non-vacuity first: the ALTER really was attempted, in the window.
        assert outcome, "the hook never fired, so nothing was tested"

        # Then the damage, before the mechanism. An unguarded tree fails here,
        # on a run that reported success over a column it no longer matches,
        # rather than on the lock error being absent.
        assert await _column_dims() == start_width, (
            "the column moved during the run and the run did not notice"
        )
        assert result["created"] > 0, result

        # And the mechanism that prevented it. Postgres can only answer this
        # while something else holds a conflicting lock, so it is also the
        # evidence that the two sides genuinely overlapped.
        assert outcome == ["blocked"], outcome
    finally:
        await _set_column_dims(test_db_session, start_width)


@pytest.mark.anyio
async def test_a_move_during_the_last_retry_is_drift_not_a_counted_error(
    test_db_session, monkeypatch
):
    """The last retried record has no successor to catch what it missed.

    fix(#1579 review r4, codex P2): the retry's width judgement asked "does this
    vector fit?" before "is the column still the one we pinned?", and returned
    early when the vector matched. A column that moved to a DIFFERENT fixed
    width during the provider call therefore went unnoticed: the flush raised
    the typmod error, the broad handler counted it as a bad record, and the run
    finished reporting one error where it should have reported a configuration
    change. Every other record is covered by the next one's pre-call check. The
    last one has no next.

    Reaching that state needs a retry loop with exactly one record in it, so the
    run is set up as a non-force run over a catalog where exactly one record
    lacks a vector: every other record is given one first. The batch call then
    fails for a reason of its own, which is what opens the retry loop, and the
    ALTER fires during the retry's own provider call.
    """
    from sqlalchemy import text as sa_text

    start_width = await _column_dims()
    moved_width = 768 if start_width != 768 else 384

    # Every existing record gets a vector under the pinned model, so the
    # non-force selection below is exactly the one record seeded after it.
    await test_db_session.execute(
        sa_text(
            "INSERT INTO catalog.record_embeddings "
            "(record_id, embedding, model_name, content_hash) "
            "SELECT r.id, (SELECT ('[' || string_agg('0.01', ',') || ']')"
            f"::vector({start_width}) FROM generate_series(1, {start_width})), "
            f"'{_MODEL}', md5(r.id::text) FROM catalog.records r "
            "ON CONFLICT (record_id, model_name) DO NOTHING"
        )
    )
    user_id = await get_user_id(test_db_session, "admin")
    await create_dataset(test_db_session, created_by=user_id, name="Last Retry Move")
    await test_db_session.commit()

    _pin_model(monkeypatch)
    calls: list[int] = []

    async def _embed(texts, _session, **_kwargs):
        calls.append(len(texts))
        if len(calls) == 1:
            # The batch's own call. Failing it is what opens the retry loop.
            raise RuntimeError("provider rejected this batch")
        if len(calls) == 2:
            # The retry's call for the only record there is. The column moves
            # while it is in flight.
            await test_db_session.commit()
            await _set_column_dims(test_db_session, moved_width)
        return [[0.1] * start_width for _ in texts]

    monkeypatch.setattr(backfill_module, "generate_embeddings_batch", _embed)

    try:
        with pytest.raises(
            RuntimeError, match="embedding column width changed"
        ) as caught:
            await backfill_module.backfill_embeddings(test_db_session)

        # The message names the width it moved TO, so the operator is told what
        # happened rather than that one record failed.
        assert f"vector({moved_width})" in str(caught.value), str(caught.value)
        # Non-vacuity: the run really did reach the retry loop, and the ALTER
        # really did fire inside it.
        assert calls == [1, 1], calls
        assert await _column_dims() == moved_width
    finally:
        await _set_column_dims(test_db_session, start_width)
