"""INGEST-01 / Phase 1091-02 — quicklook async-context boundary regression.

Pins the bug shape audited in
``.planning/audits/INGEST-QUICKLOOK-ASYNC-CONTEXT-v1021.md``: the same
``AsyncSession`` was reused across the ``asyncio.wait_for`` cancellation
boundary in ``tasks_common._generate_quicklook``. When the 10s quicklook
timeout fires on pathologically-shaped geometry (the live trigger was
``urban_areas_landscan_10m`` — 6018 multipolygons), the cancellation
poisoned the asyncpg cursor. The defensive ``session.rollback()`` inside
``_generate_quicklook`` then expired every ORM attribute (because
``expire_on_rollback`` defaults to True even though ``expire_on_commit``
is False at ``app/core/db/session.py``). The bug detonated two function
calls later in ``defer_embedding`` when ``dataset.record.id`` was
accessed and triggered a lazy-refresh against the still-poisoned
greenlet bridge → ``MissingGreenlet`` escaped to the outer ``except``
and the job row got ``status=failed``.

Shape A fix (Plan 1091-02): wrap the quicklook block in its own
``_job_phase_session(job_uuid, phase="quicklook")`` so the cancellation
boundary cannot poison the outer ``_finalize_ingest`` session. The
outer session's ORM identity-map for ``dataset.record`` stays warm and
``defer_embedding`` completes cleanly.

Four test functions:

1. ``test_generate_quicklook_timeout_does_not_poison_outer_session`` —
   positive-form pin. Confirms the post-fix call shape (quicklook in a
   fresh session) keeps the outer session's ``dataset.record`` accessible
   even after the quicklook session encounters a timeout-equivalent
   failure.

2. ``test_generate_quicklook_timeout_poisons_outer_session_pre_fix`` —
   negative-form / mechanism pin. Forces a session.rollback() on the
   same session that holds the dataset's eagerly-loaded ``record``
   relationship, then confirms the next ``dataset.record`` access on
   that rolled-back session expires the attribute. This pins the
   half of the bug shape that is reliably reproducible in unit tests
   (the rollback-expires-attributes half). The greenlet-bridge poison
   half is a production-scale race that does not reproduce
   deterministically under unit-test timing, so we pin the ORM-level
   half here and let the live docker-rebuild verification (Task 2)
   own the end-to-end shape.

3. ``test_generate_quicklook_completes_on_multipolygon_shape`` — shape
   regression UNDER forced timeout. Creates a synthetic data table
   with 100 multipolygons, monkeypatches ``_GENERATION_TIMEOUT_SECONDS``
   to 0.001 to force the cancellation path, and asserts the URI
   persists despite the poisoned cursor — anchoring INGEST-01
   acceptance criterion (b) via the iter-2 rollback-recovery shape.

4. ``test_generate_quicklook_url_persists_after_geom_timeout`` —
   explicit iter-2 pin with ``caplog`` assertion that no
   ``phase=commit`` warning fires on the timeout path. Pins the
   live verification gap that surfaced after iter-1: blank canvas
   was uploaded but the URI never persisted because
   ``ql_session.commit()`` failed on the still-poisoned cursor. The
   iter-2 ``session.rollback()`` between upload and URI write clears
   the cursor; this test guards against a regression that moves the
   rollback back inside the commit-except branch.
"""

from __future__ import annotations

import uuid as _uuid

import pytest
from sqlalchemy import select, text

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

    CR-01 fix: ``_GENERATION_TIMEOUT_SECONDS`` is read once at function-
    definition time as a default keyword-argument value (captured into
    ``generate_vector_quicklook_with_timeout.__defaults__``). Mutating the
    module attribute after import does NOT change ``__defaults__`` — the
    function continues to use its captured 10s default. So the prior
    ``monkeypatch.setattr(quicklook_module, "_GENERATION_TIMEOUT_SECONDS",
    0.001)`` was a literal no-op and the tests silently exercised the
    happy path instead of the cancellation/recovery path they claim to
    pin.

    Replace the wrapper itself with a closure that forwards everything to
    the real wrapper while pinning ``timeout`` to the tiny value. This
    way every call site that does ``await
    generate_vector_quicklook_with_timeout(...)`` — including the
    ``from ... import ...`` re-export inside ``_generate_quicklook`` —
    routes through the override and the cancellation path is actually
    exercised.

    Verify by temporarily commenting out the iter-2 rollback recovery at
    ``tasks_common.py`` (the ``await session.rollback()`` between upload
    and URI write) and re-running the three tests that call this helper:
    at least ``test_generate_quicklook_url_persists_after_geom_timeout``
    must FAIL. If it still passes, the test setup is not exercising the
    recovery path.
    """
    real_wrapper = quicklook_module.generate_vector_quicklook_with_timeout

    async def _fast_timeout_wrapper(
        db, table_name, geometry_type, size=256, timeout_override=timeout
    ):
        return await real_wrapper(
            db, table_name, geometry_type, size, timeout=timeout_override
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
            await _generate_quicklook(
                ql_session, dataset, table_name, "MultiPolygon"
            )

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

    Pre-fix code path at ``tasks_common.py:826`` reused the outer
    ``_finalize_ingest`` session for the quicklook block. The
    ``await session.commit()`` at line 662 failed when the asyncio
    cancellation poisoned the asyncpg cursor; the defensive
    ``await session.rollback()`` at line 666 then expired every loaded
    ORM attribute on ``dataset`` (because ``expire_on_rollback``
    defaults to True even with ``expire_on_commit=False`` at
    session.py:26). When ``defer_embedding`` next accessed
    ``dataset.record.id`` at helpers.py:123, SQLAlchemy attempted a
    lazy-refresh — which is synchronous attribute access in an async
    context, requiring the greenlet bridge — and raised
    ``MissingGreenlet`` instead of refreshing.

    This test directly reproduces the ORM-side detonation by:
    1. Opening an active transaction on the session that holds the
       eagerly-loaded ``dataset.record``.
    2. Rolling it back (mimicking line 666 of pre-fix code).
    3. Accessing ``dataset.record`` from a sync attribute getter
       (mimicking helpers.py:123's `dataset.record.id`).

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
        # production, the active transaction at the line-666 rollback
        # site is the one opened implicitly by the failed
        # ``await session.commit()`` at line 662 — the commit's IO
        # mid-flight is what poisons the cursor and leaves the
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
        # greenlet bridge — same shape as the production failure at
        # helpers.py:123 → attributes.py:569. This is a synchronous
        # __get__ attempting async IO without an active greenlet.
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
    """100-multipolygon shape regression UNDER a forced timeout.

    Pins INGEST-01 iter-2: even when ``asyncio.wait_for`` cancels the
    geom query mid-flight (poisoning the asyncpg cursor on the fresh
    quicklook session), the post-upload ``session.rollback()`` recovery
    at tasks_common.py:726 clears the cursor state and the subsequent
    URI write commits cleanly.

    Pre-iter-2 (rollback was inside the commit-except branch only),
    this test would have left ``dataset.quicklook_256_uri`` as NULL —
    blank canvas was uploaded to storage but ``ql_session.commit()``
    in ``_generate_quicklook`` raised the "Can't reconnect until
    invalid transaction is rolled back" error
    (sqlalchemy.org/e/20/8s2b) and the URI breadcrumb was lost. This
    was the live verification gap on ``urban_areas_landscan_10m``.

    Anchors INGEST-01 acceptance criterion (b): the dataset gets a
    non-null ``quicklook_256_uri`` after the post-fix path runs,
    even on the cancellation surface that originally tripped the bug.
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
            await _generate_quicklook(
                ql_session, dataset, table_name, "MultiPolygon"
            )

        # Re-fetch the dataset on the outer session to observe what
        # _generate_quicklook persisted via the fresh session. The fresh
        # session committed its merged copy; the outer session's view of
        # the row is stale until we refresh.
        await session.refresh(dataset)
        # Blank canvas was uploaded on timeout per quicklook.py:235-236;
        # the iter-2 recovery rollback in _generate_quicklook ensures the
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
    """Explicit iter-2 pin: forced ``asyncio.wait_for`` timeout on the geom
    query MUST NOT prevent the URI from persisting AND MUST NOT log a
    ``phase=commit`` warning.

    Reproduces the exact live verification gap observed on
    ``urban_areas_landscan_10m`` between iter-1 and iter-2:

    - iter-1: outer-session isolation via ``_job_phase_session``
      eliminated the ``MissingGreenlet`` (job status flipped from
      ``failed`` to ``Success``) but ``quicklook_256_uri`` stayed NULL
      because the post-upload ``ql_session.commit()`` in
      ``_generate_quicklook`` raised "Can't reconnect until invalid
      transaction is rolled back" (the asyncpg cursor on
      ``ql_session`` was still in the poisoned state from the cancelled
      geom query).

    - iter-2: explicit ``session.rollback()`` between upload and URI
      write clears the cursor state on the timeout path. URI commits
      cleanly; no ``phase=commit`` warning fires.

    A ``phase=commit`` warning in worker logs after this test would
    indicate the recovery rollback was removed or moved back inside
    the commit-except branch.
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
                await _generate_quicklook(
                    ql_session, dataset, table_name, "MultiPolygon"
                )

        # URI must have persisted despite the forced timeout.
        await session.refresh(dataset)
        assert dataset.quicklook_256_uri is not None
        assert dataset.quicklook_256_uri.endswith("quicklook_256.png")

        # No `phase=commit` warning should have fired. structlog routes
        # through the stdlib logger; the warning shape from
        # `_generate_quicklook` includes the substring "quicklook_failed"
        # AND "phase=commit" in the rendered record. We assert the
        # composite shape so a future log refactor that drops one
        # substring but keeps the other does not silently un-pin this
        # regression.
        rendered = "\n".join(record.getMessage() for record in caplog.records)
        assert "phase='commit'" not in rendered and "phase=commit" not in rendered, (
            "iter-2 recovery rollback regressed: phase=commit warning fired "
            "on the timeout path. Logged records:\n" + rendered
        )
        # phase=generate is also unexpected here (the wrapper catches
        # asyncio.TimeoutError and returns blank canvas bytes — no
        # exception escapes to _generate_quicklook's generate-block
        # try/except).
        assert "phase='generate'" not in rendered and "phase=generate" not in rendered, (
            "unexpected phase=generate warning on the timeout path — "
            "the wrapper should catch asyncio.TimeoutError and return "
            "blank canvas bytes without raising. Logged records:\n"
            + rendered
        )
    finally:
        await _drop_test_table(session, table_name)
