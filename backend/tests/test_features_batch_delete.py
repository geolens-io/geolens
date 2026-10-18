"""POST /datasets/{id}/features/delete/ deletes listed features, all or none.

Requires the Docker test database.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.modules.audit.models import AuditLog
from app.modules.catalog.datasets.domain.models import Dataset
from app.modules.catalog.features.schemas import MAX_FEATURES_PER_BATCH

from tests.factories import get_user_id
from tests.test_features_crud import _cleanup_table, _create_test_table_and_dataset

POINTS = [
    {"type": "Point", "coordinates": [-73.9857, 40.7484]},
    {"type": "Point", "coordinates": [-118.2437, 34.0522]},
    {"type": "Point", "coordinates": [-87.6298, 41.8781]},
    {"type": "Point", "coordinates": [-95.3698, 29.7604]},
]


async def _layer(session, visibility: str = "public"):
    admin_id = await get_user_id(session, "admin")
    return await _create_test_table_and_dataset(
        session, created_by=admin_id, geometry_type="POINT", visibility=visibility
    )


async def _drop_layer(session, dataset) -> None:
    table_name, record_id = dataset.table_name, dataset.record_id
    await _cleanup_table(session, table_name)
    await session.execute(
        text("DELETE FROM catalog.records WHERE id = :id"), {"id": record_id}
    )
    await session.commit()


@pytest.fixture
async def point_layer(test_db_session):
    dataset = await _layer(test_db_session)
    yield dataset
    await _drop_layer(test_db_session, dataset)


@pytest.fixture
async def private_layer(test_db_session):
    dataset = await _layer(test_db_session, visibility="private")
    yield dataset
    await _drop_layer(test_db_session, dataset)


async def _add_points(client: AsyncClient, headers: dict, dataset) -> list[int]:
    resp = await client.post(
        f"/datasets/{dataset.id}/features/",
        json={
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "geometry": p, "properties": {"name": str(i)}}
                for i, p in enumerate(POINTS)
            ],
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return [feature["id"] for feature in resp.json()["features"]]


async def _gids(session, dataset) -> list[int]:
    result = await session.execute(
        text(f"SELECT gid FROM data.{dataset.table_name} ORDER BY gid")
    )
    return [row[0] for row in result.all()]


async def _catalog_state(session, dataset) -> tuple:
    result = await session.execute(
        select(Dataset.feature_count, Dataset.tile_cache_version).where(
            Dataset.id == dataset.id
        )
    )
    return tuple(result.one())


async def _delete(client, dataset, headers, gids, **params):
    return await client.post(
        f"/datasets/{dataset.id}/features/delete/",
        json={"gids": gids},
        params=params,
        headers=headers,
    )


async def _audit_actions(session, dataset) -> list[AuditLog]:
    result = await session.execute(
        select(AuditLog)
        .where(AuditLog.resource_id == dataset.id)
        .where(AuditLog.action == "feature.bulk_delete")
    )
    return list(result.scalars().all())


async def test_deletes_exactly_the_listed_features_once(
    client: AsyncClient, admin_auth_header: dict, test_db_session, point_layer
):
    gids = await _add_points(client, admin_auth_header, point_layer)
    _, version_before = await _catalog_state(test_db_session, point_layer)

    resp = await _delete(client, point_layer, admin_auth_header, [gids[1], gids[3]])

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert await _gids(test_db_session, point_layer) == [gids[0], gids[2]]
    count, version_after = await _catalog_state(test_db_session, point_layer)
    assert body == {"deleted": 2, "tile_cache_version": version_after}
    assert count == 2
    # One tile generation and one audit entry for the batch, not one per row.
    assert version_after == version_before + 1
    events = await _audit_actions(test_db_session, point_layer)
    assert len(events) == 1
    assert events[0].details["gids"] == [gids[1], gids[3]]
    assert events[0].details["count"] == 2


async def test_the_no_slash_path_and_a_repeated_gid_delete_once(
    client: AsyncClient, admin_auth_header: dict, test_db_session, point_layer
):
    gids = await _add_points(client, admin_auth_header, point_layer)
    resp = await client.post(
        f"/datasets/{point_layer.id}/features/delete",
        json={"gids": [gids[0], gids[0]]},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted"] == 1
    assert await _gids(test_db_session, point_layer) == gids[1:]


async def test_a_missing_gid_deletes_nothing_and_is_named(
    client: AsyncClient, admin_auth_header: dict, test_db_session, point_layer
):
    gids = await _add_points(client, admin_auth_header, point_layer)
    state_before = await _catalog_state(test_db_session, point_layer)
    missing = max(gids) + 1000

    resp = await _delete(
        client, point_layer, admin_auth_header, [gids[0], missing, gids[1]]
    )

    assert resp.status_code == 404, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "feature_not_found"
    assert detail["gids"] == [missing]
    assert str(missing) in detail["message"]
    assert await _gids(test_db_session, point_layer) == gids
    assert await _catalog_state(test_db_session, point_layer) == state_before
    assert await _audit_actions(test_db_session, point_layer) == []


async def test_a_gid_past_the_integer_range_is_reported_missing(
    client: AsyncClient, admin_auth_header: dict, test_db_session, point_layer
):
    gids = await _add_points(client, admin_auth_header, point_layer)
    out_of_range = [2**31, 10**20]

    resp = await _delete(
        client, point_layer, admin_auth_header, [gids[0], *out_of_range]
    )

    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"]["gids"] == out_of_range
    assert await _gids(test_db_session, point_layer) == gids


@pytest.mark.parametrize("bad", [[True], [False], [1, True]])
async def test_boolean_gids_are_refused(
    client: AsyncClient, admin_auth_header: dict, test_db_session, point_layer, bad
):
    gids = await _add_points(client, admin_auth_header, point_layer)

    resp = await _delete(client, point_layer, admin_auth_header, bad)

    assert resp.status_code == 422, resp.text
    assert await _gids(test_db_session, point_layer) == gids


async def test_more_than_the_cap_is_refused(
    client: AsyncClient, admin_auth_header: dict, test_db_session, point_layer
):
    gids = await _add_points(client, admin_auth_header, point_layer)
    resp = await _delete(
        client,
        point_layer,
        admin_auth_header,
        [gids[0]] + list(range(10**6, 10**6 + MAX_FEATURES_PER_BATCH)),
    )
    assert resp.status_code == 422, resp.text
    assert f"at most {MAX_FEATURES_PER_BATCH} items" in resp.json()["detail"]
    assert await _gids(test_db_session, point_layer) == gids

    empty = await _delete(client, point_layer, admin_auth_header, [])
    assert empty.status_code == 422, empty.text


async def test_a_stale_table_id_is_refused_and_deletes_nothing(
    client: AsyncClient, admin_auth_header: dict, test_db_session, point_layer
):
    gids = await _add_points(client, admin_auth_header, point_layer)
    read = await client.get(
        f"/datasets/{point_layer.id}/features/{gids[0]}", headers=admin_auth_header
    )
    table_id = read.json()["table_id"]
    stale = str(int(table_id) + 1)

    resp = await _delete(
        client, point_layer, admin_auth_header, gids[:2], table_id=stale
    )

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "dataset_replaced"
    assert await _gids(test_db_session, point_layer) == gids

    fresh = await _delete(
        client, point_layer, admin_auth_header, gids[:2], table_id=table_id
    )
    assert fresh.status_code == 200, fresh.text
    assert await _gids(test_db_session, point_layer) == gids[2:]


async def test_a_non_owner_editor_is_refused(
    client: AsyncClient,
    admin_auth_header: dict,
    editor_auth_header: dict,
    test_db_session,
    point_layer,
):
    gids = await _add_points(client, admin_auth_header, point_layer)
    resp = await _delete(client, point_layer, editor_auth_header, gids[:1])
    assert resp.status_code == 403, resp.text
    assert await _gids(test_db_session, point_layer) == gids


async def test_a_private_dataset_the_caller_cannot_see_is_not_found(
    client: AsyncClient,
    admin_auth_header: dict,
    editor_auth_header: dict,
    test_db_session,
    private_layer,
):
    gids = await _add_points(client, admin_auth_header, private_layer)
    resp = await _delete(client, private_layer, editor_auth_header, gids[:1])
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "Dataset not found"
    assert await _gids(test_db_session, private_layer) == gids


async def test_refused_while_dataset_editing_is_off(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    point_layer,
    monkeypatch,
):
    import app.core.persistent_config as pc

    gids = await _add_points(client, admin_auth_header, point_layer)

    class _AlwaysOff:
        async def get(self, _db):
            return False

    monkeypatch.setattr(pc, "ENABLE_DATASET_EDITING", _AlwaysOff())
    resp = await _delete(client, point_layer, admin_auth_header, gids[:1])
    assert resp.status_code == 403, resp.text
    assert await _gids(test_db_session, point_layer) == gids


async def test_rows_without_geometry_are_deleted(
    client: AsyncClient, admin_auth_header: dict, test_db_session, point_layer
):
    gids = await _add_points(client, admin_auth_header, point_layer)
    bare = await test_db_session.scalar(
        text(
            f"INSERT INTO data.{point_layer.table_name} (name) "
            "VALUES ('no geometry') RETURNING gid"
        )
    )
    await test_db_session.commit()

    resp = await _delete(client, point_layer, admin_auth_header, [bare, gids[0]])

    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted"] == 2
    assert await _gids(test_db_session, point_layer) == gids[1:]
    count, _ = await _catalog_state(test_db_session, point_layer)
    assert count == 3


async def test_the_rows_page_names_the_table_a_batch_delete_checks(
    client: AsyncClient, admin_auth_header: dict, test_db_session, point_layer
):
    gids = await _add_points(client, admin_auth_header, point_layer)
    page = await client.get(
        f"/datasets/{point_layer.id}/rows/", headers=admin_auth_header
    )
    assert page.status_code == 200, page.text
    read = await client.get(
        f"/datasets/{point_layer.id}/features/{gids[0]}", headers=admin_auth_header
    )
    table_id = page.json()["table_id"]
    assert table_id == read.json()["table_id"]

    resp = await _delete(
        client, point_layer, admin_auth_header, gids[:1], table_id=table_id
    )
    assert resp.status_code == 200, resp.text
