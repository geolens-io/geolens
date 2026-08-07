from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.layer_info import LayerInfo


T = TypeVar("T", bound="ProbeResponse")


@_attrs_define
class ProbeResponse:
    """
    Attributes:
        service_type (str): Detected service type, e.g. 'WFS 2.0' or 'ArcGIS FeatureServer'.
        url (str): Normalized service URL after probing.
        layers (list[LayerInfo]): Layers exposed by the probed service.
        selected_layer_id (int | None | str | Unset): Auto-selected layer ID when the input URL contained a specific
            layer number.
    """

    service_type: str
    url: str
    layers: list[LayerInfo]
    selected_layer_id: int | None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        service_type = self.service_type

        url = self.url

        layers = []
        for layers_item_data in self.layers:
            layers_item = layers_item_data.to_dict()
            layers.append(layers_item)

        selected_layer_id: int | None | str | Unset
        if isinstance(self.selected_layer_id, Unset):
            selected_layer_id = UNSET
        else:
            selected_layer_id = self.selected_layer_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "service_type": service_type,
                "url": url,
                "layers": layers,
            }
        )
        if selected_layer_id is not UNSET:
            field_dict["selected_layer_id"] = selected_layer_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.layer_info import LayerInfo

        d = dict(src_dict)
        service_type = d.pop("service_type")

        url = d.pop("url")

        layers = []
        _layers = d.pop("layers")
        for layers_item_data in _layers:
            layers_item = LayerInfo.from_dict(layers_item_data)

            layers.append(layers_item)

        def _parse_selected_layer_id(data: object) -> int | None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | str | Unset, data)

        selected_layer_id = _parse_selected_layer_id(d.pop("selected_layer_id", UNSET))

        probe_response = cls(
            service_type=service_type,
            url=url,
            layers=layers,
            selected_layer_id=selected_layer_id,
        )

        probe_response.additional_properties = d
        return probe_response

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
