"""The ArcGIS web map translator: renderers, labels, popups, filters and the loss report."""

from __future__ import annotations

import copy
import json
import time
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
    if op == "any":
        return any(_eval(a, props) for a in args)
    if op == "!":
        return not _eval(args[0], props)
    if op == "literal":
        return args[0]
    left, right = (_eval(a, props) for a in args)
    if op == "==":
        return left == right
    if op == "!=":
        return left != right
    if op == "in":
        return left in right
    if left is None:
        return False
    return {
        "<=": left <= right,
        ">=": left >= right,
        "<": left < right,
        ">": left > right,
    }[op]


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

    def test_becomes_the_builders_null_guarded_step(self) -> None:
        result = _translate(_with_renderer(self._renderer()))
        layer = result.layers[0]
        assert layer.style_config["mode"] == "graduated"
        assert layer.style_config["breaks"] == [10.0, 100.0]
        assert layer.style_config["colors"] == ["#00ff00", "#ffff00", "#ff0000"]
        assert layer.paint["fill-color"] == [
            "case",
            ["==", ["get", "POP"], None],
            "rgba(0,0,0,0)",
            ["step", ["get", "POP"], "#00ff00", 10.0, "#ffff00", 100.0, "#ff0000"],
        ]
        assert _kinds(result) == {"class_boundary", "class_range"}

    def test_gaps_between_classes_are_reported(self) -> None:
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
        assert _kinds(_translate(_with_renderer(renderer))) == {
            "class_boundary",
            "class_gap",
            "class_range",
        }

    def test_contiguous_classes_report_no_gap(self) -> None:
        renderer = {
            "type": "classBreaks",
            "field": "POP",
            "classBreakInfos": [
                {"classMinValue": 0, "classMaxValue": 10, "symbol": _fill()},
                {"classMinValue": 10, "classMaxValue": 30, "symbol": _fill()},
            ],
        }
        assert "class_gap" not in _kinds(_translate(_with_renderer(renderer)))

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
            (
                "N <> 3",
                ["all", ["!=", ["get", "N"], None], ["!=", ["get", "N"], 3]],
            ),
            ("N >= 2.5", [">=", ["get", "N"], 2.5]),
            ("A IS NULL", ["==", ["get", "A"], None]),
            ("A IS NOT NULL", ["!=", ["get", "A"], None]),
            ("A IN ('x', 'y')", ["in", ["get", "A"], ["literal", ["x", "y"]]]),
            (
                "A NOT IN (1, 2)",
                [
                    "all",
                    ["!=", ["get", "A"], None],
                    ["!", ["in", ["get", "A"], ["literal", [1, 2]]]],
                ],
            ),
            (
                "A = 'it''s' AND (B < 1 OR NOT C = 2)",
                [
                    "all",
                    ["==", ["get", "A"], "it's"],
                    [
                        "any",
                        ["<", ["get", "B"], 1],
                        [
                            "all",
                            ["!=", ["get", "C"], None],
                            ["!", ["==", ["get", "C"], 2]],
                        ],
                    ],
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


class TestNullSemantics:
    """SQL hides a row whose compared field is NULL; MapLibre's negations don't."""

    @pytest.mark.parametrize(
        ("sql", "shown", "hidden"),
        [
            ("A <> 3", [{"A": 5}], [{"A": 3}, {"A": None}, {}]),
            ("A != 3", [{"A": 5}], [{"A": 3}, {"A": None}, {}]),
            ("A NOT IN (1, 2)", [{"A": 5}], [{"A": 1}, {"A": None}, {}]),
            ("NOT A = 2", [{"A": 5}], [{"A": 2}, {"A": None}, {}]),
            ("NOT A IN (1)", [{"A": 5}], [{"A": 1}, {}]),
            ("NOT (A < 2)", [{"A": 5}], [{"A": 1}, {}]),
            ("NOT A IS NULL", [{"A": 5}], [{}, {"A": None}]),
            ("NOT A IS NOT NULL", [{}, {"A": None}], [{"A": 5}]),
            ("NOT NOT A = 2", [{"A": 2}], [{"A": 5}, {}]),
            ("NOT A <> 3", [{"A": 3}], [{"A": 5}, {}]),
            (
                "A = 1 OR NOT B = 2",
                [{"A": 1}, {"A": 0, "B": 5}],
                [{"A": 0}, {"A": 0, "B": 2}],
            ),
        ],
    )
    def test_negations_hide_null_rows(
        self, sql: str, shown: list, hidden: list
    ) -> None:
        expression = definition_expression_to_filter(sql)
        assert expression is not None
        for props in shown:
            assert _eval(expression, props) is True, props
        for props in hidden:
            assert _eval(expression, props) is False, props

    @pytest.mark.parametrize(
        "sql",
        [
            "NOT (A = 1 AND B = 2)",
            "NOT (A = 1 OR B = 2)",
            "NOT (NOT (A = 1 AND B = 2))",
        ],
    )
    def test_a_negated_compound_has_no_faithful_filter(self, sql: str) -> None:
        assert definition_expression_to_filter(sql) is None


class TestTokenizerCost:
    """Pathological expressions are refused or tokenized in linear time."""

    @pytest.mark.parametrize(
        "expression",
        [
            " " * 200_000 + "!",
            "A = 1" + " " * 200_000 + "!",
            "A > 0" + "0" * 200_000 + "!",
            "A > " + "0" * 200_000 + "e",
            "A > '" + " 0" * 100_000,
            "A > [" + " [" * 100_000,
            "A = " + "[" * 200_000,
            "A > " + "-" * 200_000,
            "A > " + "." * 200_000,
        ],
    )
    def test_linear_time(self, expression: str) -> None:
        started = time.monotonic()
        definition_expression_to_filter(expression)
        assert time.monotonic() - started < 1.0

    def test_scanner_reads_the_same_tokens_as_before(self) -> None:
        assert definition_expression_to_filter("A >= -1.5e3") == [
            ">=",
            ["get", "A"],
            -1500.0,
        ]
        assert definition_expression_to_filter("A = .5") == ["==", ["get", "A"], 0.5]
        assert definition_expression_to_filter("A = 5.") == ["==", ["get", "A"], 5.0]
        assert definition_expression_to_filter("A = 'a''b'") == [
            "==",
            ["get", "A"],
            "a'b",
        ]
        assert definition_expression_to_filter("[Odd Name] = 1") == [
            "==",
            ["get", "Odd Name"],
            1,
        ]
        assert definition_expression_to_filter("A = 'open") is None
        assert definition_expression_to_filter("A = 1e") is None


def _alpha_fill(color: list[int]) -> dict:
    return {**_fill(color), "outline": _fill()["outline"]}


class TestPerClassSymbols:
    def test_a_transparent_category_keeps_its_alpha(self) -> None:
        renderer = {
            "type": "uniqueValue",
            "field1": "K",
            "uniqueValueInfos": [
                {"value": "a", "symbol": _alpha_fill([255, 0, 0, 255])},
                {"value": "b", "symbol": _alpha_fill([0, 0, 255, 0])},
            ],
        }
        layer = _translate(_with_renderer(renderer)).layers[0]
        match = layer.paint["fill-color"][3]
        assert match[2:6] == ["a", "#ff0000", "b", "rgba(0,0,255,0.0)"]
        assert layer.paint["fill-opacity"] == 1.0
        assert [c["color"] for c in layer.style_config["categories"]] == [
            "#ff0000",
            "#0000ff",
        ]

    def test_class_break_colours_carry_alpha(self) -> None:
        renderer = {
            "type": "classBreaks",
            "field": "N",
            "classBreakInfos": [
                {"classMaxValue": 1, "symbol": _alpha_fill([255, 0, 0, 128])},
                {"classMaxValue": 2, "symbol": _alpha_fill([0, 255, 0, 255])},
            ],
        }
        layer = _translate(_with_renderer(renderer)).layers[0]
        step = layer.paint["fill-color"][3]
        assert step[2] == "rgba(255,0,0,0.502)"
        assert step[4] == "#00ff00"

    def test_classes_with_other_sizes_are_reported(self) -> None:
        renderer = {
            "type": "uniqueValue",
            "field1": "K",
            "uniqueValueInfos": [
                {"value": "a", "symbol": _point(size=6)},
                {"value": "b", "symbol": _point(size=20)},
            ],
        }
        result = _translate(_with_renderer(renderer))
        assert _kinds(result) == {"symbol_style"}
        assert "1 classes differ" in result.loss.items[0].detail

    def test_identical_shapes_report_nothing(self) -> None:
        renderer = {
            "type": "uniqueValue",
            "field1": "K",
            "uniqueValueInfos": [
                {"value": "a", "symbol": _point(color=_red())},
                {"value": "b", "symbol": _point(color=[0, 0, 255, 255])},
            ],
        }
        assert not _translate(_with_renderer(renderer)).loss.items


class TestClassBreakRange:
    def _renderer(self, **extra) -> dict:
        return {
            "type": "classBreaks",
            "field": "N",
            "minValue": 0,
            "classBreakInfos": [
                {"classMaxValue": 10, "symbol": _fill([255, 0, 0, 255])},
                {"classMaxValue": 20, "symbol": _fill([0, 0, 255, 255])},
            ],
            **extra,
        }

    def test_range_limits_are_reported(self) -> None:
        assert "class_range" in _kinds(_translate(_with_renderer(self._renderer())))

    def test_the_default_symbol_colours_unclassified_features(self) -> None:
        renderer = self._renderer(defaultSymbol=_fill([1, 2, 3, 255]))
        layer = _translate(_with_renderer(renderer)).layers[0]
        assert layer.paint["fill-color"][2] == "#010203"

    def test_duplicate_maxima_keep_stops_strictly_ascending(self) -> None:
        renderer = self._renderer()
        renderer["classBreakInfos"].insert(
            1, {"classMaxValue": 10, "symbol": _fill([9, 9, 9, 255])}
        )
        result = _translate(_with_renderer(renderer))
        step = result.layers[0].paint["fill-color"][3]
        stops = step[3::2]
        assert stops == sorted(set(stops)) and len(stops) == 1
        assert "renderer_class_dropped" in _kinds(result)

    def test_all_duplicate_maxima_fall_back_to_one_paint(self) -> None:
        renderer = self._renderer()
        renderer["classBreakInfos"][1]["classMaxValue"] = 10
        result = _translate(_with_renderer(renderer))
        expression = result.layers[0].paint["fill-color"]
        assert _eval(expression, {"N": 5}) == "#ff0000"
        assert _eval(expression, {"N": None}) == "rgba(0,0,0,0)"
        assert "renderer_class_dropped" in _kinds(result)


class TestNothingDroppedSilently:
    def _kinds_for(self, symbol: dict) -> set[str]:
        return _kinds(_translate(_with_renderer({"type": "simple", "symbol": symbol})))

    def test_marker_angle_and_offset(self) -> None:
        assert self._kinds_for({**_point(), "angle": 45}) == {"symbol_style"}
        assert self._kinds_for({**_point(), "xoffset": 3}) == {"symbol_style"}

    def test_marker_outline_style(self) -> None:
        symbol = _point()
        symbol["outline"] = {**symbol["outline"], "style": "esriSLSDash"}
        assert self._kinds_for(symbol) == {"symbol_style"}

    def test_a_marker_without_an_outline_has_no_stroke(self) -> None:
        symbol = _point()
        symbol["outline"] = {**symbol["outline"], "style": "esriSLSNull"}
        result = _translate(_with_renderer({"type": "simple", "symbol": symbol}))
        assert result.layers[0].paint["circle-stroke-width"] == 0
        assert not result.loss.items

    def test_line_end_markers(self) -> None:
        assert self._kinds_for({**_line(), "marker": {"style": "arrow"}}) == {
            "symbol_style"
        }

    def test_fill_outline_transparency(self) -> None:
        symbol = _fill()
        symbol["outline"] = {**symbol["outline"], "color": [0, 0, 0, 100]}
        assert self._kinds_for(symbol) == {"symbol_style"}

    def test_rotation(self) -> None:
        renderer = {"type": "simple", "symbol": _point(), "rotationType": "geographic"}
        assert _kinds(_translate(_with_renderer(renderer))) == {"visual_variable"}

    def test_heatmap_intensity_range(self) -> None:
        renderer = {"type": "heatmap", "field": "W", "maxPixelIntensity": 50}
        assert _kinds(_translate(_with_renderer(renderer))) == {"heatmap_ramp"}


class TestLabelAndPopupSweep:
    def _label(self, **info) -> set[str]:
        symbol = {"type": "esriTS", "color": [0, 0, 0, 255], "font": {"size": 10}}
        symbol.update(info.pop("symbol", {}))
        webmap = _webmap(
            {
                "showLabels": True,
                "layerDefinition": {
                    "drawingInfo": {
                        "labelingInfo": [
                            {
                                "labelExpressionInfo": {"expression": "$feature.N"},
                                "symbol": symbol,
                                **info,
                            }
                        ]
                    }
                },
            }
        )
        return _kinds(_translate(webmap)) - {"renderer_missing"}

    def test_unmapped_placement(self) -> None:
        assert self._label(labelPlacement="esriServerLinePlacementAboveStart") == {
            "label_placement"
        }

    def test_default_polygon_placement_is_not_a_loss(self) -> None:
        assert not self._label(
            labelPlacement="esriServerPolygonPlacementAlwaysHorizontal"
        )

    def test_label_offset_and_angle(self) -> None:
        assert self._label(symbol={"xoffset": 4}) == {"label_placement"}

    def test_label_background_and_weight(self) -> None:
        assert self._label(symbol={"backgroundColor": [1, 1, 1, 255]}) == {
            "label_style"
        }
        weight = {"font": {"size": 10, "weight": "bold"}}
        assert self._label(symbol=weight) == {"label_style"}

    def test_a_formatted_popup_placeholder_is_not_copied(self) -> None:
        webmap = _webmap({"popupInfo": {"title": "{POP:NumberFormat(places:0)}"}})
        layer = _translate(webmap).layers[0]
        assert layer.popup_config.expression is None
        assert "popup_expression" in _kinds(_translate(webmap))

    def test_overlong_popup_field_names_are_counted(self) -> None:
        popup = {"fieldInfos": [{"fieldName": "F" * 200, "visible": True}]}
        result = _translate(_webmap({"popupInfo": popup}))
        assert result.layers[0].popup_config.visible_fields == []
        assert "popup_field_cap" in _kinds(result)


class TestLayerSettingsSweep:
    def _extra_kinds(self, layer: dict) -> set[str]:
        return _kinds(_translate(_webmap(layer))) - {"renderer_missing"}

    @pytest.mark.parametrize(
        ("layer", "kind"),
        [
            ({"blendMode": "multiply"}, "layer_effect"),
            ({"effect": [{"type": "drop-shadow"}]}, "layer_effect"),
            ({"featureReduction": {"type": "cluster"}}, "feature_reduction"),
            ({"timeInfo": {"startTimeField": "T"}}, "time"),
            ({"layerDefinition": {"timeInfo": {"startTimeField": "T"}}}, "time"),
            ({"refreshInterval": 5}, "refresh_interval"),
            ({"customParameters": {"token": "secret"}}, "custom_parameters"),
        ],
    )
    def test_reported(self, layer: dict, kind: str) -> None:
        assert self._extra_kinds(layer) == {kind}

    def test_defaults_are_not_losses(self) -> None:
        layer = {"blendMode": "normal", "refreshInterval": 0, "effect": []}
        assert not self._extra_kinds(layer)

    def test_custom_parameter_values_stay_out_of_the_report(self) -> None:
        result = _translate(_webmap({"customParameters": {"token": "s3cr3t"}}))
        assert "s3cr3t" not in json.dumps(result.loss.as_dict())

    def test_a_groups_effect_is_reported(self) -> None:
        webmap = {
            "operationalLayers": [
                {
                    "id": "G",
                    "layerType": "GroupLayer",
                    "blendMode": "screen",
                    "layers": [{"id": "L1", "layerType": "ArcGISFeatureLayer"}],
                }
            ]
        }
        assert "layer_effect" in _kinds(_translate(webmap))

    def test_renderer_transparency_lowers_the_layer_opacity(self) -> None:
        layer = {
            "opacity": 0.5,
            "layerDefinition": {"drawingInfo": {"transparency": 40}},
        }
        assert _translate(_webmap(layer)).layers[0].opacity == 0.3


def _unknown_in(path: list, webmap: dict) -> dict:
    node = webmap
    for key in path[:-1]:
        node = node[key]
    node[path[-1]]["zzUnknown"] = "secret-value"
    return webmap


def _full_webmap() -> dict:
    symbol = {**_point(), "outline": {"type": "esriSLS", "color": _red(), "width": 1}}
    return {
        "operationalLayers": [
            {
                "id": "L1",
                "layerType": "ArcGISFeatureLayer",
                "title": "T",
                "showLabels": True,
                "popupInfo": {
                    "title": "{A}",
                    "popupElements": [
                        {"type": "fields", "fieldInfos": [{"fieldName": "A"}]}
                    ],
                },
                "layerDefinition": {
                    "drawingInfo": {
                        "renderer": {"type": "simple", "symbol": symbol},
                        "labelingInfo": [
                            {
                                "labelExpressionInfo": {"expression": "$feature.A"},
                                "symbol": {"type": "esriTS", "color": [0, 0, 0, 255]},
                            }
                        ],
                    }
                },
            }
        ]
    }


_LAYER = ["operationalLayers", 0]
_DRAW = [*_LAYER, "layerDefinition", "drawingInfo"]


class TestUnsupportedProperty:
    @pytest.mark.parametrize(
        "path",
        [
            [*_LAYER],
            [*_LAYER, "layerDefinition"],
            [*_DRAW],
            [*_DRAW, "renderer"],
            [*_DRAW, "renderer", "symbol"],
            [*_DRAW, "renderer", "symbol", "outline"],
            [*_DRAW, "labelingInfo", 0],
            [*_DRAW, "labelingInfo", 0, "symbol"],
            [*_LAYER, "popupInfo"],
            [*_LAYER, "popupInfo", "popupElements", 0],
        ],
    )
    def test_an_unknown_key_is_reported_by_name_only(self, path: list) -> None:
        webmap = _unknown_in(path, _full_webmap())
        result = _translate(webmap)
        items = [i for i in result.loss.items if i.kind == "unsupported_property"]
        assert len(items) == 1, result.loss.items
        assert items[0].detail == "zzUnknown"
        assert "secret-value" not in json.dumps(result.loss.as_dict())

    @pytest.mark.parametrize(
        "symbol",
        [
            {**_point()},
            {**_line()},
            {**_fill()},
            {"type": "esriPMS", "url": "x", "width": 1, "height": 1},
            {"type": "esriPFS", "url": "x", "width": 1, "height": 1},
        ],
    )
    def test_every_symbol_type_reports_unknown_keys(self, symbol: dict) -> None:
        symbol["zzUnknown"] = 1
        result = _translate(_with_renderer({"type": "simple", "symbol": symbol}))
        assert any(
            i.kind == "unsupported_property" and i.detail == "zzUnknown"
            for i in result.loss.items
        )

    @pytest.mark.parametrize(
        "renderer",
        [
            {
                "type": "uniqueValue",
                "field1": "A",
                "uniqueValueInfos": [{"value": "x", "symbol": _fill()}],
            },
            {
                "type": "classBreaks",
                "field": "A",
                "classBreakInfos": [{"classMaxValue": 1, "symbol": _fill()}],
            },
            {"type": "heatmap", "field": "A"},
        ],
    )
    def test_every_renderer_type_reports_unknown_keys(self, renderer: dict) -> None:
        renderer = {**renderer, "zzUnknown": 1}
        result = _translate(_with_renderer(renderer))
        assert any(
            i.kind == "unsupported_property" and i.detail == "zzUnknown"
            for i in result.loss.items
        )

    def test_unknown_class_keys_are_reported_once_for_all_classes(self) -> None:
        infos = [{"value": str(n), "symbol": _fill(), "zzUnknown": 1} for n in range(5)]
        renderer = {"type": "uniqueValue", "field1": "A", "uniqueValueInfos": infos}
        result = _translate(_with_renderer(renderer))
        assert result.loss.summary.get("unsupported_property") == 1

    def test_a_group_reports_unknown_keys(self) -> None:
        webmap = {
            "operationalLayers": [
                {"id": "G", "layerType": "GroupLayer", "zzUnknown": 1, "layers": []}
            ]
        }
        assert "unsupported_property" in _kinds(_translate(webmap))

    def test_the_hosted_layer_fixture_needs_no_generic_report(self) -> None:
        webmap = json.loads((FIXTURES / "hosted_feature_layers.json").read_text())
        matches = {layer["id"]: uuid.uuid4() for layer in webmap["operationalLayers"]}
        result = _translate(webmap, matches)
        assert "unsupported_property" not in _kinds(result), [
            i for i in result.loss.items if i.kind == "unsupported_property"
        ]


class TestRound3:
    def test_an_enabled_display_filter_is_reported(self) -> None:
        layer = {
            "layerDefinition": {"displayFilterInfo": {"filters": [{"where": "A=1"}]}}
        }
        assert "display_filter" in _kinds(_translate(_webmap(layer)))

    @pytest.mark.parametrize(
        "layer",
        [
            {
                "layerDefinition": {
                    "displayFilterInfo": {"enabled": False, "filters": [{}]}
                }
            },
            {
                "disableDisplayFilter": True,
                "layerDefinition": {"displayFilterInfo": {"filters": [{}]}},
            },
        ],
    )
    def test_a_disabled_display_filter_is_not(self, layer: dict) -> None:
        assert "display_filter" not in _kinds(_translate(_webmap(layer)))

    def test_label_text_alpha_becomes_text_opacity(self) -> None:
        webmap = _full_webmap()
        symbol = webmap["operationalLayers"][0]["layerDefinition"]["drawingInfo"][
            "labelingInfo"
        ][0]["symbol"]
        symbol.update(
            {"color": [0, 0, 0, 128], "haloColor": [255, 255, 255, 100], "haloSize": 1}
        )
        result = _translate(webmap)
        config = result.layers[0].label_config
        assert config["textOpacity"] == 0.502
        assert "label_style" in _kinds(result)

    def _popup(self, elements: list, **info) -> tuple[set[str], dict]:
        popup = {"popupElements": elements, **info}
        result = _translate(_webmap({"popupInfo": popup}))
        return _kinds(result) - {"renderer_missing"}, result.layers[
            0
        ].popup_config.model_dump()

    @pytest.mark.parametrize(
        ("kind", "code"),
        [
            ("text", "popup_html"),
            ("media", "popup_media"),
            ("attachments", "popup_attachments"),
            ("expression", "popup_expression"),
            ("arcade", "popup_element"),
        ],
    )
    def test_unsupported_popup_elements_are_reported(
        self, kind: str, code: str
    ) -> None:
        kinds, config = self._popup([{"type": kind}])
        assert kinds == {code}
        assert config["visible_fields"] == []

    def test_a_fields_element_supplies_the_field_list(self) -> None:
        elements = [
            {"type": "fields", "fieldInfos": [{"fieldName": "B"}, {"fieldName": "A"}]},
            {"type": "text"},
        ]
        kinds, config = self._popup(
            elements, fieldInfos=[{"fieldName": "Z", "visible": True}]
        )
        assert config["visible_fields"] == ["B", "A"]
        assert kinds == {"popup_html"}

    def test_a_fields_element_without_its_own_list_uses_the_popups(self) -> None:
        _, config = self._popup(
            [{"type": "fields"}],
            fieldInfos=[{"fieldName": "Z", "visible": True}, {"fieldName": "Y"}],
        )
        assert config["visible_fields"] == ["Z", "Y"]

    def test_a_fill_outline_reports_unknown_keys(self) -> None:
        symbol = _fill()
        symbol["outline"]["zzUnknown"] = 1
        result = _translate(_with_renderer({"type": "simple", "symbol": symbol}))
        assert any(
            i.kind == "unsupported_property" and i.detail == "zzUnknown"
            for i in result.loss.items
        )


class TestUnclassifiedFeatures:
    """ArcGIS leaves features no class or default symbol covers undrawn."""

    def _unique(self, **extra) -> dict:
        return {
            "type": "uniqueValue",
            "field1": "K",
            "uniqueValueInfos": [{"value": "a", "symbol": _fill([255, 0, 0, 255])}],
            **extra,
        }

    def _breaks(self, **extra) -> dict:
        return {
            "type": "classBreaks",
            "field": "N",
            "classBreakInfos": [
                {"classMaxValue": 1, "symbol": _fill([255, 0, 0, 255])},
                {"classMaxValue": 2, "symbol": _fill([0, 0, 255, 255])},
            ],
            **extra,
        }

    def _color(self, renderer: dict):
        return _translate(_with_renderer(renderer)).layers[0].paint["fill-color"]

    def test_unique_value_without_a_default_hides_the_rest(self) -> None:
        expression = self._color(self._unique())
        assert expression[2] == "rgba(0,0,0,0)"
        assert expression[3][-1] == "rgba(0,0,0,0)"

    def test_unique_value_with_a_default_paints_the_rest(self) -> None:
        expression = self._color(self._unique(defaultSymbol=_fill([1, 2, 3, 255])))
        assert expression[2] == "#010203"
        assert expression[3][-1] == "#010203"

    def test_class_breaks_without_a_default_hide_nulls(self) -> None:
        assert self._color(self._breaks())[2] == "rgba(0,0,0,0)"

    def test_class_breaks_with_a_default_paint_nulls(self) -> None:
        expression = self._color(self._breaks(defaultSymbol=_fill([1, 2, 3, 255])))
        assert expression[2] == "#010203"


def _scale(zoom: float) -> float:
    return 591657550.5 / 2 ** (zoom + 1)


class TestGroupScaleLimits:
    def _group(self, group: dict, layer: dict | None = None) -> list:
        leaf = {"id": "L1", "layerType": "ArcGISFeatureLayer", **(layer or {})}
        webmap = {
            "operationalLayers": [
                {"id": "G", "layerType": "GroupLayer", **group, "layers": [leaf]}
            ]
        }
        return _translate(webmap)

    def test_members_inherit_the_groups_limits(self) -> None:
        result = self._group({"minScale": _scale(5), "maxScale": _scale(12)})
        assert result.layers[0].layout == {"_minzoom": 5.0, "_maxzoom": 12.0}

    def test_the_tighter_of_group_and_layer_wins(self) -> None:
        result = self._group(
            {"minScale": _scale(5), "maxScale": _scale(12)},
            {"minScale": _scale(7), "maxScale": _scale(20)},
        )
        assert result.layers[0].layout == {"_minzoom": 7.0, "_maxzoom": 12.0}

    def test_nested_groups_intersect_with_every_ancestor(self) -> None:
        inner = {
            "id": "G2",
            "layerType": "GroupLayer",
            "minScale": _scale(8),
            "layers": [{"id": "L1", "layerType": "ArcGISFeatureLayer"}],
        }
        webmap = {
            "operationalLayers": [
                {
                    "id": "G",
                    "layerType": "GroupLayer",
                    "maxScale": _scale(10),
                    "layers": [inner],
                }
            ]
        }
        layer = _translate(webmap).layers[0]
        assert layer.layout == {"_minzoom": 8.0, "_maxzoom": 10.0}

    def test_limits_that_never_overlap_hide_the_layer_and_are_reported(self) -> None:
        result = self._group({"maxScale": _scale(5)}, {"minScale": _scale(9)})
        layer = result.layers[0]
        assert layer.visible is False
        assert layer.layout is None
        assert "scale_range_empty" in _kinds(result)

    def test_a_group_that_hides_its_legend_hides_its_members(self) -> None:
        assert self._group({"showLegend": False}).layers[0].show_in_legend is False

    def test_nested_visibility_applies(self) -> None:
        inner = {
            "id": "G2",
            "layerType": "GroupLayer",
            "visibility": False,
            "layers": [{"id": "L1", "layerType": "ArcGISFeatureLayer"}],
        }
        webmap = {
            "operationalLayers": [
                {"id": "G", "layerType": "GroupLayer", "layers": [inner]}
            ]
        }
        assert _translate(webmap).layers[0].visible is False

    @pytest.mark.parametrize("key", ["popupInfo", "showLabels", "layerDefinition"])
    def test_group_keys_that_do_not_apply_are_reported(self, key: str) -> None:
        result = self._group({key: {"x": 1}})
        details = [
            i.detail for i in result.loss.items if i.kind == "unsupported_property"
        ]
        assert details == [key]


class TestFieldVisibilityDefault:
    def _fields(self, infos: list) -> list:
        result = _translate(_webmap({"popupInfo": {"fieldInfos": infos}}))
        return result.layers[0].popup_config.visible_fields

    def test_a_field_without_visible_is_shown(self) -> None:
        assert self._fields(
            [{"fieldName": "A"}, {"fieldName": "B", "visible": True}]
        ) == [
            "A",
            "B",
        ]

    def test_only_an_explicit_false_hides_a_field(self) -> None:
        infos = [{"fieldName": "A", "visible": False}, {"fieldName": "B"}]
        assert self._fields(infos) == ["B"]


class TestSingleClassBreak:
    def _renderer(self, **extra) -> dict:
        return {
            "type": "classBreaks",
            "field": "N",
            "classBreakInfos": [
                {
                    "classMinValue": 0,
                    "classMaxValue": 10,
                    "symbol": _fill([255, 0, 0, 255]),
                }
            ],
            **extra,
        }

    def _expression(self, renderer: dict):
        return _translate(_with_renderer(renderer)).layers[0].paint["fill-color"]

    def test_values_outside_the_class_are_hidden_without_a_default(self) -> None:
        expression = self._expression(self._renderer())
        assert _eval(expression, {"N": 5}) == "#ff0000"
        assert _eval(expression, {"N": 10}) == "#ff0000"
        assert _eval(expression, {"N": 11}) == "rgba(0,0,0,0)"
        assert _eval(expression, {"N": -1}) == "rgba(0,0,0,0)"
        assert _eval(expression, {"N": None}) == "rgba(0,0,0,0)"

    def test_the_default_symbol_colours_the_rest(self) -> None:
        expression = self._expression(
            self._renderer(defaultSymbol=_fill([1, 2, 3, 255]))
        )
        assert _eval(expression, {"N": 11}) == "#010203"
        assert _eval(expression, {"N": None}) == "#010203"
        assert _eval(expression, {"N": 5}) == "#ff0000"

    def test_a_class_left_over_after_deduplication_keeps_the_guard(self) -> None:
        renderer = self._renderer()
        renderer["classBreakInfos"].append(
            {"classMaxValue": 10, "symbol": _fill([9, 9, 9, 255])}
        )
        expression = self._expression(renderer)
        assert _eval(expression, {"N": None}) == "rgba(0,0,0,0)"


def _viewpoint(**extra) -> dict:
    return _webmap(
        initialState={
            "viewpoint": {
                "targetGeometry": {
                    "xmin": -8300000,
                    "ymin": 4900000,
                    "xmax": -8200000,
                    "ymax": 5000000,
                    "spatialReference": {"wkid": 102100},
                },
                **extra,
            }
        }
    )


class TestViewpointRotation:
    @pytest.mark.parametrize(
        ("rotation", "bearing"),
        [(30, -30), (270, 90), (-90, 90), (180, 180), (350, 10)],
    )
    def test_rotation_becomes_the_opposite_bearing(
        self, rotation: float, bearing: float
    ) -> None:
        assert _translate(_viewpoint(rotation=rotation)).bearing == bearing

    def test_no_rotation_leaves_the_bearing_alone(self) -> None:
        assert _translate(_viewpoint()).bearing is None
        assert _translate(_viewpoint(rotation=0)).bearing is None


class TestDefaultSymbolDifferences:
    def _renderer(self, default_size: float, classes: int) -> dict:
        infos = [
            {"classMaxValue": (n + 1) * 10, "symbol": _point(size=6)}
            for n in range(classes)
        ]
        return {
            "type": "classBreaks",
            "field": "N",
            "classBreakInfos": infos,
            "defaultSymbol": _point(size=default_size),
        }

    @pytest.mark.parametrize("classes", [1, 2])
    def test_a_default_symbol_of_another_size_is_reported(self, classes: int) -> None:
        result = _translate(_with_renderer(self._renderer(20, classes)))
        assert any(
            i.kind == "symbol_style" and "differ" in i.detail for i in result.loss.items
        )

    @pytest.mark.parametrize("classes", [1, 2])
    def test_a_matching_default_symbol_is_not(self, classes: int) -> None:
        result = _translate(_with_renderer(self._renderer(6, classes)))
        assert not any(i.kind == "symbol_style" for i in result.loss.items)


class TestWebMapAllowlist:
    @pytest.mark.parametrize(
        "where",
        ["root", "initialState", "viewpoint", "baseMap", "baseMapLayer"],
    )
    def test_unknown_keys_are_reported_by_name(self, where: str) -> None:
        webmap = _viewpoint(rotation=0)
        webmap["baseMap"] = {"baseMapLayers": [{"url": "https://esri/base"}]}
        target = {
            "root": webmap,
            "initialState": webmap["initialState"],
            "viewpoint": webmap["initialState"]["viewpoint"],
            "baseMap": webmap["baseMap"],
            "baseMapLayer": webmap["baseMap"]["baseMapLayers"][0],
        }[where]
        target["zzUnknown"] = "secret-value"
        result = _translate(webmap)
        items = [i for i in result.loss.items if i.kind == "unsupported_property"]
        assert [i.detail for i in items] == ["zzUnknown"]
        assert "secret-value" not in json.dumps(result.loss.as_dict())

    def test_an_opaque_visible_basemap_is_not_a_loss(self) -> None:
        assert "basemap" not in _kinds(_translate(_webmap()))

    def test_basemap_opacity_is_reported(self) -> None:
        webmap = _webmap(
            baseMap={"baseMapLayers": [{"url": "https://esri/base", "opacity": 0.5}]}
        )
        assert "basemap" in _kinds(_translate(webmap))

    def test_a_projection_other_than_web_mercator_is_reported(self) -> None:
        assert "spatial_reference" in _kinds(
            _translate(_webmap(spatialReference={"wkid": 2263}))
        )
        assert "spatial_reference" not in _kinds(
            _translate(_webmap(spatialReference={"latestWkid": 3857, "wkid": 102100}))
        )
