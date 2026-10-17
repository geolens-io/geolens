"""A dataset's row retention: the setting, its checks and the worker run.

The DB-backed tests require the Docker test database.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import NamedTuple

import pytest
import structlog
from httpx import AsyncClient
from sqlalchemy import func, select, text

from app.core.db.tenant_session import current_tenant_var
from app.modules.admin import retention_jobs
from app.modules.audit.models import AuditLog
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.catalog.features import retention
from app.modules.catalog.features import service as features_service
from app.processing.ingest.tasks import task_app
from tests.factories import create_user, get_user_id

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)
CUTOFF = NOW - timedelta(days=30)


class Seeded(NamedTuple):
    id: uuid.UUID
    table_name: str


@pytest.fixture
async def seed(test_db_session):
    """Make point layers whose table has one column of each temporal type."""
    tables: list[str] = []
    records: list[uuid.UUID] = []

    async def _seed(
        *,
        rows: list[dict],
        created_by: uuid.UUID,
        column: str | None = None,
        days: int | None = None,
        visibility: str = "private",
        record_type: str = "vector_dataset",
        geometry_type: str | None = "POINT",
        source_format: str = "geojson",
    ) -> Seeded:
        table = f"test_ret_{uuid.uuid4().hex[:8]}"
        tables.append(table)
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{table} (gid SERIAL PRIMARY KEY, "
                "geom geometry(Geometry, 4326), geom_4326 geometry(Geometry, 4326), "
                "seen_at timestamptz, seen_on date, seen_local timestamp, name text)"
            )
        )
        await test_db_session.execute(
            text(f"GRANT SELECT ON data.{table} TO geolens_reader")
        )
        for row in rows:
            await test_db_session.execute(
                text(
                    f"INSERT INTO data.{table} "
                    "(geom, geom_4326, seen_at, seen_on, seen_local, name) VALUES ("
                    "COALESCE(ST_GeomFromText(:wkt, 4326), "
                    "ST_SetSRID(ST_MakePoint(:x, :y), 4326)), "
                    "COALESCE(ST_GeomFromText(:wkt, 4326), "
                    "ST_SetSRID(ST_MakePoint(:x, :y), 4326)), "
                    ":seen_at, :seen_on, :seen_local, :name)"
                ),
                {
                    "wkt": row.get("wkt"),
                    "x": row.get("x", 10.5),
                    "y": row.get("y", 10.5),
                    "seen_at": row.get("seen_at"),
                    "seen_on": row.get("seen_on"),
                    "seen_local": row.get("seen_local"),
                    "name": row.get("name"),
                },
            )
        record = Record(
            title=f"Retention {table}",
            summary="Fixture layer",
            theme_category=["test"],
            visibility=visibility,
            record_status="published",
            record_type=record_type,
            created_by=created_by,
        )
        test_db_session.add(record)
        await test_db_session.flush()
        records.append(record.id)
        dataset = Dataset(
            record_id=record.id,
            table_name=table,
            srid=4326,
            geometry_type=geometry_type,
            feature_count=0,
            column_info=[
                {"name": "seen_at", "type": "timestamp with time zone"},
                {"name": "seen_on", "type": "date"},
                {"name": "seen_local", "type": "timestamp without time zone"},
                {"name": "name", "type": "text"},
            ],
            source_format=source_format,
            retention_column=column,
            retention_days=days,
        )
        test_db_session.add(dataset)
        await test_db_session.flush()
        await features_service.refresh_dataset_metadata(test_db_session, dataset)
        await test_db_session.commit()
        return Seeded(dataset.id, table)

    yield _seed

    for record_id in records:
        await test_db_session.execute(
            text("DELETE FROM catalog.records WHERE id = :id"), {"id": record_id}
        )
    for table in tables:
        await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{table}"))
    await test_db_session.commit()


async def _names(session, dataset: Seeded) -> set[str]:
    rows = await session.execute(text(f"SELECT name FROM data.{dataset.table_name}"))
    return {row.name for row in rows}


async def _catalog_state(session, dataset_id: uuid.UUID):
    session.expire_all()
    return (
        await session.execute(
            select(
                Dataset.feature_count,
                Dataset.tile_cache_version,
                Dataset.data_revision,
                func.ST_XMin(Record.spatial_extent),
                func.ST_XMax(Record.spatial_extent),
            )
            .join(Record, Record.id == Dataset.record_id)
            .where(Dataset.id == dataset_id)
        )
    ).one()


async def _settle_pending(session, dataset_id: uuid.UUID) -> bool:
    session.expire_all()
    return await session.scalar(
        select(Dataset.retention_settle_pending).where(Dataset.id == dataset_id)
    )


async def _prune_audits(session, dataset_id: uuid.UUID) -> list[AuditLog]:
    session.expire_all()
    return list(
        await session.scalars(
            select(AuditLog)
            .where(
                AuditLog.action == "dataset.retention_prune",
                AuditLog.resource_id == dataset_id,
            )
            .order_by(AuditLog.created_at)
        )
    )


class TestRun:
    async def test_a_timestamptz_layer_loses_only_rows_strictly_older(
        self, seed, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await seed(
            created_by=admin_id,
            column="seen_at",
            days=30,
            rows=[
                # The only row at x=0, so removing it shrinks the extent.
                {"name": "old", "seen_at": CUTOFF - timedelta(seconds=1), "x": 0},
                {"name": "at", "seen_at": CUTOFF},
                {"name": "new", "seen_at": CUTOFF + timedelta(seconds=1), "x": 11},
                {"name": "undated", "seen_at": None},
            ],
        )
        before = await _catalog_state(test_db_session, dataset.id)

        pruned = await retention.prune_expired_rows(now=NOW)

        assert pruned == {dataset.id: 1}
        assert await _names(test_db_session, dataset) == {"at", "new", "undated"}
        after = await _catalog_state(test_db_session, dataset.id)
        assert after.feature_count == 3
        assert (before[3], after[3]) == pytest.approx((0.0, 10.5), abs=1e-6)
        assert after.tile_cache_version == before.tile_cache_version + 1
        assert after.data_revision == before.data_revision + 1
        audits = await _prune_audits(test_db_session, dataset.id)
        assert len(audits) == 1
        assert audits[0].user_id is None
        assert audits[0].details["deleted"] == 1
        assert audits[0].details["column"] == "seen_at"
        assert audits[0].details["retention_days"] == 30

    async def test_a_date_layer_compares_against_the_cutoff_date(
        self, seed, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        cutoff_day = CUTOFF.date()
        dataset = await seed(
            created_by=admin_id,
            column="seen_on",
            days=30,
            rows=[
                {"name": "old", "seen_on": cutoff_day - timedelta(days=1)},
                {"name": "at", "seen_on": cutoff_day},
                {"name": "undated", "seen_on": None},
            ],
        )

        assert await retention.prune_expired_rows(now=NOW) == {dataset.id: 1}
        assert await _names(test_db_session, dataset) == {"at", "undated"}

    async def test_a_timestamp_without_zone_is_read_as_utc(self, seed, test_db_session):
        admin_id = await get_user_id(test_db_session, "admin")
        naive_cutoff = CUTOFF.replace(tzinfo=None)
        dataset = await seed(
            created_by=admin_id,
            column="seen_local",
            days=30,
            rows=[
                {"name": "old", "seen_local": naive_cutoff - timedelta(seconds=1)},
                {"name": "at", "seen_local": naive_cutoff},
            ],
        )

        assert await retention.prune_expired_rows(now=NOW) == {dataset.id: 1}
        assert await _names(test_db_session, dataset) == {"at"}

    async def test_a_layer_without_retention_keeps_everything(
        self, seed, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await seed(
            created_by=admin_id,
            rows=[{"name": "ancient", "seen_at": NOW - timedelta(days=3000)}],
        )
        before = await _catalog_state(test_db_session, dataset.id)

        pruned = await retention.prune_expired_rows(now=NOW)

        assert dataset.id not in pruned
        assert await _names(test_db_session, dataset) == {"ancient"}
        assert await _catalog_state(test_db_session, dataset.id) == before
        assert await _prune_audits(test_db_session, dataset.id) == []

    async def test_a_backlog_is_deleted_in_bounded_batches(
        self, seed, test_db_session, monkeypatch
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        old = NOW - timedelta(days=90)
        dataset = await seed(
            created_by=admin_id,
            column="seen_at",
            days=30,
            rows=[{"name": f"old{i}", "seen_at": old} for i in range(25)]
            + [{"name": "new", "seen_at": NOW}],
        )
        statements: list[int] = []
        real_delete = retention._delete_batch

        async def counted(session, window, after, limit):
            gids = await real_delete(session, window, after, limit)
            statements.append(len(gids))
            return gids

        monkeypatch.setattr(retention, "_delete_batch", counted)
        before = await _catalog_state(test_db_session, dataset.id)

        pruned = await retention.prune_expired_rows(now=NOW, batch_rows=10)

        assert pruned == {dataset.id: 25}
        assert statements == [10, 10, 5]
        assert await _names(test_db_session, dataset) == {"new"}
        audits = await _prune_audits(test_db_session, dataset.id)
        assert [audit.details["deleted"] for audit in audits] == [10, 10, 5]
        after = await _catalog_state(test_db_session, dataset.id)
        assert after.feature_count == 1
        assert after.tile_cache_version == before.tile_cache_version + 3
        assert after.data_revision == before.data_revision + 3

    async def test_a_worker_lost_mid_run_leaves_each_committed_batch_settled(
        self, seed, test_db_session, monkeypatch
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        old = NOW - timedelta(days=90)
        dataset = await seed(
            created_by=admin_id,
            column="seen_at",
            days=30,
            rows=[{"name": f"old{i}", "seen_at": old} for i in range(25)],
        )
        real_delete = retention._delete_batch
        calls = 0

        async def second_batch_fails(session, window, after, limit):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("worker lost")
            return await real_delete(session, window, after, limit)

        async def never_settles(*_args):
            raise RuntimeError("worker lost")

        monkeypatch.setattr(retention, "_delete_batch", second_batch_fails)
        monkeypatch.setattr(retention, "_settle", never_settles)
        before = await _catalog_state(test_db_session, dataset.id)

        assert dataset.id not in await retention.prune_expired_rows(
            now=NOW, batch_rows=10
        )

        assert len(await _names(test_db_session, dataset)) == 15
        after = await _catalog_state(test_db_session, dataset.id)
        assert after.feature_count == 15
        assert after.tile_cache_version == before.tile_cache_version + 1
        assert after.data_revision == before.data_revision + 1
        audits = await _prune_audits(test_db_session, dataset.id)
        assert [audit.details["deleted"] for audit in audits] == [10]
        assert audits[0].details["cutoff"] == CUTOFF.isoformat()

    async def test_a_batch_whose_audit_row_fails_deletes_nothing(
        self, seed, test_db_session, monkeypatch
    ):
        from app.modules.audit import service as audit_service

        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await seed(
            created_by=admin_id,
            column="seen_at",
            days=30,
            rows=[{"name": "old", "seen_at": NOW - timedelta(days=90)}],
        )

        async def insert_fails(*_args, **_kwargs):
            raise RuntimeError("audit store down")

        monkeypatch.setattr(audit_service, "log_action", insert_fails)

        assert dataset.id not in await retention.prune_expired_rows(now=NOW)
        assert await _names(test_db_session, dataset) == {"old"}

    @pytest.mark.parametrize(
        "cleared_before_next_run", [False, True], ids=["kept", "cleared"]
    )
    async def test_the_next_run_repairs_what_a_lost_settle_left_behind(
        self,
        client: AsyncClient,
        admin_auth_header,
        seed,
        test_db_session,
        monkeypatch,
        cleared_before_next_run,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await seed(
            created_by=admin_id,
            column="seen_at",
            days=30,
            geometry_type="GEOMETRY",
            source_format="created",
            rows=[
                {"name": "old", "seen_at": NOW - timedelta(days=90), "x": 0, "y": 0},
                {
                    "name": "new",
                    "seen_at": NOW,
                    "wkt": "POLYGON((10 10, 11 10, 11 11, 10 11, 10 10))",
                },
            ],
        )

        async def geometry_and_west_edge():
            test_db_session.expire_all()
            return tuple(
                (
                    await test_db_session.execute(
                        select(
                            Dataset.geometry_type, func.ST_XMin(Record.spatial_extent)
                        )
                        .join(Record, Record.id == Dataset.record_id)
                        .where(Dataset.id == dataset.id)
                    )
                ).one()
            )

        assert await geometry_and_west_edge() == ("GEOMETRY", 0.0)
        real_settle = retention._settle

        async def worker_lost(*_args):
            raise RuntimeError("worker lost")

        monkeypatch.setattr(retention, "_settle", worker_lost)
        await retention.prune_expired_rows(now=NOW)
        assert await _names(test_db_session, dataset) == {"new"}
        assert await geometry_and_west_edge() == ("GEOMETRY", 0.0)
        assert await _settle_pending(test_db_session, dataset.id) is True

        if cleared_before_next_run:
            resp = await client.put(
                f"/datasets/{dataset.id}/retention/",
                json={"retention": None},
                headers=admin_auth_header,
            )
            assert resp.status_code == 200, resp.text
        monkeypatch.setattr(retention, "_settle", real_settle)
        assert await retention.prune_expired_rows(now=NOW) == {}

        assert await geometry_and_west_edge() == ("POLYGON", 10.0)
        assert (await _catalog_state(test_db_session, dataset.id)).feature_count == 1
        assert await _settle_pending(test_db_session, dataset.id) is False

    @pytest.mark.parametrize("cleared", [False, True], ids=["kept", "cleared"])
    async def test_a_pending_settle_on_a_dataset_turned_non_spatial_clears(
        self, client: AsyncClient, admin_auth_header, seed, test_db_session, cleared
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await seed(
            created_by=admin_id,
            column="seen_at",
            days=30,
            rows=[{"name": "recent", "seen_at": NOW}],
        )
        await test_db_session.execute(
            text(
                "UPDATE catalog.datasets SET retention_settle_pending = true "
                "WHERE id = :id"
            ),
            {"id": dataset.id},
        )
        await test_db_session.commit()
        await _make_non_spatial(dataset, swap=False)
        if cleared:
            resp = await client.put(
                f"/datasets/{dataset.id}/retention/",
                json={"retention": None},
                headers=admin_auth_header,
            )
            assert resp.status_code == 200, resp.text

        with structlog.testing.capture_logs() as first:
            assert await retention.prune_expired_rows(now=NOW) == {}
        assert await _settle_pending(test_db_session, dataset.id) is False
        with structlog.testing.capture_logs() as second:
            assert await retention.prune_expired_rows(now=NOW) == {}

        for logs in (first, second):
            assert not [e for e in logs if e["event"] == "dataset_retention_failed"]
        assert await _names(test_db_session, dataset) == {"recent"}

    async def test_an_idle_run_leaves_the_catalog_rows_alone(
        self, seed, test_db_session, monkeypatch
    ):
        import app.core.db as db_module
        from app.platform import catalog_locks

        # A refresh would wait this long on the held row, then fail the dataset.
        monkeypatch.setattr(catalog_locks, "REQUEST_LOCK_TIMEOUT", "100ms")
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await seed(
            created_by=admin_id,
            column="seen_at",
            days=30,
            rows=[{"name": "new", "seen_at": NOW}],
        )
        before = await _catalog_state(test_db_session, dataset.id)

        async with db_module.async_session() as holder:
            await holder.execute(
                select(Dataset.id).where(Dataset.id == dataset.id).with_for_update()
            )
            with structlog.testing.capture_logs() as logs:
                assert await retention.prune_expired_rows(now=NOW) == {}
            await holder.rollback()

        assert not [e for e in logs if e["event"] == "dataset_retention_failed"]
        assert await _catalog_state(test_db_session, dataset.id) == before

    async def test_a_batch_planned_as_a_nested_loop_still_stops_at_its_limit(
        self, seed, test_db_session
    ):
        """Stale statistics and a nested-loop plan must not widen a batch."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await seed(created_by=admin_id, column="seen_at", days=30, rows=[])
        session = test_db_session
        await session.execute(text(f"ANALYZE data.{dataset.table_name}"))
        await session.execute(
            text(
                f"INSERT INTO data.{dataset.table_name} (geom, geom_4326, seen_at, name) "
                "SELECT ST_SetSRID(ST_MakePoint(10.5, 10.5), 4326), "
                "ST_SetSRID(ST_MakePoint(10.5, 10.5), 4326), "
                "CAST(:old AS timestamptz), 'old' || n FROM generate_series(1, 25) AS n"
            ),
            {"old": NOW - timedelta(days=90)},
        )
        for flag in ("hashjoin", "mergejoin", "hashagg", "material", "sort"):
            await session.execute(text(f"SET LOCAL enable_{flag} = off"))

        _, window = await retention._window(session, dataset.id, NOW)
        try:
            gids = await retention._delete_batch(
                session, window, retention._GID_FLOOR, 10
            )
            left = await session.scalar(
                text(f"SELECT count(*) FROM data.{dataset.table_name}")
            )
        finally:
            await session.rollback()

        assert len(gids) == 10
        assert left == 15

    async def _layer_losing_its_last_geometry(self, seed, test_db_session):
        """An old placed row and a recent row with no geometry."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await seed(
            created_by=admin_id,
            column="seen_at",
            days=30,
            rows=[
                {"name": "old", "seen_at": NOW - timedelta(days=90), "x": 0, "y": 0},
                {"name": "unplaced", "seen_at": NOW},
            ],
        )
        await test_db_session.execute(
            text(
                f"UPDATE data.{dataset.table_name} SET geom = NULL, "
                "geom_4326 = NULL WHERE name = 'unplaced'"
            )
        )
        await test_db_session.commit()
        return dataset

    async def _extent_is_null(self, test_db_session, dataset) -> bool:
        test_db_session.expire_all()
        return await test_db_session.scalar(
            select(Record.spatial_extent.is_(None))
            .join(Dataset, Dataset.record_id == Record.id)
            .where(Dataset.id == dataset.id)
        )

    async def test_each_pruning_run_advances_the_record_modified_time(
        self, seed, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await seed(
            created_by=admin_id,
            column="seen_at",
            days=30,
            rows=[
                {"name": "old", "seen_at": NOW - timedelta(days=90), "x": 0, "y": 0},
                {"name": "unplaced", "seen_at": NOW - timedelta(days=20)},
            ],
        )
        await test_db_session.execute(
            text(
                f"UPDATE data.{dataset.table_name} SET geom = NULL, "
                "geom_4326 = NULL WHERE name = 'unplaced'"
            )
        )
        await test_db_session.commit()

        async def modified():
            test_db_session.expire_all()
            return await test_db_session.scalar(
                select(Record.updated_at)
                .join(Dataset, Dataset.record_id == Record.id)
                .where(Dataset.id == dataset.id)
            )

        seeded = await modified()
        assert await retention.prune_expired_rows(now=NOW) == {dataset.id: 1}
        after_first = await modified()
        assert await self._extent_is_null(test_db_session, dataset) is True

        later = NOW + timedelta(days=15)
        assert await retention.prune_expired_rows(now=later) == {dataset.id: 1}
        after_second = await modified()

        assert seeded < after_first < after_second
        assert await _names(test_db_session, dataset) == set()

    async def test_a_pruning_run_is_not_credited_to_the_last_editor(
        self, client: AsyncClient, admin_auth_header, seed, test_db_session
    ):
        from app.modules.catalog.sources.provenance import SYSTEM_ACTOR_LABEL

        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await seed(
            created_by=admin_id,
            column="seen_at",
            days=30,
            rows=[{"name": "old", "seen_at": NOW - timedelta(days=90)}],
        )
        await test_db_session.execute(
            text(
                "UPDATE catalog.records SET updated_by = :user WHERE id = "
                "(SELECT record_id FROM catalog.datasets WHERE id = :id)"
            ),
            {"user": admin_id, "id": dataset.id},
        )
        await test_db_session.commit()

        assert await retention.prune_expired_rows(now=NOW) == {dataset.id: 1}

        detail = await client.get(f"/datasets/{dataset.id}", headers=admin_auth_header)
        assert detail.status_code == 200, detail.text
        assert detail.json()["updated_by"] is None
        assert detail.json()["last_edited_by_display"] == SYSTEM_ACTOR_LABEL

    async def test_pruning_the_last_geometry_clears_the_extent(
        self, seed, test_db_session
    ):
        dataset = await self._layer_losing_its_last_geometry(seed, test_db_session)
        assert await self._extent_is_null(test_db_session, dataset) is False

        assert await retention.prune_expired_rows(now=NOW) == {dataset.id: 1}

        assert await _names(test_db_session, dataset) == {"unplaced"}
        assert await self._extent_is_null(test_db_session, dataset) is True
        assert (await _catalog_state(test_db_session, dataset.id)).feature_count == 1

    async def test_a_lost_settle_that_left_no_geometry_clears_the_extent_next_run(
        self, seed, test_db_session, monkeypatch
    ):
        dataset = await self._layer_losing_its_last_geometry(seed, test_db_session)
        real_settle = retention._settle

        async def worker_lost(*_args):
            raise RuntimeError("worker lost")

        monkeypatch.setattr(retention, "_settle", worker_lost)
        await retention.prune_expired_rows(now=NOW)
        assert await self._extent_is_null(test_db_session, dataset) is False

        monkeypatch.setattr(retention, "_settle", real_settle)
        assert await retention.prune_expired_rows(now=NOW) == {}

        assert await self._extent_is_null(test_db_session, dataset) is True
        assert await _settle_pending(test_db_session, dataset.id) is False

    async def _registered_table_without_a_gid_key(self, seed, test_db_session, rows):
        """A table edited outside GeoLens: no key on gid, rows given explicit gids."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await seed(created_by=admin_id, column="seen_at", days=30, rows=[])
        table = dataset.table_name
        await test_db_session.execute(
            text(f"ALTER TABLE data.{table} DROP CONSTRAINT {table}_pkey")
        )
        for gid, name, seen_at in rows:
            await self._insert_with_gid(test_db_session, table, gid, name, seen_at)
        await test_db_session.commit()
        return dataset

    @staticmethod
    async def _insert_with_gid(session, table, gid, name, seen_at):
        await session.execute(
            text(
                f"INSERT INTO data.{table} (gid, geom, geom_4326, seen_at, name) "
                "VALUES (:gid, ST_SetSRID(ST_MakePoint(10.5, 10.5), 4326), "
                "ST_SetSRID(ST_MakePoint(10.5, 10.5), 4326), :seen_at, :name)"
            ),
            {"gid": gid, "name": name, "seen_at": seen_at},
        )

    async def test_a_shared_gid_deletes_only_the_expired_row(
        self, seed, test_db_session
    ):
        old = NOW - timedelta(days=90)
        dataset = await self._registered_table_without_a_gid_key(
            seed,
            test_db_session,
            [
                (1, "old_1", old),
                (1, "recent_1", NOW),
                (2, "old_2", old),
                (2, "undated_2", None),
            ],
        )

        assert await retention.prune_expired_rows(now=NOW) == {dataset.id: 2}

        assert await _names(test_db_session, dataset) == {"recent_1", "undated_2"}
        audits = await _prune_audits(test_db_session, dataset.id)
        assert [audit.details["deleted"] for audit in audits] == [2]
        assert (await _catalog_state(test_db_session, dataset.id)).feature_count == 2

    async def test_rows_without_a_gid_are_pruned_too(
        self, seed, test_db_session, monkeypatch
    ):
        old = NOW - timedelta(days=90)
        dataset = await self._registered_table_without_a_gid_key(
            seed, test_db_session, []
        )
        table = dataset.table_name
        await test_db_session.execute(
            text(f"ALTER TABLE data.{table} ALTER COLUMN gid DROP NOT NULL")
        )
        for gid, name, seen_at in (
            (None, "old_a", old),
            (None, "old_b", old),
            (None, "recent_null", NOW),
            (5, "old_5", old),
            (6, "recent_6", NOW),
        ):
            await self._insert_with_gid(test_db_session, table, gid, name, seen_at)
        await test_db_session.commit()
        statements: list[int] = []
        real_delete = retention._delete_batch

        async def counted(session, window, after, limit):
            gids = await real_delete(session, window, after, limit)
            statements.append(len(gids))
            return gids

        monkeypatch.setattr(retention, "_delete_batch", counted)

        assert await retention.prune_expired_rows(now=NOW, batch_rows=2) == {
            dataset.id: 3
        }

        assert statements == [2, 1]
        assert await _names(test_db_session, dataset) == {"recent_null", "recent_6"}

    async def test_a_batch_of_shared_gids_stays_within_its_limit(
        self, seed, test_db_session, monkeypatch
    ):
        old = NOW - timedelta(days=90)
        dataset = await self._registered_table_without_a_gid_key(
            seed,
            test_db_session,
            [(gid, f"old_{gid}_{copy}", old) for gid in range(1, 7) for copy in "ab"],
        )
        statements: list[int] = []
        real_delete = retention._delete_batch

        async def counted(session, window, after, limit):
            gids = await real_delete(session, window, after, limit)
            statements.append(len(gids))
            return gids

        monkeypatch.setattr(retention, "_delete_batch", counted)

        pruned = await retention.prune_expired_rows(now=NOW, batch_rows=5)

        assert statements == [5, 5, 2]
        assert pruned == {dataset.id: 12}
        assert await _names(test_db_session, dataset) == set()

    async def test_column_info_reports_a_domain_column_by_its_base_type(
        self, seed, test_db_session
    ):
        """The card offers columns by their column_info type; a domain's is its base."""
        from app.platform.extensions import get_catalog_port

        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await seed(created_by=admin_id, rows=[])
        domain = f"data.ret_{uuid.uuid4().hex[:8]}"
        await test_db_session.execute(text(f"CREATE DOMAIN {domain} AS timestamptz"))
        await test_db_session.execute(
            text(
                f"ALTER TABLE data.{dataset.table_name} "
                f"ALTER COLUMN seen_at TYPE {domain}"
            )
        )
        await test_db_session.commit()
        try:
            columns = await get_catalog_port().get_column_info(
                test_db_session, dataset.table_name
            )
            types = {column["name"]: column["type"] for column in columns}
            assert types["seen_at"] == "timestamp with time zone"
        finally:
            await test_db_session.execute(text(f"DROP DOMAIN {domain} CASCADE"))
            await test_db_session.commit()

    async def test_a_column_typed_by_a_domain_is_pruned_by_its_base_type(
        self, seed, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await seed(
            created_by=admin_id,
            column="seen_at",
            days=30,
            rows=[
                {"name": "old", "seen_at": CUTOFF - timedelta(seconds=1)},
                {"name": "at", "seen_at": CUTOFF},
                {"name": "undated", "seen_at": None},
            ],
        )
        domain = f"data.ret_{uuid.uuid4().hex[:8]}"
        await test_db_session.execute(text(f"CREATE DOMAIN {domain} AS timestamptz"))
        await test_db_session.execute(
            text(
                f"ALTER TABLE data.{dataset.table_name} "
                f"ALTER COLUMN seen_at TYPE {domain}"
            )
        )
        await test_db_session.commit()
        try:
            assert await retention.prune_expired_rows(now=NOW) == {dataset.id: 1}
            assert await _names(test_db_session, dataset) == {"at", "undated"}
        finally:
            await test_db_session.execute(text(f"DROP DOMAIN {domain} CASCADE"))
            await test_db_session.commit()

    async def test_a_run_stops_at_its_batch_bound_and_the_next_run_goes_on(
        self, seed, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        old = NOW - timedelta(days=90)
        dataset = await seed(
            created_by=admin_id,
            column="seen_at",
            days=30,
            rows=[{"name": f"old{i}", "seen_at": old} for i in range(25)],
        )

        first = await retention.prune_expired_rows(
            now=NOW, batch_rows=10, max_batches=2
        )
        second = await retention.prune_expired_rows(
            now=NOW, batch_rows=10, max_batches=2
        )

        assert first[dataset.id] == 20
        assert second[dataset.id] == 5
        assert await _names(test_db_session, dataset) == set()
        assert (await _catalog_state(test_db_session, dataset.id)).feature_count == 0

    async def test_a_dropped_retention_column_skips_the_layer(
        self, seed, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await seed(
            created_by=admin_id,
            column="seen_at",
            days=30,
            rows=[{"name": "old", "seen_at": NOW - timedelta(days=90)}],
        )
        await test_db_session.execute(
            text(f"ALTER TABLE data.{dataset.table_name} DROP COLUMN seen_at")
        )
        await test_db_session.commit()

        assert dataset.id not in await retention.prune_expired_rows(now=NOW)
        assert await _names(test_db_session, dataset) == {"old"}


async def _commit_elsewhere(sql: str, params: dict) -> None:
    """Commit a write in a session of its own, as a concurrent request would."""
    import app.core.db as db_module

    async with db_module.async_session() as other:
        await other.execute(text(sql), params)
        await other.commit()


async def _stored_setting(session, dataset_id: uuid.UUID) -> tuple:
    session.expire_all()
    row = (
        await session.execute(
            select(Dataset.retention_column, Dataset.retention_days).where(
                Dataset.id == dataset_id
            )
        )
    ).one()
    return tuple(row)


_SET_RETENTION = (
    "UPDATE catalog.datasets SET retention_column = :column, "
    "retention_days = :days WHERE id = :id"
)


async def _point_dataset_at_a_view(session, dataset) -> str:
    """Register the dataset against an updatable view over its own table."""
    view = f"{dataset.table_name}_v"
    await session.execute(
        text(
            f"CREATE VIEW data.{view} AS SELECT gid, geom, geom_4326, seen_at, "
            f"seen_on, seen_local, name FROM data.{dataset.table_name}"
        )
    )
    await session.execute(
        text("UPDATE catalog.datasets SET table_name = :view WHERE id = :id"),
        {"view": view, "id": dataset.id},
    )
    await session.commit()
    return view


async def _drop_view(session, view: str) -> None:
    await session.execute(text(f"DROP VIEW IF EXISTS data.{view}"))
    await session.commit()


async def _make_non_spatial(dataset, *, swap: bool) -> None:
    """Turn the dataset non-spatial as a restore (swap) or a PostGIS refresh would."""
    table = dataset.table_name
    if swap:
        await _commit_elsewhere(
            f"ALTER TABLE data.{table} RENAME TO {table}_spatial", {}
        )
        await _commit_elsewhere(
            f"CREATE TABLE data.{table} AS SELECT gid, seen_at, seen_on, "
            f"seen_local, name FROM data.{table}_spatial",
            {},
        )
    else:
        await _commit_elsewhere(
            f"ALTER TABLE data.{table} DROP COLUMN geom, DROP COLUMN geom_4326", {}
        )
    await _commit_elsewhere(
        "UPDATE catalog.datasets SET geometry_type = NULL WHERE id = :id",
        {"id": dataset.id},
    )
    await _commit_elsewhere(
        "UPDATE catalog.records SET record_type = 'table' WHERE id = "
        "(SELECT record_id FROM catalog.datasets WHERE id = :id)",
        {"id": dataset.id},
    )


def _refusal_code(resp) -> str | None:
    detail = resp.json().get("detail")
    return detail.get("code") if isinstance(detail, dict) else None


class TestRace:
    """A run or a save meeting a change another transaction committed first."""

    @pytest.fixture
    def interleave(self, monkeypatch):
        """Run ``action`` after each batch's DELETE, before its catalog lock."""

        def install(action):
            real_delete = retention._delete_batch

            async def delete_then_act(session, window, after, limit):
                gids = await real_delete(session, window, after, limit)
                await action()
                return gids

            monkeypatch.setattr(retention, "_delete_batch", delete_then_act)

        return install

    async def _old_layer(self, seed, test_db_session):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await seed(
            created_by=admin_id,
            column="seen_at",
            days=30,
            rows=[
                {"name": f"old{i}", "seen_at": NOW - timedelta(days=90)}
                for i in range(3)
            ],
        )
        record_id = await test_db_session.scalar(
            select(Dataset.record_id).where(Dataset.id == dataset.id)
        )
        return dataset, record_id, admin_id

    async def _assert_untouched(self, test_db_session, dataset, *dataset_ids):
        assert await _names(test_db_session, dataset) == {"old0", "old1", "old2"}
        for dataset_id in dataset_ids:
            assert await _prune_audits(test_db_session, dataset_id) == []

    @pytest.fixture
    def west_of_utc(self):
        """A host clock behind UTC, where a cutoff of the wrong type moves."""
        import os
        import time

        previous = os.environ.get("TZ")
        os.environ["TZ"] = "America/New_York"
        time.tzset()
        yield
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time.tzset()

    async def test_a_column_retyped_before_the_batch_uses_its_live_type(
        self, seed, test_db_session, monkeypatch, west_of_utc
    ):
        """A naive timestamp retyped to timestamptz after the window was read.

        The window's naive cutoff, bound to the new column, is read in the
        host's zone, which moves it hours later west of UTC.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        naive_cutoff = CUTOFF.replace(tzinfo=None)
        dataset = await seed(
            created_by=admin_id,
            column="seen_local",
            days=30,
            rows=[
                {"name": "older", "seen_local": naive_cutoff - timedelta(hours=1)},
                {
                    "name": "after_cutoff",
                    "seen_local": naive_cutoff + timedelta(hours=1),
                },
            ],
        )
        real_window = retention._window

        async def window_then_retype(session, dataset_id, now):
            due = await real_window(session, dataset_id, now)
            await _commit_elsewhere(
                f"ALTER TABLE data.{dataset.table_name} ALTER COLUMN seen_local "
                "TYPE timestamptz USING seen_local AT TIME ZONE 'UTC'",
                {},
            )
            return due

        monkeypatch.setattr(retention, "_window", window_then_retype)

        assert await retention.prune_expired_rows(now=NOW) == {dataset.id: 1}
        assert await _names(test_db_session, dataset) == {"after_cutoff"}

    async def test_a_column_retyped_to_text_ends_the_pass(
        self, seed, test_db_session, monkeypatch
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await seed(
            created_by=admin_id,
            column="seen_at",
            days=30,
            rows=[{"name": "old", "seen_at": NOW - timedelta(days=90)}],
        )
        real_window = retention._window

        async def window_then_retype(session, dataset_id, now):
            due = await real_window(session, dataset_id, now)
            await _commit_elsewhere(
                f"ALTER TABLE data.{dataset.table_name} ALTER COLUMN seen_at TYPE text",
                {},
            )
            return due

        monkeypatch.setattr(retention, "_window", window_then_retype)

        assert await retention.prune_expired_rows(now=NOW) == {}
        assert await _names(test_db_session, dataset) == {"old"}
        assert await _prune_audits(test_db_session, dataset.id) == []
        assert await _settle_pending(test_db_session, dataset.id) is False

    async def test_a_retype_waits_for_the_batch_holding_the_table(
        self, seed, test_db_session, monkeypatch
    ):
        import app.core.db as db_module
        from sqlalchemy.exc import DBAPIError

        from app.core.db.sqlstate import is_lock_conflict

        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await seed(
            created_by=admin_id,
            column="seen_at",
            days=30,
            rows=[{"name": "old", "seen_at": NOW - timedelta(days=90)}],
        )
        real_delete = retention._delete_batch
        refused: list[bool] = []

        async def retype_attempt_then_delete(session, window, after, limit):
            async with db_module.async_session() as other:
                await other.execute(text("SET LOCAL lock_timeout = '200ms'"))
                try:
                    await other.execute(
                        text(
                            f"ALTER TABLE data.{dataset.table_name} "
                            "ALTER COLUMN seen_at TYPE date"
                        )
                    )
                except DBAPIError as exc:
                    refused.append(is_lock_conflict(exc))
                await other.rollback()
            return await real_delete(session, window, after, limit)

        monkeypatch.setattr(retention, "_delete_batch", retype_attempt_then_delete)

        assert await retention.prune_expired_rows(now=NOW) == {dataset.id: 1}
        assert refused == [True]

    async def test_a_view_backed_setting_deletes_nothing_and_fails_nothing(
        self, seed, test_db_session
    ):
        dataset, _, _ = await self._old_layer(seed, test_db_session)
        view = await _point_dataset_at_a_view(test_db_session, dataset)
        try:
            with structlog.testing.capture_logs() as logs:
                assert await retention.prune_expired_rows(now=NOW) == {}
            events = [entry["event"] for entry in logs]
            assert "dataset_retention_failed" not in events
            assert "dataset_retention_batch_rolled_back" in events
            await self._assert_untouched(test_db_session, dataset, dataset.id)
        finally:
            await _drop_view(test_db_session, view)

    @pytest.mark.parametrize("swap", [True, False], ids=["restore", "postgis-refresh"])
    async def test_a_dataset_turned_non_spatial_before_the_batch_loses_no_rows(
        self, seed, test_db_session, monkeypatch, swap
    ):
        dataset, _, _ = await self._old_layer(seed, test_db_session)
        before = await _catalog_state(test_db_session, dataset.id)
        real_get = retention.get_dataset

        async def load_then_go_non_spatial(session, dataset_id):
            loaded = await real_get(session, dataset_id)
            if loaded is not None and loaded.geometry_type is not None:
                await _make_non_spatial(dataset, swap=swap)
            return loaded

        monkeypatch.setattr(retention, "get_dataset", load_then_go_non_spatial)
        try:
            assert await retention.prune_expired_rows(now=NOW) == {}

            assert await _names(test_db_session, dataset) == {"old0", "old1", "old2"}
            assert await _prune_audits(test_db_session, dataset.id) == []
            after = await test_db_session.scalar(
                select(Dataset.data_revision).where(Dataset.id == dataset.id)
            )
            assert after == before.data_revision
        finally:
            if swap:
                await test_db_session.execute(
                    text(f"DROP TABLE IF EXISTS data.{dataset.table_name}_spatial")
                )
                await test_db_session.commit()

    async def test_a_dataset_detached_before_the_lock_loses_no_rows(
        self, seed, test_db_session, interleave
    ):
        dataset, record_id, _ = await self._old_layer(seed, test_db_session)
        # Single and bulk delete both detach through delete_dataset, which
        # leaves a registered table in place.
        interleave(
            lambda: _commit_elsewhere(
                "DELETE FROM catalog.records WHERE id = :id", {"id": record_id}
            )
        )

        assert await retention.prune_expired_rows(now=NOW) == {}
        await self._assert_untouched(test_db_session, dataset, dataset.id)

    async def test_a_table_registered_again_keeps_its_rows(
        self, seed, test_db_session, interleave
    ):
        dataset, record_id, admin_id = await self._old_layer(seed, test_db_session)
        new_record_id, new_dataset_id = uuid.uuid4(), uuid.uuid4()

        async def detach_and_register_again():
            await _commit_elsewhere(
                "DELETE FROM catalog.records WHERE id = :id", {"id": record_id}
            )
            await _commit_elsewhere(
                "INSERT INTO catalog.records (id, title, visibility, record_status, "
                "record_type, created_by) VALUES (:id, 'Registered again', "
                "'private', 'published', 'vector_dataset', :owner)",
                {"id": new_record_id, "owner": admin_id},
            )
            await _commit_elsewhere(
                "INSERT INTO catalog.datasets (id, record_id, table_name, srid, "
                "geometry_type, feature_count, source_format) VALUES (:id, :record, "
                "CAST(:table AS varchar), 4326, 'POINT', 3, 'geojson')",
                {
                    "id": new_dataset_id,
                    "record": new_record_id,
                    "table": dataset.table_name,
                },
            )

        interleave(detach_and_register_again)
        try:
            assert await retention.prune_expired_rows(now=NOW) == {}
            await self._assert_untouched(
                test_db_session, dataset, dataset.id, new_dataset_id
            )
        finally:
            await test_db_session.execute(
                text("DELETE FROM catalog.records WHERE id = :id"),
                {"id": new_record_id},
            )
            await test_db_session.commit()

    @pytest.mark.parametrize(
        "changed", [("seen_at", 3650), ("seen_on", 30), (None, None)]
    )
    async def test_a_setting_changed_before_the_lock_deletes_nothing(
        self, seed, test_db_session, interleave, changed
    ):
        dataset, _, _ = await self._old_layer(seed, test_db_session)
        column, days = changed
        interleave(
            lambda: _commit_elsewhere(
                _SET_RETENTION, {"id": dataset.id, "column": column, "days": days}
            )
        )

        modified_before = await test_db_session.scalar(
            select(Record.updated_at)
            .join(Dataset, Dataset.record_id == Record.id)
            .where(Dataset.id == dataset.id)
        )

        assert await retention.prune_expired_rows(now=NOW) == {}
        await self._assert_untouched(test_db_session, dataset, dataset.id)
        assert await _settle_pending(test_db_session, dataset.id) is False
        test_db_session.expire_all()
        assert (
            await test_db_session.scalar(
                select(Record.updated_at)
                .join(Dataset, Dataset.record_id == Record.id)
                .where(Dataset.id == dataset.id)
            )
            == modified_before
        )

    @pytest.mark.parametrize(
        ("start", "concurrent", "requested"),
        [
            (("seen_at", 30), ("seen_at", 1), ("seen_on", 30)),
            (("seen_at", 30), ("seen_on", 30), ("seen_at", 7)),
            (("seen_at", 30), ("seen_on", 1), ("seen_at", 30)),
            (("seen_at", 30), (None, None), ("seen_on", 30)),
            ((None, None), ("seen_at", 1), None),
        ],
        ids=["column-only", "days-only", "unchanged", "enable", "clear"],
    )
    async def test_a_save_stores_what_it_asked_for_over_a_concurrent_change(
        self,
        client: AsyncClient,
        admin_auth_header,
        seed,
        test_db_session,
        monkeypatch,
        start,
        concurrent,
        requested,
    ):
        from app.modules.catalog.datasets.api import router_retention

        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await seed(
            created_by=admin_id, column=start[0], days=start[1], rows=[]
        )
        real_lock = router_retention.lock_dataset_rows_for_write

        async def lock_after_a_concurrent_save(db, target, **kwargs):
            await _commit_elsewhere(
                _SET_RETENTION,
                {"id": dataset.id, "column": concurrent[0], "days": concurrent[1]},
            )
            return await real_lock(db, target, **kwargs)

        monkeypatch.setattr(
            router_retention,
            "lock_dataset_rows_for_write",
            lock_after_a_concurrent_save,
        )
        body = {
            "retention": (
                {"column": requested[0], "days": requested[1]} if requested else None
            )
        }

        resp = await client.put(
            f"/datasets/{dataset.id}/retention/", json=body, headers=admin_auth_header
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["retention"] == body["retention"]
        assert await _stored_setting(test_db_session, dataset.id) == (
            requested or (None, None)
        )


_DELETE_ACTIONS = ["CASCADE", "SET NULL", "SET DEFAULT", "RESTRICT", "NO ACTION"]


class TestForeignKeys:
    """A table a foreign key points at never takes retention."""

    async def _family(self, seed, test_db_session):
        """An expired parent with a recent and an undated child, retention on."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await seed(
            created_by=admin_id,
            column="seen_at",
            days=30,
            rows=[
                {"name": "parent", "seen_at": NOW - timedelta(days=90)},
                {"name": "recent_child", "seen_at": NOW},
                {"name": "undated_child", "seen_at": None},
            ],
        )
        return dataset

    async def _put(self, client, dataset_id, headers, dry_run):
        return await client.put(
            f"/datasets/{dataset_id}/retention/",
            params={"dry_run": "true"} if dry_run else None,
            json={"retention": {"column": "seen_at", "days": 30}},
            headers=headers,
        )

    @pytest.mark.parametrize("action", _DELETE_ACTIONS)
    async def test_a_self_referenced_table_is_refused_and_never_pruned(
        self, client: AsyncClient, admin_auth_header, seed, test_db_session, action
    ):
        dataset = await self._family(seed, test_db_session)
        table = dataset.table_name
        await test_db_session.execute(
            text(
                f"ALTER TABLE data.{table} ADD COLUMN parent_gid integer "
                f"REFERENCES data.{table}(gid) ON DELETE {action}"
            )
        )
        await test_db_session.execute(
            text(
                f"UPDATE data.{table} SET parent_gid = (SELECT gid FROM "
                f"data.{table} WHERE name = 'parent') WHERE name <> 'parent'"
            )
        )
        await test_db_session.commit()

        for dry_run in (True, False):
            resp = await self._put(client, dataset.id, admin_auth_header, dry_run)
            assert resp.status_code == 422, resp.text
            assert _refusal_code(resp) == "retention_referenced"

        with structlog.testing.capture_logs() as logs:
            assert await retention.prune_expired_rows(now=NOW) == {}
        assert not [e for e in logs if e["event"] == "dataset_retention_failed"]
        assert await _names(test_db_session, dataset) == {
            "parent",
            "recent_child",
            "undated_child",
        }
        assert await _prune_audits(test_db_session, dataset.id) == []

    @pytest.mark.parametrize("action", _DELETE_ACTIONS)
    async def test_a_table_another_table_references_is_refused_and_never_pruned(
        self, client: AsyncClient, admin_auth_header, seed, test_db_session, action
    ):
        dataset = await self._family(seed, test_db_session)
        table = dataset.table_name
        referrer = f"{table}_ref"
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{referrer} (id serial PRIMARY KEY, "
                f"event_gid integer REFERENCES data.{table}(gid) ON DELETE {action})"
            )
        )
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{referrer} (event_gid) SELECT gid FROM "
                f"data.{table} WHERE name = 'parent'"
            )
        )
        await test_db_session.commit()
        try:
            for dry_run in (True, False):
                resp = await self._put(client, dataset.id, admin_auth_header, dry_run)
                assert resp.status_code == 422, resp.text
                assert _refusal_code(resp) == "retention_referenced"

            with structlog.testing.capture_logs() as logs:
                assert await retention.prune_expired_rows(now=NOW) == {}
            assert not [e for e in logs if e["event"] == "dataset_retention_failed"]
            assert "parent" in await _names(test_db_session, dataset)
            assert (
                await test_db_session.scalar(
                    text(
                        f"SELECT count(*) FROM data.{referrer} WHERE event_gid IS NOT NULL"
                    )
                )
                == 1
            )
        finally:
            await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{referrer}"))
            await test_db_session.commit()


class TestRelationShape:
    """Retention runs only on a plain table whose deletes remove exactly what they ask."""

    async def _layer(self, seed, test_db_session):
        admin_id = await get_user_id(test_db_session, "admin")
        return await seed(
            created_by=admin_id,
            column="seen_at",
            days=30,
            rows=[
                {"name": "old", "seen_at": NOW - timedelta(days=90)},
                {"name": "recent", "seen_at": NOW},
            ],
        )

    async def _refused(self, client, headers, dataset_id, code) -> None:
        for dry_run in (True, False):
            resp = await client.put(
                f"/datasets/{dataset_id}/retention/",
                params={"dry_run": "true"} if dry_run else None,
                json={"retention": {"column": "seen_at", "days": 30}},
                headers=headers,
            )
            assert resp.status_code == 422, resp.text
            assert _refusal_code(resp) == code

    async def _skipped(self, test_db_session, dataset) -> None:
        with structlog.testing.capture_logs() as logs:
            assert await retention.prune_expired_rows(now=NOW) == {}
        events = [entry["event"] for entry in logs]
        assert "dataset_retention_failed" not in events
        assert "dataset_retention_batch_rolled_back" in events
        assert await _names(test_db_session, dataset) == {"old", "recent"}
        assert await _prune_audits(test_db_session, dataset.id) == []

    async def test_a_partitioned_table_is_refused(
        self, client: AsyncClient, admin_auth_header, seed, test_db_session
    ):
        dataset = await self._layer(seed, test_db_session)
        parted = f"{dataset.table_name}_parted"
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{parted} (gid integer, geom geometry, "
                "geom_4326 geometry, seen_at timestamptz, seen_on date, "
                "seen_local timestamp, name text) PARTITION BY RANGE (gid)"
            )
        )
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{parted}_1 PARTITION OF data.{parted} "
                "FOR VALUES FROM (0) TO (1000000)"
            )
        )
        await test_db_session.execute(
            text("UPDATE catalog.datasets SET table_name = :t WHERE id = :id"),
            {"t": parted, "id": dataset.id},
        )
        await test_db_session.commit()
        try:
            await self._refused(
                client, admin_auth_header, dataset.id, "retention_unsupported_relation"
            )
        finally:
            await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{parted}"))
            await test_db_session.commit()

    async def test_a_table_with_an_inheritance_child_is_refused_and_skipped(
        self, client: AsyncClient, admin_auth_header, seed, test_db_session
    ):
        dataset = await self._layer(seed, test_db_session)
        child = f"{dataset.table_name}_child"
        await test_db_session.execute(
            text(f"CREATE TABLE data.{child} () INHERITS (data.{dataset.table_name})")
        )
        await test_db_session.commit()
        try:
            await self._refused(
                client, admin_auth_header, dataset.id, "retention_has_children"
            )
            await self._skipped(test_db_session, dataset)
        finally:
            await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{child}"))
            await test_db_session.commit()

    async def test_a_foreign_table_child_is_refused(
        self, client: AsyncClient, admin_auth_header, seed, test_db_session
    ):
        dataset = await self._layer(seed, test_db_session)
        server = f"ret_files_{uuid.uuid4().hex[:8]}"
        child = f"{dataset.table_name}_files"
        await test_db_session.execute(text("CREATE EXTENSION IF NOT EXISTS file_fdw"))
        await test_db_session.execute(
            text(f"CREATE SERVER {server} FOREIGN DATA WRAPPER file_fdw")
        )
        await test_db_session.execute(
            text(
                f"CREATE FOREIGN TABLE data.{child} () "
                f"INHERITS (data.{dataset.table_name}) SERVER {server} "
                "OPTIONS (filename '/dev/null', format 'csv')"
            )
        )
        await test_db_session.commit()
        try:
            await self._refused(
                client, admin_auth_header, dataset.id, "retention_has_children"
            )
        finally:
            await test_db_session.execute(text(f"DROP SERVER {server} CASCADE"))
            await test_db_session.commit()

    async def test_a_child_attached_mid_batch_keeps_its_rows_and_their_referrers(
        self, seed, test_db_session, monkeypatch
    ):
        """Holds without the inheritance recheck: the batch deletes FROM ONLY."""
        dataset = await self._layer(seed, test_db_session)
        table = dataset.table_name
        child, referrer = f"{table}_late", f"{table}_late_ref"
        real_delete = retention._delete_batch
        attached = False

        async def attach_then_delete(session, window, after, limit):
            nonlocal attached
            if not attached:
                attached = True
                for sql in (
                    f"CREATE TABLE data.{child} () INHERITS (data.{table})",
                    f"ALTER TABLE data.{child} ADD PRIMARY KEY (gid)",
                    f"INSERT INTO data.{child} (gid, seen_at, name) "
                    f"VALUES (900001, now() - interval '400 days', 'child_old')",
                    f"CREATE TABLE data.{referrer} (id serial PRIMARY KEY, "
                    f"child_gid integer REFERENCES data.{child}(gid) "
                    "ON DELETE CASCADE)",
                    f"INSERT INTO data.{referrer} (child_gid) VALUES (900001)",
                ):
                    await _commit_elsewhere(sql, {})
            return await real_delete(session, window, after, limit)

        monkeypatch.setattr(retention, "_delete_batch", attach_then_delete)
        try:
            await retention.prune_expired_rows(now=NOW)

            assert (
                await test_db_session.scalar(
                    text(f"SELECT count(*) FROM ONLY data.{child}")
                )
                == 1
            )
            assert (
                await test_db_session.scalar(
                    text(f"SELECT count(*) FROM data.{referrer}")
                )
                == 1
            )
        finally:
            await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{referrer}"))
            await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{child}"))
            await test_db_session.commit()

    async def test_a_delete_rule_is_refused(
        self, client: AsyncClient, admin_auth_header, seed, test_db_session
    ):
        dataset = await self._layer(seed, test_db_session)
        await test_db_session.execute(
            text(
                f"CREATE RULE keep_rows AS ON DELETE TO data.{dataset.table_name} "
                "DO INSTEAD NOTHING"
            )
        )
        await test_db_session.commit()
        await self._refused(
            client, admin_auth_header, dataset.id, "retention_delete_rule"
        )

    async def _add_trigger(self, test_db_session, dataset, timing, level):
        function = f"data.ret_trg_{uuid.uuid4().hex[:8]}"
        returns = "NULL" if level == "STATEMENT" or timing == "BEFORE" else "OLD"
        await test_db_session.execute(
            text(
                f"CREATE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql "
                f"AS $$ BEGIN RETURN {returns}; END $$"
            )
        )
        await test_db_session.execute(
            text(
                f"CREATE TRIGGER on_delete {timing} DELETE "
                f"ON data.{dataset.table_name} FOR EACH {level} "
                f"EXECUTE FUNCTION {function}()"
            )
        )
        await test_db_session.commit()
        return function

    @pytest.mark.parametrize(
        ("timing", "level"),
        [("BEFORE", "ROW"), ("AFTER", "ROW"), ("AFTER", "STATEMENT")],
        ids=["before-row", "after-row", "after-statement"],
    )
    async def test_a_delete_trigger_is_refused_and_skipped(
        self,
        client: AsyncClient,
        admin_auth_header,
        seed,
        test_db_session,
        timing,
        level,
    ):
        dataset = await self._layer(seed, test_db_session)
        function = await self._add_trigger(test_db_session, dataset, timing, level)
        try:
            await self._refused(
                client, admin_auth_header, dataset.id, "retention_delete_trigger"
            )
            await self._skipped(test_db_session, dataset)
        finally:
            await test_db_session.execute(text(f"DROP FUNCTION {function}() CASCADE"))
            await test_db_session.commit()

    @pytest.mark.parametrize("mode", ["DISABLE", "ENABLE REPLICA"])
    async def test_a_disabled_or_replica_only_delete_trigger_still_prunes(
        self, seed, test_db_session, mode
    ):
        dataset = await self._layer(seed, test_db_session)
        function = await self._add_trigger(test_db_session, dataset, "AFTER", "ROW")
        await test_db_session.execute(
            text(f"ALTER TABLE data.{dataset.table_name} {mode} TRIGGER on_delete")
        )
        await test_db_session.commit()
        try:
            assert await retention.prune_expired_rows(now=NOW) == {dataset.id: 1}
            assert await _names(test_db_session, dataset) == {"recent"}
        finally:
            await test_db_session.execute(text(f"DROP FUNCTION {function}() CASCADE"))
            await test_db_session.commit()


class TestScheduling:
    def test_the_job_runs_hourly_on_the_ingest_queue(self):
        periodic = task_app.periodic_registry.periodic_tasks[
            (retention_jobs.apply_dataset_retention.name, "dataset-retention")
        ]

        assert periodic.cron == "23 * * * *"
        assert retention_jobs.apply_dataset_retention.queue == "ingest"

    def test_a_fresh_worker_discovers_the_job_through_its_import_paths(self):
        # This module already imports retention_jobs, so only a fresh interpreter
        # shows whether the worker's own startup import finds it.
        script = (
            "import sys\n"
            "from app.processing.ingest.tasks import task_app\n"
            "assert 'app.modules.admin.retention_jobs' not in sys.modules\n"
            "task_app.perform_import_paths()\n"
            "print(any(k[1] == 'dataset-retention' for k in task_app.periodic_registry.periodic_tasks))\n"
        )
        backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=backend,
            capture_output=True,
            text=True,
            check=True,
        )

        assert result.stdout.strip().splitlines()[-1] == "True"

    async def test_each_tenant_runs_under_its_own_context(self, monkeypatch):
        tenants = [str(uuid.uuid4()), str(uuid.uuid4())]
        seen: list[str | None] = []

        async def fake_prune():
            seen.append(current_tenant_var.get())
            if len(seen) == 1:
                raise RuntimeError("first tenant fails")
            return {}

        async def registered():
            return tenants

        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
        monkeypatch.setattr(retention_jobs, "prune_expired_rows", fake_prune)
        monkeypatch.setattr(
            "app.platform.jobs.worker._registered_tenant_ids_for_recovery", registered
        )

        await retention_jobs.prune_expired_rows_for_all_tenants()

        assert seen == tenants


class TestSetting:
    async def _put(self, client, dataset_id, body, headers, dry_run=False):
        return await client.put(
            f"/datasets/{dataset_id}/retention/",
            params={"dry_run": "true"} if dry_run else None,
            json=body,
            headers=headers,
        )

    async def test_a_save_does_not_count_rows_again(
        self, client: AsyncClient, admin_auth_header, seed, test_db_session, monkeypatch
    ):
        from app.modules.catalog.datasets.api import router_retention

        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await seed(
            created_by=admin_id,
            rows=[
                {
                    "name": "old",
                    "seen_at": datetime.now(timezone.utc) - timedelta(days=90),
                }
            ],
        )
        counts: list[str] = []
        real_count = router_retention.count_rows_past

        async def counted(session, table_name, column, cutoff):
            counts.append(column)
            return await real_count(session, table_name, column, cutoff)

        monkeypatch.setattr(router_retention, "count_rows_past", counted)
        body = {"retention": {"column": "seen_at", "days": 30}}

        preview = await self._put(
            client, dataset.id, body, admin_auth_header, dry_run=True
        )
        saved = await self._put(client, dataset.id, body, admin_auth_header)

        assert preview.json()["rows_past_cutoff"] == 1
        assert saved.status_code == 200, saved.text
        assert saved.json()["rows_past_cutoff"] is None
        assert counts == ["seen_at"]

    async def test_a_dry_run_counts_rows_and_saves_nothing(
        self, client: AsyncClient, admin_auth_header, seed, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        now = datetime.now(timezone.utc)
        dataset = await seed(
            created_by=admin_id,
            rows=[
                {"name": "old", "seen_at": now - timedelta(days=40)},
                {"name": "older", "seen_at": now - timedelta(days=400)},
                {"name": "new", "seen_at": now - timedelta(days=1)},
                {"name": "undated"},
            ],
        )
        body = {"retention": {"column": "seen_at", "days": 30}}

        preview = await self._put(
            client, dataset.id, body, admin_auth_header, dry_run=True
        )

        assert preview.status_code == 200, preview.text
        assert preview.json()["rows_past_cutoff"] == 2
        assert datetime.fromisoformat(preview.json()["cutoff"]).tzinfo is not None
        test_db_session.expire_all()
        stored = await test_db_session.get(Dataset, dataset.id)
        assert (stored.retention_column, stored.retention_days) == (None, None)

    async def test_a_date_column_dry_run_returns_utc_midnight_of_the_cutoff_date(
        self, client: AsyncClient, admin_auth_header, seed, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await seed(created_by=admin_id, rows=[])
        body = {"retention": {"column": "seen_on", "days": 30}}

        before = (datetime.now(timezone.utc) - timedelta(days=30)).date()
        preview = await self._put(
            client, dataset.id, body, admin_auth_header, dry_run=True
        )
        after = (datetime.now(timezone.utc) - timedelta(days=30)).date()

        assert preview.status_code == 200, preview.text
        assert preview.json()["cutoff"] in {
            f"{before.isoformat()}T00:00:00Z",
            f"{after.isoformat()}T00:00:00Z",
        }

    async def test_a_save_and_a_clear_stamp_the_record_and_a_dry_run_does_not(
        self, client: AsyncClient, admin_auth_header, seed, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await seed(created_by=admin_id, rows=[])

        async def stamp():
            test_db_session.expire_all()
            return tuple(
                (
                    await test_db_session.execute(
                        select(Record.updated_at, Record.updated_by)
                        .join(Dataset, Dataset.record_id == Record.id)
                        .where(Dataset.id == dataset.id)
                    )
                ).one()
            )

        seeded = await stamp()
        assert seeded[1] is None
        body = {"retention": {"column": "seen_at", "days": 30}}

        preview = await self._put(
            client, dataset.id, body, admin_auth_header, dry_run=True
        )
        assert preview.status_code == 200, preview.text
        assert await stamp() == seeded

        saved = await self._put(client, dataset.id, body, admin_auth_header)
        assert saved.status_code == 200, saved.text
        after_save = await stamp()
        assert after_save[0] > seeded[0]
        assert after_save[1] == admin_id

        cleared = await self._put(
            client, dataset.id, {"retention": None}, admin_auth_header
        )
        assert cleared.status_code == 200, cleared.text
        after_clear = await stamp()
        assert after_clear[0] > after_save[0]
        assert after_clear[1] == admin_id

    async def test_a_save_holds_the_table_against_a_new_delete_trigger(
        self, client: AsyncClient, admin_auth_header, seed, test_db_session, monkeypatch
    ):
        import app.core.db as db_module
        from sqlalchemy.exc import DBAPIError

        from app.core.db.sqlstate import is_lock_conflict
        from app.modules.catalog.datasets.api import router_retention

        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await seed(created_by=admin_id, rows=[])
        function = f"data.ret_trg_{uuid.uuid4().hex[:8]}"
        await test_db_session.execute(
            text(
                f"CREATE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql "
                "AS $$ BEGIN RETURN OLD; END $$"
            )
        )
        await test_db_session.commit()
        real_check = router_retention.check_retention
        refused: list[bool] = []

        async def trigger_attempt_then_check(session, target, retention):
            async with db_module.async_session() as other:
                await other.execute(text("SET LOCAL lock_timeout = '200ms'"))
                try:
                    await other.execute(
                        text(
                            f"CREATE TRIGGER on_delete AFTER DELETE ON "
                            f"data.{dataset.table_name} FOR EACH ROW "
                            f"EXECUTE FUNCTION {function}()"
                        )
                    )
                    await other.commit()
                except DBAPIError as exc:
                    refused.append(is_lock_conflict(exc))
                    await other.rollback()
            return await real_check(session, target, retention)

        monkeypatch.setattr(
            router_retention, "check_retention", trigger_attempt_then_check
        )
        try:
            resp = await self._put(
                client,
                dataset.id,
                {"retention": {"column": "seen_at", "days": 30}},
                admin_auth_header,
            )

            assert refused == [True]
            assert resp.status_code == 200, resp.text
            assert await _stored_setting(test_db_session, dataset.id) == ("seen_at", 30)
        finally:
            await test_db_session.execute(text(f"DROP FUNCTION {function}() CASCADE"))
            await test_db_session.commit()

    @pytest.mark.parametrize(
        ("start", "requested"),
        [
            ((None, None), {"column": "seen_at", "days": 30}),
            (("seen_at", 30), {"column": "seen_on", "days": 7}),
            (("seen_at", 30), None),
        ],
        ids=["enable", "change", "clear"],
    )
    async def test_a_save_credits_its_editor_over_a_concurrent_prune(
        self,
        client: AsyncClient,
        admin_auth_header,
        seed,
        test_db_session,
        monkeypatch,
        start,
        requested,
    ):
        from app.modules.catalog.datasets.api import router_retention

        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await seed(
            created_by=admin_id, column=start[0], days=start[1], rows=[]
        )
        record_of = "(SELECT record_id FROM catalog.datasets WHERE id = :id)"
        await test_db_session.execute(
            text(
                f"UPDATE catalog.records SET updated_by = :user WHERE id = {record_of}"
            ),
            {"user": admin_id, "id": dataset.id},
        )
        await test_db_session.commit()
        real_lock = router_retention.lock_dataset_rows_for_write

        async def prune_clears_the_editor_then_lock(db, target, **kwargs):
            await _commit_elsewhere(
                f"UPDATE catalog.records SET updated_by = NULL WHERE id = {record_of}",
                {"id": dataset.id},
            )
            return await real_lock(db, target, **kwargs)

        monkeypatch.setattr(
            router_retention,
            "lock_dataset_rows_for_write",
            prune_clears_the_editor_then_lock,
        )

        resp = await self._put(
            client, dataset.id, {"retention": requested}, admin_auth_header
        )

        assert resp.status_code == 200, resp.text
        test_db_session.expire_all()
        editor = await test_db_session.scalar(
            select(Record.updated_by)
            .join(Dataset, Dataset.record_id == Record.id)
            .where(Dataset.id == dataset.id)
        )
        assert editor == admin_id

    async def test_the_owner_saves_and_clears_retention(
        self, client: AsyncClient, admin_auth_header, seed, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await seed(created_by=admin_id, rows=[{"name": "a"}])

        saved = await self._put(
            client,
            dataset.id,
            {"retention": {"column": "seen_on", "days": 7}},
            admin_auth_header,
        )
        assert saved.status_code == 200, saved.text
        detail = await client.get(f"/datasets/{dataset.id}", headers=admin_auth_header)
        assert detail.json()["retention"] == {"column": "seen_on", "days": 7}

        cleared = await self._put(
            client, dataset.id, {"retention": None}, admin_auth_header
        )
        assert cleared.status_code == 200, cleared.text
        detail = await client.get(f"/datasets/{dataset.id}", headers=admin_auth_header)
        assert detail.json()["retention"] is None

    async def test_the_editing_switch_does_not_gate_retention(
        self, client: AsyncClient, admin_auth_header, seed, test_db_session, monkeypatch
    ):
        import app.core.persistent_config as pc

        class _AlwaysOff:
            async def get(self, _db):
                return False

        monkeypatch.setattr(pc, "ENABLE_DATASET_EDITING", _AlwaysOff())
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await seed(created_by=admin_id, rows=[])

        resp = await self._put(
            client,
            dataset.id,
            {"retention": {"column": "seen_at", "days": 30}},
            admin_auth_header,
        )

        assert resp.status_code == 200, resp.text

    @pytest.mark.parametrize(
        "retention_body",
        [
            {"column": "name", "days": 30},
            {"column": "missing", "days": 30},
            {"column": "seen_at", "days": 0},
            {"column": "seen_at", "days": 3651},
            {"column": 'seen_at" OR true --', "days": 30},
        ],
        ids=["text-column", "missing-column", "zero-days", "too-many-days", "quoted"],
    )
    async def test_a_setting_the_layer_cannot_take_is_refused(
        self,
        client: AsyncClient,
        admin_auth_header,
        seed,
        test_db_session,
        retention_body,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await seed(created_by=admin_id, rows=[])

        resp = await self._put(
            client, dataset.id, {"retention": retention_body}, admin_auth_header
        )

        assert resp.status_code == 422, resp.text
        assert _refusal_code(resp) == {
            "name": "retention_column_not_temporal",
            "missing": "retention_column_missing",
        }.get(retention_body["column"])
        test_db_session.expire_all()
        stored = await test_db_session.get(Dataset, dataset.id)
        assert stored.retention_column is None

    @pytest.mark.parametrize(
        ("column", "base"),
        [
            ("seen_on", "date"),
            ("seen_local", "timestamp"),
            ("seen_at", "timestamptz"),
        ],
    )
    async def test_a_column_typed_by_a_domain_takes_retention(
        self,
        client: AsyncClient,
        admin_auth_header,
        seed,
        test_db_session,
        column,
        base,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await seed(created_by=admin_id, rows=[])
        domain = f"data.ret_{uuid.uuid4().hex[:8]}"
        await test_db_session.execute(text(f"CREATE DOMAIN {domain} AS {base}"))
        await test_db_session.execute(
            text(
                f"ALTER TABLE data.{dataset.table_name} "
                f"ALTER COLUMN {column} TYPE {domain}"
            )
        )
        await test_db_session.commit()
        body = {"retention": {"column": column, "days": 30}}
        try:
            preview = await self._put(
                client, dataset.id, body, admin_auth_header, dry_run=True
            )
            saved = await self._put(client, dataset.id, body, admin_auth_header)

            assert preview.status_code == 200, preview.text
            assert saved.status_code == 200, saved.text
            assert await _stored_setting(test_db_session, dataset.id) == (column, 30)
        finally:
            await test_db_session.execute(text(f"DROP DOMAIN {domain} CASCADE"))
            await test_db_session.commit()

    @pytest.mark.parametrize("dry_run", [True, False], ids=["dry-run", "save"])
    async def test_a_dataset_read_from_a_view_is_refused(
        self, client: AsyncClient, admin_auth_header, seed, test_db_session, dry_run
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await seed(created_by=admin_id, rows=[])
        view = await _point_dataset_at_a_view(test_db_session, dataset)
        try:
            resp = await self._put(
                client,
                dataset.id,
                {"retention": {"column": "seen_at", "days": 30}},
                admin_auth_header,
                dry_run=dry_run,
            )
            assert resp.status_code == 422, resp.text
            assert _refusal_code(resp) == "retention_unsupported_relation"
            assert await _stored_setting(test_db_session, dataset.id) == (None, None)
        finally:
            await _drop_view(test_db_session, view)

    @pytest.mark.parametrize(
        ("record_type", "geometry_type"),
        [("raster_dataset", "POINT"), ("table", None)],
        ids=["raster", "table-without-geometry"],
    )
    async def test_a_dataset_without_features_is_refused(
        self,
        client: AsyncClient,
        admin_auth_header,
        seed,
        test_db_session,
        record_type,
        geometry_type,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await seed(
            created_by=admin_id,
            rows=[],
            record_type=record_type,
            geometry_type=geometry_type,
        )

        resp = await self._put(
            client,
            dataset.id,
            {"retention": {"column": "seen_at", "days": 30}},
            admin_auth_header,
        )

        assert resp.status_code == 422, resp.text
        assert _refusal_code(resp) == "retention_not_feature_dataset"

    @pytest.mark.parametrize(
        ("visibility", "expected"), [("public", 403), ("private", 404)]
    )
    async def test_a_non_owner_gets_the_write_guard_answer(
        self,
        client: AsyncClient,
        admin_auth_header,
        seed,
        test_db_session,
        visibility,
        expected,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await seed(created_by=admin_id, rows=[], visibility=visibility)
        editor_headers, _ = await create_user(client, admin_auth_header, "editor")

        resp = await self._put(
            client,
            dataset.id,
            {"retention": {"column": "seen_at", "days": 30}},
            editor_headers,
            dry_run=True,
        )

        assert resp.status_code == expected, resp.text


def test_cutoffs_by_column_type():
    assert retention.cutoff_for(NOW, 30, "date") == date(2026, 9, 17)
    assert retention.cutoff_for(NOW, 30, "timestamp without time zone") == datetime(
        2026, 9, 17, 12, 0
    )
    assert retention.cutoff_for(NOW, 30, "timestamp with time zone") == CUTOFF
