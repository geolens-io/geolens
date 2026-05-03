from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.settings_update_request_settings import SettingsUpdateRequestSettings


T = TypeVar("T", bound="SettingsUpdateRequest")


@_attrs_define
class SettingsUpdateRequest:
    """Request for PUT /settings/.

    Attributes:
        settings (SettingsUpdateRequestSettings): Map of setting keys to new values. Maximum 50 settings per request.
    """

    settings: SettingsUpdateRequestSettings
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        settings = self.settings.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "settings": settings,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.settings_update_request_settings import (
            SettingsUpdateRequestSettings,
        )

        d = dict(src_dict)
        settings = SettingsUpdateRequestSettings.from_dict(d.pop("settings"))

        settings_update_request = cls(
            settings=settings,
        )

        settings_update_request.additional_properties = d
        return settings_update_request

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
