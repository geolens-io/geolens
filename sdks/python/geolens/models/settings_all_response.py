from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.settings_all_response_tabs import SettingsAllResponseTabs


T = TypeVar("T", bound="SettingsAllResponse")


@_attrs_define
class SettingsAllResponse:
    """Response for GET /settings/all/.

    Attributes:
        env_only (bool): Whether the instance is in env-only mode (settings are read-only and managed via environment
            variables).
        tabs (SettingsAllResponseTabs): Settings grouped by admin UI tab (general, auth, ai, etc.).
    """

    env_only: bool
    tabs: SettingsAllResponseTabs
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        env_only = self.env_only

        tabs = self.tabs.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "env_only": env_only,
                "tabs": tabs,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.settings_all_response_tabs import SettingsAllResponseTabs

        d = dict(src_dict)
        env_only = d.pop("env_only")

        tabs = SettingsAllResponseTabs.from_dict(d.pop("tabs"))

        settings_all_response = cls(
            env_only=env_only,
            tabs=tabs,
        )

        settings_all_response.additional_properties = d
        return settings_all_response

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
