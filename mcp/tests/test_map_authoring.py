# SPDX-License-Identifier: Apache-2.0
"""The map authoring tools send exactly the builder's style and nothing a
map_author key may not set."""

from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path

import httpx
import pytest

from geolens_mcp import server, styles
from geolens_mcp.authoring import GeoLensAPI

MAP = "11111111-1111-4111-8111-111111111111"
DS = "22222222-2222-4222-8222-222222222222"
LAYER = "33333333-3333-4333-8333-333333333333"
_ROOT = Path(__file__).resolve().parents[2]

POLYGON_DATASET = {
    "id": DS,
    "record_type": "vector_dataset",
    "geometry_type": "MultiPolygon",
    "column_info": [
        {"name": "zone", "type": "character varying"},
        {"name": "population", "type": "integer"},
        {"name": "density", "type": "double precision"},
        {"name": "is_open", "type": "boolean"},
        {"name": "opened", "type": "date"},
    ],
}
DEFAULT_POLYGON_LAYER = {
    "id": LAYER,
    "dataset_id": DS,
    "dataset_geometry_type": "MultiPolygon",
    "dataset_column_info": POLYGON_DATASET["column_info"],
    "layer_type": "vector_geolens",
    "paint": {"fill-color": "#3b82f6", "fill-opacity": 0.3},
    "style_config": {"builder": {"outline_color": "#1e40af", "outline_width": 1}},
    "popup_config": None,
}


def _settable_fields() -> dict[str, set[str]]:
    """MAP_AUTHOR_SETTABLE_FIELDS from the backend source, by model name."""
    path = _ROOT / "backend/app/modules/catalog/maps/author_key.py"
    tree = ast.parse(path.read_text())
    names: dict[str, set[str]] = {}
    for node in tree.body:
        target = (
            getattr(node, "target", None)
            or (getattr(node, "targets", None) or [None])[0]
        )
        if isinstance(target, ast.Name) and target.id == "_LAYER_STYLE_FIELDS":
            names["_LAYER_STYLE_FIELDS"] = set(ast.literal_eval(node.value.args[0]))
        if isinstance(target, ast.Name) and target.id == "MAP_AUTHOR_SETTABLE_FIELDS":
            out = {}
            for key, value in zip(node.value.keys, node.value.values, strict=True):
                fields: set[str] = set()
                parts = [value]
                while parts:
                    part = parts.pop()
                    if isinstance(part, ast.BinOp):
                        parts += [part.left, part.right]
                    elif isinstance(part, ast.Name):
                        fields |= names[part.id]
                    else:
                        fields |= set(ast.literal_eval(part.args[0]))
                out[key.id] = fields
            return out
    raise AssertionError("MAP_AUTHOR_SETTABLE_FIELDS not found")


SETTABLE = _settable_fields()


class Stack:
    """A stub GeoLens API that records every request."""

    def __init__(self, routes):
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = (request.method, request.url.path)
        if key not in self.routes:
            return httpx.Response(404, json={"detail": f"no route {key}"})
        status, body = self.routes[key]
        return httpx.Response(status, json=body)

    def api(self) -> GeoLensAPI:
        http = httpx.Client(
            base_url="https://geolens.example.com/api",
            transport=httpx.MockTransport(self.handler),
        )
        return GeoLensAPI(http)

    def writes(self) -> list[tuple[str, str, dict]]:
        return [
            (r.method, r.url.path, json.loads(r.content))
            for r in self.requests
            if r.method != "GET"
        ]

    def assert_scope(self) -> None:
        """Every write is a map_author route carrying only settable fields."""
        for method, path, body in self.writes():
            if (method, path) == ("POST", "/api/maps/"):
                assert set(body) <= SETTABLE["MapCreate"], body
            elif method == "PUT" and path == f"/api/maps/{MAP}":
                assert set(body) <= SETTABLE["MapUpdate"], body
            elif (method, path) == ("POST", f"/api/maps/{MAP}/layers"):
                assert set(body) <= SETTABLE["MapLayerInput"], body
            elif (method, path) == ("PATCH", f"/api/maps/{MAP}/layers"):
                assert set(body) <= SETTABLE["MapLayerDiffRequest"], body
                for layer in body.get("updated", []):
                    assert set(layer) <= SETTABLE["MapLayerPatch"], layer
                for layer in body.get("added", []):
                    assert set(layer) <= SETTABLE["MapLayerInput"], layer
            else:
                raise AssertionError(
                    f"write outside the map_author scope: {method} {path}"
                )


def _layer_routes(stats=None, values=None, layer=DEFAULT_POLYGON_LAYER):
    routes = {
        ("GET", f"/api/datasets/{DS}"): (200, POLYGON_DATASET),
        ("POST", f"/api/maps/{MAP}/layers"): (201, layer),
        ("PATCH", f"/api/maps/{MAP}/layers"): (200, {"id": MAP}),
    }
    if stats is not None:
        for column, body in stats.items():
            routes[("GET", f"/api/datasets/{DS}/columns/{column}/stats/")] = (200, body)
    if values is not None:
        for column, body in values.items():
            routes[("GET", f"/api/datasets/{DS}/columns/{column}/values/")] = (
                200,
                {"values": body, "count": len(body)},
            )
    return routes


def _patched_layer(stack: Stack) -> dict:
    (patch,) = [b for m, _, b in stack.writes() if m == "PATCH"]
    assert set(patch) == {"updated"}
    (layer,) = patch["updated"]
    return layer


# --- create_map / set_camera / set_basemap ---


def test_create_map_sends_only_name_and_description_and_returns_its_url():
    stack = Stack({("POST", "/api/maps/"): (201, {"id": MAP, "name": "Parks"})})

    out = stack.api().create_map("Parks", description="City parks")

    assert stack.writes() == [
        ("POST", "/api/maps/", {"name": "Parks", "description": "City parks"})
    ]
    assert out["id"] == MAP
    assert out["url"] == f"https://geolens.example.com/maps/{MAP}"
    stack.assert_scope()


def test_create_map_sets_a_listed_basemap_after_creating_it():
    stack = Stack(
        {
            ("GET", "/api/settings/basemaps/"): (
                200,
                [
                    {"id": "openfreemap-dark", "enabled": True},
                    {"id": "retired", "enabled": False},
                ],
            ),
            ("POST", "/api/maps/"): (201, {"id": MAP}),
            ("PUT", f"/api/maps/{MAP}"): (
                200,
                {"id": MAP, "basemap_style": "openfreemap-dark"},
            ),
        }
    )

    out = stack.api().create_map("Parks", basemap="openfreemap-dark")

    assert stack.writes() == [
        ("POST", "/api/maps/", {"name": "Parks"}),
        ("PUT", f"/api/maps/{MAP}", {"basemap_style": "openfreemap-dark"}),
    ]
    assert out["basemap_style"] == "openfreemap-dark"
    stack.assert_scope()


@pytest.mark.parametrize("basemap", ["retired", "https://tiles.example.com/style.json"])
def test_create_map_refuses_an_unlisted_basemap_before_creating_anything(basemap):
    stack = Stack(
        {
            ("GET", "/api/settings/basemaps/"): (
                200,
                [
                    {"id": "positron", "enabled": True},
                    {"id": "retired", "enabled": False},
                ],
            )
        }
    )

    with pytest.raises(ValueError, match="Unknown basemap"):
        stack.api().create_map("Parks", basemap=basemap)
    assert stack.writes() == []


def test_set_camera_sends_only_the_view_fields_given(monkeypatch):
    stack = Stack({("PUT", f"/api/maps/{MAP}"): (200, {"id": MAP, "zoom": 11})})
    monkeypatch.setattr(server, "_api", stack.api())

    server.set_camera(MAP, center=[-73.9, 40.7], zoom=11)

    assert stack.writes() == [
        (
            "PUT",
            f"/api/maps/{MAP}",
            {"center_lng": -73.9, "center_lat": 40.7, "zoom": 11},
        )
    ]
    stack.assert_scope()


@pytest.mark.parametrize(
    "kwargs",
    [{}, {"center": [200, 10]}, {"center": [10, -95]}],
)
def test_set_camera_refuses_an_empty_or_off_earth_view(monkeypatch, kwargs):
    stack = Stack({})
    monkeypatch.setattr(server, "_api", stack.api())

    with pytest.raises(ValueError):
        server.set_camera(MAP, **kwargs)
    assert stack.requests == []


def test_set_basemap_puts_only_the_basemap(monkeypatch):
    stack = Stack({("PUT", f"/api/maps/{MAP}"): (200, {"id": MAP})})
    monkeypatch.setattr(server, "_api", stack.api())

    server.set_basemap(MAP, "blank")

    assert stack.writes() == [("PUT", f"/api/maps/{MAP}", {"basemap_style": "blank"})]


# --- add_layer ---


def test_add_layer_without_a_style_posts_only_the_dataset():
    stack = Stack(_layer_routes())

    out = stack.api().add_layer(MAP, DS)

    assert stack.writes() == [("POST", f"/api/maps/{MAP}/layers", {"dataset_id": DS})]
    assert out["layer_id"] == LAYER
    assert out["style"] is None
    stack.assert_scope()


def test_add_layer_single_colour_keeps_the_default_paint_and_outline():
    stack = Stack(_layer_routes())

    stack.api().add_layer(MAP, DS, style={"type": "single", "color": "#FF0000"})

    assert _patched_layer(stack) == {
        "id": LAYER,
        "paint": {"fill-color": "#ff0000", "fill-opacity": 0.3},
        "style_config": {"builder": {"outline_color": "#1e40af", "outline_width": 1}},
    }
    stack.assert_scope()


def test_add_layer_categories_colours_each_value_from_set2():
    stack = Stack(_layer_routes(values={"zone": ["civic", "park", "school"]}))

    out = stack.api().add_layer(
        MAP, DS, style={"type": "categories", "column": "zone"}, popup_fields=["zone"]
    )

    values_request = next(r for r in stack.requests if r.url.path.endswith("/values/"))
    assert values_request.url.params["limit"] == "101"
    post = stack.writes()[0]
    assert post == (
        "POST",
        f"/api/maps/{MAP}/layers",
        {
            "dataset_id": DS,
            "popup_config": {
                "enabled": True,
                "expression": None,
                "visible_fields": ["zone"],
            },
        },
    )
    colors = ["#66c2a5", "#fc8d62", "#8da0cb"]
    layer = _patched_layer(stack)
    assert layer["paint"] == {
        "fill-color": [
            "case",
            ["==", ["get", "zone"], None],
            "#cccccc",
            [
                "match",
                ["get", "zone"],
                "civic",
                colors[0],
                "park",
                colors[1],
                "school",
                colors[2],
                "#cccccc",
            ],
        ],
        "fill-opacity": 0.3,
    }
    assert layer["style_config"] == {
        "mode": "categorical",
        "column": "zone",
        "ramp": "Set2",
        "reversed": False,
        "categories": [
            {"value": "civic", "color": colors[0]},
            {"value": "park", "color": colors[1]},
            {"value": "school", "color": colors[2]},
        ],
        "builder": {"outline_color": "#1e40af", "outline_width": 1},
    }
    assert out["style"]["categories"][1] == {"value": "park", "color": colors[1]}
    stack.assert_scope()


def test_boolean_categories_match_on_the_string_form():
    stack = Stack(_layer_routes(values={"is_open": [False, True]}))

    stack.api().add_layer(MAP, DS, style={"type": "categories", "column": "is_open"})

    expression = _patched_layer(stack)["paint"]["fill-color"]
    assert expression[3][1] == ["to-string", ["get", "is_open"]]
    assert expression[3][2::2][:2] == ["false", "true"]


def test_custom_category_colours_store_the_custom_ramp():
    stack = Stack(_layer_routes(values={"zone": ["civic", "park"]}))

    stack.api().add_layer(
        MAP,
        DS,
        style={
            "type": "categories",
            "column": "zone",
            "colors": ["#111111", "#222222", "#333333"],
        },
    )

    config = _patched_layer(stack)["style_config"]
    assert config["ramp"] == "custom"
    assert [c["color"] for c in config["categories"]] == ["#111111", "#222222"]


def test_add_layer_classes_equal_interval_on_the_column_range():
    stack = Stack(
        _layer_routes(
            stats={
                "population": {
                    "min": 0,
                    "max": 100,
                    "count": 9,
                    "quantiles": [10, 30, 50, 70],
                }
            }
        )
    )

    out = stack.api().add_layer(
        MAP, DS, style={"type": "classes", "column": "population", "colors": "Blues"}
    )

    colors = styles.ramp_colors("Blues", 5)
    layer = _patched_layer(stack)
    assert layer["paint"]["fill-color"] == [
        "case",
        ["==", ["get", "population"], None],
        "#cccccc",
        [
            "step",
            ["get", "population"],
            colors[0],
            20,
            colors[1],
            40,
            colors[2],
            60,
            colors[3],
            80,
            colors[4],
        ],
    ]
    assert layer["style_config"] == {
        "mode": "graduated",
        "column": "population",
        "ramp": "Blues",
        "reversed": False,
        "classCount": 5,
        "method": "equal_interval",
        "breaks": [20, 40, 60, 80],
        "colors": colors,
        "target": "color",
        "builder": {"outline_color": "#1e40af", "outline_width": 1},
    }
    assert out["style"]["breaks"] == [20, 40, 60, 80]
    stack.assert_scope()


def test_quantile_classes_use_the_server_quantiles():
    stack = Stack(
        _layer_routes(
            stats={
                "density": {
                    "min": 0.5,
                    "max": 99.5,
                    "count": 9,
                    "quantiles": [2.5, 7.25, 19.0, 44.0],
                }
            }
        )
    )

    stack.api().add_layer(
        MAP, DS, style={"type": "classes", "column": "density", "method": "quantile"}
    )

    assert _patched_layer(stack)["style_config"]["breaks"] == [2.5, 7.25, 19.0, 44.0]


def test_manual_breaks_need_no_column_stats():
    stack = Stack(_layer_routes())

    stack.api().add_layer(
        MAP,
        DS,
        style={"type": "classes", "column": "population", "breaks": [10, 10, 50]},
    )

    assert not any("/columns/" in r.url.path for r in stack.requests)
    config = _patched_layer(stack)["style_config"]
    assert config["method"] == "manual"
    assert config["breaks"] == [10, 50]
    assert config["classCount"] == 3


def test_point_layers_take_circle_colour():
    point_layer = {
        **DEFAULT_POLYGON_LAYER,
        "dataset_geometry_type": "Point",
        "paint": {"circle-radius": 5, "circle-color": "#3b82f6"},
        "style_config": None,
    }
    stack = Stack(_layer_routes(layer=point_layer))

    stack.api().add_layer(MAP, DS, style={"type": "single", "color": "#00ff00"})

    layer = _patched_layer(stack)
    assert layer["paint"] == {"circle-radius": 5, "circle-color": "#00ff00"}
    assert layer["style_config"] is None


@pytest.mark.parametrize(
    ("style", "popup_fields", "message"),
    [
        ({"type": "categories", "column": "nope"}, None, "not in this dataset"),
        ({"type": "categories", "column": "density"}, None, "categories need"),
        ({"type": "categories", "column": "opened"}, None, "categories need"),
        ({"type": "classes", "column": "zone"}, None, "classes need a numeric"),
        ({"type": "classes", "column": "opened"}, None, "classes need a numeric"),
        ({"type": "single", "color": "red"}, None, "hex colour"),
        ({"type": "single", "color": "#fff", "column": "zone"}, None, "doesn't take"),
        ({"type": "heatmap"}, None, "style.type"),
        ({"type": "classes", "column": "population", "count": 12}, None, "count"),
        (
            {
                "type": "classes",
                "column": "population",
                "method": "quantile",
                "count": 4,
            },
            None,
            "quantile",
        ),
        (
            {"type": "classes", "column": "population", "breaks": [5, 1]},
            None,
            "ascending",
        ),
        (
            {"type": "categories", "column": "zone", "colors": "Rainbow"},
            None,
            "Unknown colour ramp",
        ),
        (None, ["zone", "missing"], "Not columns"),
        (None, ["zone", "zone"], "repeat"),
    ],
)
def test_bad_style_or_popup_fields_are_refused_before_any_write(
    style, popup_fields, message
):
    stack = Stack(_layer_routes())

    with pytest.raises(ValueError, match=message):
        stack.api().add_layer(MAP, DS, style=style, popup_fields=popup_fields)
    assert stack.writes() == []


def test_a_column_with_too_many_values_is_refused():
    stack = Stack(_layer_routes(values={"zone": [f"v{i}" for i in range(101)]}))

    with pytest.raises(ValueError, match="more than 100 values"):
        stack.api().add_layer(MAP, DS, style={"type": "categories", "column": "zone"})
    assert stack.writes() == []


def test_too_few_custom_colours_are_refused():
    stack = Stack(_layer_routes(values={"zone": ["a", "b", "c"]}))

    with pytest.raises(ValueError, match="at least 3 colours"):
        stack.api().add_layer(
            MAP,
            DS,
            style={"type": "categories", "column": "zone", "colors": ["#111111"]},
        )
    assert stack.writes() == []


def test_a_raster_layer_takes_no_style():
    stack = Stack(
        {
            ("GET", f"/api/datasets/{DS}"): (
                200,
                {**POLYGON_DATASET, "record_type": "raster_dataset"},
            )
        }
    )

    with pytest.raises(ValueError, match="raster"):
        stack.api().add_layer(MAP, DS, style={"type": "single", "color": "#ffffff"})
    assert stack.writes() == []


# --- update_layer_style ---


def _map_with(layer):
    return {("GET", f"/api/maps/{MAP}"): (200, {"id": MAP, "layers": [layer]})}


def test_update_layer_style_to_single_drops_the_classification():
    styled = {
        **DEFAULT_POLYGON_LAYER,
        "paint": {
            "fill-color": ["match", ["get", "zone"], "a", "#111111", "#cccccc"],
            "fill-opacity": 0.3,
        },
        "style_config": {
            "mode": "categorical",
            "column": "zone",
            "ramp": "Set2",
            "categories": [{"value": "a", "color": "#111111"}],
            "builder": {"outline_color": "#1e40af", "fill_color_saved": "#abcdef"},
        },
        "popup_config": {
            "enabled": False,
            "expression": "{zone}",
            "visible_fields": None,
        },
    }
    stack = Stack(
        {**_map_with(styled), ("PATCH", f"/api/maps/{MAP}/layers"): (200, {})}
    )

    stack.api().update_layer_style(
        MAP,
        LAYER,
        style={"type": "single", "color": "#123456"},
        popup_fields=["zone", "population"],
    )

    assert _patched_layer(stack) == {
        "id": LAYER,
        "paint": {"fill-color": "#123456", "fill-opacity": 0.3},
        "style_config": {"builder": {"outline_color": "#1e40af"}},
        "popup_config": {
            "enabled": False,
            "expression": "{zone}",
            "visible_fields": ["zone", "population"],
        },
    }
    stack.assert_scope()


def test_update_layer_popup_only_leaves_the_style_alone():
    stack = Stack(
        {
            **_map_with(DEFAULT_POLYGON_LAYER),
            ("PATCH", f"/api/maps/{MAP}/layers"): (200, {}),
        }
    )

    stack.api().update_layer_style(MAP, LAYER, popup_fields=[])

    assert _patched_layer(stack) == {
        "id": LAYER,
        "popup_config": {"enabled": True, "expression": None, "visible_fields": []},
    }


def test_update_layer_style_needs_something_to_change():
    stack = Stack({})

    with pytest.raises(ValueError, match="Give a style"):
        stack.api().update_layer_style(MAP, LAYER)
    assert stack.requests == []


def test_update_layer_style_refuses_a_layer_not_on_the_map():
    stack = Stack(_map_with({**DEFAULT_POLYGON_LAYER, "id": DS}))

    with pytest.raises(ValueError, match="has no layer"):
        stack.api().update_layer_style(MAP, LAYER, popup_fields=["zone"])
    assert stack.writes() == []


# --- refusals ---


@pytest.mark.parametrize("status", [401, 403])
def test_a_refused_write_says_a_map_author_key_is_needed(status):
    stack = Stack(
        {("POST", "/api/maps/"): (status, {"detail": {"code": "api_key_scope"}})}
    )

    with pytest.raises(RuntimeError) as excinfo:
        stack.api().create_map("Parks")
    message = str(excinfo.value)
    assert "map_author API key" in message
    assert "only the maps it created" in message
    assert f"GeoLens API {status}" in message


def test_a_refused_read_keeps_the_plain_error():
    stack = Stack({("GET", f"/api/datasets/{DS}"): (403, {"detail": "Forbidden"})})

    with pytest.raises(RuntimeError) as excinfo:
        stack.api().add_layer(MAP, DS)
    assert "map_author" not in str(excinfo.value)


def test_a_refused_style_after_the_add_names_the_unstyled_layer():
    routes = _layer_routes()
    routes[("PATCH", f"/api/maps/{MAP}/layers")] = (403, {"detail": "nope"})
    stack = Stack(routes)

    with pytest.raises(RuntimeError, match=f"Layer {LAYER} was added"):
        stack.api().add_layer(MAP, DS, style={"type": "single", "color": "#ffffff"})


def test_the_refusal_reaches_the_agent_through_the_tool(monkeypatch):
    stack = Stack(
        {
            ("PATCH", f"/api/maps/{MAP}/layers"): (403, {"detail": "x"}),
            **_map_with(DEFAULT_POLYGON_LAYER),
        }
    )
    monkeypatch.setattr(server, "_api", stack.api())

    async def scenario():
        from mcp import Client

        async with Client(server.mcp) as client:
            return await client.call_tool(
                "update_layer_style",
                {"map_id": MAP, "layer_id": LAYER, "popup_fields": ["zone"]},
            )

    result = asyncio.run(scenario())
    assert result.is_error
    assert "map_author API key" in result.content[0].text


def test_every_tool_write_stays_inside_the_scope(monkeypatch):
    routes = {
        **_layer_routes(
            values={"zone": ["a", "b"]},
            stats={
                "population": {
                    "min": 0,
                    "max": 9,
                    "count": 9,
                    "quantiles": [1, 2, 3, 4],
                }
            },
        ),
        **_map_with(DEFAULT_POLYGON_LAYER),
        ("POST", "/api/maps/"): (201, {"id": MAP}),
        ("PUT", f"/api/maps/{MAP}"): (200, {"id": MAP}),
        ("GET", "/api/settings/basemaps/"): (
            200,
            [{"id": "positron", "enabled": True}],
        ),
    }
    stack = Stack(routes)
    monkeypatch.setattr(server, "_api", stack.api())

    server.create_map("Parks", description="d", basemap="positron")
    server.add_layer(
        MAP, DS, style={"type": "categories", "column": "zone"}, popup_fields=["zone"]
    )
    server.update_layer_style(
        MAP, LAYER, style={"type": "classes", "column": "population"}
    )
    server.set_camera(MAP, center=[1, 2], zoom=3, pitch=4, bearing=5)
    server.set_basemap(MAP, "positron")

    assert len(stack.writes()) == 7
    stack.assert_scope()


# --- the builder's shape ---

_RAMP_FIXTURE = json.loads(
    (_ROOT / "backend/tests/fixtures/ramp_parity.json").read_text()
)


@pytest.mark.parametrize(("ramp", "by_count"), sorted(_RAMP_FIXTURE.items()))
def test_ramp_colours_match_the_builder_fixture(ramp, by_count):
    for count, colors in by_count.items():
        assert styles.ramp_colors(ramp, int(count)) == colors


def test_breaks_match_the_builder_classification_tests():
    # Literals from frontend/src/lib/__tests__/classification.test.ts.
    assert styles.equal_interval_breaks(0, 100, 5) == [20, 40, 60, 80]
    assert styles.equal_interval_breaks(0, 100, 1) == []
    assert styles.jenks_breaks([1, 2, 3, 10, 11, 12, 20, 21, 22], 3) == [10, 20]
    assert styles.jenks_breaks([1, 1, 1, 2, 3, 50, 51, 99, 100], 4) == [2, 50, 99]
    assert styles.jenks_breaks([42, 42, 42], 4) == styles.equal_interval_breaks(
        42, 42, 4
    )
    assert styles.std_dev_breaks(50, 10, 4) == [40, 50, 60]
    assert styles.std_dev_breaks(50, 10, 5) == [35, 45, 55, 65]
    assert styles.std_dev_breaks(50, 10, 2) == [50]
    assert styles.std_dev_breaks(50, 0, 4) == []
    assert styles.std_dev_breaks(0, 3.333, 4) == [-3.33, 0, 3.33]


def test_expressions_match_the_builder_colour_ramp_tests():
    # Literals from frontend/src/lib/__tests__/color-ramps.test.ts.
    assert styles.categorical_expression("kind", [], "#aabbcc") == "#aabbcc"
    assert styles.categorical_expression("kind", [("a", "#111111")], "#aabbcc") == [
        "case",
        ["==", ["get", "kind"], None],
        "#aabbcc",
        ["match", ["get", "kind"], "a", "#111111", "#aabbcc"],
    ]
    assert styles.graduated_expression("pop", [100, 500, 1000], [3, 6, 10, 16], 0) == [
        "case",
        ["==", ["get", "pop"], None],
        0,
        ["step", ["get", "pop"], 3, 100, 6, 500, 10, 1000, 16],
    ]
    assert styles.color_property("Polygon") == "fill-color"
    assert styles.color_property("LineString") == "line-color"
    assert styles.color_property("MultiPoint") == "circle-color"
    assert styles.color_property(None) == "fill-color"
