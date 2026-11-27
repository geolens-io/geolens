"""Repairing saved map layers that read a column by a name that is not the stored one.

A layer can read a column by its source name, or by a name that differs from
the stored column only in case, while the tile server and MapLibre's ``get``
are both case-sensitive, so the layer renders without its data-driven
styling. ``repair_layer_columns`` rewrites those references to the name the
dataset stores the column under, resolving each against the dataset's
``column_info`` the way the manifest apply does, and reports the names it
cannot resolve instead of guessing between two columns.
"""

import uuid
from urllib.parse import parse_qs, urlsplit

from app.modules.catalog.maps.manifest_columns import (
    ColumnRepair,
    named_columns,
    repair_layer_columns,
)
from app.modules.catalog.maps.models import Map
from app.modules.catalog.maps.schemas import (
    MapLayerInput,
    MapLayerResponse,
    PopupConfig,
)
from app.modules.catalog.maps.style_json import build_maplibre_style


def _layer(**overrides):
    return MapLayerInput(
        dataset_id=overrides.get("dataset_id", uuid.uuid4()),
        paint=overrides.get("paint"),
        layout=overrides.get("layout"),
        filter=overrides.get("filter"),
        label_config=overrides.get("label_config"),
        popup_config=overrides.get("popup_config"),
        style_config=overrides.get("style_config"),
    )


def _map(**overrides):
    return Map(
        id=overrides.get("id", uuid.uuid4()),
        name=overrides.get("name", "Transit map"),
        description=overrides.get("description", "Routes and stops"),
        created_by=uuid.uuid4(),
        center_lng=-73.98,
        center_lat=40.75,
        zoom=11,
        bearing=15,
        pitch=30,
        basemap_style="openfreemap-positron",
        show_basemap_labels=True,
        visibility="private",
    )


def _response(layer: MapLayerInput, **overrides):
    return MapLayerResponse(
        id=overrides.get("id", uuid.uuid4()),
        dataset_id=layer.dataset_id,
        dataset_name=overrides.get("dataset_name", "Stops"),
        dataset_geometry_type=overrides.get("dataset_geometry_type", "POINT"),
        dataset_table_name=overrides.get("dataset_table_name", "public_stops"),
        dataset_extent_bbox=None,
        dataset_column_info=None,
        dataset_feature_count=None,
        dataset_sample_values=None,
        display_name=layer.display_name,
        sort_order=layer.sort_order if layer.sort_order is not None else 0,
        visible=layer.visible,
        opacity=layer.opacity,
        paint=layer.paint or {},
        layout=layer.layout or {},
        layer_type=overrides.get("layer_type", "vector_geolens"),
        dataset_record_type=overrides.get("dataset_record_type", "vector_dataset"),
        filter=layer.filter,
        label_config=layer.label_config,
        popup_config=layer.popup_config,
        style_config=layer.style_config,
        show_in_legend=layer.show_in_legend,
        is_3d=False,
        is_dem=False,
        dem_vertical_units=None,
        dataset_attribution=None,
    )


def _tile_cols(style, dataset_id):
    tile_url = style["sources"][f"geolens-{dataset_id}"]["tiles"][0]
    return parse_qs(urlsplit(tile_url).query)["cols"][0].split(",")


def test_repair_rewrites_a_case_variant_and_the_tile_url_asks_for_the_stored_name():
    dataset_id = uuid.uuid4()
    layer = _layer(
        dataset_id=dataset_id,
        paint={"circle-color": ["get", "Some_Field"], "circle-radius": 6},
        label_config={"column": "name"},
        filter=["==", "status", "open"],
    )

    repaired, report = repair_layer_columns(
        layer, [{"name": "some_field"}, {"name": "name"}, {"name": "status"}]
    )

    assert report == ColumnRepair(repaired={"Some_Field": "some_field"}, unrepaired={})
    assert repaired.paint == {
        "circle-color": ["get", "some_field"],
        "circle-radius": 6,
    }
    assert layer.paint == {"circle-color": ["get", "Some_Field"], "circle-radius": 6}

    style = build_maplibre_style(_map(), [_response(repaired)])
    cols = _tile_cols(style, dataset_id)
    assert cols == ["name", "some_field", "status"]
    assert "Some_Field" not in cols


def test_repair_reports_missing_and_ambiguous_names_without_guessing():
    layer = _layer(
        paint={"circle-color": ["get", "zone"]},
        label_config={"column": "No_Such"},
        filter=["==", "name", "x"],
    )

    repaired, report = repair_layer_columns(
        layer, [{"name": "Zone"}, {"name": "ZONE"}, {"name": "name"}]
    )

    assert report == ColumnRepair(
        repaired={}, unrepaired={"zone": "ambiguous", "No_Such": "missing"}
    )
    assert repaired.paint == {"circle-color": ["get", "zone"]}
    assert repaired.label_config == {"column": "No_Such"}
    assert named_columns(repaired) == {"zone", "No_Such", "name"}


def test_repair_leaves_an_exact_match_alone_even_when_another_column_differs_only_by_case():
    layer = _layer(paint={"circle-color": ["get", "Zone"]})

    repaired, report = repair_layer_columns(layer, [{"name": "Zone"}, {"name": "zone"}])

    assert report == ColumnRepair(repaired={}, unrepaired={})
    assert repaired.paint == {"circle-color": ["get", "Zone"]}


def test_repair_reads_a_source_name_before_a_case_variant_stored_name():
    layer = _layer(paint={"circle-color": ["get", "Name"]})

    repaired, report = repair_layer_columns(
        layer,
        [
            {"name": "full_name", "source_name": "Name"},
            {"name": "name", "source_name": "Label"},
        ],
    )

    assert report == ColumnRepair(repaired={"Name": "full_name"}, unrepaired={})
    assert repaired.paint == {"circle-color": ["get", "full_name"]}


def test_repair_leaves_a_stored_name_alone_when_another_column_records_it_as_a_source_name():
    layer = _layer(paint={"circle-color": ["get", "name"]})

    repaired, report = repair_layer_columns(
        layer,
        [
            {"name": "name_2", "source_name": "name"},
            {"name": "name", "source_name": "Label"},
        ],
    )

    assert report == ColumnRepair(repaired={}, unrepaired={})
    assert repaired.paint == {"circle-color": ["get", "name"]}


def test_repair_does_not_swap_two_columns_that_name_each_other_as_source():
    columns = [
        {"name": "x", "source_name": "y"},
        {"name": "y", "source_name": "x"},
    ]
    first_layer = _layer(paint={"circle-color": ["get", "x"]})
    second_layer = _layer(paint={"circle-color": ["get", "y"]})

    repaired_once, first = repair_layer_columns(first_layer, columns)
    repaired_twice, second = repair_layer_columns(repaired_once, columns)

    assert first == ColumnRepair(repaired={}, unrepaired={})
    assert second == ColumnRepair(repaired={}, unrepaired={})
    assert repaired_twice.paint == {"circle-color": ["get", "x"]}

    repaired_other, other = repair_layer_columns(second_layer, columns)
    assert other == ColumnRepair(repaired={}, unrepaired={})
    assert repaired_other.paint == {"circle-color": ["get", "y"]}


def test_repair_leaves_a_stored_name_alone_when_another_columns_source_differs_only_by_case():
    layer = _layer(
        paint={"circle-color": ["get", "name"]},
        label_config={"column": "full_name"},
    )

    repaired, report = repair_layer_columns(
        layer,
        [
            {"name": "full_name", "source_name": "Name"},
            {"name": "name", "source_name": "Label"},
        ],
    )

    assert report == ColumnRepair(repaired={}, unrepaired={})
    assert repaired.paint == {"circle-color": ["get", "name"]}
    assert repaired.label_config == {"column": "full_name"}


def test_repair_resolves_a_source_name_that_differs_from_the_stored_name():
    layer = _layer(paint={"circle-color": ["get", "Some Field"]})

    repaired, report = repair_layer_columns(
        layer, [{"name": "some_field", "source_name": "Some Field"}]
    )

    assert report == ColumnRepair(repaired={"Some Field": "some_field"}, unrepaired={})
    assert repaired.paint == {"circle-color": ["get", "some_field"]}


def test_repair_rewrites_a_case_variant_of_a_stored_name_that_records_a_source_name():
    layer = _layer(
        paint={"circle-color": ["get", "Some_Field"]},
        label_config={"column": "SOME_FIELD"},
    )

    repaired, report = repair_layer_columns(
        layer, [{"name": "some_field", "source_name": "Some Field"}]
    )

    assert report == ColumnRepair(
        repaired={"Some_Field": "some_field", "SOME_FIELD": "some_field"},
        unrepaired={},
    )
    assert repaired.paint == {"circle-color": ["get", "some_field"]}
    assert repaired.label_config == {"column": "some_field"}


def test_repair_does_not_override_an_ambiguous_source_name_match():
    layer = _layer(paint={"circle-color": ["get", "ZONE"]})

    repaired, report = repair_layer_columns(
        layer,
        [
            {"name": "Zone", "source_name": "zone"},
            {"name": "other", "source_name": "Zone"},
        ],
    )

    assert report.repaired == {}
    assert "ZONE" in report.unrepaired
    assert repaired.paint == {"circle-color": ["get", "ZONE"]}


def test_repair_resolves_a_dashed_name_by_laundering():
    layer = _layer(paint={"circle-color": ["get", "Some-Field"]})

    repaired, report = repair_layer_columns(layer, [{"name": "some_field"}])

    assert report == ColumnRepair(repaired={"Some-Field": "some_field"}, unrepaired={})
    assert repaired.paint == {"circle-color": ["get", "some_field"]}


def test_repair_rewrites_references_in_filter_labels_popup_and_layout():
    layer = _layer(
        paint={"circle-color": ["get", "Some_Field"]},
        layout={"text-field": "{Some_Field} park"},
        filter=["==", ["get", "Some_Field"], "x"],
        label_config={"column": "Some_Field"},
        popup_config={
            "enabled": True,
            "visible_fields": ["Some_Field"],
            "expression": "{Some_Field}",
        },
    )

    repaired, report = repair_layer_columns(layer, [{"name": "some_field"}])

    assert report == ColumnRepair(repaired={"Some_Field": "some_field"}, unrepaired={})
    assert repaired.paint == {"circle-color": ["get", "some_field"]}
    assert repaired.layout == {"text-field": "{some_field} park"}
    assert repaired.filter == ["==", ["get", "some_field"], "x"]
    assert repaired.label_config == {"column": "some_field"}
    assert repaired.popup_config.visible_fields == ["some_field"]
    assert repaired.popup_config.expression == "{some_field}"


def test_repair_keeps_one_popup_field_when_two_references_resolve_to_it():
    layer = _layer(
        popup_config={"enabled": True, "visible_fields": ["NAME", "kind", "name"]},
    )

    repaired, report = repair_layer_columns(layer, [{"name": "name"}, {"name": "kind"}])

    assert report.repaired == {"NAME": "name"}
    assert repaired.popup_config.visible_fields == ["name", "kind"]
    PopupConfig.model_validate(repaired.popup_config.model_dump())


def test_repair_leaves_a_layer_alone_when_the_renames_would_not_validate():
    # 80 placeholders fit the popup's 500-character limit as "{geom}" (480)
    # and overflow it as "{src_geom}" (800).
    layer = _layer(
        paint={"circle-color": ["get", "Some_Field"]},
        popup_config={"enabled": True, "expression": "{geom}" * 80},
    )

    repaired, report = repair_layer_columns(
        layer,
        [{"name": "src_geom", "source_name": "geom"}, {"name": "some_field"}],
    )

    assert repaired is layer
    assert report.repaired == {}
    assert report.unrepaired == {"geom": "invalid", "Some_Field": "invalid"}
    assert report.refused is not None
    assert "popup_config.expression" in report.refused


def test_repair_leaves_a_layer_with_no_recorded_columns_alone():
    layer = _layer(paint={"circle-color": ["get", "Some_Field"]})

    repaired, report = repair_layer_columns(layer, [])

    assert report == ColumnRepair(repaired={}, unrepaired={})
    assert repaired.paint == {"circle-color": ["get", "Some_Field"]}


def test_repair_leaves_a_layer_with_unknown_columns_alone():
    layer = _layer(paint={"circle-color": ["get", "Some_Field"]})

    repaired, report = repair_layer_columns(layer, None)

    assert report == ColumnRepair(repaired={}, unrepaired={})
    assert repaired.paint == {"circle-color": ["get", "Some_Field"]}


def test_repair_leaves_the_layer_it_was_given_alone():
    layer = _layer(paint={"circle-color": ["get", "Some_Field"]})
    before = layer.model_dump_json()

    repair_layer_columns(layer, [{"name": "some_field"}])

    assert layer.model_dump_json() == before


def test_repairing_a_repaired_layer_changes_nothing():
    layer = _layer(paint={"circle-color": ["get", "Some_Field"]})
    repaired, _ = repair_layer_columns(layer, [{"name": "some_field"}])

    repaired_again, report = repair_layer_columns(repaired, [{"name": "some_field"}])

    assert report == ColumnRepair(repaired={}, unrepaired={})
    assert repaired_again.paint == {"circle-color": ["get", "some_field"]}
