from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.fan_out_layer_request import FanOutLayerRequest


T = TypeVar("T", bound="FanOutCommitRequest")


@_attrs_define
class FanOutCommitRequest:
    """Request body for POST /ingest/commit-fan-out/{job_id}.

    Converts one pending IngestJob (multi-layer file) into N independent
    ingest tasks — one per requested layer. Maximum 50 layers per request.

        Attributes:
            layers (list[FanOutLayerRequest]): Layers to ingest as separate datasets. Maximum 50 per request.
    """

    layers: list[FanOutLayerRequest]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        layers = []
        for layers_item_data in self.layers:
            layers_item = layers_item_data.to_dict()
            layers.append(layers_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "layers": layers,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.fan_out_layer_request import FanOutLayerRequest

        d = dict(src_dict)
        layers = []
        _layers = d.pop("layers")
        for layers_item_data in _layers:
            layers_item = FanOutLayerRequest.from_dict(layers_item_data)

            layers.append(layers_item)

        fan_out_commit_request = cls(
            layers=layers,
        )

        fan_out_commit_request.additional_properties = d
        return fan_out_commit_request

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
