from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

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
            item_id (None | str | Unset): ArcGIS portal item ID the file came from. Stored as provenance when it is 32 hex
                characters, otherwise dropped and reported in origin_link_loss.
            portal_url (None | str | Unset): ArcGIS portal address for the item link. Stored only when it is an https URL,
                otherwise dropped and reported in origin_link_loss.
    """

    layers: list[FanOutLayerRequest]
    item_id: None | str | Unset = UNSET
    portal_url: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        layers = []
        for layers_item_data in self.layers:
            layers_item = layers_item_data.to_dict()
            layers.append(layers_item)

        item_id: None | str | Unset
        if isinstance(self.item_id, Unset):
            item_id = UNSET
        else:
            item_id = self.item_id

        portal_url: None | str | Unset
        if isinstance(self.portal_url, Unset):
            portal_url = UNSET
        else:
            portal_url = self.portal_url

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "layers": layers,
            }
        )
        if item_id is not UNSET:
            field_dict["item_id"] = item_id
        if portal_url is not UNSET:
            field_dict["portal_url"] = portal_url

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

        def _parse_item_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        item_id = _parse_item_id(d.pop("item_id", UNSET))

        def _parse_portal_url(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        portal_url = _parse_portal_url(d.pop("portal_url", UNSET))

        fan_out_commit_request = cls(
            layers=layers,
            item_id=item_id,
            portal_url=portal_url,
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
