from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset


T = TypeVar("T", bound="SettingItem")


@_attrs_define
class SettingItem:
    """A single setting in the unified response.

    Attributes:
        key (str): Setting key (e.g. 'login_rate_limit', 'basemaps').
        value (Any): Current value. Type depends on the setting.
        source (str): Where the value came from: 'default' (built-in default), 'overridden' (admin set via UI), or
            'env_only' (configured via environment variable, read-only).
        label (str): Human-readable label for display in the admin UI.
        default_value (Any | Unset): Runtime default the setting resets to. Reported only for embedding_dims, so the UI
            can tell whether a reset changes the live width.
    """

    key: str
    value: Any
    source: str
    label: str
    default_value: Any | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        key = self.key

        value = self.value

        source = self.source

        label = self.label

        default_value = self.default_value

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "key": key,
                "value": value,
                "source": source,
                "label": label,
            }
        )
        if default_value is not UNSET:
            field_dict["default_value"] = default_value

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        key = d.pop("key")

        value = d.pop("value")

        source = d.pop("source")

        label = d.pop("label")

        default_value = d.pop("default_value", UNSET)

        setting_item = cls(
            key=key,
            value=value,
            source=source,
            label=label,
            default_value=default_value,
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
