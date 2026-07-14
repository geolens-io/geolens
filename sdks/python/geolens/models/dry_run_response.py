from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

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
        preview_token (None | str | Unset): Short-lived signed confirmation token required to apply an overwrite. Bound
            to the normalized payload, overwrite mode, and current configuration state.
    """

    oauth_providers: DryRunResponseOauthProviders
    settings: DryRunResponseSettings
    preview_token: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        oauth_providers = self.oauth_providers.to_dict()

        settings = self.settings.to_dict()

        preview_token: None | str | Unset
        if isinstance(self.preview_token, Unset):
            preview_token = UNSET
        else:
            preview_token = self.preview_token

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "oauth_providers": oauth_providers,
                "settings": settings,
            }
        )
        if preview_token is not UNSET:
            field_dict["preview_token"] = preview_token

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

        def _parse_preview_token(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        preview_token = _parse_preview_token(d.pop("preview_token", UNSET))

        dry_run_response = cls(
            oauth_providers=oauth_providers,
            settings=settings,
            preview_token=preview_token,
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
