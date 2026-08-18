from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="BrandingResponse")


@_attrs_define
class BrandingResponse:
    """Response for GET /settings/branding/.

    Attributes:
        show_badge (bool): Whether to show the 'Powered by GeoLens' label in public and shared footers. Badge-removal
            writes are restricted controls.
        privacy_url (None | str | Unset): Operator-configured privacy-policy URL shown on the login and register pages,
            or null when unset (no link is shown).
    """

    show_badge: bool
    privacy_url: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        show_badge = self.show_badge

        privacy_url: None | str | Unset
        if isinstance(self.privacy_url, Unset):
            privacy_url = UNSET
        else:
            privacy_url = self.privacy_url

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "show_badge": show_badge,
            }
        )
        if privacy_url is not UNSET:
            field_dict["privacy_url"] = privacy_url

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        show_badge = d.pop("show_badge")

        def _parse_privacy_url(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        privacy_url = _parse_privacy_url(d.pop("privacy_url", UNSET))

        branding_response = cls(
            show_badge=show_badge,
            privacy_url=privacy_url,
        )

        branding_response.additional_properties = d
        return branding_response

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
