from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


T = TypeVar("T", bound="ArcgisUnmatchedLayer")


@_attrs_define
class ArcgisUnmatchedLayer:
    """
    Attributes:
        layer_id (str):
        title (str):
        url (str):
        reason (str): `no_match` or `invalid`.
    """

    layer_id: str
    title: str
    url: str
    reason: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        layer_id = self.layer_id

        title = self.title

        url = self.url

        reason = self.reason

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "layer_id": layer_id,
                "title": title,
                "url": url,
                "reason": reason,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        layer_id = d.pop("layer_id")

        title = d.pop("title")

        url = d.pop("url")

        reason = d.pop("reason")

        arcgis_unmatched_layer = cls(
            layer_id=layer_id,
            title=title,
            url=url,
            reason=reason,
        )

        arcgis_unmatched_layer.additional_properties = d
        return arcgis_unmatched_layer

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
