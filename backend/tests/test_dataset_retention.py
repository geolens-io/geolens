"""A dataset's row retention: the setting, its checks and the worker run.

The DB-backed tests require the Docker test database.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import NamedTuple

import pytest
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
                    "ST_SetSRID(ST_MakePoint(:x, :y), 4326), "
                    "ST_SetSRID(ST_MakePoint(:x, :y), 4326), "
                    ":seen_at, :seen_on, :seen_local, :name)"
                ),
                {
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
            source_format="geojson",
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


class TestScheduling:
    def test_the_job_runs_hourly_on_the_ingest_queue(self):
        periodic = task_app.periodic_registry.periodic_tasks[
            (retention_jobs.apply_dataset_retention.name, "dataset-retention")
        ]

        assert periodic.cron == "23 * * * *"
        assert retention_jobs.apply_dataset_retention.queue == "ingest"

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

    async def test_a_date_column_dry_run_returns_the_bare_cutoff_date(
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
        assert preview.json()["cutoff"] in {before.isoformat(), after.isoformat()}

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
        test_db_session.expire_all()
        stored = await test_db_session.get(Dataset, dataset.id)
        assert stored.retention_column is None

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
