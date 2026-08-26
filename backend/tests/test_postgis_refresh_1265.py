"""Registered-PostGIS refresh strategy (#1265, ADR-002 Decision 5a).

A dataset registered from an existing table is the one origin kind GeoLens
never re-reads: registration copies no data, so the catalog serves the live
relation while describing it with a measurement taken once, on the day it was
registered. Everything below is about the two halves of correcting that.

**The door** must admit a postgis origin through the SAME machinery every
other strategy uses — one Rule 1 gate, one ``create_pending_run``, one
partial unique index refereeing concurrent clicks. A strategy that grew its
own admission path would pass all of its own tests and still be the bug
(handoff invariant 11), so the assertions here are about which shared
function ran, not merely about the status code.

**The worker** must leave the dataset better described or exactly as it
found it, and never in between. The failure tests are the load-bearing ones:
a dropped table has to produce a failed run, a ``missing`` verdict, and
metadata still describing the last measurement that actually happened —
invariant 10 says a failed refresh changes no data and no freshness, and for
this strategy "the data" is a table GeoLens does not own.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import joinedload

from app.modules.catalog.datasets.api import router_refresh
from app.modules.catalog.datasets.domain.models import Dataset, RecordDistribution
from app.modules.catalog.records.service import (
    create_distribution,
    generate_distributions,
)
from app.platform.dataset_origin import set_dataset_origin, set_postgis_origin
from app.platform.jobs.models import IngestJob
from app.platform.refresh.models import DatasetRefreshRun
from app.processing.ingest import metadata as tasks_postgis_refresh_metadata
from app.processing.ingest import tasks_postgis_refresh
from app.processing.ingest.tasks_postgis_refresh import refresh_postgis
from tests.factories import create_dataset as _create_dataset, get_user_id

pytestmark = pytest.mark.anyio

_SQUARE = "POLYGON((0 0, 0 1, 1 1, 1 0, 0 0))"
_FAR_SQUARE = "POLYGON((10 10, 10 11, 11 11, 11 10, 10 10))"

# What get_column_info reports for the seed table below: it excludes gid,
# geom and geom_4326, so `name` is the whole of the visible schema.
_SEED_COLUMNS = [
    {
        "name": "name",
        "type": "text",
        "ordinal_position": 2,
        "is_nullable": True,
    }
]


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


async def _registered_dataset(
    session,
    *,
    created_by: uuid.UUID,
    rows: int = 2,
    stored_feature_count: int = 2,
    stored_columns: list[dict] | None = None,
):
    """A dataset bound to a real table the way ``register_existing_table`` binds one.

    The physical table is genuinely created — every assertion in this file is
    about what a query of the live relation returns, and a mocked measurement
    would prove only that the mock was wired up.

    ``stored_feature_count`` and ``stored_columns`` are the catalog's *stale*
    view, which is the whole premise: the dataset row says one thing and the
    table says another, and the refresh is what reconciles them.
    """
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    await session.execute(
        text(
            f"CREATE TABLE data.{table_name} ("  # noqa: S608
            "  gid SERIAL PRIMARY KEY,"
            "  name text,"
            "  geom geometry(Polygon, 4326),"
            "  geom_4326 geometry(Polygon, 4326)"
            ")"
        )
    )
    for i in range(rows):
        await session.execute(
            text(
                f"INSERT INTO data.{table_name} (name, geom, geom_4326) "  # noqa: S608
                f"VALUES (:name, ST_GeomFromText('{_SQUARE}', 4326), "
                f"ST_GeomFromText('{_SQUARE}', 4326))"
            ),
            {"name": f"row-{i}"},
        )
    await session.commit()

    dataset = await _create_dataset(
        session,
        created_by=created_by,
        table_name=table_name,
        geometry_type="POLYGON",
        feature_count=stored_feature_count,
        column_info=(_SEED_COLUMNS if stored_columns is None else stored_columns),
        # Registration stores no source_format — a null format is what makes
        # classify_origin say "postgis".
        source_format=None,
        source_filename=None,
    )
    set_postgis_origin(dataset, table_name, schema="data")
    await session.commit()
    await session.refresh(dataset)
    return dataset


@asynccontextmanager
async def _dispatch_harness():
    """Patch the deferred task and yield the mock the door should reach for."""
    task = MagicMock()
    task.defer_async = AsyncMock(return_value=None)
    port = MagicMock()
    port.refresh_postgis_task.return_value = task
    with patch.object(router_refresh, "get_catalog_port", return_value=port):
        yield task


async def _run_for(session, dataset_id: uuid.UUID) -> DatasetRefreshRun | None:
    return (
        await session.execute(
            select(DatasetRefreshRun).where(DatasetRefreshRun.dataset_id == dataset_id)
        )
    ).scalar_one_or_none()


async def _job_for(session, job_id: uuid.UUID) -> IngestJob:
    return (
        await session.execute(select(IngestJob).where(IngestJob.id == job_id))
    ).scalar_one()


async def _reload(session, dataset_id: uuid.UUID) -> Dataset:
    """Read the dataset back from the database, past the identity map."""
    session.expire_all()
    return (
        await session.execute(
            select(Dataset)
            .options(joinedload(Dataset.record))
            .where(Dataset.id == dataset_id)
        )
    ).scalar_one()


async def _distribution_pairs(session, record_id: uuid.UUID) -> set[tuple[str, str]]:
    """The (distribution_type, format) pairs this record currently advertises.

    A column select rather than an entity one, deliberately: the worker writes
    these rows from its own session, and a query that went through this
    session's identity map could answer from objects loaded before it ran.
    """
    rows = (
        await session.execute(
            select(
                RecordDistribution.distribution_type,
                RecordDistribution.format,
            ).where(RecordDistribution.record_id == record_id)
        )
    ).all()
    return {(row[0], row[1]) for row in rows}


async def _distribution_ids(session, record_id: uuid.UUID) -> set[uuid.UUID]:
    return set(
        (
            await session.execute(
                select(RecordDistribution.id).where(
                    RecordDistribution.record_id == record_id
                )
            )
        )
        .scalars()
        .all()
    )


async def _dispatch(client: AsyncClient, headers: dict, dataset_id: uuid.UUID) -> dict:
    """Queue a refresh through the real door and return the payload."""
    async with _dispatch_harness():
        resp = await client.post(f"/datasets/{dataset_id}/refresh", headers=headers)
    assert resp.status_code == 202, resp.text
    return resp.json()


async def _execute(session, payload: dict) -> None:
    """Run the worker for a dispatched refresh, as the queue would.

    ``.func`` is the Procrastinate-registered callable — the same one a worker
    invokes — so the run ledger, the heartbeat and the failure handler all
    execute for real.
    """
    job = await _job_for(session, uuid.UUID(payload["job_id"]))
    attempt_id = str(job.attempt_id)
    await refresh_postgis.func(
        job_id=payload["job_id"],
        dataset_id=payload["dataset_id"],
        attempt_id=attempt_id,
    )


def _pg_error(code: str) -> DBAPIError:
    """A driver error carrying one SQLSTATE, as asyncpg would raise it."""

    class _Orig(Exception):
        sqlstate = code

    return DBAPIError("SELECT 1", {}, _Orig("simulated"))


# ---------------------------------------------------------------------------
# The vocabulary is the probe's, not a second one
# ---------------------------------------------------------------------------


def test_the_health_words_are_the_ones_the_api_already_describes() -> None:
    """Structural: processing/ retypes these, so a test has to pin them.

    ``app.modules.catalog.sources.origin_probe`` owns the closed vocabulary
    and the API description is generated from it, but processing/ may not
    import catalog (``test_no_processing_imports_catalog``). The constants are
    therefore mirrored, and this is what makes the mirror non-optional: a
    value that drifts out of the probe's set would be persisted, served, and
    absent from the schema that claims to enumerate it.
    """
    from app.modules.catalog.sources.origin_probe import DETAIL_CODES
    from app.platform.dataset_origin import SOURCE_HEALTH_VALUES

    healths = {
        tasks_postgis_refresh._HEALTHY,
        tasks_postgis_refresh._MISSING,
        tasks_postgis_refresh._INACCESSIBLE,
    }
    assert healths <= set(SOURCE_HEALTH_VALUES)

    details = {
        tasks_postgis_refresh._NOT_FOUND,
        tasks_postgis_refresh._UNAUTHORIZED,
        tasks_postgis_refresh._NETWORK_ERROR,
    }
    assert details <= DETAIL_CODES

    verdicts = [
        *tasks_postgis_refresh._VERDICT_BY_SQLSTATE.values(),
        tasks_postgis_refresh._CONNECTION_VERDICT,
        tasks_postgis_refresh._MISSING_VERDICT,
    ]
    for verdict in verdicts:
        assert verdict.health in SOURCE_HEALTH_VALUES
        assert verdict.detail in DETAIL_CODES
        # ADR-002 Decision 3: no raw driver text in a stored reason string.
        # These are composed here, so the property is checkable by reading
        # them — an interpolated exception would be visible as a placeholder.
        assert "{" not in verdict.message


def test_a_slow_query_is_not_reported_as_a_broken_table() -> None:
    """A statement timeout says something about the query, not the origin.

    The distinction matters because ``source_health`` is sticky: this
    strategy is the only writer of it for its origin kind (the probe refuses
    postgis), so a verdict written from a timeout would sit on the dataset
    until somebody happened to refresh again.
    """
    verdict = tasks_postgis_refresh._classify_db_failure(_pg_error("57014"))
    assert verdict.health is None
    assert verdict.error_code == "postgis_refresh_failed"

    missing = tasks_postgis_refresh._classify_db_failure(_pg_error("42P01"))
    assert (missing.health, missing.detail) == ("missing", "not_found")

    denied = tasks_postgis_refresh._classify_db_failure(_pg_error("42501"))
    assert (denied.health, denied.detail) == ("inaccessible", "unauthorized")

    dropped_connection = tasks_postgis_refresh._classify_db_failure(_pg_error("08006"))
    assert (dropped_connection.health, dropped_connection.detail) == (
        "inaccessible",
        "network_error",
    )


def test_the_verdict_survives_an_aborted_transaction_wrapper() -> None:
    """fix(#1313 review): the outermost SQLSTATE is not always the real one.

    ``extract_metadata``'s spatial fast path catches every exception and
    immediately retries its per-helper queries inside the transaction the
    first failure already aborted. A table dropped between two statements of
    the measurement therefore arrives here as ``25P02`` with the real
    ``42P01`` in ``__context__`` — and classifying only the outer code would
    report the exact mid-flight race the classifier exists to cover as
    inconclusive, leaving the dataset unmarked.

    Staged as a chained exception rather than by racing a real DROP: a
    REPEATABLE READ transaction that has already read the table holds an
    ACCESS SHARE lock on it, so a concurrent DROP blocks instead of
    interleaving. What has to hold is the classifier's rule, and the chain is
    that rule's whole input.
    """

    def _raised_while_handling(outer: str, inner: str) -> DBAPIError:
        try:
            raise _pg_error(inner)
        except DBAPIError:
            try:
                raise _pg_error(outer)
            except DBAPIError as exc:
                return exc

    aborted = _raised_while_handling("25P02", "42P01")
    assert aborted.__context__ is not None
    verdict = tasks_postgis_refresh._classify_db_failure(aborted)
    assert (verdict.health, verdict.detail) == ("missing", "not_found")
    assert verdict.error_code == "source_missing"

    revoked = _raised_while_handling("25P02", "42501")
    denied = tasks_postgis_refresh._classify_db_failure(revoked)
    assert (denied.health, denied.detail) == ("inaccessible", "unauthorized")

    # A chain with nothing informative anywhere on it stays inconclusive, and
    # reports the OUTERMOST code — the one an operator sees in their own logs.
    opaque = tasks_postgis_refresh._classify_db_failure(
        _raised_while_handling("25P02", "57014")
    )
    assert opaque.health is None
    assert "25P02" in str(opaque)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


class TestPostgisRefreshDispatch:
    async def test_a_registered_table_is_no_longer_refresh_not_applicable(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _registered_dataset(test_db_session, created_by=admin_id)

        async with _dispatch_harness() as task:
            resp = await client.post(
                f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
            )

        assert resp.status_code == 202, resp.text
        payload = resp.json()
        assert payload["origin_kind"] == "postgis"
        assert payload["trigger"] == "api"
        assert payload["status"] == "pending"

        run = await _run_for(test_db_session, dataset.id)
        assert run is not None
        assert str(run.id) == payload["run_id"]
        assert (run.trigger, run.origin_kind, run.status) == (
            "api",
            "postgis",
            "pending",
        )
        assert run.triggered_by == admin_id
        assert run.feature_count_before == dataset.feature_count

        # No source pointer travels in the task arguments: the worker reads
        # the binding, exactly as this handler did.
        kwargs = task.defer_async.call_args.kwargs
        assert set(kwargs) == {"job_id", "attempt_id", "dataset_id"}
        assert kwargs["dataset_id"] == str(dataset.id)

    async def test_the_job_is_a_refresh_and_not_a_reupload(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """The marker is load-bearing, not cosmetic.

        ``reupload: True`` means "a task is replacing this dataset's data",
        and two pieces of shared SQL key off it — the legacy-live admission
        probe and the abandoned-run sweep's other-live-task clause. Both
        reason about swaps this strategy never performs, so claiming the
        marker would make a metadata recount referee other datasets' runs.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _registered_dataset(test_db_session, created_by=admin_id)

        payload = await _dispatch(client, admin_auth_header, dataset.id)

        job = await _job_for(test_db_session, uuid.UUID(payload["job_id"]))
        assert job.user_metadata["refresh"] is True
        assert "reupload" not in job.user_metadata
        assert job.user_metadata["origin_kind"] == "postgis"
        assert job.source_url is None
        assert job.file_path is None
        assert job.source_filename == f"data.{dataset.table_name}"

    async def test_a_binding_without_a_table_name_is_origin_unavailable(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """Distinct from ``refresh_not_applicable``, and for the same reason
        the service door draws that line: this dataset HAS an origin, GeoLens
        just never recorded which table. "Re-upload instead" would be wrong
        advice; "register the table again" is right."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _registered_dataset(test_db_session, created_by=admin_id)
        dataset.origin_ref = None
        await test_db_session.commit()

        async with _dispatch_harness():
            resp = await client.post(
                f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
            )

        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "origin_unavailable"
        assert resp.json()["detail"]["origin_kind"] == "postgis"
        assert await _run_for(test_db_session, dataset.id) is None

    async def test_a_token_is_refused_rather_than_silently_dropped(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """202 plus a discarded secret is the worst available answer.

        Nothing on this path can use a credential — the origin is a relation
        reached over the connection the request already holds — so a caller
        who sent one has to be told, or they will assume it was used.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _registered_dataset(test_db_session, created_by=admin_id)

        async with _dispatch_harness() as task:
            resp = await client.post(
                f"/datasets/{dataset.id}/refresh",
                headers=admin_auth_header,
                json={"token": "not-a-real-token"},
            )

        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"]["code"] == "credential_not_applicable"
        assert await _run_for(test_db_session, dataset.id) is None
        task.defer_async.assert_not_awaited()

    async def test_a_second_refresh_is_refused_as_dataset_busy(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """Admission is the shared index, not a per-strategy check.

        And the refusal leaves nothing behind: the ingest job the refused
        request wrote rolls back with it, so a busy dataset does not
        accumulate orphan pending jobs for the stale sweep to find.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _registered_dataset(test_db_session, created_by=admin_id)

        first = await _dispatch(client, admin_auth_header, dataset.id)

        async with _dispatch_harness() as task:
            second = await client.post(
                f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
            )

        assert second.status_code == 409, second.text
        assert second.json()["detail"]["code"] == "dataset_busy"
        task.defer_async.assert_not_awaited()

        jobs = (
            (
                await test_db_session.execute(
                    select(IngestJob).where(IngestJob.dataset_id == dataset.id)
                )
            )
            .scalars()
            .all()
        )
        assert [str(job.id) for job in jobs] == [first["job_id"]]

    async def test_a_rebind_at_the_reservation_releases_the_reservation(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """The TOCTOU the service door closed, on the other strategy.

        A file re-upload finishing mid-request rebinds the dataset to an
        upload origin. The post-reservation read then refuses, and the
        reservation has to be released on that path too — a leaked run row
        refuses every later refresh with ``dataset_busy`` until the sweep
        cancels it an hour later.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _registered_dataset(test_db_session, created_by=admin_id)

        real_create_pending_run = router_refresh.create_pending_run

        async def _rebind_then_reserve(*args, **kwargs):
            set_dataset_origin(
                dataset,
                "upload",
                uri=None,
                filename="replacement.gpkg",
                file_hash="abc123",
            )
            dataset.source_format = "gpkg"
            await test_db_session.commit()
            return await real_create_pending_run(*args, **kwargs)

        async with _dispatch_harness() as task:
            with patch.object(
                router_refresh, "create_pending_run", _rebind_then_reserve
            ):
                resp = await client.post(
                    f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
                )

        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"]["code"] == "refresh_not_applicable"
        task.defer_async.assert_not_awaited()
        assert await _run_for(test_db_session, dataset.id) is None


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


class TestPostgisRefreshExecution:
    async def test_a_refresh_re_measures_the_live_table(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """The whole point: the catalog stops describing registration day.

        The dataset is seeded believing the table holds two rows and one
        attribute. The table actually holds three rows and two, which is the
        ordinary state of a registered table somebody keeps writing to.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _registered_dataset(
            test_db_session, created_by=admin_id, rows=3, stored_feature_count=2
        )
        table = dataset.table_name
        await test_db_session.execute(
            text(f"ALTER TABLE data.{table} ADD COLUMN owner text")  # noqa: S608
        )
        await test_db_session.commit()

        payload = await _dispatch(client, admin_auth_header, dataset.id)
        await _execute(test_db_session, payload)

        refreshed = await _reload(test_db_session, dataset.id)
        assert refreshed.feature_count == 3
        assert [c["name"] for c in refreshed.column_info] == ["name", "owner"]
        assert refreshed.geometry_type == "POLYGON"
        assert refreshed.srid == 4326
        assert refreshed.sample_values is not None
        assert refreshed.quality_detail is not None
        assert refreshed.last_refreshed_at is not None
        assert refreshed.last_checked_at is not None
        # The strategy is the only observer this origin kind gets, so a
        # successful measurement is what clears a stale verdict.
        assert refreshed.source_health == "healthy"
        assert refreshed.source_health_detail is None
        # #1223, live-vs-recorded: there is no staging copy to diff against,
        # so the comparison is the table as it is now against what the
        # catalog last wrote down. Recorded, never refused.
        assert refreshed.schema_drift_status == "drifted"

        extent = await test_db_session.scalar(
            text(
                "SELECT ST_AsText(spatial_extent) FROM catalog.records WHERE id = :rid"
            ),
            {"rid": refreshed.record_id},
        )
        assert extent is not None and extent.startswith("POLYGON")

        run = await _run_for(test_db_session, dataset.id)
        assert run is not None
        assert run.status == "succeeded"
        assert (run.feature_count_before, run.feature_count_after) == (2, 3)
        assert [c["name"] for c in run.schema_diff["columns_added"]] == ["owner"]
        # No data moved, so there is no new version of it to point at.
        assert run.dataset_version_id is None
        assert run.claimed_at is not None and run.finished_at is not None

        job = await _job_for(test_db_session, uuid.UUID(payload["job_id"]))
        assert job.status == "complete"

    async def test_the_measurement_runs_under_one_read_only_snapshot(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """fix(#1313 review): one transaction is not one state by default.

        The session's default isolation is READ COMMITTED, where every
        statement takes its own snapshot — so the count, the extent, the
        samples and the validity score could each describe a different
        instant of a table somebody else is writing to, and the catalog would
        store a combination that never existed. READ ONLY is asserted too: it
        is what keeps a future write from being added to a phase holding a
        snapshot it must not hold, and it is why the job and run finalization
        live in a separate transaction (the heartbeat renews the same job row
        throughout, and would collide).
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _registered_dataset(test_db_session, created_by=admin_id)
        payload = await _dispatch(client, admin_auth_header, dataset.id)

        seen: dict[str, str] = {}
        real_extract = tasks_postgis_refresh_metadata.extract_metadata

        async def _record_isolation(session, table_name, **kwargs):
            row = (
                await session.execute(
                    text(
                        "SELECT current_setting('transaction_isolation'), "
                        "current_setting('transaction_read_only')"
                    )
                )
            ).one()
            seen["isolation"], seen["read_only"] = row
            return await real_extract(session, table_name, **kwargs)

        with patch(
            "app.processing.ingest.metadata.extract_metadata", _record_isolation
        ):
            await _execute(test_db_session, payload)

        assert seen == {"isolation": "repeatable read", "read_only": "on"}

        # And the write still landed, from the phase that is allowed to write.
        refreshed = await _reload(test_db_session, dataset.id)
        assert refreshed.last_refreshed_at is not None
        run = await _run_for(test_db_session, dataset.id)
        assert run is not None and run.status == "succeeded"

    async def test_the_snapshot_survives_a_query_at_transaction_begin(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """fix(#1313 review round 4): the multi-tenant shape, in single-tenant.

        ``tenant_session._on_begin`` issues ``SELECT set_config('app.
        current_tenant', ...)`` the instant a multi-tenant transaction starts,
        and PostgreSQL refuses ``SET TRANSACTION`` once any query has run
        (25001). The first version of this phase used that statement, so it
        passed here — where the hook is a hard no-op — and would have failed
        every registered-table refresh on a multi-tenant deployment.

        Rather than flipping tenancy mode (which would also repoint the schema
        at a ``data_t_*`` that does not exist here and fail for an unrelated
        reason), this installs its own begin-time query on the test engine.
        That is the whole of the hostile condition, and ``SELECT 1`` is enough
        to reproduce it: PostgreSQL's refusal is triggered by a query having
        run, not by which query it was. Standing in with a real
        ``set_config('app.current_tenant', ...)`` would additionally arm the
        tenant stamping triggers and fail this test on unrelated writes.
        """
        from sqlalchemy import event

        import app.core.db as db_module

        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _registered_dataset(test_db_session, created_by=admin_id)
        payload = await _dispatch(client, admin_auth_header, dataset.id)

        seen: dict[str, str] = {}
        real_extract = tasks_postgis_refresh_metadata.extract_metadata

        async def _record_isolation(session, table_name, **kwargs):
            row = (
                await session.execute(
                    text(
                        "SELECT current_setting('transaction_isolation'), "
                        "current_setting('transaction_read_only')"
                    )
                )
            ).one()
            seen["isolation"], seen["read_only"] = row
            return await real_extract(session, table_name, **kwargs)

        def _query_on_begin(conn) -> None:
            conn.execute(text("SELECT 1"))

        engine = db_module.async_session.kw["bind"]
        event.listen(engine.sync_engine, "begin", _query_on_begin)
        try:
            with patch(
                "app.processing.ingest.metadata.extract_metadata", _record_isolation
            ):
                await _execute(test_db_session, payload)
        finally:
            event.remove(engine.sync_engine, "begin", _query_on_begin)

        assert seen == {"isolation": "repeatable read", "read_only": "on"}
        run = await _run_for(test_db_session, dataset.id)
        assert run is not None and run.status == "succeeded"

    async def test_tiles_are_purged_even_when_the_count_is_unchanged(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """fix(#1313 review): the count is not a proxy for "the tiles are fine".

        Editing geometry, rewriting attributes, or deleting and reinserting
        the same number of rows changes every tile while leaving the total
        identical — and the MVT cache key has no content-version dimension,
        so gating the purge on a changed count made the common case the one
        that kept serving stale bytes until expiry.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _registered_dataset(
            test_db_session, created_by=admin_id, rows=2, stored_feature_count=2
        )
        # Same row count, different geometry — the shape a tile cache cares
        # about and a recount cannot see.
        await test_db_session.execute(
            text(  # noqa: S608
                f"UPDATE data.{dataset.table_name} SET "
                f"geom = ST_GeomFromText('{_FAR_SQUARE}', 4326), "
                f"geom_4326 = ST_GeomFromText('{_FAR_SQUARE}', 4326)"
            )
        )
        await test_db_session.commit()
        before_version = (await _reload(test_db_session, dataset.id)).tile_cache_version

        payload = await _dispatch(client, admin_auth_header, dataset.id)
        purge = AsyncMock()
        with patch.object(
            tasks_postgis_refresh, "invalidate_tile_cache_for_table", purge
        ):
            await _execute(test_db_session, payload)

        refreshed = await _reload(test_db_session, dataset.id)
        assert refreshed.feature_count == 2  # unchanged, which is the point
        purge.assert_awaited_once_with(dataset.table_name)
        # fix(#1313 review round 3): and the half the purge cannot do. The
        # Valkey purge clears the server cache; `_v=` in the tile URL is the
        # only thing that reaches a browser or a CDN.
        assert (refreshed.tile_cache_version or 1) > (before_version or 1)

    async def test_a_matching_table_records_no_drift(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """The other half of the drift assertion above.

        Without this, "drifted" could be what the code always writes and the
        first test would still pass.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _registered_dataset(
            test_db_session, created_by=admin_id, rows=2, stored_feature_count=2
        )

        payload = await _dispatch(client, admin_auth_header, dataset.id)
        await _execute(test_db_session, payload)

        refreshed = await _reload(test_db_session, dataset.id)
        assert refreshed.schema_drift_status == "none"

    async def test_a_dropped_table_fails_the_run_and_keeps_the_old_metadata(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """Invariant 10 for a strategy whose data GeoLens does not own.

        Nothing on this path writes ``last_refreshed_at`` except the success
        block, so the dataset keeps describing the last measurement that
        actually happened. Blanking the metadata instead would destroy the
        only record of what the table held, at the exact moment the table is
        gone.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _registered_dataset(
            test_db_session, created_by=admin_id, rows=2, stored_feature_count=2
        )
        before = await _reload(test_db_session, dataset.id)
        stored_columns = before.column_info
        stored_count = before.feature_count
        assert before.last_refreshed_at is None

        payload = await _dispatch(client, admin_auth_header, dataset.id)
        await test_db_session.execute(
            text(f"DROP TABLE data.{dataset.table_name}")  # noqa: S608
        )
        await test_db_session.commit()

        with pytest.raises(tasks_postgis_refresh.PostgisRefreshError):
            await _execute(test_db_session, payload)

        after = await _reload(test_db_session, dataset.id)
        assert after.source_health == "missing"
        assert after.source_health_detail == "not_found"
        assert after.last_checked_at is not None
        assert after.last_refreshed_at is None
        assert after.feature_count == stored_count
        assert after.column_info == stored_columns

        run = await _run_for(test_db_session, dataset.id)
        assert run is not None
        assert run.status == "failed"
        assert run.error_code == "source_missing"
        assert run.finished_at is not None
        assert "no longer exists" in run.error_message

        job = await _job_for(test_db_session, uuid.UUID(payload["job_id"]))
        assert job.status == "failed"

    async def test_a_renamed_table_reads_as_missing(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """A rename is a drop as far as the binding is concerned.

        Worth its own case because ``to_regclass`` answers for a NAME: the
        relation still exists, and the only thing that stopped existing is
        the one the catalog points at.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _registered_dataset(test_db_session, created_by=admin_id)
        payload = await _dispatch(client, admin_auth_header, dataset.id)
        await test_db_session.execute(
            text(  # noqa: S608
                f"ALTER TABLE data.{dataset.table_name} "
                f"RENAME TO {dataset.table_name}_moved"
            )
        )
        await test_db_session.commit()

        with pytest.raises(tasks_postgis_refresh.PostgisRefreshError):
            await _execute(test_db_session, payload)

        after = await _reload(test_db_session, dataset.id)
        assert after.source_health == "missing"

    async def test_a_permission_failure_records_inaccessible(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """Revoked access is not a gone table, and the SQLSTATE says so.

        Injected rather than staged with a real REVOKE: the test session
        connects as the owner, and a role swap inside one transaction would
        be testing the fixture. What has to hold is that the verdict is read
        off the driver at the point the read failed, which is what the patch
        exercises.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _registered_dataset(test_db_session, created_by=admin_id)
        payload = await _dispatch(client, admin_auth_header, dataset.id)

        with patch(
            "app.processing.ingest.metadata.extract_metadata",
            AsyncMock(side_effect=_pg_error("42501")),
        ):
            with pytest.raises(tasks_postgis_refresh.PostgisRefreshError):
                await _execute(test_db_session, payload)

        after = await _reload(test_db_session, dataset.id)
        assert after.source_health == "inaccessible"
        assert after.source_health_detail == "unauthorized"
        assert after.last_refreshed_at is None

        run = await _run_for(test_db_session, dataset.id)
        assert run is not None
        assert run.status == "failed"
        assert run.error_code == "source_inaccessible"

    async def test_an_inconclusive_failure_writes_no_health_verdict(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """A timeout leaves the stored verdict alone.

        ``source_health`` is sticky for this origin kind — the probe refuses
        postgis, so nothing else will ever correct it — which makes writing
        one from a failure that established nothing worse than writing none.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _registered_dataset(test_db_session, created_by=admin_id)
        payload = await _dispatch(client, admin_auth_header, dataset.id)

        with patch(
            "app.processing.ingest.metadata.extract_metadata",
            AsyncMock(side_effect=_pg_error("57014")),
        ):
            with pytest.raises(tasks_postgis_refresh.PostgisRefreshError):
                await _execute(test_db_session, payload)

        after = await _reload(test_db_session, dataset.id)
        assert after.source_health is None
        assert after.last_checked_at is None

        run = await _run_for(test_db_session, dataset.id)
        assert run is not None
        assert (run.status, run.error_code) == ("failed", "postgis_refresh_failed")

    async def test_a_binding_naming_another_table_stops_the_refresh(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """``origin_ref`` names the table; it does not get to steer the read.

        A JSONB value dropped into a query is one bad row away from
        measuring somebody else's relation and writing the result onto this
        dataset. The pointer has to agree with the table the dataset serves
        from, and disagreement stops the refresh rather than picking a
        winner.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _registered_dataset(
            test_db_session, created_by=admin_id, rows=2, stored_feature_count=2
        )
        other = await _registered_dataset(
            test_db_session, created_by=admin_id, rows=7, stored_feature_count=7
        )
        dataset.origin_ref = {
            "kind": "postgis",
            "table_name": f"data.{other.table_name}",
        }
        await test_db_session.commit()

        payload = await _dispatch(client, admin_auth_header, dataset.id)
        with pytest.raises(tasks_postgis_refresh.PostgisRefreshError):
            await _execute(test_db_session, payload)

        after = await _reload(test_db_session, dataset.id)
        # Neither measured nor judged: the attempt never reached a relation.
        assert after.feature_count == 2
        assert after.source_health is None
        assert after.last_refreshed_at is None

        run = await _run_for(test_db_session, dataset.id)
        assert run is not None
        assert (run.status, run.error_code) == ("failed", "postgis_refresh_failed")

    async def test_an_emptied_table_clears_the_stored_extent(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """Where this parts from the swap path, deliberately.

        ``_apply_reupload_swap`` only ever writes a non-NULL extent, so an
        emptied source leaves the old footprint in place. That is tolerable
        for a path installing bytes it fetched; it is not tolerable for the
        one operation whose entire job is making the stored metadata agree
        with the live table, because the footprint is what spatial search
        matches on.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _registered_dataset(test_db_session, created_by=admin_id)
        await test_db_session.execute(
            text(
                "UPDATE catalog.records SET spatial_extent = "
                "ST_GeomFromText(:wkt, 4326) WHERE id = :rid"
            ),
            {"wkt": _FAR_SQUARE, "rid": dataset.record_id},
        )
        await test_db_session.execute(
            text(f"DELETE FROM data.{dataset.table_name}")  # noqa: S608
        )
        await test_db_session.commit()

        payload = await _dispatch(client, admin_auth_header, dataset.id)
        await _execute(test_db_session, payload)

        refreshed = await _reload(test_db_session, dataset.id)
        assert refreshed.feature_count == 0
        extent = await test_db_session.scalar(
            text("SELECT spatial_extent FROM catalog.records WHERE id = :rid"),
            {"rid": refreshed.record_id},
        )
        assert extent is None

    async def test_an_emptied_table_keeps_its_geometry_type(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """fix(#1313 review round 5): rows are not the only evidence.

        ``extract_metadata`` derives the geometry type by sampling a row, so
        an emptied spatial table reports None — the same answer a genuinely
        tabular one gives. Writing it reclassified the dataset as
        non-spatial, and ``_require_feature_table`` refuses feature writes to
        a dataset whose ``geometry_type`` is None: a refresh of an emptied
        table would have locked the API out of ever repopulating it, and the
        builder drops its layers as unsupported. The declared column type is
        the evidence the rows cannot supply.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _registered_dataset(test_db_session, created_by=admin_id)
        await test_db_session.execute(
            text(f"DELETE FROM data.{dataset.table_name}")  # noqa: S608
        )
        await test_db_session.commit()

        payload = await _dispatch(client, admin_auth_header, dataset.id)
        await _execute(test_db_session, payload)

        refreshed = await _reload(test_db_session, dataset.id)
        assert refreshed.feature_count == 0
        assert refreshed.geometry_type == "POLYGON"

    async def test_an_emptied_generic_column_keeps_what_was_already_known(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """The branch where neither the rows nor the column say anything.

        A ``geometry`` column with no subtype and no rows establishes only
        that the relation is spatial, so the honest write is no write at all
        — the catalog keeps the type it last measured.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _registered_dataset(test_db_session, created_by=admin_id)
        await test_db_session.execute(
            text(  # noqa: S608
                f"ALTER TABLE data.{dataset.table_name} "
                f"ALTER COLUMN geom TYPE geometry(Geometry, 4326)"
            )
        )
        await test_db_session.execute(
            text(f"DELETE FROM data.{dataset.table_name}")  # noqa: S608
        )
        await test_db_session.commit()

        payload = await _dispatch(client, admin_auth_header, dataset.id)
        await _execute(test_db_session, payload)

        refreshed = await _reload(test_db_session, dataset.id)
        assert refreshed.geometry_type == "POLYGON"  # the stored value, kept

    async def test_an_emptied_generic_column_with_nothing_known_stays_spatial(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """fix(#1382 review r1): the sub-case with no last measurement.

        Same branch as above, minus the stored value to fall back on: a table
        registered while it was empty and generic has never had a type
        measured. Resolving that to None classified a relation with a geometry
        column as tabular and refused the feature writes that would have given
        it a row to measure. The generic sentinel says what is actually known.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _registered_dataset(test_db_session, created_by=admin_id)
        await test_db_session.execute(
            text(  # noqa: S608
                f"ALTER TABLE data.{dataset.table_name} "
                f"ALTER COLUMN geom TYPE geometry(Geometry, 4326)"
            )
        )
        await test_db_session.execute(
            text(f"DELETE FROM data.{dataset.table_name}")  # noqa: S608
        )
        dataset.geometry_type = None
        dataset.record.record_type = "table"
        await test_db_session.commit()

        payload = await _dispatch(client, admin_auth_header, dataset.id)
        await _execute(test_db_session, payload)

        refreshed = await _reload(test_db_session, dataset.id)
        assert refreshed.geometry_type == "GEOMETRY"
        assert refreshed.record.record_type == "vector_dataset"

    async def test_a_table_that_gains_geometry_becomes_a_vector_dataset(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """fix(#1313 review round 6): modality is derived, so keep deriving it.

        ``service_create.py`` sets ``record_type`` from whether the dataset
        has geometry, and this task is the only thing that can change the
        answer afterwards — registering a spatial table while it is empty
        classifies it as ``table``. ``build_assets`` reads ``record_type``
        live, so without this the dataset would go on being presented as
        tabular and would never advertise vector tiles or OGC features.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _registered_dataset(test_db_session, created_by=admin_id)
        dataset.record.record_type = "table"
        dataset.geometry_type = None
        await test_db_session.commit()

        payload = await _dispatch(client, admin_auth_header, dataset.id)
        await _execute(test_db_session, payload)

        refreshed = await _reload(test_db_session, dataset.id)
        assert refreshed.geometry_type == "POLYGON"
        assert refreshed.record.record_type == "vector_dataset"

    async def test_a_dataset_that_loses_geometry_becomes_a_table(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """The inverse, which is the one that advertises what it cannot serve.

        A vector dataset whose geometry columns are dropped keeps offering
        vector tiles and OGC features against a relation that has no geometry
        left to serve.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _registered_dataset(test_db_session, created_by=admin_id)
        assert dataset.record.record_type == "vector_dataset"

        # A first refresh while the table is still spatial, so the synthetic
        # `geom` attribute row exists to be retired. Without it the assertion
        # below passes against a dataset that simply never had one.
        await _execute(
            test_db_session, await _dispatch(client, admin_auth_header, dataset.id)
        )
        assert (
            await test_db_session.scalar(
                text(
                    "SELECT is_current FROM catalog.attribute_metadata "
                    "WHERE dataset_id = :did AND field_name = 'geom'"
                ),
                {"did": dataset.id},
            )
            is True
        )

        await test_db_session.execute(
            text(  # noqa: S608
                f"ALTER TABLE data.{dataset.table_name} "
                f"DROP COLUMN geom, DROP COLUMN geom_4326"
            )
        )
        await test_db_session.commit()

        payload = await _dispatch(client, admin_auth_header, dataset.id)
        await _execute(test_db_session, payload)

        refreshed = await _reload(test_db_session, dataset.id)
        assert refreshed.geometry_type is None
        assert refreshed.record.record_type == "table"

        # fix(#1313 review round 7): refresh_attribute_metadata touches the
        # synthetic `geom` row only when geometry_type is non-null, and
        # excludes it from the removed-column sweep by name — so without an
        # explicit retirement the attributes API would go on advertising a
        # geometry field that no longer exists.
        geom_current = await test_db_session.scalar(
            text(
                "SELECT is_current FROM catalog.attribute_metadata "
                "WHERE dataset_id = :did AND field_name = 'geom'"
            ),
            {"did": refreshed.id},
        )
        assert geom_current is False

    async def test_a_table_that_gains_geometry_advertises_the_spatial_formats(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """fix(#1314): the persisted half of the modality change.

        ``record_type`` is re-derived above, and ``build_assets`` computes its
        links from it live — but ``record_distributions`` rows are generated
        once, at creation, and nothing re-derived them. A table registered
        while it was still empty kept only its CSV and OGC Features rows
        forever, however much geometry it later grew.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _registered_dataset(test_db_session, created_by=admin_id)
        record_id = dataset.record_id
        dataset.record.record_type = "table"
        dataset.geometry_type = None
        await generate_distributions(
            test_db_session,
            dataset.id,
            record_id,
            dataset.table_name,
            geometry_type=None,
        )
        await test_db_session.commit()
        assert await _distribution_pairs(test_db_session, record_id) == {
            ("download", "csv"),
            ("ogc_features", "geojson"),
        }

        await _execute(
            test_db_session, await _dispatch(client, admin_auth_header, dataset.id)
        )

        assert await _distribution_pairs(test_db_session, record_id) == {
            ("download", "gpkg"),
            ("download", "geojson"),
            ("download", "shp"),
            ("download", "parquet"),
            ("download", "csv"),
            ("download", "fgb"),
            ("ogc_features", "geojson"),
            ("vector_tiles", "pbf"),
        }

    async def test_a_dataset_that_loses_geometry_stops_advertising_them(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """The inverse, and the one that offers what the relation cannot serve.

        The user-authored row is here rather than in a test of its own because
        the preservation policy only means anything at the call site: it is
        this refresh that has to leave somebody's hand-written entry alone
        while removing the generated ones beside it.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _registered_dataset(test_db_session, created_by=admin_id)
        record_id = dataset.record_id
        await generate_distributions(
            test_db_session,
            dataset.id,
            record_id,
            dataset.table_name,
            geometry_type="POLYGON",
        )
        mine = await create_distribution(
            test_db_session,
            record_id,
            distribution_type="download",
            format="shp",
            url="https://example.org/mine.zip",
        )
        mine_id = mine.id
        await test_db_session.commit()

        await test_db_session.execute(
            text(  # noqa: S608
                f"ALTER TABLE data.{dataset.table_name} "
                f"DROP COLUMN geom, DROP COLUMN geom_4326"
            )
        )
        await test_db_session.commit()

        await _execute(
            test_db_session, await _dispatch(client, admin_auth_header, dataset.id)
        )

        assert await _distribution_pairs(test_db_session, record_id) == {
            ("download", "csv"),
            ("ogc_features", "geojson"),
            # The user's own Shapefile row, which the demote must not sweep up
            # with the generated one that shared its pair.
            ("download", "shp"),
        }
        assert (
            await test_db_session.scalar(
                select(RecordDistribution.id).where(RecordDistribution.id == mine_id)
            )
            is not None
        )

    async def test_a_refresh_that_keeps_the_modality_leaves_distributions_alone(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """Why the reconcile is gated on the flip rather than run every time.

        It normalizes ``is_primary`` across the generated rows, so calling it
        on every refresh would make an ordinary re-measurement rewrite a field
        the refresh has no opinion about.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _registered_dataset(test_db_session, created_by=admin_id)
        record_id = dataset.record_id
        await generate_distributions(
            test_db_session,
            dataset.id,
            record_id,
            dataset.table_name,
            geometry_type="POLYGON",
        )
        await test_db_session.commit()
        before = await _distribution_ids(test_db_session, record_id)

        await _execute(
            test_db_session, await _dispatch(client, admin_auth_header, dataset.id)
        )

        assert await _distribution_ids(test_db_session, record_id) == before

    async def test_the_quality_score_uses_the_measured_modality(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """fix(#1313 review round 7): the score and the record must agree.

        ``compute_quality_score`` branches on ``record_type`` to choose which
        dimensions apply, and the loaded record still carries the pre-refresh
        modality. A table that has just gained geometry would be scored under
        the tabular branch — geometry and CRS omitted — and that score is then
        persisted beside a ``vector_dataset`` record. The mismatch is stored,
        not transient.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _registered_dataset(test_db_session, created_by=admin_id)
        dataset.record.record_type = "table"
        dataset.geometry_type = None
        await test_db_session.commit()

        payload = await _dispatch(client, admin_auth_header, dataset.id)
        await _execute(test_db_session, payload)

        refreshed = await _reload(test_db_session, dataset.id)
        assert refreshed.record.record_type == "vector_dataset"
        # The tabular branch returns None for both of these; the spatial
        # branch scores them. Their presence IS the assertion that the score
        # was computed under the modality that got stored.
        assert refreshed.quality_detail["geometry_validity"] is not None
        assert refreshed.quality_detail["crs_defined"] is not None

    async def test_a_concurrent_feature_edit_is_not_rolled_back(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """fix(#1313 review round 5): a stale measurement must not win.

        Feature writes are not blocked by the refresh admission index, and
        every one of them recomputes ``feature_count`` and the record extent
        from the live table. A measurement taken before such a write, applied
        after it, rolls the catalog back to a state that is no longer true —
        and leaves it there until the next write.

        The edit is committed from a second session while the measure phase is
        mid-flight, which is the exact interleaving the window allows.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _registered_dataset(
            test_db_session, created_by=admin_id, rows=2, stored_feature_count=2
        )
        dataset_uuid = dataset.id
        payload = await _dispatch(client, admin_auth_header, dataset_uuid)

        real_extract = tasks_postgis_refresh_metadata.extract_metadata

        async def _edit_then_measure(session, table_name, **kwargs):
            import app.core.db as db_module

            async with db_module.async_session() as other:
                await other.execute(
                    text(
                        "UPDATE catalog.datasets SET feature_count = 999, "
                        "tile_cache_version = COALESCE(tile_cache_version, 1) + 1 "
                        "WHERE id = :did"
                    ),
                    {"did": dataset_uuid},
                )
                await other.commit()
            return await real_extract(session, table_name, **kwargs)

        with patch(
            "app.processing.ingest.metadata.extract_metadata", _edit_then_measure
        ):
            with pytest.raises(tasks_postgis_refresh.PostgisRefreshError):
                await _execute(test_db_session, payload)

        after = await _reload(test_db_session, dataset_uuid)
        # The newer value survives; the older measurement was discarded.
        assert after.feature_count == 999
        assert after.last_refreshed_at is None
        assert after.source_health is None

        run = await _run_for(test_db_session, dataset_uuid)
        assert run is not None
        assert (run.status, run.error_code) == ("failed", "superseded")

    async def test_a_finished_run_releases_the_dataset_for_the_next_one(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """The admission index is a reservation, not a lock the worker keeps.

        A refresh that finished has to leave the dataset refreshable, or the
        first successful run would wedge every later one behind the abandoned
        -run sweep.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _registered_dataset(test_db_session, created_by=admin_id)

        first = await _dispatch(client, admin_auth_header, dataset.id)
        await _execute(test_db_session, first)

        second = await _dispatch(client, admin_auth_header, dataset.id)
        assert second["run_id"] != first["run_id"]

        runs = (
            (
                await test_db_session.execute(
                    select(DatasetRefreshRun)
                    .where(DatasetRefreshRun.dataset_id == dataset.id)
                    .order_by(DatasetRefreshRun.started_at)
                )
            )
            .scalars()
            .all()
        )
        assert [r.status for r in runs] == ["succeeded", "pending"]


# ---------------------------------------------------------------------------
# Job-list wording
# ---------------------------------------------------------------------------


async def test_a_failed_refresh_job_is_not_offered_as_a_replayable_import(
    test_db_session,
) -> None:
    """The retry explainer has to describe the thing that failed.

    A refresh job carries neither a file path nor a source URL, so without
    its own branch it fell through to the import copy and told the user
    their source was gone — for a dataset that was never imported from one.
    """
    from app.platform.jobs.router import _retry_capability

    admin_id = await get_user_id(test_db_session, "admin")
    job = IngestJob(
        created_by=admin_id,
        status="failed",
        completed_at=datetime.now(timezone.utc),
        user_metadata={"refresh": True, "origin_kind": "postgis"},
    )
    can_retry, message = await _retry_capability(job)
    assert can_retry is False
    assert "Refresh runs cannot be replayed" in message
