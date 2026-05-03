from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


T = TypeVar("T", bound="SettingItem")


@_attrs_define
class SettingItem:
    """A single setting in the unified response.

    Attributes:
        key (str): Setting key (e.g. 'login_rate_limit', 'basemaps').
        label (str): Human-readable label for display in the admin UI.
        source (str): Where the value came from: 'default' (built-in default), 'overridden' (admin set via UI), or
            'env_only' (configured via environment variable, read-only).
        value (Any): Current value. Type depends on the setting.
    """

    key: str
    label: str
    source: str
    value: Any
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        key = self.key

        label = self.label

        source = self.source

        value = self.value

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "key": key,
                "label": label,
                "source": source,
                "value": value,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        key = d.pop("key")

        label = d.pop("label")

        source = d.pop("source")

        value = d.pop("value")

        setting_item = cls(
            key=key,
            label=label,
            source=source,
            value=value,
        )

        setting_item.additional_properties = d
        return setting_item

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
