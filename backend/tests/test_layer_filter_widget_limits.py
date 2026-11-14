"""A layer filter change that puts a dashboard widget past the aggregate's limits is refused."""

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from tests.test_dataset_aggregate import _dropped
from tests.test_map_dashboard_config import _map_with_layers, _store, _widget
from tests.test_map_save_keeps_unreadable_layers import _map_with_hidden_middle_layer

pytestmark = pytest.mark.anyio

READS = ["indicator:1", "indicator:2", "indicator:3"]


def _listing(count: int) -> list:
    return ["in", ["get", "kind"], ["literal", [f"v{i}" for i in range(count)]]]


async def _layer_filter(session, layer_id: str):
    return await session.scalar(
        text("SELECT filter FROM catalog.map_layers WHERE id = :id"),
        {"id": uuid.UUID(layer_id)},
    )


async def _patch(client, headers, map_id, layer_id, filter_):
    return await client.patch(
        f"/maps/{map_id}/layers",
        json={"updated": [{"id": layer_id, "filter": filter_}]},
        headers=headers,
    )


async def _put(client, headers, map_id, dataset, layer_id, filter_, dashboard=None):
    body: dict = {
        "layers": [{"id": layer_id, "dataset_id": str(dataset.id), "filter": filter_}]
    }
    if dashboard is not None:
        body["dashboard_config"] = dashboard
    return await client.put(f"/maps/{map_id}", json=body, headers=headers)


async def _with_widget(client, headers, map_id, widget):
    resp = await client.put(
        f"/maps/{map_id}",
        json={"dashboard_config": {"readable": READS, "widgets": [widget]}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


def _refused(resp, widget) -> None:
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["widgets"] == [
        {
            "id": widget["id"],
            "layer_id": widget["layer_id"],
            "reason": "filter_too_large",
        }
    ]


ROUTES = ["patch_layers", "put_layers", "put_layers_and_dashboard"]


async def _save(route, client, headers, map_id, dataset, layer_id, filter_, widget):
    if route == "patch_layers":
        return await _patch(client, headers, map_id, layer_id, filter_)
    dashboard = None
    if route == "put_layers_and_dashboard":
        dashboard = {"readable": READS, "widgets": [widget]}
    return await _put(
        client, headers, map_id, dataset, layer_id, filter_, dashboard=dashboard
    )


@pytest.mark.parametrize("route", ROUTES)
async def test_a_layer_filter_past_the_limits_is_refused_for_a_plain_widget(
    client: AsyncClient, admin_auth_header: dict, test_db_session, route
):
    async with _dropped(test_db_session) as dataset:
        map_id, (layer_id,) = await _map_with_layers(client, admin_auth_header, dataset)
        widget = _widget("indicator", layer_id)
        await _with_widget(client, admin_auth_header, map_id, widget)

        resp = await _save(
            route,
            client,
            admin_auth_header,
            map_id,
            dataset,
            layer_id,
            _listing(1001),
            widget,
        )

        _refused(resp, widget)
        assert await _layer_filter(test_db_session, layer_id) is None


@pytest.mark.parametrize("route", ROUTES)
async def test_a_layer_filter_that_takes_a_widget_filter_past_the_limits_is_refused(
    client: AsyncClient, admin_auth_header: dict, test_db_session, route
):
    async with _dropped(test_db_session) as dataset:
        map_id, (layer_id,) = await _map_with_layers(client, admin_auth_header, dataset)
        widget = _widget("indicator", layer_id, v=3, filter=_listing(600))
        await _with_widget(client, admin_auth_header, map_id, widget)

        resp = await _save(
            route,
            client,
            admin_auth_header,
            map_id,
            dataset,
            layer_id,
            _listing(600),
            widget,
        )

        _refused(resp, widget)
        assert await _layer_filter(test_db_session, layer_id) is None


@pytest.mark.parametrize("route", ["patch_layers", "put_layers"])
async def test_a_layer_with_no_widgets_saves_a_filter_past_the_limits(
    client: AsyncClient, admin_auth_header: dict, test_db_session, route
):
    async with _dropped(test_db_session) as dataset:
        map_id, (layer_id, other_id) = await _map_with_layers(
            client, admin_auth_header, dataset, dataset
        )
        await _with_widget(
            client, admin_auth_header, map_id, _widget("indicator", other_id)
        )

        if route == "patch_layers":
            resp = await _patch(
                client, admin_auth_header, map_id, layer_id, _listing(1001)
            )
        else:
            resp = await client.put(
                f"/maps/{map_id}",
                json={
                    "layers": [
                        {
                            "id": layer_id,
                            "dataset_id": str(dataset.id),
                            "filter": _listing(1001),
                        },
                        {"id": other_id, "dataset_id": str(dataset.id)},
                    ]
                },
                headers=admin_auth_header,
            )

        assert resp.status_code == 200, resp.text
        assert await _layer_filter(test_db_session, layer_id) == _listing(1001)


async def test_a_save_that_keeps_a_layer_filter_is_not_refused_for_it(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    async with _dropped(test_db_session) as dataset:
        map_id, (layer_id,) = await _map_with_layers(client, admin_auth_header, dataset)
        widget = _widget("indicator", layer_id)
        await _with_widget(client, admin_auth_header, map_id, widget)
        await test_db_session.execute(
            text(
                "UPDATE catalog.map_layers SET filter = cast(:f AS jsonb) WHERE id = :id"
            ),
            {"f": json.dumps(_listing(1001)), "id": uuid.UUID(layer_id)},
        )
        await test_db_session.commit()

        put = await _put(
            client, admin_auth_header, map_id, dataset, layer_id, _listing(1001)
        )
        renamed = await client.patch(
            f"/maps/{map_id}/layers",
            json={"updated": [{"id": layer_id, "display_name": "Renamed"}]},
            headers=admin_auth_header,
        )

        assert put.status_code == 200, put.text
        assert renamed.status_code == 200, renamed.text


async def test_a_widget_the_client_keeps_without_showing_is_checked(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    async with _dropped(test_db_session) as dataset:
        map_id, (layer_id,) = await _map_with_layers(client, admin_auth_header, dataset)
        kept = _widget("pie_chart", layer_id)
        await _store(test_db_session, map_id, {"version": 1, "widgets": [kept]})

        # A client reading the earlier widgets keeps the pie chart unseen.
        resp = await _put(
            client,
            admin_auth_header,
            map_id,
            dataset,
            layer_id,
            _listing(1001),
            dashboard={"widgets": []},
        )

        _refused(resp, kept)


@pytest.mark.parametrize("path", ["layers", "layers/"])
async def test_a_filter_change_on_a_layer_the_caller_cant_read_names_no_widget(
    client: AsyncClient, admin_auth_header: dict, test_db_session, path
):
    owner, map_id, layer_ids, _ = await _map_with_hidden_middle_layer(
        client, admin_auth_header, test_db_session
    )
    hidden = _widget("indicator", layer_ids["hidden"])
    await _store(test_db_session, map_id, {"version": 1, "widgets": [hidden]})

    resp = await client.patch(
        f"/maps/{map_id}/{path}",
        json={"updated": [{"id": layer_ids["hidden"], "filter": _listing(1001)}]},
        headers=owner,
    )

    assert resp.status_code == 403, resp.text
    assert hidden["id"] not in resp.text
    assert await _layer_filter(test_db_session, layer_ids["hidden"]) is None


@pytest.mark.parametrize("own", [None, ["==", ["get", "kind"], "keep"]])
async def test_a_layer_filter_on_a_column_the_layer_lacks_is_not_counted(
    client: AsyncClient, admin_auth_header: dict, test_db_session, own
):
    gone = ["in", ["get", "gone"], ["literal", [f"v{i}" for i in range(1001)]]]
    async with _dropped(test_db_session) as dataset:
        map_id, (layer_id,) = await _map_with_layers(client, admin_auth_header, dataset)
        widget = (
            _widget("indicator", layer_id)
            if own is None
            else _widget("indicator", layer_id, v=3, filter=own)
        )
        await _with_widget(client, admin_auth_header, map_id, widget)

        resp = await _patch(client, admin_auth_header, map_id, layer_id, gone)

        assert resp.status_code == 200, resp.text


async def _set_columns(session, dataset, columns) -> None:
    await session.execute(
        text(
            "UPDATE catalog.datasets SET column_info = cast(:c AS jsonb) WHERE id = :id"
        ),
        {"c": json.dumps(columns), "id": dataset.id},
    )
    await session.commit()


async def test_a_filter_on_a_layer_with_no_columns_is_not_counted(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    async with _dropped(test_db_session) as dataset:
        await _set_columns(test_db_session, dataset, [])
        map_id, (layer_id,) = await _map_with_layers(client, admin_auth_header, dataset)
        await _with_widget(
            client, admin_auth_header, map_id, _widget("indicator", layer_id)
        )

        resp = await _patch(client, admin_auth_header, map_id, layer_id, _listing(1001))

        assert resp.status_code == 200, resp.text


@pytest.mark.parametrize("route", ["patch_layers", "put_layers"])
async def test_a_large_whole_number_the_viewer_sends_is_counted(
    client: AsyncClient, admin_auth_header: dict, test_db_session, route
):
    async with _dropped(test_db_session) as dataset:
        await _set_columns(
            test_db_session,
            dataset,
            [
                {"name": "kind", "type": "text"},
                {"name": "score", "type": "double precision"},
            ],
        )
        map_id, (layer_id,) = await _map_with_layers(client, admin_auth_header, dataset)
        widget = _widget("indicator", layer_id)
        await _with_widget(client, admin_auth_header, map_id, widget)
        filter_ = ["all", [">", ["get", "score"], 1e20], _listing(1000)]

        resp = await _save(
            route, client, admin_auth_header, map_id, dataset, layer_id, filter_, widget
        )

        _refused(resp, widget)
