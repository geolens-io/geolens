"""The ArcGIS web map translator: renderers, labels, popups, filters and the loss report."""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path

import pytest

from app.modules.catalog.maps.arcgis_webmap.filter_sql import (
    definition_expression_to_filter,
    is_match_all,
)
from app.modules.catalog.maps.arcgis_webmap.layout import (
    color_to_hex,
    extent_to_view,
    scale_to_zoom,
)
from app.modules.catalog.maps.arcgis_webmap.loss import LossReport
from app.modules.catalog.maps.arcgis_webmap.translate import (
    DEFAULT_MAP_NAME,
    translate_webmap,
)
from app.modules.catalog.maps.schemas import MapLayerInput

FIXTURES = Path(__file__).parent / "fixtures" / "arcgis_webmaps"
BASEMAPS = ["openfreemap-positron", "openstreetmap"]


def _red(alpha: int = 255) -> list[int]:
    return [255, 0, 0, alpha]


def _webmap(layer: dict | None = None, **extra) -> dict:
    base = {
        "id": "L1",
        "layerType": "ArcGISFeatureLayer",
        "title": "Layer",
        "url": "https://x/arcgis/rest/services/S/FeatureServer/0",
        "visibility": True,
        "opacity": 1,
        "layerDefinition": {"drawingInfo": {}},
    }
    base.update(layer or {})
    return {
        "operationalLayers": [base],
        "baseMap": {"baseMapLayers": [{"url": "https://esri/base"}]},
        **extra,
    }


def _translate(webmap: dict, matches: dict | None = None, **kwargs):
    matches = {"L1": uuid.uuid4()} if matches is None else matches
    return translate_webmap(
        webmap,
        name=kwargs.pop("name", None),
        dataset_matches=matches,
        basemap_map=kwargs.pop("basemap_map", {"https://esri/base": "openstreetmap"}),
        available_basemaps=kwargs.pop("available_basemaps", BASEMAPS),
    )


def _with_renderer(renderer: dict, **layer) -> dict:
    return _webmap(
        {"layerDefinition": {"drawingInfo": {"renderer": renderer}}, **layer}
    )


def _kinds(result) -> set[str]:
    return set(result.loss.summary)


def _point(color=None, size=9, outline_width=1) -> dict:
    return {
        "type": "esriSMS",
        "style": "esriSMSCircle",
        "color": color or _red(),
        "size": size,
        "outline": {"color": [0, 0, 0, 255], "width": outline_width},
    }


def _fill(color=None, outline_style="esriSLSSolid") -> dict:
    return {
        "type": "esriSFS",
        "style": "esriSFSSolid",
        "color": color or [0, 128, 0, 128],
        "outline": {
            "type": "esriSLS",
            "style": outline_style,
            "color": [10, 20, 30, 255],
            "width": 1.5,
        },
    }


def _line(style="esriSLSSolid") -> dict:
    return {"type": "esriSLS", "style": style, "color": _red(), "width": 3}


class TestUnits:
    def test_scale_to_zoom_uses_the_512_px_world(self) -> None:
        assert scale_to_zoom(591657550.5 / 2**10) == 9.0
        assert scale_to_zoom(0) is None
        assert scale_to_zoom(None) is None
        assert scale_to_zoom(591657550.5 * 10) == 0.0
        assert scale_to_zoom(1) == 24.0

    def test_color_alpha_becomes_opacity(self) -> None:
        assert color_to_hex([255, 128, 0, 128]) == ("#ff8000", 0.502)
        assert color_to_hex([1, 2, 3]) == ("#010203", 1.0)
        assert color_to_hex("red") is None

    def test_extent_fits_the_viewport(self) -> None:
        world = 20037508.342789244
        extent = {
            "xmin": -world,
            "ymin": -world,
            "xmax": world,
            "ymax": world,
            "spatialReference": {"wkid": 102100},
        }
        lng, lat, zoom = extent_to_view(extent)
        assert (lng, lat) == (0.0, 0.0)
        assert zoom == 0.6

    def test_geographic_extent(self) -> None:
        view = extent_to_view(
            {
                "xmin": -75,
                "ymin": 40,
                "xmax": -73,
                "ymax": 41,
                "spatialReference": {"wkid": 4326},
            }
        )
        assert view is not None
        assert view[0] == -74.0
        assert 7 < view[2] < 9

    def test_unknown_projection_is_not_guessed(self) -> None:
        extent = {
            "xmin": 0,
            "ymin": 0,
            "xmax": 1,
            "ymax": 1,
            "spatialReference": {"wkid": 2263},
        }
        assert extent_to_view(extent) is None


class TestSimpleRenderer:
    def test_point(self) -> None:
        result = _translate(_with_renderer({"type": "simple", "symbol": _point()}))
        paint = result.layers[0].paint
        assert paint["circle-color"] == "#ff0000"
        assert paint["circle-radius"] == 6.0
        assert paint["circle-stroke-color"] == "#000000"
        assert paint["circle-stroke-width"] == 1.33
        assert not result.loss.items

    def test_other_marker_style_is_reported(self) -> None:
        symbol = {**_point(), "style": "esriSMSDiamond"}
        result = _translate(_with_renderer({"type": "simple", "symbol": symbol}))
        assert result.layers[0].paint["circle-color"] == "#ff0000"
        assert _kinds(result) == {"symbol_style"}

    @pytest.mark.parametrize(
        ("style", "dash"),
        [
            ("esriSLSDash", [4, 2]),
            ("esriSLSDot", [1, 2]),
            ("esriSLSDashDot", [4, 2, 1, 2]),
        ],
    )
    def test_dashed_line(self, style: str, dash: list) -> None:
        result = _translate(_with_renderer({"type": "simple", "symbol": _line(style)}))
        paint = result.layers[0].paint
        assert paint["line-dasharray"] == dash
        assert paint["line-width"] == 4.0
        assert not result.loss.items

    def test_unsupported_line_style_is_reported(self) -> None:
        result = _translate(
            _with_renderer({"type": "simple", "symbol": _line("esriSLSDashDotDot")})
        )
        assert "line-dasharray" not in result.layers[0].paint
        assert _kinds(result) == {"symbol_style"}

    def test_fill_keeps_alpha_and_outline(self) -> None:
        result = _translate(_with_renderer({"type": "simple", "symbol": _fill()}))
        layer = result.layers[0]
        assert layer.paint["fill-color"] == "#008000"
        assert layer.paint["fill-opacity"] == 0.502
        assert layer.style_config["builder"] == {
            "outline_color": "#0a141e",
            "outline_width": 2.0,
        }

    def test_dashed_outline_is_reported(self) -> None:
        result = _translate(
            _with_renderer(
                {"type": "simple", "symbol": _fill(outline_style="esriSLSDash")}
            )
        )
        assert _kinds(result) == {"symbol_style"}

    def test_null_fill_disables_the_fill(self) -> None:
        symbol = {**_fill(), "style": "esriSFSNull"}
        result = _translate(_with_renderer({"type": "simple", "symbol": symbol}))
        assert result.layers[0].style_config["builder"]["fill_disabled"] is True

    def test_pattern_fill_is_reported(self) -> None:
        symbol = {**_fill(), "style": "esriSFSDiagonalCross"}
        result = _translate(_with_renderer({"type": "simple", "symbol": symbol}))
        assert _kinds(result) == {"symbol_style"}

    def test_picture_marker_uses_the_builtin_icon(self) -> None:
        symbol = {"type": "esriPMS", "url": "x.png", "width": 12, "height": 12}
        result = _translate(_with_renderer({"type": "simple", "symbol": symbol}))
        config = result.layers[0].style_config
        assert config["render_mode"] == "symbol"
        assert config["symbol"]["iconImage"] == "marker"
        assert _kinds(result) == {"picture_marker"}

    def test_missing_renderer_keeps_geolens_defaults(self) -> None:
        result = _translate(_webmap())
        assert result.layers[0].paint is None
        assert _kinds(result) == {"renderer_missing"}


class TestUniqueValueRenderer:
    def _renderer(self, **extra) -> dict:
        return {
            "type": "uniqueValue",
            "field1": "KIND",
            "defaultSymbol": _fill([200, 200, 200, 255]),
            "uniqueValueInfos": [
                {"value": "a", "label": "Alpha", "symbol": _fill([255, 0, 0, 255])},
                {"value": 2, "label": "Two", "symbol": _fill([0, 0, 255, 255])},
            ],
            **extra,
        }

    def test_becomes_a_match_with_categories(self) -> None:
        result = _translate(_with_renderer(self._renderer()))
        layer = result.layers[0]
        assert layer.style_config["mode"] == "categorical"
        assert layer.style_config["column"] == "KIND"
        assert layer.style_config["categories"] == [
            {"value": "a", "label": "Alpha", "color": "#ff0000"},
            {"value": "2", "label": "Two", "color": "#0000ff"},
        ]
        expression = layer.paint["fill-color"]
        assert expression[0] == "case"
        match = expression[3]
        assert match == [
            "match",
            ["to-string", ["get", "KIND"]],
            "a",
            "#ff0000",
            "2",
            "#0000ff",
            "#c8c8c8",
        ]
        assert not result.loss.items

    def test_duplicate_values_are_reported(self) -> None:
        renderer = self._renderer()
        renderer["uniqueValueInfos"].append(
            {"value": "a", "label": "again", "symbol": _fill()}
        )
        result = _translate(_with_renderer(renderer))
        assert len(result.layers[0].style_config["categories"]) == 2
        assert _kinds(result) == {"renderer_class_dropped"}

    @pytest.mark.parametrize(
        ("extra", "kind"),
        [
            ({"field2": "OTHER"}, "multi_field_renderer"),
            ({"valueExpression": "$feature.A"}, "arcade"),
        ],
    )
    def test_multi_field_and_arcade_fall_back_to_one_paint(
        self, extra: dict, kind: str
    ) -> None:
        result = _translate(_with_renderer(self._renderer(**extra)))
        assert result.layers[0].style_config.get("mode") is None
        assert kind in _kinds(result)

    def test_visual_variables_are_reported(self) -> None:
        renderer = self._renderer(visualVariables=[{"type": "sizeInfo"}])
        assert "visual_variable" in _kinds(_translate(_with_renderer(renderer)))


def _eval(expression, props: dict):
    """Evaluate the small MapLibre subset the translator emits for class breaks."""
    if not isinstance(expression, list):
        return expression
    op, *args = expression
    if op == "get":
        return props.get(args[0])
    if op == "case":
        pairs, fallback = args[:-1], args[-1]
        for test, value in zip(pairs[::2], pairs[1::2]):
            if _eval(test, props):
                return value
        return fallback
    if op == "all":
        return all(_eval(a, props) for a in args)
    left, right = (_eval(a, props) for a in args)
    if op == "==":
        return left == right
    if left is None:
        return False
    return {"<=": left <= right, ">=": left >= right}[op]


class TestClassBreaksRenderer:
    def _renderer(self, **extra) -> dict:
        return {
            "type": "classBreaks",
            "field": "POP",
            "minValue": 0,
            "classBreakInfos": [
                {"classMaxValue": 100, "symbol": _fill([255, 255, 0, 255])},
                {"classMaxValue": 10, "symbol": _fill([0, 255, 0, 255])},
                {"classMaxValue": 1000, "symbol": _fill([255, 0, 0, 255])},
            ],
            **extra,
        }

    def test_becomes_inclusive_per_class_bounds(self) -> None:
        result = _translate(_with_renderer(self._renderer()))
        layer = result.layers[0]
        assert layer.style_config["mode"] == "graduated"
        assert layer.style_config["breaks"] == [10.0, 100.0]
        assert layer.style_config["colors"] == ["#00ff00", "#ffff00", "#ff0000"]
        expression = layer.paint["fill-color"]
        assert "step" not in json.dumps(expression)
        colors = {
            v: _eval(expression, {"POP": v}) for v in (0, 5, 10, 11, 100, 101, 1000)
        }
        assert colors == {
            0: "#00ff00",
            5: "#00ff00",
            10: "#00ff00",
            11: "#ffff00",
            100: "#ffff00",
            101: "#ff0000",
            1000: "#ff0000",
        }
        assert _eval(expression, {"POP": None}) == "#cccccc"
        assert not result.loss.items

    def test_values_in_a_gap_between_classes_get_the_default_colour(self) -> None:
        renderer = {
            "type": "classBreaks",
            "field": "POP",
            "classBreakInfos": [
                {
                    "classMinValue": 0,
                    "classMaxValue": 10,
                    "symbol": _fill([255, 0, 0, 255]),
                },
                {
                    "classMinValue": 20,
                    "classMaxValue": 30,
                    "symbol": _fill([0, 0, 255, 255]),
                },
            ],
        }
        result = _translate(_with_renderer(renderer))
        expression = result.layers[0].paint["fill-color"]
        assert _eval(expression, {"POP": 10}) == "#ff0000"
        assert _eval(expression, {"POP": 15}) == "#cccccc"
        assert _eval(expression, {"POP": 20}) == "#0000ff"
        assert _eval(expression, {"POP": 30}) == "#0000ff"
        assert _eval(expression, {"POP": 31}) == "#cccccc"
        assert _kinds(result) == {"class_gap"}

    def test_normalization_is_reported_and_not_applied_to_the_raw_field(self) -> None:
        result = _translate(
            _with_renderer(self._renderer(normalizationType="esriNormalizeByField"))
        )
        assert result.layers[0].style_config.get("mode") is None
        assert _kinds(result) == {"normalization"}


class TestOtherRenderers:
    def test_heatmap(self) -> None:
        renderer = {
            "type": "heatmap",
            "field": "W",
            "blurRadius": 10,
            "colorStops": [{"ratio": 0, "color": _red()}],
        }
        result = _translate(_with_renderer(renderer))
        layer = result.layers[0]
        assert layer.style_config["render_mode"] == "heatmap"
        assert layer.style_config["builder"]["heatmap_weight_column"] == "W"
        assert layer.paint["heatmap-weight"] == ["get", "W"]
        assert _kinds(result) == {"heatmap_ramp"}

    @pytest.mark.parametrize(
        "kind", ["dotDensity", "dictionary", "pieChart", "vectorField"]
    )
    def test_unsupported_renderers_keep_defaults(self, kind: str) -> None:
        result = _translate(_with_renderer({"type": kind}))
        assert result.layers[0].paint is None
        assert _kinds(result) == {"unsupported_renderer"}


class TestLayerProperties:
    def test_title_visibility_opacity_and_legend(self) -> None:
        result = _translate(
            _webmap(
                {
                    "title": "Parks",
                    "visibility": False,
                    "opacity": 0.4,
                    "showLegend": False,
                }
            )
        )
        layer = result.layers[0]
        assert (layer.display_name, layer.visible, layer.opacity) == (
            "Parks",
            False,
            0.4,
        )
        assert layer.show_in_legend is False

    def test_scale_range_becomes_zoom_limits(self) -> None:
        result = _translate(
            _webmap({"minScale": 591657550.5 / 2**9, "maxScale": 591657550.5 / 2**15})
        )
        assert result.layers[0].layout == {"_minzoom": 8.0, "_maxzoom": 14.0}

    def test_layers_are_ordered_bottom_to_top(self) -> None:
        webmap = {
            "operationalLayers": [
                {"id": f"L{i}", "layerType": "ArcGISFeatureLayer", "title": str(i)}
                for i in range(3)
            ]
        }
        matches = {f"L{i}": uuid.uuid4() for i in range(3)}
        result = _translate(webmap, matches)
        assert [(x.display_name, x.sort_order) for x in result.layers] == [
            ("0", 0),
            ("1", 1),
            ("2", 2),
        ]

    def test_group_members_share_a_folder(self) -> None:
        webmap = {
            "operationalLayers": [
                {
                    "id": "G",
                    "layerType": "GroupLayer",
                    "title": "Water",
                    "visibility": False,
                    "opacity": 0.5,
                    "layers": [
                        {"id": "L1", "layerType": "ArcGISFeatureLayer", "title": "a"},
                        {
                            "id": "G2",
                            "layerType": "GroupLayer",
                            "title": "Inner",
                            "layers": [
                                {
                                    "id": "L2",
                                    "layerType": "ArcGISFeatureLayer",
                                    "title": "b",
                                }
                            ],
                        },
                    ],
                }
            ]
        }
        result = _translate(webmap, {"L1": uuid.uuid4(), "L2": uuid.uuid4()})
        assert [x.display_name for x in result.layers] == ["a", "b"]
        for layer in result.layers:
            assert layer.style_config["builder"]["folder_group_id"] == "G"
            assert layer.style_config["builder"]["folder_group_name"] == "Water"
            assert layer.visible is False
            assert layer.opacity == 0.5
        assert "nested_group" in _kinds(result)

    @pytest.mark.parametrize(
        "layer_type",
        [
            "ArcGISTiledMapServiceLayer",
            "WMS",
            "VectorTileLayer",
            "ArcGISSceneServiceLayer",
        ],
    )
    def test_other_layer_types_are_reported(self, layer_type: str) -> None:
        result = _translate(_webmap({"layerType": layer_type}))
        assert result.layers == []
        assert result.unmatched == []
        assert result.loss.items[0].kind == "unsupported_layer_type"
        assert result.loss.items[0].detail == layer_type

    def test_unmatched_layer_is_listed(self) -> None:
        result = _translate(_webmap(), matches={})
        assert result.layers == []
        assert [(u.layer_id, u.reason) for u in result.unmatched] == [
            ("L1", "no_match")
        ]
        assert _kinds(result) == {"unmatched_layer"}

    def test_layers_past_the_cap_are_losses(self) -> None:
        count = 205
        webmap = {
            "operationalLayers": [
                {"id": f"L{i}", "layerType": "ArcGISFeatureLayer", "title": str(i)}
                for i in range(count)
            ]
        }
        matches = {f"L{i}": uuid.uuid4() for i in range(count)}
        result = _translate(webmap, matches)
        assert len(result.layers) == 200
        assert result.loss.summary["layer_cap"] == 5


class TestDefinitionExpression:
    @pytest.mark.parametrize(
        ("sql", "expected"),
        [
            ("STATUS = 'open'", ["==", ["get", "STATUS"], "open"]),
            ("N <> 3", ["!=", ["get", "N"], 3]),
            ("N >= 2.5", [">=", ["get", "N"], 2.5]),
            ("A IS NULL", ["==", ["get", "A"], None]),
            ("A IS NOT NULL", ["!=", ["get", "A"], None]),
            ("A IN ('x', 'y')", ["in", ["get", "A"], ["literal", ["x", "y"]]]),
            ("A NOT IN (1, 2)", ["!", ["in", ["get", "A"], ["literal", [1, 2]]]]),
            (
                "A = 'it''s' AND (B < 1 OR NOT C = 2)",
                [
                    "all",
                    ["==", ["get", "A"], "it's"],
                    ["any", ["<", ["get", "B"], 1], ["!", ["==", ["get", "C"], 2]]],
                ],
            ),
            ('"Odd Name" = 1', ["==", ["get", "Odd Name"], 1]),
        ],
    )
    def test_converts(self, sql: str, expected: list) -> None:
        assert definition_expression_to_filter(sql) == expected

    @pytest.mark.parametrize(
        "sql",
        [
            "A IN (SELECT B FROM T)",
            "UPPER(A) = 'X'",
            "A LIKE 'x%'",
            "A BETWEEN 1 AND 2",
            "A = B",
            "A = 1 AND",
            "A = 1; DROP TABLE T",
            "(" * 40 + "A = 1" + ")" * 40,
        ],
    )
    def test_rejects_what_it_cannot_express(self, sql: str) -> None:
        assert definition_expression_to_filter(sql) is None

    def test_match_all(self) -> None:
        assert is_match_all("1=1") and is_match_all(" 1 = 1 ") and is_match_all("")
        assert not is_match_all("A = 1")

    def test_unsupported_expression_is_reported_and_no_partial_filter_applied(
        self,
    ) -> None:
        result = _translate(
            _webmap(
                {
                    "layerDefinition": {
                        "definitionExpression": "A = 1 AND UPPER(B) = 'X'",
                        "drawingInfo": {},
                    }
                }
            )
        )
        assert result.layers[0].filter is None
        assert "definition_expression" in _kinds(result)

    def test_supported_expression_becomes_the_layer_filter(self) -> None:
        result = _translate(
            _webmap(
                {
                    "layerDefinition": {
                        "definitionExpression": "A = 1",
                        "drawingInfo": {},
                    }
                }
            )
        )
        assert result.layers[0].filter == ["==", ["get", "A"], 1]
        assert "definition_expression" not in _kinds(result)


class TestLabels:
    def _labeled(self, expression: str, **info) -> dict:
        return _webmap(
            {
                "showLabels": True,
                "layerDefinition": {
                    "drawingInfo": {
                        "labelingInfo": [
                            {
                                "labelExpressionInfo": {"expression": expression},
                                "labelPlacement": "esriServerPointLabelPlacementAboveCenter",
                                "minScale": 591657550.5 / 2**9,
                                "maxScale": 0,
                                "symbol": {
                                    "type": "esriTS",
                                    "color": [0, 0, 0, 255],
                                    "haloColor": [255, 255, 255, 255],
                                    "haloSize": 1,
                                    "font": {"family": "Tahoma", "size": 12},
                                },
                                **info,
                            }
                        ]
                    }
                },
            }
        )

    def test_single_field_label(self) -> None:
        result = _translate(self._labeled("$feature.NAME"))
        assert result.layers[0].label_config == {
            "column": "NAME",
            "fontSize": 16.0,
            "textColor": "#000000",
            "haloColor": "#ffffff",
            "haloWidth": 1.33,
            "minZoom": 8.0,
            "textAnchor": "bottom",
        }
        assert _kinds(result) == {"renderer_missing", "label_font"}

    @pytest.mark.parametrize("expression", ["[NAME]", "{NAME}", '$feature["NAME"]'])
    def test_other_spellings_of_a_single_field(self, expression: str) -> None:
        result = _translate(self._labeled(expression))
        assert result.layers[0].label_config["column"] == "NAME"

    def test_expressions_are_reported(self) -> None:
        result = _translate(self._labeled("$feature.A + ' ' + $feature.B"))
        assert result.layers[0].label_config is None
        assert "label_expression" in _kinds(result)

    def test_extra_classes_are_reported(self) -> None:
        webmap = self._labeled("$feature.NAME")
        info = webmap["operationalLayers"][0]["layerDefinition"]["drawingInfo"]
        info["labelingInfo"].append(copy.deepcopy(info["labelingInfo"][0]))
        assert "label_class" in _kinds(_translate(webmap))

    def test_labels_switched_off_are_reported(self) -> None:
        webmap = self._labeled("$feature.NAME")
        webmap["operationalLayers"][0]["showLabels"] = False
        result = _translate(webmap)
        assert result.layers[0].label_config is None
        assert "labels_hidden" in _kinds(result)


class TestPopups:
    def test_title_and_visible_fields_in_order(self) -> None:
        popup = {
            "title": "{NAME} ({ID})",
            "fieldInfos": [
                {"fieldName": "ID", "visible": True},
                {"fieldName": "HIDDEN", "visible": False},
                {"fieldName": "NAME", "visible": True},
            ],
        }
        result = _translate(_webmap({"popupInfo": popup}))
        assert result.layers[0].popup_config.model_dump() == {
            "enabled": True,
            "expression": "{NAME} ({ID})",
            "visible_fields": ["ID", "NAME"],
        }
        assert _kinds(result) == {"renderer_missing"}

    def test_losses(self) -> None:
        popup = {
            "title": "{expression/expr0}",
            "description": "<b>{A}</b>",
            "mediaInfos": [{"type": "image"}],
            "showAttachments": True,
            "fieldInfos": [
                {
                    "fieldName": "A",
                    "visible": True,
                    "label": "Alias",
                    "format": {"places": 2},
                },
                {"fieldName": "expression/expr0", "visible": True},
            ],
        }
        result = _translate(_webmap({"popupInfo": popup}))
        assert result.layers[0].popup_config.expression is None
        assert result.layers[0].popup_config.visible_fields == ["A"]
        assert _kinds(result) - {"renderer_missing"} == {
            "popup_expression",
            "popup_html",
            "popup_media",
            "popup_attachments",
            "popup_field_label",
            "popup_field_format",
        }

    def test_field_list_is_capped(self) -> None:
        popup = {
            "fieldInfos": [{"fieldName": f"F{i}", "visible": True} for i in range(120)]
        }
        result = _translate(_webmap({"popupInfo": popup}))
        assert len(result.layers[0].popup_config.visible_fields) == 100
        assert "popup_field_cap" in _kinds(result)

    def test_disabled_popup(self) -> None:
        result = _translate(
            _webmap({"disablePopup": True, "popupInfo": {"title": "x"}})
        )
        assert result.layers[0].popup_config.enabled is False


class TestMapLevel:
    def test_mapped_basemap(self) -> None:
        webmap = _webmap(baseMap={"baseMapLayers": [{"url": "https://esri/topo"}]})
        result = _translate(webmap, basemap_map={"https://esri/topo": "openstreetmap"})
        assert result.basemap_style == "openstreetmap"
        assert "basemap" not in _kinds(result)

    def test_unmapped_basemap_falls_back_to_the_first_and_is_reported(self) -> None:
        webmap = _webmap(
            baseMap={"baseMapLayers": [{"url": "https://esri/topo"}, {"url": "r"}]}
        )
        result = _translate(webmap)
        assert result.basemap_style == "openfreemap-positron"
        assert {"basemap", "basemap_reference_layer"} <= _kinds(result)

    def test_a_mapping_to_an_unknown_basemap_is_not_trusted(self) -> None:
        webmap = _webmap(baseMap={"baseMapLayers": [{"url": "https://esri/topo"}]})
        result = _translate(webmap, basemap_map={"https://esri/topo": "https://evil/x"})
        assert result.basemap_style == "openfreemap-positron"

    def test_no_basemaps_configured_leaves_the_column_default(self) -> None:
        result = _translate(_webmap(), available_basemaps=[])
        assert result.basemap_style is None

    def test_viewpoint_sets_the_view(self) -> None:
        webmap = _webmap(
            initialState={
                "viewpoint": {
                    "targetGeometry": {
                        "xmin": -8300000,
                        "ymin": 4900000,
                        "xmax": -8200000,
                        "ymax": 5000000,
                        "spatialReference": {"wkid": 102100},
                    }
                }
            }
        )
        result = _translate(webmap)
        assert result.center_lng == pytest.approx(-74.0, abs=0.5)
        assert result.zoom is not None and 8 < result.zoom < 12

    def test_unsupported_parts_are_reported(self) -> None:
        webmap = _webmap(
            tables=[{"title": "T"}],
            bookmarks=[{"name": "b"}],
            timeSlider={"x": 1},
            widgets={"y": 1},
        )
        assert {"table_in_map", "bookmarks", "time", "widget"} <= _kinds(
            _translate(webmap)
        )

    def test_name_falls_back(self) -> None:
        assert _translate(_webmap(), name="  Mine ").name == "Mine"
        assert _translate(_webmap()).name == DEFAULT_MAP_NAME


class TestFixtures:
    def test_hosted_feature_layers(self) -> None:
        webmap = json.loads((FIXTURES / "hosted_feature_layers.json").read_text())
        matches = {layer["id"]: uuid.uuid4() for layer in webmap["operationalLayers"]}
        result = _translate(webmap, matches)

        assert len(result.layers) == 4
        assert [x.visible for x in result.layers] == [False, False, True, True]
        first = result.layers[0]
        assert first.label_config["column"] == "APP_NAME"
        assert first.popup_config.visible_fields[0] == "OBJECTID"
        assert first.paint["fill-color"] == "#828282"
        assert not result.unmatched
        for layer in result.layers:
            MapLayerInput.model_validate(layer.model_dump())

    def test_malformed_parts_never_raise(self) -> None:
        junk = [None, 1, "x", [], {"a": 1}, [None], {"type": []}]
        for value in junk:
            webmap = {
                "operationalLayers": [
                    value,
                    {
                        "id": "L1",
                        "layerType": "ArcGISFeatureLayer",
                        "layerDefinition": value,
                        "popupInfo": value,
                        "labelingInfo": value,
                        "minScale": value,
                    },
                ],
                "baseMap": value,
                "initialState": value,
                "tables": value,
            }
            _translate(webmap)
            webmap["operationalLayers"][1]["layerDefinition"] = {
                "drawingInfo": {"renderer": value, "labelingInfo": value}
            }
            _translate(webmap)


class TestLossReport:
    def test_summary_counts_kinds(self) -> None:
        report = LossReport()
        report.add("a", "x")
        report.add("b", "x")
        report.add("c", "y")
        assert report.summary == {"x": 2, "y": 1}

    def test_text_is_one_plain_line_per_item(self) -> None:
        report = LossReport()
        report.add("p", "k", "line one\nline two\x00<script>")
        lines = report.render_text("2026-10-22").splitlines()
        assert lines[0] == "ArcGIS migration notes (2026-10-22)"
        assert len(lines) == 2
        assert lines[1].startswith("- p: k (line one line two")

    def test_truncation_keeps_whole_lines_and_points_to_the_cli_report(self) -> None:
        report = LossReport()
        for index in range(100):
            report.add(f"operationalLayers[{index}]", "unmatched_layer", "x" * 100)
        text = report.render_text("2026-10-22", limit=1000)
        assert len(text) <= 1000
        lines = text.splitlines()
        assert lines[-1].startswith("... ") and lines[-1].endswith(
            "more entries in the CLI report"
        )
        kept = len(lines) - 2
        assert lines[-1] == f"... {100 - kept} more entries in the CLI report"
        assert all(line.startswith("- ") for line in lines[1:-1])
        assert all(line.endswith(")") for line in lines[1:-1])

    def test_nothing_is_cut_when_it_fits(self) -> None:
        report = LossReport()
        report.add("a", "k")
        assert "more entries" not in report.render_text("2026-10-22")

    def test_the_default_limit_is_the_notes_column_limit(self) -> None:
        report = LossReport()
        for index in range(2000):
            report.add(
                f"operationalLayers[{index}].layerDefinition", "x" * 20, "d" * 200
            )
        assert len(report.render_text("2026-10-22")) <= 50_000


def _nested(depth: int) -> list:
    value: list = []
    for _ in range(depth):
        value = [value]
    return value


class TestHostileInput:
    def test_a_long_not_chain_is_refused_not_recursed(self) -> None:
        assert definition_expression_to_filter("NOT " * 1500 + "a = 1") is None

    def test_deeply_nested_values_are_reported_without_recursing(self) -> None:
        deep = _nested(60_000)
        webmap = _with_renderer({"type": deep}, layerType="ArcGISFeatureLayer")
        result = _translate(webmap)
        assert len(result.layers) == 1
        assert "unsupported_renderer" in _kinds(result)

    def test_unhashable_types_never_raise(self) -> None:
        layer = {
            "layerType": ["x"],
            "layerDefinition": {
                "drawingInfo": {
                    "renderer": {
                        "type": "simple",
                        "symbol": {"type": ["x"], "style": []},
                    }
                }
            },
        }
        result = _translate(_webmap(layer))
        assert result.layers == []
        assert result.loss.items[0].kind == "unsupported_layer_type"
        feature = {**layer, "layerType": "ArcGISFeatureLayer"}
        assert len(_translate(_webmap(feature)).layers) == 1

    @pytest.mark.parametrize(
        "extent",
        [
            {
                "xmin": -1.7e308,
                "ymin": 0,
                "xmax": 1.7e308,
                "ymax": 1,
                "spatialReference": {"wkid": 3857},
            },
            {
                "xmin": 0,
                "ymin": 1e300,
                "xmax": 1,
                "ymax": 1e300,
                "spatialReference": {"wkid": 4326},
            },
            {
                "xmin": 0,
                "ymin": 0,
                "xmax": 1,
                "ymax": 1,
                "spatialReference": {"wkid": [1]},
            },
        ],
    )
    def test_unusable_extents_are_reported(self, extent: dict) -> None:
        result = _translate(
            _webmap(initialState={"viewpoint": {"targetGeometry": extent}})
        )
        assert result.center_lng is None
        assert "viewpoint" in _kinds(result)

    def test_huge_sizes_stay_finite(self) -> None:
        symbol = {**_line(), "width": 1.7e308}
        result = _translate(_with_renderer({"type": "simple", "symbol": symbol}))
        paint = result.layers[0].paint
        json.dumps(paint, allow_nan=False)
        assert paint["line-width"] == 1333.33

    def test_a_huge_popup_field_list_is_handled_in_linear_time(self) -> None:
        popup = {
            "fieldInfos": [
                {"fieldName": f"F{i}", "visible": True} for i in range(30_000)
            ]
        }
        result = _translate(_webmap({"popupInfo": popup}))
        assert len(result.layers[0].popup_config.visible_fields) == 100
        assert result.loss.summary["popup_field_cap"] == 1

    def test_deeply_nested_groups_stop_at_the_depth_cap(self) -> None:
        layer: dict = {"id": "L1", "layerType": "ArcGISFeatureLayer"}
        for depth in range(40):
            layer = {"id": f"G{depth}", "layerType": "GroupLayer", "layers": [layer]}
        result = _translate({"operationalLayers": [layer]})
        assert result.layers == []
        assert "nested_group" in _kinds(result)

    def test_report_text_cannot_be_split_into_forged_entries(self) -> None:
        report = LossReport()
        report.add("p", "k", "x\x85- operationalLayers[9]: forged‮\r\nmore")
        text = report.render_text("2026-10-22")
        assert len(text.splitlines()) == 2
        assert "\x85" not in text and "‮" not in text


class TestBoundedWork:
    def test_loss_items_are_capped_and_the_summary_still_counts_everything(
        self,
    ) -> None:
        report = LossReport()
        for index in range(5000):
            report.add(f"p{index}", "x")
        report.add("q", "y")
        data = report.as_dict()
        assert len(report.items) == 1000
        assert len(data["items"]) == 1001
        assert data["items"][-1]["kind"] == "loss_truncated"
        assert data["items"][-1]["detail"] == "4001 more entries"
        assert data["summary"]["x"] == 5000 and data["summary"]["y"] == 1
        text = report.render_text("2026-10-22")
        assert text.splitlines()[-1].startswith("- : loss_truncated")

    def test_classes_past_the_limit_are_never_parsed(self) -> None:
        renderer = {
            "type": "uniqueValue",
            "field1": "f",
            "uniqueValueInfos": [0] * 100_000,
        }
        result = _translate(_with_renderer(renderer))
        assert len(result.loss.items) <= 300

    def test_class_breaks_past_the_limit_are_never_parsed(self) -> None:
        renderer = {
            "type": "classBreaks",
            "field": "f",
            "classBreakInfos": [0] * 100_000,
        }
        result = _translate(_with_renderer(renderer))
        assert len(result.loss.items) <= 300

    @pytest.mark.parametrize("literal", ["1e400", "-1e400", "9" * 400 + ".5e1000"])
    def test_non_finite_numbers_are_not_filters(self, literal: str) -> None:
        assert definition_expression_to_filter(f"A > {literal}") is None
        assert definition_expression_to_filter(f"A IN (1, {literal})") is None

    def test_repeated_layer_ids_import_the_first_only(self) -> None:
        webmap = {
            "operationalLayers": [
                {"id": "a", "layerType": "ArcGISFeatureLayer", "title": "first"},
                {"id": "a", "layerType": "ArcGISFeatureLayer", "title": "second"},
            ]
        }
        result = _translate(webmap, {"a": uuid.uuid4()})
        assert [x.display_name for x in result.layers] == ["first"]
        assert result.layer_sources == ["a"]
        assert result.loss.summary["duplicate_layer_id"] == 1


class TestHugeIntegers:
    def test_a_huge_size_keeps_the_layer_and_only_loses_the_value(self) -> None:
        symbol = {**_point(), "size": 10**400}
        result = _translate(_with_renderer({"type": "simple", "symbol": symbol}))
        assert len(result.layers) == 1
        assert result.layers[0].paint["circle-color"] == "#ff0000"
        assert "layer_invalid" not in _kinds(result)

    def test_a_huge_scale_keeps_the_layer_and_drops_the_limit(self) -> None:
        result = _translate(_webmap({"minScale": 10**400, "maxScale": 10**400}))
        assert len(result.layers) == 1
        assert result.layers[0].layout is None

    def test_a_huge_opacity_keeps_the_default(self) -> None:
        result = _translate(_webmap({"opacity": 10**400}))
        assert result.layers[0].opacity == 1.0
