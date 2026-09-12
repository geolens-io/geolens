"""Record subresource changes advance modification metadata atomically."""

import asyncio
import importlib.util
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import func, select, text, update

from app.modules.catalog.datasets.domain.models import Record
from tests.factories import create_dataset, get_user_id


async def _modified(session, record_id):
    return (
        await session.execute(
            select(Record.updated_at, Record.updated_by).where(Record.id == record_id)
        )
    ).one()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("resource", "body", "patch"),
    [
        ("contacts", {"role": "author", "name": "Initial"}, {"name": "Changed"}),
        ("keywords", {"keyword": "initial"}, None),
        (
            "distributions",
            {
                "distribution_type": "download",
                "format": "GeoJSON",
                "url": "https://example.com/data.geojson",
            },
            {"title": "Changed"},
        ),
    ],
)
async def test_subresource_writes_advance_record_modified(
    client, admin_auth_header, test_db_session, resource, body, patch
):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await create_dataset(test_db_session, created_by=admin_id)
    path = f"/records/{dataset.record_id}/{resource}/"
    before = await _modified(test_db_session, dataset.record_id)

    response = await client.post(path, json=body, headers=admin_auth_header)
    assert response.status_code == 201, response.text
    child_id = response.json()["id"]
    after = await _modified(test_db_session, dataset.record_id)
    assert after.updated_at > before.updated_at
    assert after.updated_by == admin_id

    child_path = f"{path}{child_id}/"
    if patch is not None:
        before = after
        response = await client.patch(child_path, json=patch, headers=admin_auth_header)
        assert response.status_code == 200, response.text
        after = await _modified(test_db_session, dataset.record_id)
        assert after.updated_at > before.updated_at
        assert after.updated_by == admin_id

    response = await client.delete(child_path, headers=admin_auth_header)
    assert response.status_code == 204, response.text
    deleted = await _modified(test_db_session, dataset.record_id)
    assert deleted.updated_at > after.updated_at
    assert deleted.updated_by == admin_id

    detail = await client.get(f"/datasets/{dataset.id}", headers=admin_auth_header)
    assert detail.status_code == 200, detail.text
    assert detail.json()["updated_at"] == deleted.updated_at.isoformat().replace(
        "+00:00", "Z"
    )


@pytest.mark.anyio
async def test_rejected_subresource_write_preserves_record_modified(
    client, admin_auth_header, test_db_session
):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await create_dataset(test_db_session, created_by=admin_id)
    path = f"/records/{dataset.record_id}/contacts/"
    response = await client.post(
        path, json={"role": "author", "name": "Initial"}, headers=admin_auth_header
    )
    assert response.status_code == 201, response.text
    child_id = response.json()["id"]
    before = await _modified(test_db_session, dataset.record_id)

    invalid = await client.patch(
        f"{path}{child_id}/",
        json={"role": "not-an-iso-role", "name": "Invalid"},
        headers=admin_auth_header,
    )
    assert invalid.status_code == 400, invalid.text
    assert await _modified(test_db_session, dataset.record_id) == before

    missing = await client.delete(f"{path}{uuid.uuid4()}/", headers=admin_auth_header)
    assert missing.status_code == 404, missing.text
    assert await _modified(test_db_session, dataset.record_id) == before
    listing = await client.get(path, headers=admin_auth_header)
    assert listing.status_code == 200, listing.text
    assert (
        next(c for c in listing.json()["contacts"] if c["id"] == child_id)["name"]
        == "Initial"
    )


@pytest.mark.anyio
async def test_older_transaction_cannot_regress_record_modified(
    client, admin_auth_header, test_db_session, monkeypatch
):
    import app.modules.catalog.records.router as record_router

    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await create_dataset(test_db_session, created_by=admin_id)
    path = f"/records/{dataset.record_id}/contacts/"
    older_ready = asyncio.Event()
    resume_older = asyncio.Event()
    original_touch = record_router._touch_record
    calls = 0

    async def pause_first_touch(db, record, user):
        nonlocal calls
        calls += 1
        if calls == 1:
            # Authorization has already started this request's transaction.
            older_ready.set()
            await asyncio.wait_for(resume_older.wait(), timeout=10)
        await original_touch(db, record, user)

    monkeypatch.setattr(record_router, "_touch_record", pause_first_touch)
    older = asyncio.create_task(
        client.post(
            path,
            json={"role": "author", "name": "Older request"},
            headers=admin_auth_header,
        )
    )
    try:
        await asyncio.wait_for(older_ready.wait(), timeout=10)
        newer = await client.post(
            path,
            json={"role": "author", "name": "Newer request"},
            headers=admin_auth_header,
        )
        assert newer.status_code == 201, newer.text
        after_newer = await _modified(test_db_session, dataset.record_id)
    finally:
        resume_older.set()
        older_response = await asyncio.wait_for(older, timeout=10)

    assert older_response.status_code == 201, older_response.text
    after_older = await _modified(test_db_session, dataset.record_id)
    assert after_older.updated_at >= after_newer.updated_at
    listing = await client.get(path, headers=admin_auth_header)
    assert listing.status_code == 200, listing.text
    assert {contact["name"] for contact in listing.json()["contacts"]} >= {
        "Older request",
        "Newer request",
    }


@pytest.mark.anyio
async def test_modified_clock_migration_round_trip(test_db_session):
    path = Path(__file__).parents[1] / "alembic/versions/0062_record_modified_clock.py"
    spec = importlib.util.spec_from_file_location("record_modified_clock", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    session = test_db_session
    future = datetime(2099, 1, 1, tzinfo=UTC)
    dataset = await create_dataset(session, created_by=None, updated_at=future)

    def run_migration(sync_session, direction):
        context = MigrationContext.configure(sync_session.connection())
        with Operations.context(context):
            getattr(migration, direction)()

    try:
        targets = await session.scalars(
            text(
                "SELECT tgrelid::regclass::text FROM pg_trigger "
                "WHERE tgfoid = 'catalog.set_updated_at()'::regprocedure"
            )
        )
        assert list(targets) == ["catalog.records"]
        await session.execute(
            update(Record).where(Record.id == dataset.record_id).values(title="Changed")
        )
        assert (await _modified(session, dataset.record_id)).updated_at == future

        await session.run_sync(run_migration, "downgrade")
        transaction_start = await session.scalar(select(func.now()))
        await session.execute(
            update(Record)
            .where(Record.id == dataset.record_id)
            .values(updated_at=func.clock_timestamp())
        )
        assert (
            await _modified(session, dataset.record_id)
        ).updated_at == transaction_start

        await session.run_sync(run_migration, "upgrade")
        wall_clock = await session.scalar(select(func.clock_timestamp()))
        await session.execute(
            update(Record)
            .where(Record.id == dataset.record_id)
            .values(title="Restored")
        )
        assert (await _modified(session, dataset.record_id)).updated_at >= wall_clock
    finally:
        await session.rollback()
