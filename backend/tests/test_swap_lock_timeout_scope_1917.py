"""The reupload swap's DDL lock_timeout does not outlive its savepoint (#1917).

PostgreSQL keeps a ``SET LOCAL`` across ``RELEASE SAVEPOINT`` — only
``ROLLBACK TO`` reverts it. ``_apply_reupload_swap`` installs one for its
``ALTER TABLE`` renames, so on the success path it has to put the previous
value back; otherwise the ``lock_catalog_rows(lock_timeout=None)`` wait that
follows runs on the swap's budget and fails on contention it must wait out.

The DB-backed tests require the Docker test database.
"""

import asyncio
import uuid

import pytest
from sqlalchemy import select, text

from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.platform.catalog_locks import CatalogLockConflict
from app.processing.ingest import tasks_common
from app.processing.ingest.tasks_common import _apply_reupload_swap

from tests.factories import get_user_id
from tests.test_feature_lock_order_1847 import _await_lock_wait
from tests.test_reupload_swap_lock_retry import (
    _make_dataset_stub,
    _make_port,
    _minimal_metadata,
    _stub_atomic_bump,
)

pytestmark = pytest.mark.anyio

# The swap's DDL budget for these tests, shrunk so the contended wait below
# outlasts it in about a second instead of the production five.
_TEST_SWAP_MS = 500
_TEST_SWAP_TIMEOUT = f"{_TEST_SWAP_MS}ms"
_PAST_THE_CLAMP_SECONDS = (_TEST_SWAP_MS / 1000.0) * 3


async def make_swap_target(client, test_db_session):
    """A committed dataset row and the live/staging table pair its swap renames."""
    suffix = uuid.uuid4().hex[:8]
    live = f"swap_scope_{suffix}"
    staging = f"swap_scopes_{suffix}"
    for table in (live, staging):
        await test_db_session.execute(
            text(
                f'CREATE TABLE data."{table}" '
                "(id serial PRIMARY KEY, name text, geom geometry(Point, 4326))"
            )
        )
        await test_db_session.execute(
            text(f"INSERT INTO data.\"{table}\" (name) VALUES ('row')")
        )
    admin_id = await get_user_id(test_db_session, "admin")
    record = Record(
        title=f"Swap scope {suffix}",
        summary="Fixture layer",
        theme_category=["test"],
        visibility="private",
        record_status="published",
        created_by=admin_id,
    )
    test_db_session.add(record)
    await test_db_session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=live,
        srid=4326,
        geometry_type="POINT",
        feature_count=1,
        column_info=[{"name": "name", "type": "text"}],
        source_format="csv",
    )
    test_db_session.add(dataset)
    await test_db_session.commit()
    await test_db_session.refresh(dataset)

    stub = _make_dataset_stub(live)
    stub.id = dataset.id
    stub.record_id = dataset.record_id
    yield stub, staging

    await test_db_session.execute(
        text("DELETE FROM catalog.records WHERE id = :record_id"),
        {"record_id": stub.record_id},
    )
    for table in (live, staging, f"{live}_old"):
        await test_db_session.execute(
            text(f'DROP TABLE IF EXISTS data."{table}" CASCADE')
        )
    await test_db_session.commit()


@pytest.fixture
async def swap_target(client, test_db_session):
    async for target in make_swap_target(client, test_db_session):
        yield target


def _stub_downstream(monkeypatch, session) -> None:
    """Neutralize the metadata, audit and tile-bump writes the swap makes after its lock."""

    async def _noop(*args, **kwargs):
        return None

    async def _noop_quality(*args, **kwargs):
        return {"score": 0.0, "issues": []}

    monkeypatch.setattr(
        "app.processing.ingest.metadata.refresh_attribute_metadata", _noop
    )
    monkeypatch.setattr(
        "app.processing.ingest.metadata.compute_quality_score", _noop_quality
    )
    monkeypatch.setattr("app.modules.audit.service.audit_emit", _noop)
    monkeypatch.setattr("app.platform.extensions.get_processing_port", _make_port)
    monkeypatch.setattr(session, "add", lambda *args, **kwargs: None)
    # The atomic bump itself is covered by test_worker_swap_bump_after_lock_1911.py.
    _stub_atomic_bump(monkeypatch)


async def _run_swap(session, stub, staging):
    return await _apply_reupload_swap(
        session,
        dataset=stub,
        staging_table=staging,
        metadata=_minimal_metadata(),
        sample_values={},
        user_id=str(uuid.uuid4()),
        source_filename="x.csv",
        source_format="csv",
        original_srid=4326,
    )


class TestSwapLockTimeoutScope:
    async def test_the_swap_restores_the_lock_timeout_it_installed(
        self, swap_target, monkeypatch
    ) -> None:
        """After the swap the transaction is back on the budget it arrived with."""
        stub, staging = swap_target
        import app.core.db as db_module

        async with db_module.async_session() as session:
            _stub_downstream(monkeypatch, session)
            before = await session.scalar(
                text("SELECT current_setting('lock_timeout')")
            )
            await _run_swap(session, stub, staging)
            after = await session.scalar(text("SELECT current_setting('lock_timeout')"))
            await session.rollback()

        assert after == before, (
            f"the swap left lock_timeout at {after!r} (it was {before!r}). A "
            "SET LOCAL survives RELEASE SAVEPOINT, so the DDL budget is still "
            "in force and clamps every wait the rest of this transaction takes."
        )

    async def test_a_contended_catalog_row_is_waited_out_not_failed(
        self, swap_target, monkeypatch
    ) -> None:
        """A holder past the DDL budget is waited out, not answered with a conflict."""
        stub, staging = swap_target
        monkeypatch.setattr(tasks_common, "_SWAP_FIRST_TIMEOUT", _TEST_SWAP_TIMEOUT)
        import app.core.db as db_module

        async with (
            db_module.async_session() as holder,
            db_module.async_session() as api,
            db_module.async_session() as probe,
        ):
            await holder.execute(
                select(Dataset.id).where(Dataset.id == stub.id).with_for_update()
            )
            _stub_downstream(monkeypatch, api)
            api_pid = await api.scalar(text("SELECT pg_backend_pid()"))
            swap = asyncio.create_task(_run_swap(api, stub, staging))
            try:
                await _await_lock_wait(probe, api_pid)
                await asyncio.sleep(_PAST_THE_CLAMP_SECONDS)
                still_waiting = not swap.done()
            finally:
                await holder.rollback()

            try:
                version = await asyncio.wait_for(swap, timeout=30)
            except CatalogLockConflict as exc:
                raise AssertionError(
                    "the swap failed on the contended datasets row instead of "
                    "waiting for it: the DDL lock_timeout outlived the savepoint "
                    "that set it and clamped a wait that asked for no clamp"
                ) from exc
            await api.rollback()

        assert still_waiting, (
            "the swap finished before the DDL budget could have clamped its "
            "wait, so this run proves nothing about the clamp"
        )
        assert version is not None
