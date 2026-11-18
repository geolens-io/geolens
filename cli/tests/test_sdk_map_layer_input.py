"""The generated SDK leaves an unset ``sort_order`` out of the request body."""

from uuid import uuid4

from geolens.models.map_layer_input import MapLayerInput


def test_unset_sort_order_is_omitted_from_the_body():
    body = MapLayerInput(dataset_id=uuid4()).to_dict()
    assert "sort_order" not in body


def test_an_explicit_zero_is_sent():
    body = MapLayerInput(dataset_id=uuid4(), sort_order=0).to_dict()
    assert body["sort_order"] == 0
