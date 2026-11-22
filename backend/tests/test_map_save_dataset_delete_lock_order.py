"""A map save takes the datasets it adds or repoints layers onto before any
layer row, so it and a dataset delete wait on each other in one order and never
deadlock, and a save that adds nothing waits on no dataset change."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

import app.core.db as db_module
import app.modules.catalog.maps.service_diff as service_diff
import app.modules.catalog.maps.service_layers as service_layers
from app.modules.catalog.datasets.domain import service_lifecycle
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.catalog.maps.models import MapLayer
from app.processing.ingest.manifest_schemas import ManifestApplyRequest
from app.processing.ingest.manifest_service import apply_manifest
from tests.factories import create_dataset, create_user
from tests.lock_wait import await_lock_wait_query
from tests.test_dataset_delete_shared_maps import _vector_dataset
from tests.test_embed_tokens import _cleanup_data_table
from tests.test_manifest_maps_dry_run import _body, _http_request, _layer, _person
from tests.test_map_share_waits_on_dataset_change import _drain, _until_blocked

pytestmark = pytest.mark.usefixtures("_init_tile_pool_for_tests")


def _entry(key: str, dataset_id: uuid.UUID, *, republish: bool = False) -> dict:
    """A private map with one keyed layer on the dataset; a republish changes
    that layer and adds a second one on the same dataset."""
    layers = [
        _layer("parks", dataset_id=str(dataset_id), opacity=0.5 if republish else 1.0)
    ]
    if republish:
        layers.append(_layer("more", dataset_id=str(dataset_id)))
    return {"key": key, "name": "Parks", "styling": "replace", "layers": layers}


async def _manifest(session, world, *, republish: bool):
    body = _body(
        _entry(world["key"], world["dataset_id"], republish=republish), dry_run=False
    )
    response = await apply_manifest(
        session,
        ManifestApplyRequest.model_validate(body),
        world["owner"],
        _http_request(),
    )
    [result] = response.maps
    return result


@pytest.fixture
async def world(client: AsyncClient, admin_auth_header: dict, test_db_session):
    """An editor's private map, published by a manifest, with one keyed layer
    on the editor's vector dataset."""
    owner, headers = await _person(client, test_db_session, admin_auth_header)
    dataset = await _vector_dataset(test_db_session, owner.id)
    world = {
        "owner": owner,
        "headers": headers,
        "dataset_id": dataset.id,
        "title": dataset.record.title,
        "table": dataset.table_name,
        "key": f"lock-order-{uuid.uuid4().hex[:8]}",
    }
    created = await _manifest(test_db_session, world, republish=False)
    assert created.action == "create", created
    world["map_id"] = created.map_id
    world["layer_id"] = await test_db_session.scalar(
        sa.select(MapLayer.id).where(MapLayer.map_id == created.map_id)
    )
    yield world
    await _cleanup_data_table(test_db_session, world["table"])


@pytest.fixture
async def children():
    tasks: list[asyncio.Task] = []
    yield tasks
    await _drain(tasks)


async def _delete(client: AsyncClient, world):
    return await client.request(
        "DELETE",
        f"/datasets/{world['dataset_id']}",
        json={"confirm_title": world["title"]},
        headers=world["headers"],
    )


async def _save(client: AsyncClient, world, writer: str) -> tuple[object, str]:
    """Change the map's layer on the dataset and add one on it, or with an
    ``-add`` writer only add one. Returns the status, or the manifest
    action, and the body's text."""
    map_id, headers = world["map_id"], world["headers"]
    dataset_id, layer_id = str(world["dataset_id"]), str(world["layer_id"])
    if writer == "manifest":
        async with db_module.async_session() as session:
            result = await _manifest(session, world, republish=True)
        return result.action, result.model_dump_json()
    if writer == "put":
        resp = await client.put(
            f"/maps/{map_id}",
            json={
                "layers": [
                    {"id": layer_id, "dataset_id": dataset_id, "opacity": 0.5},
                    {"dataset_id": dataset_id},
                ]
            },
            headers=headers,
        )
    elif writer.startswith("patch"):
        body: dict = {"added": [{"dataset_id": dataset_id}]}
        if writer == "patch":
            body["updated"] = [{"id": layer_id, "opacity": 0.5}]
        resp = await client.patch(f"/maps/{map_id}/layers", json=body, headers=headers)
    else:
        resp = await client.post(
            f"/maps/{map_id}/layers", json={"dataset_id": dataset_id}, headers=headers
        )
    return resp.status_code, resp.text


def _pause_delete_after_its_stranding_check(monkeypatch):
    """Hold the delete with its dataset row taken; resolves the returned
    future with its backend pid and goes on once the event is set."""
    real = service_lifecycle._refuse_stranding_shared_maps
    held: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    go = asyncio.Event()

    async def pausing(session, dataset):
        await real(session, dataset)
        held.set_result(await session.scalar(sa.text("SELECT pg_backend_pid()")))
        await go.wait()

    monkeypatch.setattr(service_lifecycle, "_refuse_stranding_shared_maps", pausing)
    return held, go


_REFUSED = {
    "put": (403, "Cannot access one or more layer datasets"),
    "patch": (403, "Cannot access one or more layer datasets"),
    "patch-add": (403, "Cannot access one or more layer datasets"),
    "post-add": (403, "Cannot access this dataset"),
    "manifest": ("error", "Cannot access one or more layer datasets"),
}


@pytest.mark.parametrize("writer", list(_REFUSED))
async def test_a_save_behind_a_dataset_delete_waits_and_is_refused(
    client: AsyncClient, world, test_db_session, monkeypatch, children, writer: str
):
    held, go = _pause_delete_after_its_stranding_check(monkeypatch)
    children.append(asyncio.create_task(_delete(client, world)))
    try:
        delete_pid = await asyncio.wait_for(held, 30)
        children.append(asyncio.create_task(_save(client, world, writer)))
        waiting_on = await await_lock_wait_query(blocked_by=delete_pid)
    finally:
        go.set()
    deleted, (outcome, text) = await children[0], await children[1]

    assert deleted.status_code == 204, deleted.text
    status, marker = _REFUSED[writer]
    assert outcome == status, text
    assert marker in text
    assert "FOR KEY SHARE" in waiting_on, waiting_on
    assert not await test_db_session.scalar(
        sa.select(sa.func.count())
        .select_from(MapLayer)
        .where(MapLayer.map_id == world["map_id"])
    )


_SAVED = {"put": 200, "patch": 200, "post-add": 201, "manifest": "update"}


@pytest.mark.parametrize("writer", list(_SAVED))
async def test_a_delete_behind_a_save_that_adds_a_layer_waits_and_the_save_lands(
    client: AsyncClient, world, monkeypatch, children, writer: str
):
    real = service_layers.lock_new_layer_datasets

    async def locking(session, dataset_ids):
        gone = await real(session, dataset_ids)
        if not children:
            children.append(asyncio.create_task(_delete(client, world)))
            await _until_blocked(session, children[0])
        return gone

    for module in (service_layers, service_diff):
        monkeypatch.setattr(module, "lock_new_layer_datasets", locking)
    outcome, text = await _save(client, world, writer)

    assert outcome == _SAVED[writer], text
    assert children, "the save never took the dataset it adds a layer on"
    deleted = await children[0]
    assert deleted.status_code in (204, 409), deleted.text
    if deleted.status_code == 409:
        assert deleted.json()["code"] == "catalog_lock_conflict", deleted.text


@pytest.mark.parametrize("change", ["paint", "remove", "put-paint"])
async def test_a_save_that_adds_no_layer_waits_on_no_dataset_change(
    client: AsyncClient, world, change: str
):
    map_id, layer_id = world["map_id"], str(world["layer_id"])
    paint = {"circle-color": "#123456"}
    body = (
        {"updated": [{"id": layer_id, "paint": paint}]}
        if change == "paint"
        else {"removed": [layer_id]}
    )
    async with db_module.async_session() as holder:
        await holder.execute(
            sa.select(Dataset.id)
            .where(Dataset.id == world["dataset_id"])
            .with_for_update()
        )
        started = time.monotonic()
        if change == "put-paint":
            layer = {"id": layer_id, "dataset_id": str(world["dataset_id"])}
            resp = await client.put(
                f"/maps/{map_id}",
                json={"layers": [{**layer, "paint": paint}]},
                headers=world["headers"],
            )
        else:
            resp = await client.patch(
                f"/maps/{map_id}/layers", json=body, headers=world["headers"]
            )
        elapsed = time.monotonic() - started
        assert holder.in_transaction()
        await holder.rollback()

    assert resp.status_code == 200, resp.text
    assert elapsed < 1, elapsed


async def test_a_layer_update_a_delete_removed_meanwhile_is_refused(
    client: AsyncClient, world, monkeypatch, caplog
):
    """A dataset delete that commits after a PATCH read the map's layers
    cascades away the layer the PATCH updates; the PATCH answers the 400 a
    retry gets."""
    caplog.set_level(logging.INFO)
    deleted = []
    real = service_diff.bulk_check_dataset_access

    async def delete_first(*args, **kwargs):
        deleted.append(await _delete(client, world))
        return await real(*args, **kwargs)

    monkeypatch.setattr(service_diff, "bulk_check_dataset_access", delete_first)
    resp = await client.patch(
        f"/maps/{world['map_id']}/layers",
        json={
            "updated": [
                {"id": str(world["layer_id"]), "paint": {"circle-color": "#123456"}}
            ]
        },
        headers=world["headers"],
    )

    assert [r.status_code for r in deleted] == [204]
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == "Layer diff references layer ids outside this map"
    assert not [r for r in caplog.records if "Unhandled" in str(r.msg)]


@pytest.mark.parametrize("change", ["order", "paint-and-order"])
async def test_a_reorder_naming_a_layer_a_delete_removed_meanwhile_is_refused(
    client: AsyncClient, world, test_db_session, monkeypatch, caplog, change: str
):
    """A diff whose reorder rewrites a layer a dataset delete cascaded away
    after the diff read the map's layers answers the 400 a retry gets. The
    gap in the stored order makes the restack write that layer's row."""
    caplog.set_level(logging.INFO)
    other = await _vector_dataset(test_db_session, world["owner"].id)
    gone = {
        "dataset_id": other.id,
        "title": other.record.title,
        "headers": world["headers"],
    }
    table = other.table_name
    kept_id, moved_id = str(world["layer_id"]), str(uuid.uuid4())
    test_db_session.add(
        MapLayer(
            id=uuid.UUID(moved_id),
            map_id=world["map_id"],
            dataset_id=other.id,
            sort_order=5,
        )
    )
    await test_db_session.commit()
    deleted = []
    real = service_diff.bulk_check_dataset_access

    async def delete_first(*args, **kwargs):
        deleted.append(await _delete(client, gone))
        return await real(*args, **kwargs)

    monkeypatch.setattr(service_diff, "bulk_check_dataset_access", delete_first)
    body: dict = {"order": [moved_id, kept_id]}
    if change == "paint-and-order":
        body["updated"] = [{"id": kept_id, "paint": {"circle-color": "#123456"}}]
    try:
        resp = await client.patch(
            f"/maps/{world['map_id']}/layers", json=body, headers=world["headers"]
        )
    finally:
        await _cleanup_data_table(test_db_session, table)

    assert [r.status_code for r in deleted] == [204]
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == "Layer diff references layer ids outside this map"
    assert not [r for r in caplog.records if "Unhandled" in str(r.msg)]


_MISSING_DATASET = "00000000-0000-4000-8000-000000004001"
_UNKNOWN_LAYER = "00000000-0000-4000-8000-000000004002"


async def _add_with_unknown_layer(client: AsyncClient, world, dataset_id: str):
    return await client.patch(
        f"/maps/{world['map_id']}/layers",
        json={
            "added": [{"dataset_id": dataset_id}],
            "updated": [{"id": _UNKNOWN_LAYER, "opacity": 0.5}],
        },
        headers=world["headers"],
    )


@pytest.fixture
async def hidden_dataset(client: AsyncClient, admin_auth_header, test_db_session):
    """Another editor's private dataset the map's owner can't read."""
    _, other_id = await create_user(client, admin_auth_header, "editor")
    dataset = await create_dataset(
        test_db_session, created_by=uuid.UUID(other_id), visibility="private"
    )
    await test_db_session.commit()
    return dataset.id


async def test_an_unreadable_added_dataset_answers_as_a_missing_one(
    client: AsyncClient, world, hidden_dataset
):
    missing = await _add_with_unknown_layer(client, world, _MISSING_DATASET)
    hidden = await _add_with_unknown_layer(client, world, str(hidden_dataset))

    assert missing.status_code == 403, missing.text
    assert (hidden.status_code, hidden.json()) == (403, missing.json())


async def test_an_unreadable_added_dataset_under_a_change_is_not_waited_on(
    client: AsyncClient, world, hidden_dataset
):
    missing = await _add_with_unknown_layer(client, world, _MISSING_DATASET)
    async with db_module.async_session() as holder:
        await holder.execute(
            sa.select(Dataset.id).where(Dataset.id == hidden_dataset).with_for_update()
        )
        started = time.monotonic()
        hidden = await _add_with_unknown_layer(client, world, str(hidden_dataset))
        elapsed = time.monotonic() - started
        await holder.rollback()

    assert (hidden.status_code, hidden.json()) == (403, missing.json())
    assert elapsed < 1, elapsed


@pytest.mark.parametrize("writer", ["put", "manifest"])
async def test_a_repoint_that_waited_while_a_delete_took_its_layer_answers_409(
    client: AsyncClient, world, test_db_session, children, caplog, writer: str
):
    """A full replace that repoints a layer to a busy dataset waits holding
    only the map row; a delete of the layer's old dataset meanwhile removes
    the layer, so the save answers 409 instead of writing a gone row."""
    caplog.set_level(logging.INFO)
    target = await create_dataset(
        test_db_session, created_by=world["owner"].id, visibility="private"
    )
    await test_db_session.commit()
    target_id, layer_id = target.id, str(world["layer_id"])

    async def repoint():
        if writer == "manifest":
            entry = {
                "key": world["key"],
                "name": "Parks",
                "styling": "replace",
                "layers": [_layer("parks", dataset_id=str(target_id))],
            }
            async with db_module.async_session() as session:
                response = await apply_manifest(
                    session,
                    ManifestApplyRequest.model_validate(_body(entry, dry_run=False)),
                    world["owner"],
                    _http_request(),
                )
            [result] = response.maps
            return result.action, result.model_dump_json()
        resp = await client.put(
            f"/maps/{world['map_id']}",
            json={"layers": [{"id": layer_id, "dataset_id": str(target_id)}]},
            headers=world["headers"],
        )
        return resp.status_code, resp.text

    async with db_module.async_session() as holder:
        await holder.execute(
            sa.select(Dataset.id).where(Dataset.id == target_id).with_for_update()
        )
        children.append(asyncio.create_task(repoint()))
        await _until_blocked(holder, children[0])
        async with db_module.async_session() as third:
            await third.execute(
                sa.delete(Record).where(
                    Record.id
                    == sa.select(Dataset.record_id)
                    .where(Dataset.id == world["dataset_id"])
                    .scalar_subquery()
                )
            )
            await third.commit()
        await holder.rollback()
    outcome, text = await children[0]

    if writer == "put":
        assert outcome == 409, text
        assert '"code":"catalog_lock_conflict"' in text.replace(" ", "")
        assert "A dataset on this map is being changed. Retry shortly." in text
    else:
        assert outcome == "error", text
        assert "A099" in text
    logged = [str(r.msg) for r in caplog.records]
    assert not [msg for msg in logged if "Unhandled" in msg or "StaleData" in msg]
