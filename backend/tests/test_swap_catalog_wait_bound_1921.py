"""The reupload swap's post-swap catalog wait carries an explicit budget (#1921).

The swap holds AccessExclusiveLock on the table it installed across that wait,
so its duration is the dataset's unreadable window. Expiry rolls the whole swap
back and reports as contention. The DB tests need the Docker test database.
"""

import asyncio
import uuid

import pytest
import structlog
from asyncpg.exceptions import DeadlockDetectedError
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import joinedload

from app.modules.catalog.datasets.domain.models import Dataset
from app.processing.ingest.tasks_common import _apply_reupload_swap
from app.platform.catalog_locks import (
    CATALOG_LOCK_CONFLICT_CODE,
    CatalogLockConflict,
)
from app.processing.ingest import tasks_common
from app.processing.ingest.tasks_reupload import (
    _file_refresh_error_code,
    _service_refresh_error_code,
)

from tests.test_reupload_swap_lock_retry import _minimal_metadata
from tests.test_swap_lock_timeout_scope_1917 import (
    _run_swap,
    _stub_downstream,
    make_swap_target,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
async def swap_target(client, test_db_session):
    async for target in make_swap_target(client, test_db_session):
        yield target


# Short enough that a held row outlasts it in under a second.
_TEST_BUDGET = "500ms"
_TEST_BUDGET_MS = 500

_POST_SWAP_BUDGET = tasks_common._POST_SWAP_CATALOG_TIMEOUT
# What `current_setting` reports back for the constant above.
_NORMALIZED_BUDGET = "1min"


class TestPostSwapCatalogWaitBudget:
    async def test_the_wait_runs_on_the_swaps_own_budget(
        self, swap_target, monkeypatch
    ) -> None:
        """A budget is in force for the duration of the catalog acquisition."""
        stub, staging = swap_target
        import app.core.db as db_module
        import app.platform.catalog_locks as locks_module

        observed: dict[str, object] = {}
        real_lock = locks_module.lock_catalog_rows

        async def _recording_lock(session, **kwargs):
            observed["lock_timeout"] = kwargs.get("lock_timeout")
            # fix(#1919): the DDL budget is gone by the time this wait starts.
            observed["on_entry"] = await session.scalar(
                text("SELECT current_setting('lock_timeout')")
            )
            await real_lock(session, **kwargs)
            observed["in_force"] = await session.scalar(
                text("SELECT current_setting('lock_timeout')")
            )

        async with db_module.async_session() as session:
            _stub_downstream(monkeypatch, session)
            arrived_with = await session.scalar(
                text("SELECT current_setting('lock_timeout')")
            )
            monkeypatch.setattr(locks_module, "lock_catalog_rows", _recording_lock)
            await _run_swap(session, stub, staging)
            await session.rollback()

        assert observed["lock_timeout"] == tasks_common._POST_SWAP_CATALOG_TIMEOUT, (
            "the swap asked for "
            f"{observed['lock_timeout']!r}, not the module's post-swap budget. "
            "An unbounded wait here is an unbounded outage: the transaction "
            "holds AccessExclusiveLock on the table it just installed."
        )
        assert observed["on_entry"] == arrived_with, (
            f"the wait started on {observed['on_entry']!r}, not the "
            f"{arrived_with!r} the transaction arrived with: the swap's DDL "
            "budget leaked past the savepoint that set it (#1919)."
        )
        assert observed["in_force"] == _NORMALIZED_BUDGET, (
            f"lock_timeout read {observed['in_force']!r} inside the "
            f"acquisition, not the {_NORMALIZED_BUDGET!r} PostgreSQL "
            f"normalizes {_POST_SWAP_BUDGET!r} to."
        )

    async def test_an_uncontended_wait_is_recorded(
        self, swap_target, monkeypatch
    ) -> None:
        """The swap logs how long the acquisition took, waited or not."""
        stub, staging = swap_target
        import app.core.db as db_module

        async with db_module.async_session() as session:
            _stub_downstream(monkeypatch, session)
            with structlog.testing.capture_logs() as captured:
                await _run_swap(session, stub, staging)
            await session.rollback()

        acquired = [
            r
            for r in captured
            if r.get("event") == "reupload_swap_catalog_lock_acquired"
        ]
        assert len(acquired) == 1, (
            f"expected one reupload_swap_catalog_lock_acquired event; got {captured}"
        )
        assert acquired[0]["log_level"] == "info"
        assert acquired[0]["table_name"] == stub.table_name
        assert acquired[0]["budget"] == tasks_common._POST_SWAP_CATALOG_TIMEOUT
        assert isinstance(acquired[0]["waited_ms"], int)

    async def test_a_holder_past_the_budget_fails_the_swap_as_contention(
        self, swap_target, monkeypatch, test_db_session
    ) -> None:
        """Expiry rolls the rename back whole and reports lock contention."""
        stub, staging = swap_target
        await test_db_session.execute(
            text(f"UPDATE data.\"{staging}\" SET name = 'new_data'")
        )
        await test_db_session.commit()

        monkeypatch.setattr(tasks_common, "_POST_SWAP_CATALOG_TIMEOUT", _TEST_BUDGET)
        import app.core.db as db_module

        async with (
            db_module.async_session() as holder,
            db_module.async_session() as api,
        ):
            await holder.execute(
                select(Dataset.id).where(Dataset.id == stub.id).with_for_update()
            )
            _stub_downstream(monkeypatch, api)
            with structlog.testing.capture_logs() as captured:
                with pytest.raises(CatalogLockConflict):
                    await asyncio.wait_for(_run_swap(api, stub, staging), timeout=30)
            await holder.rollback()

        expired = [
            r
            for r in captured
            if r.get("event") == "reupload_swap_catalog_lock_timeout"
        ]
        assert len(expired) == 1, (
            f"expected one reupload_swap_catalog_lock_timeout event; got {captured}"
        )
        assert expired[0]["log_level"] == "warning"
        assert expired[0]["budget"] == _TEST_BUDGET
        assert expired[0]["sqlstate"] == "55P03", (
            f"the handler read {expired[0]['sqlstate']!r} off the conflict's "
            "cause, so it cannot tell an expired budget from a deadlock."
        )
        assert expired[0]["waited_ms"] >= _TEST_BUDGET_MS * 0.8, (
            f"the swap gave up after {expired[0]['waited_ms']}ms against a "
            f"{_TEST_BUDGET} budget, so this run proves nothing about the wait"
        )

        live_row = await test_db_session.scalar(
            text(f'SELECT name FROM data."{stub.table_name}"')
        )
        assert live_row == "row", (
            f"the live table holds {live_row!r}: the renames were not rolled "
            "back with the failed wait, leaving a half-swapped dataset"
        )
        staging_survived = await test_db_session.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema='data' AND table_name=:tn)"
            ),
            {"tn": staging},
        )
        assert staging_survived is True
        await test_db_session.rollback()

    async def test_the_expiry_handler_survives_the_rollback_that_precedes_it(
        self, swap_target, monkeypatch, test_db_session
    ) -> None:
        """A real ORM instance still reports contention, not a greenlet error."""
        stub, staging = swap_target
        monkeypatch.setattr(tasks_common, "_POST_SWAP_CATALOG_TIMEOUT", _TEST_BUDGET)
        import app.core.db as db_module

        async with (
            db_module.async_session() as holder,
            db_module.async_session() as api,
        ):
            await holder.execute(
                select(Dataset.id).where(Dataset.id == stub.id).with_for_update()
            )
            _stub_downstream(monkeypatch, api)
            loaded = (
                await api.execute(
                    select(Dataset)
                    .options(joinedload(Dataset.record))
                    .where(Dataset.id == stub.id)
                )
            ).scalar_one()
            with structlog.testing.capture_logs() as captured:
                with pytest.raises(CatalogLockConflict):
                    await asyncio.wait_for(
                        _apply_reupload_swap(
                            api,
                            dataset=loaded,
                            staging_table=staging,
                            metadata=_minimal_metadata(),
                            sample_values={},
                            user_id=str(uuid.uuid4()),
                            source_filename="x.csv",
                            source_format="csv",
                            original_srid=4326,
                        ),
                        timeout=30,
                    )
            await holder.rollback()

        expired = [
            r
            for r in captured
            if r.get("event") == "reupload_swap_catalog_lock_timeout"
        ]
        assert len(expired) == 1, (
            "the expiry warning never emitted, so the handler raised on its "
            f"own before reaching the log. Captured: {captured}"
        )
        assert expired[0]["dataset_id"] == str(stub.id)
        await test_db_session.rollback()

    @pytest.mark.parametrize(
        ("cause", "event", "code", "needle"),
        [
            (
                DBAPIError("stmt", {}, DeadlockDetectedError("cycle")),
                "reupload_swap_catalog_deadlock",
                "40P01",
                "deadlock victim",
            ),
            (None, "reupload_swap_catalog_lock_failed", None, "no SQLSTATE"),
        ],
        ids=["deadlock", "no_sqlstate"],
    )
    async def test_the_cause_picks_the_event(
        self, swap_target, monkeypatch, cause, event, code, needle
    ) -> None:
        """A lost deadlock and an unreadable cause are not reported as expiry."""
        stub, staging = swap_target
        import app.core.db as db_module
        import app.platform.catalog_locks as locks_module

        async def _raise_conflict(session, **kwargs):
            conflict = CatalogLockConflict("held")
            conflict.__cause__ = cause
            raise conflict

        monkeypatch.setattr(locks_module, "lock_catalog_rows", _raise_conflict)
        async with db_module.async_session() as session:
            _stub_downstream(monkeypatch, session)
            with structlog.testing.capture_logs() as captured:
                with pytest.raises(CatalogLockConflict):
                    await _run_swap(session, stub, staging)
            await session.rollback()

        assert [
            r.get("event")
            for r in captured
            if r.get("event", "").startswith("reupload_swap_catalog")
        ] == [event]
        logged = next(r for r in captured if r.get("event") == event)
        assert logged["log_level"] == "warning"
        assert logged["sqlstate"] == code
        assert needle in logged["hint"]
        assert isinstance(logged["waited_ms"], int)


class TestReuploadErrorCodes:
    """Pure mapping — no DB."""

    def test_a_contended_catalog_row_maps_to_its_own_code(self) -> None:
        exc = CatalogLockConflict("held")
        assert _file_refresh_error_code(exc) == CATALOG_LOCK_CONFLICT_CODE
        assert _service_refresh_error_code(exc) == CATALOG_LOCK_CONFLICT_CODE

    def test_everything_else_keeps_its_path_code(self) -> None:
        exc = RuntimeError("ogr2ogr fell over")
        assert _file_refresh_error_code(exc) == "file_refresh_failed"
        assert _service_refresh_error_code(exc) == "service_refresh_failed"

    def test_the_credential_codes_are_unchanged(self) -> None:
        from app.platform.refresh.credentials import (
            CredentialExpiredError,
            CredentialStoreUnavailable,
        )

        assert (
            _service_refresh_error_code(CredentialExpiredError("spent"))
            == "credential_expired"
        )
        assert (
            _service_refresh_error_code(CredentialStoreUnavailable("down"))
            == "credential_store_unavailable"
        )
