from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="TileConfigResponse")


@_attrs_define
class TileConfigResponse:
    """
    Attributes:
        cdn_base_url (None | str | Unset): CDN origin URL for tile delivery, if configured.
        public_api_url (None | str | Unset): Externally-reachable API base URL used in OGC self-links.
        public_app_url (None | str | Unset): Browser-facing app URL used for share links and OAuth redirects.
        public_base_url (None | str | Unset): Deprecated alias for public_api_url. Will be removed in a future release.
    """

    cdn_base_url: None | str | Unset = UNSET
    public_api_url: None | str | Unset = UNSET
    public_app_url: None | str | Unset = UNSET
    public_base_url: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        cdn_base_url: None | str | Unset
        if isinstance(self.cdn_base_url, Unset):
            cdn_base_url = UNSET
        else:
            cdn_base_url = self.cdn_base_url

        public_api_url: None | str | Unset
        if isinstance(self.public_api_url, Unset):
            public_api_url = UNSET
        else:
            public_api_url = self.public_api_url

        public_app_url: None | str | Unset
        if isinstance(self.public_app_url, Unset):
            public_app_url = UNSET
        else:
            public_app_url = self.public_app_url

        public_base_url: None | str | Unset
        if isinstance(self.public_base_url, Unset):
            public_base_url = UNSET
        else:
            public_base_url = self.public_base_url

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if cdn_base_url is not UNSET:
            field_dict["cdn_base_url"] = cdn_base_url
        if public_api_url is not UNSET:
            field_dict["public_api_url"] = public_api_url
        if public_app_url is not UNSET:
            field_dict["public_app_url"] = public_app_url
        if public_base_url is not UNSET:
            field_dict["public_base_url"] = public_base_url

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_cdn_base_url(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        cdn_base_url = _parse_cdn_base_url(d.pop("cdn_base_url", UNSET))

        def _parse_public_api_url(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        public_api_url = _parse_public_api_url(d.pop("public_api_url", UNSET))

        def _parse_public_app_url(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        public_app_url = _parse_public_app_url(d.pop("public_app_url", UNSET))

        def _parse_public_base_url(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        public_base_url = _parse_public_base_url(d.pop("public_base_url", UNSET))

        tile_config_response = cls(
            cdn_base_url=cdn_base_url,
            public_api_url=public_api_url,
            public_app_url=public_app_url,
            public_base_url=public_base_url,
        )

        tile_config_response.additional_properties = d
        return tile_config_response

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
