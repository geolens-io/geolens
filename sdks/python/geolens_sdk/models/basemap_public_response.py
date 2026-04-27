from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="BasemapPublicResponse")


@_attrs_define
class BasemapPublicResponse:
    """Public basemap response — excludes api_key.

    Attributes:
        enabled (bool): Whether the basemap is currently selectable.
        id (str): Unique basemap identifier.
        is_preset (bool): Whether this is a built-in preset.
        label (str): Display label.
        url (str): Tile URL or style JSON URL with API key already substituted (or omitted) for client use.
        attribution (None | str | Unset): Attribution string for the basemap source.
    """

    enabled: bool
    id: str
    is_preset: bool
    label: str
    url: str
    attribution: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        enabled = self.enabled

        id = self.id

        is_preset = self.is_preset

        label = self.label

        url = self.url

        attribution: None | str | Unset
        if isinstance(self.attribution, Unset):
            attribution = UNSET
        else:
            attribution = self.attribution

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "enabled": enabled,
                "id": id,
                "is_preset": is_preset,
                "label": label,
                "url": url,
            }
        )
        if attribution is not UNSET:
            field_dict["attribution"] = attribution

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        enabled = d.pop("enabled")

        id = d.pop("id")

        is_preset = d.pop("is_preset")

        label = d.pop("label")

        url = d.pop("url")

        def _parse_attribution(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        attribution = _parse_attribution(d.pop("attribution", UNSET))

        basemap_public_response = cls(
            enabled=enabled,
            id=id,
            is_preset=is_preset,
            label=label,
            url=url,
            attribution=attribution,
        )

        basemap_public_response.additional_properties = d
        return basemap_public_response

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
