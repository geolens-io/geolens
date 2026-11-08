"""Restless Earth draws its circles and heat surface from one quake dataset."""

from __future__ import annotations

import copy
import importlib.util

import httpx
import pytest

from tests.repo_paths import repo_root


SCRIPT = repo_root(__file__) / "scripts" / "seed-showcase.py"
spec = importlib.util.spec_from_file_location("seed_showcase_quake_layers", SCRIPT)
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)

HEAT_PAINT = {"heatmap-opacity": 0.7, "heatmap-weight": seed.QUAKE_HEATMAP_WEIGHT}
HEAT_STYLE = {"render_mode": "heatmap", "builder": {"heatmap_ramp": "YlOrRd"}}


def _layer(layer_id, dataset_id, name, sort_order, **extra):
    return {
        "id": layer_id,
        "dataset_id": dataset_id,
        "dataset_name": "read-only",
        "display_name": name,
        "sort_order": sort_order,
        "visible": True,
        "opacity": 1.0,
        "paint": {},
        "layout": {},
        "show_in_legend": True,
        **extra,
    }


def _restless_layers():
    return [
        _layer("circles", "q", "Earthquakes", 0),
        _layer("plates", "p", "Plates", 1),
        _layer(
            "heat",
            "h",
            "Quake intensity (heatmap)",
            5,
            paint=HEAT_PAINT,
            show_in_legend=False,
            style_config=HEAT_STYLE,
            popup_config={"enabled": False},
        ),
    ]


class FakeApi:
    username = "showcase"

    def __init__(
        self,
        maps,
        owned=None,
        roles=("admin",),
        origin="service",
        origin_uri=seed.USGS_QUAKES_SERVICE,
        tokens=None,
        copy_origins=None,
        copy_uris=None,
    ):
        self.maps = maps
        self.owned = list(
            owned
            if owned is not None
            else [(seed.QUAKES_TITLE, "q"), (seed.QUAKES_HEAT_LEGACY_TITLE, "h")]
        )
        self.roles = list(roles)
        self.origin = origin
        self.origin_uri = origin_uri
        self.tokens = tokens or {}
        self.copy_origins = dict(copy_origins or {})
        self.copy_uris = dict(copy_uris or {})
        self.calls: list[tuple] = []

    def dataset_origin(self, dataset_id):
        return self.copy_origins.get(dataset_id, self.origin)

    def service_reupload_preview(self, dataset_id, _body):
        self.calls.append(("convert", dataset_id))
        self.copy_origins[dataset_id] = "service"
        return {"schema_diff": {}, "job_id": "j"}

    def reupload_commit(self, *_):
        pass

    def poll(self, *_, **__):
        pass

    def dataset_detail(self, dataset_id):
        return {
            "origin": self.dataset_origin(dataset_id),
            "origin_uri": self.copy_uris.get(dataset_id, self.origin_uri),
        }

    def list_own_datasets(self):
        return [{"title": t, "id": d} for t, d in self.owned]

    def datasets_by_title(self):
        out: dict = {}
        for title, dataset_id in self.owned:
            out.setdefault(title, dataset_id)
        return out

    def map_embed_tokens(self, map_id):
        return copy.deepcopy(self.tokens.get(map_id, []))

    def dataset_maps(self, dataset_id):
        return [
            {
                "id": map_id,
                "name": m["name"],
                "created_by_username": m["owner"],
            }
            for map_id, m in self.maps.items()
            if any(x["dataset_id"] == dataset_id for x in m["layers"])
        ]

    def get_map(self, map_id):
        m = self.maps[map_id]
        return {
            "id": map_id,
            "name": m["name"],
            "updated_at": m.get("updated_at", "t0"),
            "dashboard_config": copy.deepcopy(m.get("dashboard_config")),
            "layers": copy.deepcopy(m["layers"]),
        }

    def replace_map_layers(self, map_id, layers, expected_updated_at):
        """A full layer save: sent ids update in place, unsent layers go."""
        self.calls.append(("replace_map_layers", map_id, expected_updated_at))
        stored = {x["id"]: x for x in self.maps[map_id]["layers"]}
        self.maps[map_id]["layers"] = [{**stored[x["id"]], **x} for x in layers]

    def delete_dataset(self, dataset_id, title):
        self.calls.append(("delete_dataset", dataset_id, title))
        for m in self.maps.values():
            m["layers"] = [x for x in m["layers"] if x["dataset_id"] != dataset_id]
        self.owned = [(t, d) for t, d in self.owned if d != dataset_id]


def _restless_api(dashboard_config=None, **kwargs):
    extra_maps = kwargs.pop("extra_maps", {})
    maps = {
        "restless": {
            "name": "Restless Earth",
            "owner": "showcase",
            "updated_at": "2026-11-07T12:00:00Z",
            "dashboard_config": dashboard_config,
            "layers": _restless_layers(),
        },
        **extra_maps,
    }
    return FakeApi(maps, **kwargs)


def test_heat_layer_keeps_its_id_on_the_quake_dataset_and_the_copy_is_deleted():
    api = _restless_api()
    before = copy.deepcopy(api.maps["restless"]["layers"])

    assert seed.repair_quake_layers(api) is True

    layers = api.maps["restless"]["layers"]
    assert [x["id"] for x in layers] == ["circles", "plates", "heat"]
    heat = layers[2]
    assert heat["dataset_id"] == "q"
    assert {k: v for k, v in heat.items() if k != "dataset_id"} == {
        k: v for k, v in before[2].items() if k != "dataset_id"
    }
    assert layers[:2] == before[:2]
    assert api.calls == [
        ("replace_map_layers", "restless", "2026-11-07T12:00:00Z"),
        ("delete_dataset", "h", seed.QUAKES_HEAT_LEGACY_TITLE),
    ]


def test_a_second_run_changes_nothing():
    api = _restless_api()
    seed.repair_quake_layers(api)
    after_first = copy.deepcopy(api.maps)
    api.calls.clear()

    assert seed.repair_quake_layers(api) is False

    assert api.calls == []
    assert api.maps == after_first


def test_the_copy_is_kept_while_another_accounts_map_still_draws_it():
    api = _restless_api(
        extra_maps={
            "visitor": {
                "name": "A visitor's quake map",
                "owner": "visitor",
                "layers": [_layer("theirs", "h", "Heat", 0)],
            }
        }
    )

    assert seed.repair_quake_layers(api) is True

    assert ("delete_dataset", "h", seed.QUAKES_HEAT_LEGACY_TITLE) not in api.calls
    assert api.maps["visitor"]["layers"][0]["dataset_id"] == "h"
    assert {x["dataset_id"] for x in api.maps["restless"]["layers"]} == {"q", "p"}


def test_nothing_is_touched_without_the_quake_dataset():
    api = _restless_api()
    api.owned = [(seed.QUAKES_HEAT_LEGACY_TITLE, "h")]

    assert seed.repair_quake_layers(api) is False

    assert api.calls == []


def test_nothing_moves_onto_a_quake_dataset_the_service_never_bound():
    api = _restless_api(origin="upload")

    assert seed.repair_quake_layers(api) is False

    assert api.calls == []
    assert api.maps["restless"]["layers"][2]["dataset_id"] == "h"


def test_a_non_admin_moves_its_layers_but_keeps_the_copy():
    api = _restless_api(roles=("editor",))

    assert seed.repair_quake_layers(api) is True

    assert api.maps["restless"]["layers"][2]["dataset_id"] == "q"
    assert [c[0] for c in api.calls] == ["replace_map_layers"]
    assert (seed.QUAKES_HEAT_LEGACY_TITLE, "h") in api.owned


def test_a_map_whose_dashboard_reads_the_heat_layer_is_left_alone():
    api = _restless_api(
        dashboard_config={"widgets": [{"id": "w1", "layer_id": "heat"}]}
    )

    assert seed.repair_quake_layers(api) is False

    assert api.calls == []
    assert api.maps["restless"]["layers"][2]["dataset_id"] == "h"


def test_nothing_moves_onto_a_quake_dataset_bound_to_another_service():
    api = _restless_api(
        origin_uri="https://example.com/arcgis/rest/services/q/MapServer/0"
    )

    assert seed.repair_quake_layers(api) is False

    assert api.calls == []
    assert api.maps["restless"]["layers"][2]["dataset_id"] == "h"


def test_every_heatmap_copy_is_repointed_and_deleted():
    api = _restless_api(
        owned=[
            (seed.QUAKES_TITLE, "q"),
            (seed.QUAKES_HEAT_LEGACY_TITLE, "h"),
            (seed.QUAKES_HEAT_LEGACY_TITLE, "h2"),
        ],
        extra_maps={
            "second": {
                "name": "Second quake map",
                "owner": "showcase",
                "layers": [_layer("heat2", "h2", "Heat", 0)],
            }
        },
    )

    assert seed.repair_quake_layers(api) is True

    assert api.maps["second"]["layers"][0]["dataset_id"] == "q"
    assert api.maps["restless"]["layers"][2]["dataset_id"] == "q"
    assert api.owned == [(seed.QUAKES_TITLE, "q")]


def _token(scope, **extra):
    return {
        "is_active": True,
        "expires_at": "2999-01-01T00:00:00+00:00",
        "token_hint": "et_...abcd1234",
        "scoped_dataset_ids": scope,
        **extra,
    }


@pytest.mark.parametrize(
    "expires_at", ["2999-01-01T00:00:00+00:00", "2020-01-01T00:00:00Z"]
)
def test_a_map_with_an_active_token_scoped_to_the_copy_is_left_alone(expires_at):
    api = _restless_api(
        tokens={"restless": [_token(["q", "p", "h"], expires_at=expires_at)]}
    )

    assert seed.repair_quake_layers(api) is False

    assert api.calls == []
    assert api.maps["restless"]["layers"][2]["dataset_id"] == "h"


@pytest.mark.parametrize(
    "token",
    [
        _token(["q", "p", "h"], is_active=False),
        _token(["q", "p"]),
    ],
)
def test_revoked_or_unrelated_tokens_do_not_block_the_repair(token):
    api = _restless_api(tokens={"restless": [token]})

    assert seed.repair_quake_layers(api) is True

    assert api.maps["restless"]["layers"][2]["dataset_id"] == "q"


OTHER_SERVICE = "https://example.com/arcgis/rest/services/q/MapServer/0"


class BindingApi:
    def __init__(
        self,
        titles,
        origins=None,
        drawn=(),
        extra_copies=(),
        uris=None,
        roles=("admin",),
        broken=(),
    ):
        self.titles = titles
        self.origins = origins or {}
        self.drawn = set(drawn)
        self.extra_copies = list(extra_copies)
        self.uris = uris or {}
        self.roles = list(roles)
        self.broken = set(broken)

    def datasets_by_title(self):
        return dict(self.titles)

    def list_own_datasets(self):
        rows = [{"title": t, "id": d} for t, d in self.titles.items()]
        return rows + [
            {"title": seed.QUAKES_HEAT_LEGACY_TITLE, "id": d} for d in self.extra_copies
        ]

    def dataset_origin(self, dataset_id):
        return self.origins.get(dataset_id, "service")

    def dataset_detail(self, dataset_id):
        if dataset_id in self.broken:
            raise httpx.ConnectError("unreachable")
        return {
            "origin": self.dataset_origin(dataset_id),
            "origin_uri": self.uris.get(dataset_id, seed.USGS_QUAKES_SERVICE),
        }

    def dataset_maps(self, dataset_id):
        return [{"id": "m", "name": "A map"}] if dataset_id in self.drawn else []


def test_a_fresh_instance_binds_the_service_once(monkeypatch):
    bound: list[str] = []

    def fake_ingest(_api, _url, title):
        bound.append(title)
        return f"id-{len(bound)}"

    monkeypatch.setattr(seed, "ingest_service", fake_ingest)
    by_title: dict = {}

    assert seed.ensure_quake_datasets(BindingApi({}), by_title) == "id-1"
    assert bound == [seed.QUAKES_TITLE]


def _refresh(monkeypatch, api, failing=()):
    refreshed: list[str] = []

    def fake_refresh(_api, dataset_id, _label, timeout=900):
        refreshed.append(dataset_id)
        return dataset_id not in failing

    monkeypatch.setattr(seed, "refresh_and_report", fake_refresh)
    return seed.refresh_quakes(api), refreshed


BOTH = {seed.QUAKES_TITLE: "q", seed.QUAKES_HEAT_LEGACY_TITLE: "h"}


def test_refresh_pulls_only_the_quake_dataset_once_the_copy_is_gone(monkeypatch):
    api = BindingApi({seed.QUAKES_TITLE: "q"})

    assert _refresh(monkeypatch, api) == (0, ["q"])


def test_refresh_keeps_a_retained_service_bound_copy_current(monkeypatch):
    api = BindingApi(BOTH, drawn={"h"})

    assert _refresh(monkeypatch, api) == (0, ["q", "h"])


def test_refresh_fails_when_the_retained_copy_does_not_refresh(monkeypatch):
    api = BindingApi(BOTH, drawn={"h"})

    assert _refresh(monkeypatch, api, failing={"h"}) == (1, ["q", "h"])


def test_refresh_fails_on_a_drawn_copy_the_service_never_bound(monkeypatch):
    api = BindingApi(BOTH, origins={"h": "upload"}, drawn={"h"})

    assert _refresh(monkeypatch, api) == (1, ["q"])


def test_refresh_skips_an_unbound_copy_no_map_draws(monkeypatch):
    api = BindingApi(BOTH, origins={"h": "upload"})

    assert _refresh(monkeypatch, api) == (0, ["q"])


def test_live_wording_needs_a_retained_copy_to_be_service_bound_too():
    assert seed._quakes_are_live(BindingApi(BOTH)) is True
    assert seed._quakes_are_live(BindingApi({seed.QUAKES_TITLE: "q"})) is True
    assert seed._quakes_are_live(BindingApi(BOTH, origins={"h": "upload"})) is False
    assert seed._quakes_are_live(BindingApi(BOTH, origins={"q": "upload"})) is False


def test_refresh_covers_every_retained_copy(monkeypatch):
    api = BindingApi(BOTH, drawn={"h", "h2"}, extra_copies=["h2"])

    assert _refresh(monkeypatch, api, failing={"h2"}) == (1, ["q", "h", "h2"])


def test_live_wording_checks_every_retained_copy():
    api = BindingApi(BOTH, origins={"h2": "upload"}, extra_copies=["h2"])

    assert seed._quakes_are_live(api) is False


@pytest.fixture
def no_probe(monkeypatch):
    monkeypatch.setattr(seed, "service_binding_body", lambda _api, _url: {})


def _foreign_map():
    return {
        "visitor": {
            "name": "A visitor's quake map",
            "owner": "visitor",
            "layers": [_layer("theirs", "h", "Heat", 0)],
        }
    }


def test_a_retained_upload_copy_is_converted_to_the_service(no_probe):
    api = _restless_api(extra_maps=_foreign_map(), copy_origins={"h": "upload"})

    assert seed.repair_quake_layers(api) is True

    assert ("convert", "h") in api.calls
    assert api.dataset_origin("h") == "service"


def test_a_retained_service_bound_copy_is_left_alone(no_probe):
    api = _restless_api(extra_maps=_foreign_map())

    seed.repair_quake_layers(api)

    assert ("convert", "h") not in api.calls


@pytest.mark.parametrize(
    "uri",
    [
        seed.USGS_QUAKES_SERVICE + "/",
        seed.USGS_QUAKES_SERVICE.replace("/MapServer/0", "/MapServer//0"),
        seed.USGS_QUAKES_SERVICE.replace("https://earthquake", "HTTPS://Earthquake"),
    ],
)
def test_a_re_entered_usgs_uri_still_counts_as_the_usgs_binding(uri, monkeypatch):
    api = BindingApi({seed.QUAKES_TITLE: "q"}, uris={"q": uri})

    assert seed._quakes_are_live(api) is True
    assert _refresh(monkeypatch, api) == (0, ["q"])
    assert seed.repair_quake_layers(_restless_api(origin_uri=uri)) is True


def test_a_retained_copy_bound_to_another_service_is_neither_refreshed_nor_live(
    monkeypatch,
):
    api = BindingApi(BOTH, uris={"h": OTHER_SERVICE}, drawn={"h"})

    assert _refresh(monkeypatch, api) == (1, ["q"])
    assert seed._quakes_are_live(api) is False


def test_a_copy_that_cannot_be_read_fails_the_refresh_and_the_sweep_continues(
    monkeypatch,
):
    api = BindingApi(BOTH, broken={"h"}, extra_copies=["h2"])

    assert _refresh(monkeypatch, api) == (1, ["q", "h2"])


def test_a_non_admin_cannot_skip_an_unbound_copy_as_unused(monkeypatch):
    api = BindingApi(BOTH, origins={"h": "upload"}, roles=("editor",))

    assert _refresh(monkeypatch, api) == (1, ["q"])


def test_a_copy_rebound_to_another_service_keeps_its_layers_and_is_not_deleted():
    api = _restless_api(copy_uris={"h": OTHER_SERVICE})

    assert seed.repair_quake_layers(api) is False

    assert api.calls == []
    assert api.maps["restless"]["layers"][2]["dataset_id"] == "h"
    assert (seed.QUAKES_HEAT_LEGACY_TITLE, "h") in api.owned


def test_an_unreadable_quake_dataset_fails_the_refresh_and_the_sweep_continues(
    monkeypatch,
):
    api = BindingApi(BOTH, broken={"q"}, drawn={"h"})

    assert _refresh(monkeypatch, api) == (1, ["h"])


def test_live_wording_is_withheld_when_the_api_is_unreachable():
    api = BindingApi({seed.QUAKES_TITLE: "q"}, broken={"q"})

    assert seed._quakes_are_live(api) is False
