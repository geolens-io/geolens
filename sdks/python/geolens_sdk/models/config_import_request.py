from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.config_import_request_oauth_providers_type_0_item import (
        ConfigImportRequestOauthProvidersType0Item,
    )
    from ..models.config_import_request_settings_type_0 import (
        ConfigImportRequestSettingsType0,
    )


T = TypeVar("T", bound="ConfigImportRequest")


@_attrs_define
class ConfigImportRequest:
    """Payload for importing configuration.

    Attributes:
        oauth_providers (list[ConfigImportRequestOauthProvidersType0Item] | None | Unset): Optional OAuth providers to
            import. Client secrets must be re-supplied via the admin UI after import.
        settings (ConfigImportRequestSettingsType0 | None | Unset): Optional settings to import. Omit to import only
            OAuth providers.
    """

    oauth_providers: list[ConfigImportRequestOauthProvidersType0Item] | None | Unset = (
        UNSET
    )
    settings: ConfigImportRequestSettingsType0 | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.config_import_request_settings_type_0 import (
            ConfigImportRequestSettingsType0,
        )

        oauth_providers: list[dict[str, Any]] | None | Unset
        if isinstance(self.oauth_providers, Unset):
            oauth_providers = UNSET
        elif isinstance(self.oauth_providers, list):
            oauth_providers = []
            for oauth_providers_type_0_item_data in self.oauth_providers:
                oauth_providers_type_0_item = oauth_providers_type_0_item_data.to_dict()
                oauth_providers.append(oauth_providers_type_0_item)

        else:
            oauth_providers = self.oauth_providers

        settings: dict[str, Any] | None | Unset
        if isinstance(self.settings, Unset):
            settings = UNSET
        elif isinstance(self.settings, ConfigImportRequestSettingsType0):
            settings = self.settings.to_dict()
        else:
            settings = self.settings

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if oauth_providers is not UNSET:
            field_dict["oauth_providers"] = oauth_providers
        if settings is not UNSET:
            field_dict["settings"] = settings

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.config_import_request_oauth_providers_type_0_item import (
            ConfigImportRequestOauthProvidersType0Item,
        )
        from ..models.config_import_request_settings_type_0 import (
            ConfigImportRequestSettingsType0,
        )

        d = dict(src_dict)

        def _parse_oauth_providers(
            data: object,
        ) -> list[ConfigImportRequestOauthProvidersType0Item] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                oauth_providers_type_0 = []
                _oauth_providers_type_0 = data
                for oauth_providers_type_0_item_data in _oauth_providers_type_0:
                    oauth_providers_type_0_item = (
                        ConfigImportRequestOauthProvidersType0Item.from_dict(
                            oauth_providers_type_0_item_data
                        )
                    )

                    oauth_providers_type_0.append(oauth_providers_type_0_item)

                return oauth_providers_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(
                list[ConfigImportRequestOauthProvidersType0Item] | None | Unset, data
            )

        oauth_providers = _parse_oauth_providers(d.pop("oauth_providers", UNSET))

        def _parse_settings(
            data: object,
        ) -> ConfigImportRequestSettingsType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                settings_type_0 = ConfigImportRequestSettingsType0.from_dict(data)

                return settings_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ConfigImportRequestSettingsType0 | None | Unset, data)

        settings = _parse_settings(d.pop("settings", UNSET))

        config_import_request = cls(
            oauth_providers=oauth_providers,
            settings=settings,
        )

        config_import_request.additional_properties = d
        return config_import_request

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
