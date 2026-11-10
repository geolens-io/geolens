"""A refresh or file replacement sent with a stale expected data revision stops for review."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.modules.catalog.datasets.domain.models import Dataset
from app.platform.refresh.service import create_pending_run
from app.platform.refresh.verification import UNKNOWN_DATA_REVISION
from tests.factories import create_dataset as _create_dataset, get_user_id
from tests.test_dataset_refresh_runs import (
    _seed,
    _stubbed_reupload_dispatch,
    _upload_for_reupload,
)
from tests.test_service_refresh_1220 import (
    _dispatch_harness,
    _run_for,
    _service_dataset,
)


async def _set_revision(session, dataset_id, revision: int) -> None:
    await session.execute(
        update(Dataset).where(Dataset.id == dataset_id).values(data_revision=revision)
    )
    await session.commit()


@pytest.mark.parametrize(
    ("baseline", "expected", "stored"),
    [
        (None, None, 3),
        (None, 3, 3),
        (None, 2, UNKNOWN_DATA_REVISION),
        (1, 1, 1),
        (1, 3, UNKNOWN_DATA_REVISION),
    ],
)
async def test_an_expected_revision_other_than_the_baseline_compares_every_write(
    test_db_session, baseline, expected, stored
) -> None:
    dataset, job = await _seed(test_db_session)
    await _set_revision(test_db_session, dataset.id, 3)

    run = await create_pending_run(
        test_db_session,
        dataset_id=dataset.id,
        origin_kind="upload",
        trigger="manual",
        triggered_by=job.created_by,
        ingest_job_id=job.id,
        feature_count_before=None,
        data_revision_baseline=baseline,
        expected_data_revision=expected,
    )

    assert run.data_revision_baseline == stored


@pytest.mark.parametrize(("expected", "stored"), [(4, 4), (3, UNKNOWN_DATA_REVISION)])
async def test_a_service_refresh_takes_the_expected_revision(
    client: AsyncClient, admin_auth_header: dict, test_db_session, expected, stored
) -> None:
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _service_dataset(test_db_session, created_by=admin_id)
    await _set_revision(test_db_session, dataset.id, 4)

    async with _dispatch_harness():
        resp = await client.post(
            f"/datasets/{dataset.id}/refresh",
            json={"expected_data_revision": expected},
            headers=admin_auth_header,
        )

    assert resp.status_code == 202, resp.text
    run = await _run_for(test_db_session, dataset.id)
    assert run.data_revision_baseline == stored


@pytest.mark.parametrize(("expected", "stored"), [(2, 2), (1, UNKNOWN_DATA_REVISION)])
async def test_a_file_replacement_takes_the_expected_revision(
    client: AsyncClient, admin_auth_header: dict, test_db_session, expected, stored
) -> None:
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _create_dataset(test_db_session, created_by=admin_id)
    await _set_revision(test_db_session, dataset.id, 2)

    with _stubbed_reupload_dispatch():
        job_id = await _upload_for_reupload(client, dataset.id, admin_auth_header)
        resp = await client.post(
            f"/datasets/{dataset.id}/reupload/{job_id}/commit",
            json={"expected_data_revision": expected},
            headers=admin_auth_header,
        )

    assert resp.status_code == 202, resp.text
    run = await _run_for(test_db_session, dataset.id)
    assert run.data_revision_baseline == stored


async def test_a_refresh_that_replaces_no_data_refuses_an_expected_revision(
    client: AsyncClient, admin_auth_header: dict, test_db_session
) -> None:
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _create_dataset(
        test_db_session, created_by=admin_id, source_format=None
    )

    resp = await client.post(
        f"/datasets/{dataset.id}/refresh",
        json={"expected_data_revision": 0},
        headers=admin_auth_header,
    )

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "expected_data_revision_not_applicable"
    assert await _run_for(test_db_session, dataset.id) is None


async def test_an_expected_revision_with_an_acceptance_is_refused(
    client: AsyncClient, admin_auth_header: dict, test_db_session
) -> None:
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _service_dataset(test_db_session, created_by=admin_id)

    resp = await client.post(
        f"/datasets/{dataset.id}/refresh",
        json={
            "expected_data_revision": 0,
            "accept_blocked_run_id": "00000000-0000-0000-0000-000000000001",
        },
        headers=admin_auth_header,
    )

    assert resp.status_code == 422, resp.text
    assert "can't be combined with accept_blocked_run_id" in resp.text


async def test_the_data_revision_is_shown_to_the_owner_only(
    client: AsyncClient,
    admin_auth_header: dict,
    viewer_auth_header: dict,
    test_db_session,
) -> None:
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _create_dataset(
        test_db_session, created_by=admin_id, visibility="public"
    )
    await _set_revision(test_db_session, dataset.id, 7)

    owner = await client.get(f"/datasets/{dataset.id}", headers=admin_auth_header)
    reader = await client.get(f"/datasets/{dataset.id}", headers=viewer_auth_header)

    assert owner.json()["data_revision"] == 7
    assert reader.status_code == 200 and reader.json()["data_revision"] is None
