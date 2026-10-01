"""The quicklook draw runs on a session of its own and survives its own timeout.

The generation timeout cancels the geom query mid-flight, which poisons the
asyncpg cursor of the session it ran on. The draw's ``session.rollback()``
recovers that cursor, and also expires every ORM attribute on the session
(``expire_on_rollback`` defaults to True even with ``expire_on_commit=False``).
Run on the session that built the dataset, that expiry turns the next
``dataset.record`` access in ``defer_embedding`` into ``MissingGreenlet`` and
fails a job whose dataset is already committed, so the first ingest draws on
its own ``_job_phase_session(job_uuid, phase="quicklook")``.

1. ``test_generate_quicklook_timeout_does_not_poison_outer_session``: a draw
   that times out on its own session leaves the outer ``dataset.record``
   readable.
2. ``test_generate_quicklook_timeout_poisons_outer_session_pre_fix``: the
   mechanism. A rollback on the session holding ``dataset.record`` expires
   it, and the next access raises ``MissingGreenlet``. The greenlet-bridge
   half of the production failure does not reproduce deterministically in a
   unit test, so this pins the ORM half.
3. ``test_generate_quicklook_completes_on_multipolygon_shape``: under a
   forced timeout on 100 multipolygons, the URI still persists.
4. ``test_generate_quicklook_url_persists_after_geom_timeout``: the same,
   with no ``recovery``, ``generate`` or ``commit`` failure logged.
"""

from __future__ import annotations

import uuid as _uuid

import pytest
from sqlalchemy import text

import app.processing.vector.quicklook as quicklook_module
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.platform.jobs.models import IngestJob
from app.processing.ingest.tasks_common import (
    _generate_quicklook,
    _job_phase_session,
)
from tests.factories import get_user_id


# ---------------------------------------------------------------------------
# Helpers — shared between the three tests
# ---------------------------------------------------------------------------


def _force_quicklook_timeout(monkeypatch, timeout: float = 0.001) -> None:
    """Force ``generate_vector_quicklook_with_timeout`` to use a tiny timeout.

    ``_GENERATION_TIMEOUT_SECONDS`` is captured as the wrapper's default
    ``timeout`` when the function is defined, so patching the module constant
    changes nothing and the tests would silently exercise the happy path.
    Replacing the wrapper itself reaches every call site, including the
    import inside ``_draw_quicklook``.

    Check it once by commenting out the draw's ``await session.rollback()``
    before the upload in ``tasks_common.py``: at least
    ``test_generate_quicklook_url_persists_after_geom_timeout`` must fail.
    """
    real_wrapper = quicklook_module.generate_vector_quicklook_with_timeout

    async def _fast_timeout_wrapper(
        db,
        table_name,
        geometry_type,
        size=256,
        timeout_override=timeout,
        *,
        schema="data",
    ):
        return await real_wrapper(
            db,
            table_name,
            geometry_type,
            size,
            timeout=timeout_override,
            schema=schema,
        )

    monkeypatch.setattr(
        quicklook_module,
        "generate_vector_quicklook_with_timeout",
        _fast_timeout_wrapper,
    )


async def _create_test_dataset_with_table(
    session,
    *,
    created_by: _uuid.UUID,
    feature_count: int = 5,
    geometry_type: str = "MultiPolygon",
) -> tuple[Dataset, str]:
    """Create a Record + Dataset + a real PostGIS table with multipolygon rows.

    Returns ``(dataset, table_name)``. The dataset is committed and refreshed
    so ``dataset.record`` is warm via the ``lazy="joined"`` relationship at
    models.py:286-288 — this is the exact attribute the production bug tries
    (and fails) to lazy-refresh in ``defer_embedding``.
    """
    table_name = f"qlasync_{_uuid.uuid4().hex[:12]}"
    record = Record(
        title="Quicklook async-context test dataset",
        summary="INGEST-01 regression pin",
        visibility="public",
        record_status="published",
        created_by=created_by,
        record_type="vector_dataset",
    )
    session.add(record)
    await session.flush()

    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        geometry_type=geometry_type,
        feature_count=feature_count,
        source_format="geojson",
        source_filename="test.geojson",
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)

    # Create the underlying PostGIS table with a geom_4326 column — this is
    # what generate_vector_quicklook queries against. Use simple square
    # multipolygons so ST_MakeValid(ST_Simplify(...)) completes quickly under
    # the test budget.
    await session.execute(
        text(
            f'CREATE TABLE data."{table_name}" ('
            "gid serial PRIMARY KEY, "
            "name text, "
            "geom_4326 geometry(MultiPolygon, 4326)"
            ")"
        )
    )
    # Seed `feature_count` rows of small multipolygons spread across a 10x10
    # grid in WGS84. Inline the INSERT to avoid asyncpg parameter binding
    # overhead in tests.
    insert_rows = []
    for i in range(feature_count):
        x = -100 + (i % 10) * 0.5
        y = 30 + (i // 10) * 0.5
        # 0.1° square polygon as a single-ring MULTIPOLYGON
        wkt = (
            f"MULTIPOLYGON((("
            f"{x} {y}, {x + 0.1} {y}, {x + 0.1} {y + 0.1}, "
            f"{x} {y + 0.1}, {x} {y}"
            f")))"
        )
        insert_rows.append(f"('row_{i}', ST_GeomFromText('{wkt}', 4326))")
    await session.execute(
        text(
            f'INSERT INTO data."{table_name}" (name, geom_4326) VALUES '
            + ", ".join(insert_rows)
        )
    )
    await session.commit()

    return dataset, table_name


async def _drop_test_table(session, table_name: str) -> None:
    """Best-effort cleanup of a synthetic data.* table after a test."""
    try:
        await session.execute(text(f'DROP TABLE IF EXISTS data."{table_name}"'))
        await session.commit()
    except Exception:
        await session.rollback()


async def _create_pending_job(session, admin_id: _uuid.UUID) -> _uuid.UUID:
    """Insert + commit a pending IngestJob so ``_job_phase_session(job_id, ...)``
    can SELECT it back. Mirrors the pattern in test_tasks_common_phase_brackets.
    """
    job = IngestJob(
        source_filename="quicklook_async_context_test.geojson",
        created_by=admin_id,
        status="running",
        user_metadata={"title": "INGEST-01 regression pin"},
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job.id


# ---------------------------------------------------------------------------
# Test 1: positive-form — post-fix path keeps outer session warm
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_generate_quicklook_timeout_does_not_poison_outer_session(
    test_db_session, monkeypatch
):
    """Post-fix shape: quicklook runs in a fresh ``_job_phase_session`` so the
    outer session's eagerly-loaded ``dataset.record`` survives even when
    the inner quicklook session encounters a timeout cancellation.

    Forces the timeout deterministically by setting
    ``_GENERATION_TIMEOUT_SECONDS`` to 0.001 — the timeout fires before
    the geometry query can complete, exercising the inner-session failure
    path. The outer session (which holds the eagerly-loaded
    ``dataset.record`` relationship) is never seen by the timeout
    cancellation under the post-fix call shape.

    Asserts:
    - ``_generate_quicklook`` returns without raising (non-fatal contract).
    - Outer session's ``dataset.record.id`` access does not raise.
    - Outer session still executes SQL normally.
    """
    session = test_db_session
    admin_id = await get_user_id(session, "admin")

    dataset, table_name = await _create_test_dataset_with_table(
        session, created_by=admin_id, feature_count=5
    )
    job_id = await _create_pending_job(session, admin_id)

    # Tiny timeout → cancellation fires synchronously the first time
    # the quicklook generator awaits a DB execute. CR-01 fix:
    # monkeypatching ``_GENERATION_TIMEOUT_SECONDS`` is a no-op because
    # the wrapper captures it as a function default; override the
    # wrapper itself instead.
    _force_quicklook_timeout(monkeypatch)

    try:
        # Post-fix shape: open a fresh session for the quicklook block. This
        # mirrors what _finalize_ingest does after the fix lands.
        async with _job_phase_session(job_id, phase="quicklook") as (
            ql_session,
            _ql_job,
        ):
            await _generate_quicklook(ql_session, dataset.id, table_name)

        # The outer session must remain healthy: dataset.record is lazy=joined
        # and was eagerly loaded inside _create_test_dataset_with_table's
        # commit+refresh. After a timeout cancellation on a SEPARATE session,
        # accessing dataset.record.id here must not raise.
        record_id = dataset.record.id
        assert record_id is not None
        assert isinstance(record_id, _uuid.UUID)

        # The outer session must also still execute SQL normally.
        result = await session.execute(text("SELECT 1"))
        assert result.scalar_one() == 1
    finally:
        await _drop_test_table(session, table_name)


# ---------------------------------------------------------------------------
# Test 2: mechanism pin — rollback on shared session expires dataset.record
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_generate_quicklook_timeout_poisons_outer_session_pre_fix(
    test_db_session,
):
    """Negative-form pin of the production ``MissingGreenlet`` shape.

    Pre-fix code path in ``_generate_quicklook`` reused the outer
    ``_finalize_ingest`` session for the quicklook block. The
    ``await session.commit()`` failed when the asyncio cancellation
    poisoned the asyncpg cursor; the defensive
    ``await session.rollback()`` then expired every loaded ORM
    attribute on ``dataset`` (because ``expire_on_rollback`` defaults
    to True even with ``expire_on_commit=False`` configured at
    ``app/core/db/session.py``). When ``defer_embedding`` next
    accessed ``dataset.record.id``, SQLAlchemy attempted a lazy-
    refresh — which is synchronous attribute access in an async
    context, requiring the greenlet bridge — and raised
    ``MissingGreenlet`` instead of refreshing.

    This test directly reproduces the ORM-side detonation by:
    1. Opening an active transaction on the session that holds the
       eagerly-loaded ``dataset.record``.
    2. Rolling it back (mimicking the defensive rollback in the
       pre-fix code path).
    3. Accessing ``dataset.record`` from a sync attribute getter
       (mimicking ``defer_embedding``'s ``dataset.record.id`` access).

    Under the pre-fix shape this raises ``MissingGreenlet``; Plan
    1091-02's Shape A fix moves the rollback onto a fresh session so
    the outer session never sees the expire, and ``dataset.record``
    stays warm. ``pytest.raises`` here asserts the bug-shape
    reproduces — if a future refactor accidentally removes the
    expire-on-rollback footgun (e.g., by setting
    ``expire_on_rollback=False`` on the session factory), the test
    will fail loudly because the raise no longer fires.
    """
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy.exc import MissingGreenlet

    session = test_db_session
    admin_id = await get_user_id(session, "admin")

    dataset, table_name = await _create_test_dataset_with_table(
        session, created_by=admin_id, feature_count=5
    )

    try:
        # `dataset.record` is lazy="joined" — at this point it's eagerly
        # loaded (just refresh'd by the helper above).
        assert dataset.record is not None

        # Force an active transaction on the session so the rollback has
        # something to roll back (without an open tx, SQLAlchemy's
        # rollback is a no-op and does NOT expire attributes). In
        # production, the active transaction at the defensive-rollback
        # site is the one opened implicitly by the failed
        # ``await session.commit()`` immediately above — the commit's
        # IO mid-flight is what poisons the cursor and leaves the
        # transaction open for the rollback to flush.
        await session.execute(text("SELECT 1"))

        # Simulate the pre-fix rollback inside `_generate_quicklook`
        # firing on the SAME session that holds the dataset.
        await session.rollback()

        # Confirm the expire-on-rollback footgun: dataset.record IS
        # expired after the rollback, despite expire_on_commit=False.
        state = sa_inspect(dataset)
        assert "record" in state.expired_attributes, (
            "expected dataset.record to be expired after session.rollback() "
            "(expire_on_rollback defaults to True); if this assertion fails "
            "the bug surface no longer exists and the post-fix path can "
            "share a session safely without isolating the quicklook block"
        )

        # The lazy-refresh on the expired relationship now trips the
        # greenlet bridge — same shape as the production failure
        # inside ``defer_embedding``'s ``dataset.record.id`` access.
        # This is a synchronous __get__ attempting async IO without
        # an active greenlet.
        with pytest.raises(MissingGreenlet):
            _ = dataset.record  # pyright: ignore[reportUnusedExpression]
    finally:
        await _drop_test_table(session, table_name)


# ---------------------------------------------------------------------------
# Test 3: shape regression — multipolygon table completes without raising
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_generate_quicklook_completes_on_multipolygon_shape(
    test_db_session, monkeypatch
):
    """100 multipolygons under a forced timeout still get a quicklook URI.

    The timeout cancels the geom query mid-flight and poisons the cursor of
    the draw's session. The rollback after generation recovers it, so the
    blank canvas is uploaded and the URI write that follows commits. Without
    it the commit raises "Can't reconnect until invalid transaction is rolled
    back" (sqlalchemy.org/e/20/8s2b) and the URI stays NULL.
    """
    session = test_db_session
    admin_id = await get_user_id(session, "admin")

    dataset, table_name = await _create_test_dataset_with_table(
        session, created_by=admin_id, feature_count=100
    )
    job_id = await _create_pending_job(session, admin_id)

    # Force timeout cancellation on every quicklook generation in the
    # test — this exercises the poisoned-cursor recovery path that the
    # iter-2 rollback closes. See ``_force_quicklook_timeout`` docstring
    # for why mutating ``_GENERATION_TIMEOUT_SECONDS`` directly does
    # not work (CR-01).
    _force_quicklook_timeout(monkeypatch)

    try:
        # Use the production-shape call: fresh session for the quicklook
        # block, ensuring it parallels the fix's call site.
        async with _job_phase_session(job_id, phase="quicklook") as (
            ql_session,
            _ql_job,
        ):
            await _generate_quicklook(ql_session, dataset.id, table_name)

        # Re-fetch the dataset on the outer session to observe what
        # _generate_quicklook persisted via the fresh session. The fresh
        # session committed the URI; the outer session's view of the row is
        # stale until we refresh.
        await session.refresh(dataset)
        # Blank canvas was uploaded on timeout — see
        # ``generate_vector_quicklook_with_timeout`` in
        # ``app/processing/vector/quicklook.py`` (TimeoutError branch).
        # The iter-2 recovery rollback in _generate_quicklook ensures the
        # URI write commits cleanly even on the cancellation path.
        assert dataset.quicklook_256_uri is not None, (
            "URI must persist on the timeout path — iter-2 rollback "
            "recovery missing if this fails"
        )
        assert dataset.quicklook_256_uri.startswith("vectors/")
        assert dataset.quicklook_256_uri.endswith("quicklook_256.png")

        # Outer session is still healthy.
        record_id = dataset.record.id
        assert record_id is not None
    finally:
        await _drop_test_table(session, table_name)


# ---------------------------------------------------------------------------
# Test 4: iter-2 explicit pin — URI persists across geom-query timeout
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_generate_quicklook_url_persists_after_geom_timeout(
    test_db_session, monkeypatch, caplog
):
    """A forced timeout on the geom query still persists the URI, quietly.

    Outer-session isolation alone leaves ``quicklook_256_uri`` NULL: the
    draw's commit raises "Can't reconnect until invalid transaction is rolled
    back" on the cursor the cancelled query poisoned. The rollback after
    generation clears it, so the URI commits and no ``phase=commit`` warning
    fires. One would mean the rollback was removed or moved into the
    commit's except branch.
    """
    session = test_db_session
    admin_id = await get_user_id(session, "admin")

    dataset, table_name = await _create_test_dataset_with_table(
        session, created_by=admin_id, feature_count=100
    )
    job_id = await _create_pending_job(session, admin_id)

    # CR-01 fix: monkeypatch the wrapper directly. Mutating the module's
    # ``_GENERATION_TIMEOUT_SECONDS`` constant has no effect because the
    # wrapper's ``timeout`` parameter default is captured at function-
    # definition time. See ``_force_quicklook_timeout`` docstring.
    _force_quicklook_timeout(monkeypatch)

    try:
        with caplog.at_level("WARNING"):
            async with _job_phase_session(job_id, phase="quicklook") as (
                ql_session,
                _ql_job,
            ):
                await _generate_quicklook(ql_session, dataset.id, table_name)

        # URI must have persisted despite the forced timeout.
        await session.refresh(dataset)
        assert dataset.quicklook_256_uri is not None
        assert dataset.quicklook_256_uri.endswith("quicklook_256.png")

        # WR-02 (post-1091 review): assert on `record.msg` as a DICT, not as
        # a string. The prior `phase='commit' not in rendered` and
        # `phase=commit not in rendered` substring checks were dead
        # assertions: structlog's BoundLogger with `stdlib.LoggerFactory()`
        # passes the kwarg dict directly as `record.msg`, and
        # `LogRecord.getMessage()` renders that dict via Python's __str__,
        # which produces `{'phase': 'commit', ...}` — i.e. the actual
        # separator is `: ` with single-quoted values. Neither
        # `phase='commit'` (equals sign, quoted) nor `phase=commit` (equals
        # sign, unquoted) was a substring of that representation, so the
        # negated assertion was trivially satisfied regardless of whether
        # the warning fired. Inspect the dict directly instead.
        def _is_quicklook_failed(rec, *, phase: str) -> bool:
            msg = rec.msg
            if not isinstance(msg, dict):
                return False
            return msg.get("event") == "quicklook_failed" and msg.get("phase") == phase

        commit_phase_records = [
            r for r in caplog.records if _is_quicklook_failed(r, phase="commit")
        ]
        assert commit_phase_records == [], (
            "iter-2 recovery rollback regressed: phase=commit warning fired "
            "on the timeout path. Logged dicts:\n"
            + "\n".join(repr(r.msg) for r in caplog.records)
        )
        # phase=generate is also unexpected here (the wrapper catches
        # asyncio.TimeoutError and returns blank canvas bytes — no
        # exception escapes to _generate_quicklook's generate-block
        # try/except).
        generate_phase_records = [
            r for r in caplog.records if _is_quicklook_failed(r, phase="generate")
        ]
        assert generate_phase_records == [], (
            "unexpected phase=generate warning on the timeout path — "
            "the wrapper should return a blank canvas on asyncio.TimeoutError "
            "and the rollback after it should recover the cursor. Logged dicts:\n"
            + "\n".join(repr(r.msg) for r in caplog.records)
        )
        # The URI write has its own try/except. A `phase=recovery` warning on
        # the timeout path would mean the write met the poisoned cursor the
        # rollback after generation should already have recovered.
        recovery_phase_records = [
            r for r in caplog.records if _is_quicklook_failed(r, phase="recovery")
        ]
        assert recovery_phase_records == [], (
            "unexpected phase=recovery warning on the timeout path — "
            "the rollback after generation should leave the URI write a clean "
            "cursor. Logged dicts:\n" + "\n".join(repr(r.msg) for r in caplog.records)
        )
    finally:
        await _drop_test_table(session, table_name)
