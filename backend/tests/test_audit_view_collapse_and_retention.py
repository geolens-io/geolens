"""Repeat dataset views collapse, and audit rows age out on a retention period."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select, update

from app.modules.audit.models import AuditLog
from app.modules.audit.service import prune_audit_logs
from app.platform.jobs.audit_retention import prune_expired_audit_logs
from tests.factories import create_dataset, get_user_id


async def _view_rows(session, dataset_id: uuid.UUID, user_id: uuid.UUID | None = None):
    query = select(func.count()).where(
        AuditLog.action == "dataset.view", AuditLog.resource_id == dataset_id
    )
    if user_id is not None:
        query = query.where(AuditLog.user_id == user_id)
    session.expire_all()
    return await session.scalar(query)


@pytest.mark.anyio
async def test_repeat_view_inside_the_window_writes_one_row(
    client: AsyncClient, viewer_auth_header: dict, test_db_session
):
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await create_dataset(test_db_session, created_by=admin_id)

    for _ in range(3):
        resp = await client.get(f"/datasets/{ds.id}", headers=viewer_auth_header)
        assert resp.status_code == 200

    assert await _view_rows(test_db_session, ds.id) == 1


@pytest.mark.anyio
async def test_view_after_the_window_writes_a_second_row(
    client: AsyncClient, viewer_auth_header: dict, test_db_session
):
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await create_dataset(test_db_session, created_by=admin_id)

    await client.get(f"/datasets/{ds.id}", headers=viewer_auth_header)
    await test_db_session.execute(
        update(AuditLog)
        .where(AuditLog.action == "dataset.view", AuditLog.resource_id == ds.id)
        .values(created_at=datetime.now(timezone.utc) - timedelta(minutes=16))
    )
    await test_db_session.commit()
    await client.get(f"/datasets/{ds.id}", headers=viewer_auth_header)

    assert await _view_rows(test_db_session, ds.id) == 2


@pytest.mark.anyio
async def test_other_users_and_datasets_keep_their_own_view_rows(
    client: AsyncClient,
    admin_auth_header: dict,
    viewer_auth_header: dict,
    test_db_session,
):
    admin_id = await get_user_id(test_db_session, "admin")
    first = await create_dataset(test_db_session, created_by=admin_id, name="first")
    second = await create_dataset(test_db_session, created_by=admin_id, name="second")

    first_id, second_id = first.id, second.id

    await client.get(f"/datasets/{first_id}", headers=viewer_auth_header)
    await client.get(f"/datasets/{first_id}", headers=admin_auth_header)
    await client.get(f"/datasets/{second_id}", headers=viewer_auth_header)

    assert await _view_rows(test_db_session, first_id) == 2
    assert await _view_rows(test_db_session, second_id) == 1


@pytest.mark.anyio
async def test_anonymous_views_write_nothing(client: AsyncClient, test_db_session):
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await create_dataset(test_db_session, created_by=admin_id)

    resp = await client.get(f"/datasets/{ds.id}")
    assert resp.status_code == 200

    assert await _view_rows(test_db_session, ds.id) == 0


@pytest.fixture
async def retention_days(client: AsyncClient, test_db_session):
    from app.core.persistent_config import AUDIT_RETENTION_DAYS
    from app.platform.cache import get_cache

    async def _set(days: int | None) -> None:
        await AUDIT_RETENTION_DAYS.set(test_db_session, days)

    yield _set

    from app.core.db.models import AppSetting

    await test_db_session.execute(
        delete(AppSetting).where(AppSetting.key == AUDIT_RETENTION_DAYS.key)
    )
    await test_db_session.commit()
    await get_cache().delete(f"config:{AUDIT_RETENTION_DAYS.key}")


async def _seed_rows(session, *, old: int, new: int) -> tuple[list, list]:
    marker = f"retention-test-{uuid.uuid4()}"
    now = datetime.now(timezone.utc)
    old_ids, new_ids = [], []
    for target, age_days, count in ((old_ids, 120, old), (new_ids, 10, new)):
        for _ in range(count):
            row = AuditLog(
                user_id=None,
                action="retention.test",
                resource_type="test",
                details={"marker": marker},
                created_at=now - timedelta(days=age_days),
            )
            session.add(row)
            await session.flush()
            target.append(row.id)
    await session.commit()
    return old_ids, new_ids


async def _surviving(session, ids: list) -> int:
    session.expire_all()
    return await session.scalar(select(func.count()).where(AuditLog.id.in_(ids)))


@pytest.mark.anyio
async def test_unset_retention_deletes_nothing(
    client: AsyncClient, test_db_session, retention_days
):
    old_ids, new_ids = await _seed_rows(test_db_session, old=2, new=1)

    assert await prune_expired_audit_logs() == 0

    assert await _surviving(test_db_session, old_ids + new_ids) == 3


@pytest.mark.anyio
async def test_rows_older_than_the_cutoff_go_and_newer_rows_stay(
    client: AsyncClient, test_db_session, retention_days
):
    await retention_days(90)
    old_ids, new_ids = await _seed_rows(test_db_session, old=3, new=2)

    deleted = await prune_expired_audit_logs()

    assert deleted >= 3
    assert await _surviving(test_db_session, old_ids) == 0
    assert await _surviving(test_db_session, new_ids) == 2


@pytest.mark.anyio
async def test_pruning_runs_across_several_batches(
    client: AsyncClient, test_db_session
):
    old_ids, new_ids = await _seed_rows(test_db_session, old=5, new=1)
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)

    deleted = await prune_audit_logs(
        test_db_session, cutoff=cutoff, batch_size=2, retention_days=90
    )

    assert deleted >= 5
    assert await _surviving(test_db_session, old_ids) == 0
    assert await _surviving(test_db_session, new_ids) == 1
    events = await test_db_session.scalars(
        select(AuditLog).where(
            AuditLog.action == "audit.prune",
            AuditLog.details["cutoff"].astext == cutoff.isoformat(),
        )
    )
    assert sum(e.details["deleted"] for e in events) == deleted


@pytest.mark.anyio
async def test_a_prune_records_one_event_with_the_count_and_cutoff(
    client: AsyncClient, test_db_session, retention_days
):
    await retention_days(90)
    await _seed_rows(test_db_session, old=2, new=0)

    deleted = await prune_expired_audit_logs()

    test_db_session.expire_all()
    event = (
        await test_db_session.scalars(
            select(AuditLog)
            .where(AuditLog.action == "audit.prune")
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )
    ).one()
    assert event.details["deleted"] == deleted
    assert event.details["retention_days"] == 90
    assert "cutoff" in event.details


@pytest.mark.anyio
async def test_a_prune_that_deletes_nothing_records_no_event(
    client: AsyncClient, test_db_session, retention_days
):
    await retention_days(3650)
    before = await test_db_session.scalar(
        select(func.count()).where(AuditLog.action == "audit.prune")
    )

    assert await prune_expired_audit_logs() == 0

    test_db_session.expire_all()
    after = await test_db_session.scalar(
        select(func.count()).where(AuditLog.action == "audit.prune")
    )
    assert after == before


def test_validator_accepts_unset_and_the_minimum_only():
    from app.modules.settings.schemas import validate_audit_retention_days

    assert validate_audit_retention_days(None) is None
    assert validate_audit_retention_days(90) == 90
    with pytest.raises(ValueError):
        validate_audit_retention_days(89)


@pytest.mark.anyio
async def test_settings_api_rejects_below_the_minimum_and_clears_with_null(
    client: AsyncClient, admin_auth_header: dict, retention_days
):
    rejected = await client.put(
        "/settings/",
        json={"settings": {"audit_retention_days": 89}},
        headers=admin_auth_header,
    )
    assert rejected.status_code == 422

    saved = await client.put(
        "/settings/",
        json={"settings": {"audit_retention_days": 90}},
        headers=admin_auth_header,
    )
    assert saved.status_code == 200
    cleared = await client.put(
        "/settings/",
        json={"settings": {"audit_retention_days": None}},
        headers=admin_auth_header,
    )
    assert cleared.status_code == 200
    items = [i for tab in cleared.json()["tabs"].values() for i in tab]
    item = next(i for i in items if i["key"] == "audit_retention_days")
    assert item["value"] is None
