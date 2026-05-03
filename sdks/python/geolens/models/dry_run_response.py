from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.dry_run_response_oauth_providers import DryRunResponseOauthProviders
    from ..models.dry_run_response_settings import DryRunResponseSettings


T = TypeVar("T", bound="DryRunResponse")


@_attrs_define
class DryRunResponse:
    """Result of a dry-run import showing what would change.

    Attributes:
        oauth_providers (DryRunResponseOauthProviders): Per-provider diff result keyed by slug.
        settings (DryRunResponseSettings): Per-setting diff result keyed by setting name.
    """

    oauth_providers: DryRunResponseOauthProviders
    settings: DryRunResponseSettings
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        oauth_providers = self.oauth_providers.to_dict()

        settings = self.settings.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "oauth_providers": oauth_providers,
                "settings": settings,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.dry_run_response_oauth_providers import (
            DryRunResponseOauthProviders,
        )
        from ..models.dry_run_response_settings import DryRunResponseSettings

        d = dict(src_dict)
        oauth_providers = DryRunResponseOauthProviders.from_dict(
            d.pop("oauth_providers")
        )

        settings = DryRunResponseSettings.from_dict(d.pop("settings"))

        dry_run_response = cls(
            oauth_providers=oauth_providers,
            settings=settings,
        )

        dry_run_response.additional_properties = d
        return dry_run_response

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
