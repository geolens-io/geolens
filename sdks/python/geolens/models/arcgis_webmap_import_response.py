from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.arcgis_loss_report import ArcgisLossReport
    from ..models.arcgis_unmatched_layer import ArcgisUnmatchedLayer
    from ..models.arcgis_webmap_import_response_layer_ids import (
        ArcgisWebmapImportResponseLayerIds,
    )
    from ..models.map_layer_input import MapLayerInput
    from ..models.map_response import MapResponse


T = TypeVar("T", bound="ArcgisWebmapImportResponse")


@_attrs_define
class ArcgisWebmapImportResponse:
    """
    Attributes:
        map_ (MapResponse | None): The new map; null on a dry run.
        layers (list[MapLayerInput]): The translated layers, in draw order.
        loss_report (ArcgisLossReport):
        unmatched_layers (list[ArcgisUnmatchedLayer]):
        layer_ids (ArcgisWebmapImportResponseLayerIds | Unset): Operational layer id to the id of the map layer created
            for it. Layers that were not imported are absent; see `loss_report`. Empty on a dry run.
    """

    map_: MapResponse | None
    layers: list[MapLayerInput]
    loss_report: ArcgisLossReport
    unmatched_layers: list[ArcgisUnmatchedLayer]
    layer_ids: ArcgisWebmapImportResponseLayerIds | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.map_response import MapResponse

        map_: dict[str, Any] | None
        if isinstance(self.map_, MapResponse):
            map_ = self.map_.to_dict()
        else:
            map_ = self.map_

        layers = []
        for layers_item_data in self.layers:
            layers_item = layers_item_data.to_dict()
            layers.append(layers_item)

        loss_report = self.loss_report.to_dict()

        unmatched_layers = []
        for unmatched_layers_item_data in self.unmatched_layers:
            unmatched_layers_item = unmatched_layers_item_data.to_dict()
            unmatched_layers.append(unmatched_layers_item)

        layer_ids: dict[str, Any] | Unset = UNSET
        if not isinstance(self.layer_ids, Unset):
            layer_ids = self.layer_ids.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "map": map_,
                "layers": layers,
                "loss_report": loss_report,
                "unmatched_layers": unmatched_layers,
            }
        )
        if layer_ids is not UNSET:
            field_dict["layer_ids"] = layer_ids

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.arcgis_loss_report import ArcgisLossReport
        from ..models.arcgis_unmatched_layer import ArcgisUnmatchedLayer
        from ..models.arcgis_webmap_import_response_layer_ids import (
            ArcgisWebmapImportResponseLayerIds,
        )
        from ..models.map_layer_input import MapLayerInput
        from ..models.map_response import MapResponse

        d = dict(src_dict)

        def _parse_map_(data: object) -> MapResponse | None:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                map_type_0 = MapResponse.from_dict(data)

                return map_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(MapResponse | None, data)

        map_ = _parse_map_(d.pop("map"))

        layers = []
        _layers = d.pop("layers")
        for layers_item_data in _layers:
            layers_item = MapLayerInput.from_dict(layers_item_data)

            layers.append(layers_item)

        loss_report = ArcgisLossReport.from_dict(d.pop("loss_report"))

        unmatched_layers = []
        _unmatched_layers = d.pop("unmatched_layers")
        for unmatched_layers_item_data in _unmatched_layers:
            unmatched_layers_item = ArcgisUnmatchedLayer.from_dict(
                unmatched_layers_item_data
            )

            unmatched_layers.append(unmatched_layers_item)

        _layer_ids = d.pop("layer_ids", UNSET)
        layer_ids: ArcgisWebmapImportResponseLayerIds | Unset
        if isinstance(_layer_ids, Unset):
            layer_ids = UNSET
        else:
            layer_ids = ArcgisWebmapImportResponseLayerIds.from_dict(_layer_ids)

        arcgis_webmap_import_response = cls(
            map_=map_,
            layers=layers,
            loss_report=loss_report,
            unmatched_layers=unmatched_layers,
            layer_ids=layer_ids,
        )

        arcgis_webmap_import_response.additional_properties = d
        return arcgis_webmap_import_response

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
