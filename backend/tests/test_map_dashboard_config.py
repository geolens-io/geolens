"""A map's dashboard_config: validation, reads by audience, saves and forks."""

import json
import uuid
from typing import Annotated, get_args

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from pydantic import Field, TypeAdapter
from sqlalchemy import text

import app.core.db as db_module
from app.modules.auth.models import User
from app.modules.catalog.maps import dashboard
from app.modules.catalog.maps.dashboard import (
    DashboardConfigInput,
    drop_repointed,
    fork_dashboard,
    merge_dashboard,
    render_dashboard,
    shows_widgets,
)
from app.modules.catalog.maps.service_crud import get_map, update_map
from app.modules.catalog.widgets.schemas import (
    BarChartWidget,
    CategorySelectorWidget,
    IndicatorWidget,
)
from tests.factories import create_dataset, create_user, get_user_id
from tests.test_embed_token_creator_access import _embed


_WIDGET_DEFAULTS = {
    "indicator": {"config": {"stat": "count"}},
    "bar_chart": {
        "scope": "view",
        "config": {"column": "kind", "stat": "sum", "stat_column": "area"},
    },
    "histogram": {"config": {"column": "height", "bins": 12}},
    "category_selector": {"config": {"column": "kind", "multiple": False}},
    "gauge": {},
}


@pytest.fixture
def histogram_unregistered(monkeypatch):
    """Clients register every dashboard type the schema has; this one plays a type they don't yet."""
    registered = IndicatorWidget | BarChartWidget | CategorySelectorWidget
    monkeypatch.setattr(dashboard, "_ACCEPTED", get_args(registered))
    monkeypatch.setattr(
        dashboard,
        "_ACCEPTED_ADAPTER",
        TypeAdapter(Annotated[registered, Field(discriminator="type")]),
    )


def _widget(type, layer_id=None, widget_id=None, **extra) -> dict:
    return {
        "id": str(widget_id or uuid.uuid4()),
        "type": type,
        "v": 1,
        **({} if layer_id is None else {"layer_id": str(layer_id)}),
        **_WIDGET_DEFAULTS[type],
        **extra,
    }


def _merge(sent, stored, readable=(), hidden=(), repointed=()):
    return merge_dashboard(
        None if sent is None else DashboardConfigInput.model_validate(sent),
        drop_repointed(stored, set(repointed)),
        layer_ids=set(readable) | set(hidden),
        hidden_layer_ids=set(hidden),
    )


def _ids(widgets) -> list[str]:
    return [str(w["id"]) for w in widgets]


# --- Database-free rules ----------------------------------------------------


class TestMergeDashboard:
    def test_kept_widgets_go_back_next_to_the_widget_stored_before_them(self):
        shown, hidden = uuid.uuid4(), uuid.uuid4()
        a, b = _widget("indicator", shown), _widget("indicator", shown)
        on_hidden, future = _widget("indicator", hidden), _widget("gauge")
        stored = {"version": 1, "widgets": [a, on_hidden, b, future]}
        sent = DashboardConfigInput.model_validate({"widgets": [b, a]})

        merged = _merge(sent, stored, readable={shown}, hidden={hidden})

        assert [w["id"] for w in merged["widgets"]] == [
            b["id"],
            future["id"],
            a["id"],
            on_hidden["id"],
        ]

    def test_widgets_on_layers_the_map_no_longer_has_are_dropped(self):
        shown = uuid.uuid4()
        stored = {"version": 1, "widgets": [_widget("indicator", uuid.uuid4())]}
        sent = DashboardConfigInput.model_validate(
            {"widgets": [_widget("indicator", shown)]}
        )

        merged = _merge(sent, stored, readable={shown})

        assert [w["layer_id"] for w in merged["widgets"]] == [str(shown)]

    def test_null_removes_what_the_editor_sees_and_keeps_the_rest(self):
        shown, hidden = uuid.uuid4(), uuid.uuid4()
        on_hidden = _widget("indicator", hidden)
        stored = {"version": 1, "widgets": [_widget("indicator", shown), on_hidden]}

        merged = _merge(None, stored, readable={shown}, hidden={hidden})
        assert merged == {"version": 1, "widgets": [on_hidden]}
        assert (
            _merge(
                None,
                {"version": 1, "widgets": [_widget("indicator", shown)]},
                readable={shown},
                hidden={hidden},
            )
            is None
        )

    @pytest.mark.parametrize("hidden", [True, False])
    def test_a_sent_widget_must_be_on_a_layer_the_editor_can_read(self, hidden):
        layer = uuid.uuid4()
        sent = DashboardConfigInput.model_validate(
            {"widgets": [_widget("indicator", layer)]}
        )
        with pytest.raises(HTTPException) as exc:
            _merge(sent, None, hidden={layer} if hidden else ())
        assert exc.value.status_code == 422
        assert exc.value.detail["widget_ids"] == [str(sent.widgets[0].id)]

    def test_a_sent_widget_cannot_replace_a_widget_on_a_hidden_layer(self):
        shown, hidden = uuid.uuid4(), uuid.uuid4()
        on_hidden = _widget("indicator", hidden)
        stored = {"version": 1, "widgets": [on_hidden]}

        with pytest.raises(HTTPException) as exc:
            _merge(
                {"widgets": [_widget("indicator", shown, widget_id=on_hidden["id"])]},
                stored,
                readable={shown},
                hidden={hidden},
            )
        assert exc.value.status_code == 422
        assert exc.value.detail["widget_ids"] == [on_hidden["id"]]

    def test_the_cap_counts_kept_widgets_without_naming_them(self):
        shown, hidden = uuid.uuid4(), uuid.uuid4()
        stored = {"version": 1, "widgets": [_widget("indicator", hidden)]}
        sent = {"widgets": [_widget("indicator", shown) for _ in range(50)]}

        with pytest.raises(HTTPException) as exc:
            _merge(sent, stored, readable={shown}, hidden={hidden})
        assert exc.value.status_code == 422
        assert exc.value.detail == "A dashboard holds at most 50 widgets"
        assert len(_merge(sent, None, readable={shown})["widgets"]) == 50

    def test_widgets_on_a_repointed_layer_are_dropped(self):
        moved, hidden_moved, kept = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        future = _widget("gauge")
        stored = {
            "version": 1,
            "widgets": [
                _widget("indicator", moved),
                _widget("indicator", hidden_moved),
                future,
            ],
        }
        merged = _merge(
            {"widgets": []},
            stored,
            readable={moved, kept},
            hidden={hidden_moved},
            repointed={moved, hidden_moved},
        )
        assert _ids(merged["widgets"]) == [future["id"]]

        pruned = drop_repointed(stored, {moved})
        assert _ids(pruned["widgets"]) == [
            stored["widgets"][1]["id"],
            future["id"],
        ]
        assert drop_repointed(stored, {kept}) is stored
        newer = {"version": 2, "widgets": [_widget("indicator", moved)]}
        assert drop_repointed(newer, {moved}) is newer

    def test_every_dashboard_type_round_trips(self):
        shown = uuid.uuid4()
        widgets = [
            _widget(kind, shown)
            for kind in ("indicator", "bar_chart", "histogram", "category_selector")
        ]
        stored = {"version": 1, "widgets": widgets}

        rendered = render_dashboard(stored, [shown]).model_dump(mode="json")
        assert _shape(rendered["widgets"]) == _shape(widgets)
        assert rendered["widgets"][2]["config"] == {"column": "height", "bins": 12}
        assert rendered["widgets"][3]["config"] == {"column": "kind", "multiple": False}
        assert shows_widgets({"version": 1, "widgets": widgets[2:]}, [shown])
        merged = _merge({"widgets": widgets}, None, readable={shown})
        assert _ids(merged["widgets"]) == _ids(widgets)

    def test_types_clients_cannot_show_yet_are_kept(self, histogram_unregistered):
        shown = uuid.uuid4()
        histogram = _widget("histogram", shown)
        stored = {"version": 1, "widgets": [histogram]}

        assert render_dashboard(stored, [shown]) is None
        assert shows_widgets(stored, [shown]) is False
        merged = _merge({"widgets": []}, stored, readable={shown})
        assert merged["widgets"] == [histogram]

    @pytest.mark.parametrize("kind", ["unparseable", "unshown_type"])
    def test_a_widget_that_goes_back_unseen_cannot_be_replaced_by_id(
        self, kind, request
    ):
        shown = uuid.uuid4()
        if kind == "unparseable":
            unseen = _widget("indicator", shown, v=2)
        else:
            request.getfixturevalue("histogram_unregistered")
            unseen = _widget("histogram", shown)
        stored = {"version": 1, "widgets": [unseen]}

        with pytest.raises(HTTPException) as exc:
            _merge(
                {"widgets": [_widget("indicator", shown, widget_id=unseen["id"])]},
                stored,
                readable={shown},
            )
        assert exc.value.status_code == 422
        assert exc.value.detail["widget_ids"] == [unseen["id"]]

        merged = _merge({"widgets": []}, stored, readable={shown})
        assert merged["widgets"] == [unseen]

    def test_a_dashboard_a_newer_server_saved_is_not_overwritten(self):
        with pytest.raises(HTTPException) as exc:
            _merge(DashboardConfigInput(), {"version": 2, "widgets": []})
        assert exc.value.status_code == 409


def _shape(widgets) -> list[tuple[str, str, str]]:
    return [(w["id"], w["type"], str(w["layer_id"])) for w in widgets]


def test_render_keeps_only_widgets_on_the_given_layers_and_parseable_ones():
    shown, other = uuid.uuid4(), uuid.uuid4()
    keep = _widget("bar_chart", shown)
    stored = {
        "version": 1,
        "widgets": [keep, _widget("indicator", other), _widget("gauge")],
    }

    rendered = render_dashboard(stored, [str(shown)]).model_dump(mode="json")
    assert render_dashboard(stored, [str(other)]).widgets[0].layer_id == other
    assert render_dashboard(stored, [uuid.uuid4()]) is None

    assert rendered["version"] == 1
    assert _shape(rendered["widgets"]) == _shape([keep])
    assert rendered["widgets"][0]["config"]["stat_column"] == "area"
    assert render_dashboard(None, [shown]) is None


def test_the_list_flag_agrees_with_what_a_read_renders():
    shown, other = uuid.uuid4(), uuid.uuid4()
    upper = {**_widget("indicator", shown), "layer_id": str(shown).upper()}
    cases = [
        None,
        {"version": 1, "widgets": []},
        {"version": 1, "widgets": [_widget("indicator", other)]},
        {"version": 1, "widgets": [_widget("indicator", shown)]},
        {"version": 1, "widgets": [upper]},
        {"version": 1, "widgets": [_widget("histogram", shown)]},
        {"version": 1, "widgets": [_widget("category_selector", shown)]},
        # Unknown types and broken rows.
        {"version": 1, "widgets": [_widget("gauge", shown)]},
        {
            "version": 1,
            "widgets": [{**_widget("indicator", shown), "config": {"stat": 7}}],
        },
        {"version": 1, "widgets": ["not a widget", {"layer_id": None}]},
        {
            "version": 1,
            "widgets": [_widget("gauge", shown), _widget("bar_chart", shown)],
        },
    ]
    for stored in cases:
        expected = render_dashboard(stored, [shown]) is not None
        assert shows_widgets(stored, [shown]) is expected, stored


def test_fork_remaps_layers_and_drops_what_it_cannot_copy():
    kept_layer, skipped_layer, copy = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    widget = _widget("indicator", kept_layer)
    stored = {
        "version": 1,
        "widgets": [widget, _widget("indicator", skipped_layer), _widget("gauge")],
    }

    forked = fork_dashboard(stored, {kept_layer: copy})

    assert forked["version"] == 1
    assert _shape(forked["widgets"]) == [(widget["id"], "indicator", str(copy))]
    assert fork_dashboard({"version": 2, "widgets": [widget]}, {}) is None


# --- Through the API ----------------------------------------------------------


async def _map_with_layers(client, headers, *datasets, visibility="private"):
    resp = await client.post(
        "/maps/", json={"name": f"Dash {uuid.uuid4().hex[:6]}"}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    map_id = resp.json()["id"]
    layer_ids = []
    for order, dataset in enumerate(datasets):
        added = await client.post(
            f"/maps/{map_id}/layers",
            json={"dataset_id": str(dataset.id), "sort_order": order},
            headers=headers,
        )
        assert added.status_code == 201, added.text
        layer_ids.append(added.json()["id"])
    if visibility != "private":
        resp = await client.put(
            f"/maps/{map_id}", json={"visibility": visibility}, headers=headers
        )
        assert resp.status_code == 200, resp.text
    return map_id, layer_ids


async def _stored(session, map_id) -> dict | None:
    return await session.scalar(
        text("SELECT dashboard_config FROM catalog.maps WHERE id = :id"),
        {"id": uuid.UUID(map_id)},
    )


async def _store(session, map_id, value: dict) -> None:
    await session.execute(
        text(
            "UPDATE catalog.maps SET dashboard_config = cast(:v AS jsonb) "
            "WHERE id = :id"
        ),
        {"v": json.dumps(value), "id": uuid.UUID(map_id)},
    )
    await session.commit()


async def _make_private(session, dataset) -> None:
    await session.execute(
        text("UPDATE catalog.records SET visibility = 'private' WHERE id = :id"),
        {"id": dataset.record_id},
    )
    await session.commit()


class TestDashboardConfigApi:
    async def test_save_reload_and_history(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(test_db_session, created_by=admin_id)
        map_id, (layer_id,) = await _map_with_layers(client, admin_auth_header, dataset)
        widgets = [
            _widget("indicator", layer_id, title="Parcels"),
            _widget("bar_chart", layer_id),
            _widget("histogram", layer_id),
            _widget("category_selector", layer_id),
        ]

        resp = await client.put(
            f"/maps/{map_id}",
            json={"dashboard_config": {"version": 1, "widgets": widgets}},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        assert [w["id"] for w in resp.json()["dashboard_config"]["widgets"]] == [
            w["id"] for w in widgets
        ]

        # A save that leaves the field out keeps the dashboard.
        resp = await client.put(
            f"/maps/{map_id}", json={"name": "Renamed"}, headers=admin_auth_header
        )
        assert resp.status_code == 200
        reloaded = (
            await client.get(f"/maps/{map_id}", headers=admin_auth_header)
        ).json()
        assert reloaded["dashboard_config"]["widgets"][0]["title"] == "Parcels"
        assert reloaded["dashboard_config"]["widgets"][1]["scope"] == "view"
        assert [w["config"] for w in reloaded["dashboard_config"]["widgets"][2:]] == [
            w["config"] for w in widgets[2:]
        ]

        history = (
            await client.get(f"/maps/{map_id}/history", headers=admin_auth_header)
        ).json()["events"]
        assert any(
            e["action"] == "map.config_update"
            and e["details"]["changed_fields"] == ["dashboard_config"]
            for e in history
        )

        resp = await client.put(
            f"/maps/{map_id}",
            json={"dashboard_config": None},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        assert resp.json()["dashboard_config"] is None
        assert await _stored(test_db_session, map_id) is None

    async def test_refuses_unknown_types_and_layers_off_the_map(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(test_db_session, created_by=admin_id)
        map_id, (layer_id,) = await _map_with_layers(client, admin_auth_header, dataset)
        _other_map, (other_layer,) = await _map_with_layers(
            client, admin_auth_header, dataset
        )

        for widgets in (
            [{**_widget("indicator", layer_id), "type": "gauge"}],
            [{**_widget("histogram", layer_id), "config": {"column": "h", "bins": 51}}],
            [{**_widget("category_selector", layer_id), "config": {"multiple": True}}],
            [{**_widget("indicator", layer_id), "extra": True}],
            [
                {
                    **_widget("indicator", layer_id),
                    "config": {"stat": "sum", "column": "c" * 64},
                }
            ],
            [_widget("indicator", layer_id) for _ in range(51)],
            [_widget("indicator", other_layer)],
        ):
            resp = await client.put(
                f"/maps/{map_id}",
                json={"dashboard_config": {"widgets": widgets}},
                headers=admin_auth_header,
            )
            assert resp.status_code == 422, resp.text
        assert await _stored(test_db_session, map_id) is None

    async def test_a_full_layer_replacement_and_widgets_are_checked_together(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        a = await create_dataset(test_db_session, created_by=admin_id)
        b = await create_dataset(test_db_session, created_by=admin_id)
        map_id, (layer_a, layer_b) = await _map_with_layers(
            client, admin_auth_header, a, b
        )

        resp = await client.put(
            f"/maps/{map_id}",
            json={
                "layers": [{"id": layer_a, "dataset_id": str(a.id)}],
                "dashboard_config": {"widgets": [_widget("indicator", layer_b)]},
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 422, resp.text

        resp = await client.put(
            f"/maps/{map_id}",
            json={
                "layers": [{"id": layer_a, "dataset_id": str(a.id)}],
                "dashboard_config": {"widgets": [_widget("indicator", layer_a)]},
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["layer_count"] == 1

    async def test_stored_widgets_this_server_cannot_parse_survive_a_save(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(test_db_session, created_by=admin_id)
        map_id, (layer_id,) = await _map_with_layers(client, admin_auth_header, dataset)
        first, future = _widget("indicator", layer_id), _widget("gauge")
        await _store(
            test_db_session, map_id, {"version": 1, "widgets": [first, future]}
        )

        got = (await client.get(f"/maps/{map_id}", headers=admin_auth_header)).json()
        assert [w["id"] for w in got["dashboard_config"]["widgets"]] == [first["id"]]

        added = _widget("bar_chart", layer_id)
        resp = await client.put(
            f"/maps/{map_id}",
            json={"dashboard_config": {"widgets": [first, added]}},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        stored = await _stored(test_db_session, map_id)
        assert [w["id"] for w in stored["widgets"]] == [
            first["id"],
            future["id"],
            added["id"],
        ]

    async def test_readers_see_widgets_only_on_layers_they_can_read(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        viewer_auth_header: dict,
        test_db_session,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        public_ds = await create_dataset(test_db_session, created_by=admin_id)
        private_ds = await create_dataset(test_db_session, created_by=admin_id)
        map_id, (public_layer, private_layer) = await _map_with_layers(
            client, admin_auth_header, public_ds, private_ds, visibility="public"
        )
        shown, hidden = (
            _widget("indicator", public_layer),
            _widget("indicator", private_layer),
        )
        resp = await client.put(
            f"/maps/{map_id}",
            json={"dashboard_config": {"widgets": [shown, hidden]}},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        share = await client.post(f"/maps/{map_id}/share/", headers=admin_auth_header)
        assert share.status_code in (200, 201), share.text
        token = share.json()["token"]
        await _make_private(test_db_session, private_ds)

        for headers in (viewer_auth_header, {}):
            got = (await client.get(f"/maps/{map_id}", headers=headers)).json()
            assert [w["id"] for w in got["dashboard_config"]["widgets"]] == [
                shown["id"]
            ]
        shared = (await client.get(f"/maps/shared/{token}")).json()
        assert [w["id"] for w in shared["dashboard_config"]["widgets"]] == [shown["id"]]
        owner = (await client.get(f"/maps/{map_id}", headers=admin_auth_header)).json()
        assert len(owner["dashboard_config"]["widgets"]) == 2

    async def test_an_editor_save_keeps_widgets_on_layers_they_cannot_read(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        editor, _ = await create_user(client, admin_auth_header, "editor")
        admin_id = await get_user_id(test_db_session, "admin")
        readable = await create_dataset(test_db_session, created_by=admin_id)
        later_private = await create_dataset(test_db_session, created_by=admin_id)
        map_id, (layer_a, layer_b) = await _map_with_layers(
            client, editor, readable, later_private
        )
        on_a, on_b = _widget("indicator", layer_a), _widget("indicator", layer_b)
        resp = await client.put(
            f"/maps/{map_id}",
            json={"dashboard_config": {"widgets": [on_a, on_b]}},
            headers=editor,
        )
        assert resp.status_code == 200, resp.text
        await _make_private(test_db_session, later_private)

        got = (await client.get(f"/maps/{map_id}", headers=editor)).json()
        assert [w["id"] for w in got["dashboard_config"]["widgets"]] == [on_a["id"]]
        # The editor can't add a widget on the layer they can no longer read.
        resp = await client.put(
            f"/maps/{map_id}",
            json={"dashboard_config": {"widgets": [_widget("indicator", layer_b)]}},
            headers=editor,
        )
        assert resp.status_code == 422

        added = _widget("bar_chart", layer_a)
        resp = await client.put(
            f"/maps/{map_id}",
            json={"dashboard_config": {"widgets": [added]}},
            headers=editor,
        )
        assert resp.status_code == 200, resp.text
        # The save's own response leaves the hidden widget out too.
        assert _ids(resp.json()["dashboard_config"]["widgets"]) == [added["id"]]
        stored = await _stored(test_db_session, map_id)
        # on_b's anchor, on_a, is gone, so it moves to the front.
        assert _ids(stored["widgets"]) == [on_b["id"], added["id"]]

        resp = await client.put(
            f"/maps/{map_id}",
            json={"dashboard_config": {"widgets": []}},
            headers=editor,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["dashboard_config"] is None
        stored = await _stored(test_db_session, map_id)
        assert _ids(stored["widgets"]) == [on_b["id"]]

    async def test_a_fork_remaps_widgets_and_drops_those_on_unreadable_layers(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        viewer_auth_header: dict,
        test_db_session,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        public_ds = await create_dataset(test_db_session, created_by=admin_id)
        private_ds = await create_dataset(test_db_session, created_by=admin_id)
        map_id, (public_layer, private_layer) = await _map_with_layers(
            client, admin_auth_header, public_ds, private_ds, visibility="internal"
        )
        shown, selector, hidden = (
            _widget("bar_chart", public_layer),
            _widget("category_selector", public_layer),
            _widget("histogram", private_layer),
        )
        resp = await client.put(
            f"/maps/{map_id}",
            json={"dashboard_config": {"widgets": [shown, selector, hidden]}},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        await _make_private(test_db_session, private_ds)

        resp = await client.post(
            f"/maps/{map_id}/duplicate/", headers=viewer_auth_header
        )
        assert resp.status_code == 201, resp.text
        fork = resp.json()
        (copied_layer,) = [layer["id"] for layer in fork["layers"]]
        assert copied_layer != public_layer
        assert _shape(fork["dashboard_config"]["widgets"]) == [
            (shown["id"], "bar_chart", copied_layer),
            (selector["id"], "category_selector", copied_layer),
        ]
        stored = await _stored(test_db_session, fork["id"])
        assert [w["layer_id"] for w in stored["widgets"]] == [copied_layer] * 2

    async def test_versions_newer_than_this_server_are_refused(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(test_db_session, created_by=admin_id)
        map_id, (layer_id,) = await _map_with_layers(client, admin_auth_header, dataset)
        widget = _widget("indicator", layer_id)

        resp = await client.put(
            f"/maps/{map_id}",
            json={"dashboard_config": {"version": 2, "widgets": [widget]}},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422, resp.text

        newer = {"version": 2, "widgets": [widget]}
        await _store(test_db_session, map_id, newer)
        got = (await client.get(f"/maps/{map_id}", headers=admin_auth_header)).json()
        assert got["dashboard_config"]["version"] == 2
        resp = await client.put(
            f"/maps/{map_id}",
            json={"dashboard_config": {"widgets": []}},
            headers=admin_auth_header,
        )
        assert resp.status_code == 409, resp.text
        assert await _stored(test_db_session, map_id) == newer

    async def test_a_repointed_layer_loses_its_widgets(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        a = await create_dataset(test_db_session, created_by=admin_id)
        b = await create_dataset(test_db_session, created_by=admin_id)
        map_id, (layer_id,) = await _map_with_layers(client, admin_auth_header, a)
        resp = await client.put(
            f"/maps/{map_id}",
            json={"dashboard_config": {"widgets": [_widget("indicator", layer_id)]}},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text

        resp = await client.put(
            f"/maps/{map_id}",
            json={"layers": [{"id": layer_id, "dataset_id": str(b.id)}]},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        assert [layer["id"] for layer in resp.json()["layers"]] == [layer_id]
        assert resp.json()["dashboard_config"] is None
        assert (await _stored(test_db_session, map_id))["widgets"] == []

    async def test_an_embed_token_shows_widgets_on_layers_in_its_scope(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        scoped = await create_dataset(
            test_db_session, created_by=admin_id, visibility="private"
        )
        raw_token, share_token = await _embed(
            client, test_db_session, admin_auth_header, admin_id, scoped.id
        )
        map_id = await test_db_session.scalar(
            text("SELECT map_id FROM catalog.map_layers WHERE dataset_id = :d"),
            {"d": scoped.id},
        )
        layer_id = await test_db_session.scalar(
            text("SELECT id FROM catalog.map_layers WHERE dataset_id = :d"),
            {"d": scoped.id},
        )
        widget = _widget("indicator", layer_id)
        await _store(test_db_session, str(map_id), {"version": 1, "widgets": [widget]})

        anonymous = (await client.get(f"/maps/shared/{share_token}")).json()
        assert anonymous["layers"] == []
        assert anonymous["dashboard_config"] is None
        embedded = await client.get(
            f"/maps/shared/{share_token}", headers={"X-Embed-Token": raw_token}
        )
        assert embedded.status_code == 200, embedded.text
        assert _ids(embedded.json()["dashboard_config"]["widgets"]) == [widget["id"]]

    async def test_a_save_merges_against_the_dashboard_stored_when_it_locks(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        editor_headers, editor_id = await create_user(
            client, admin_auth_header, "editor"
        )
        admin_id = await get_user_id(test_db_session, "admin")
        readable = await create_dataset(test_db_session, created_by=admin_id)
        later_private = await create_dataset(test_db_session, created_by=admin_id)
        map_id, (layer_a, layer_b) = await _map_with_layers(
            client, editor_headers, readable, later_private
        )
        on_a, on_b = _widget("indicator", layer_a), _widget("indicator", layer_b)
        await _make_private(test_db_session, later_private)
        editor = await test_db_session.get(User, uuid.UUID(editor_id))

        # The request session loads the map before the save takes its lock (and
        # holds it, as the route does), and another save commits a widget on the
        # hidden layer in between.
        loaded = await get_map(test_db_session, uuid.UUID(map_id))
        assert loaded.dashboard_config is None
        async with db_module.async_session() as other:
            await _store(other, map_id, {"version": 1, "widgets": [on_a, on_b]})

        await update_map(
            test_db_session,
            uuid.UUID(map_id),
            dashboard_config={"widgets": [on_a]},
            user=editor,
        )
        await test_db_session.commit()
        assert loaded.dashboard_config is not None

        async with db_module.async_session() as check:
            assert _ids((await _stored(check, map_id))["widgets"]) == [
                on_a["id"],
                on_b["id"],
            ]


class TestDashboardPanel:
    def test_the_panel_is_stored_only_when_it_is_not_the_default(self):
        layer = uuid.uuid4()
        widget = _widget("indicator", layer)

        right = _merge({"widgets": [widget]}, None, readable={layer})
        bottom = _merge(
            {"panel": "bottom", "widgets": [widget]}, None, readable={layer}
        )

        assert "panel" not in right
        assert bottom["panel"] == "bottom"
        assert render_dashboard(right, [layer]).panel == "right"
        assert render_dashboard(bottom, [layer]).panel == "bottom"

    def test_a_row_saved_before_the_panel_existed_reads_as_right(self):
        layer = uuid.uuid4()
        stored = {"version": 1, "widgets": [_widget("indicator", layer)]}
        assert render_dashboard(stored, [layer]).panel == "right"

    def test_saves_that_send_no_panel_keep_the_stored_one(self):
        shown, hidden, repointed, copy = (uuid.uuid4() for _ in range(4))
        on_hidden = _widget("indicator", hidden)
        stored = {
            "version": 1,
            "panel": "bottom",
            "widgets": [_widget("indicator", shown), on_hidden],
        }

        assert _merge(None, stored, readable={shown}, hidden={hidden})["panel"] == (
            "bottom"
        )
        moved = {
            **stored,
            "widgets": [*stored["widgets"], _widget("indicator", repointed)],
        }
        assert drop_repointed(moved, {repointed})["panel"] == "bottom"
        assert fork_dashboard(stored, {shown: copy})["panel"] == "bottom"

    def test_a_save_that_names_no_panel_keeps_the_stored_one(self):
        layer = uuid.uuid4()
        stored = {"version": 1, "panel": "bottom", "widgets": []}
        sent = {"widgets": [_widget("indicator", layer)]}

        assert _merge(sent, stored, readable={layer})["panel"] == "bottom"
        moved_right = _merge({**sent, "panel": "right"}, stored, readable={layer})
        assert "panel" not in moved_right

    async def test_an_api_save_without_a_panel_keeps_a_bottom_panel(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(test_db_session, created_by=admin_id)
        map_id, (layer_id,) = await _map_with_layers(client, admin_auth_header, dataset)
        widget = _widget("indicator", layer_id)
        for body in (
            {"panel": "bottom", "widgets": [widget]},
            {"widgets": [widget, _widget("indicator", layer_id)]},
        ):
            resp = await client.put(
                f"/maps/{map_id}",
                json={"dashboard_config": body},
                headers=admin_auth_header,
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["dashboard_config"]["panel"] == "bottom"

    def test_an_unknown_panel_is_refused_on_write(self):
        with pytest.raises(ValueError):
            DashboardConfigInput.model_validate({"panel": "left", "widgets": []})


class TestMapListDashboardFlag:
    async def test_a_map_is_flagged_only_where_the_reader_sees_a_widget(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        viewer_auth_header: dict,
        test_db_session,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        public_ds = await create_dataset(test_db_session, created_by=admin_id)
        private_ds = await create_dataset(test_db_session, created_by=admin_id)
        map_id, (public_layer, private_layer) = await _map_with_layers(
            client, admin_auth_header, public_ds, private_ds, visibility="public"
        )
        plain_id, _ = await _map_with_layers(
            client, admin_auth_header, public_ds, visibility="public"
        )
        resp = await client.put(
            f"/maps/{map_id}",
            json={
                "dashboard_config": {"widgets": [_widget("indicator", private_layer)]}
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        await _make_private(test_db_session, private_ds)

        async def flags(headers: dict, path: str = "/maps/?limit=200") -> dict:
            got = await client.get(path, headers=headers)
            assert got.status_code == 200, got.text
            return {m["id"]: m["has_dashboard"] for m in got.json()["maps"]}

        owner = await flags(admin_auth_header)
        assert owner[map_id] is True
        assert owner[plain_id] is False
        for headers in (viewer_auth_header, {}):
            assert (await flags(headers))[map_id] is False
        by_dataset = f"/datasets/{public_ds.id}/maps/"
        assert (await flags(admin_auth_header, by_dataset))[map_id] is True
        assert (await flags(viewer_auth_header, by_dataset))[map_id] is False

        resp = await client.put(
            f"/maps/{map_id}",
            json={
                "dashboard_config": {"widgets": [_widget("indicator", public_layer)]}
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        assert (await flags(viewer_auth_header))[map_id] is True
