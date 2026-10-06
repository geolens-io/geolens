from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.service_auth_request import ServiceAuthRequest
    from ..models.stac_asset_size_target import StacAssetSizeTarget


T = TypeVar("T", bound="StacAssetSizesRequest")


@_attrs_define
class StacAssetSizesRequest:
    """
    Attributes:
        url (str): STAC API root URL the assets were found in.
        assets (list[StacAssetSizeTarget]): Assets to measure (max 50 per request).
        auth (None | ServiceAuthRequest | Unset): Credential for a protected catalog. It is sent only to assets on the
            catalog's own origin.
    """

    url: str
    assets: list[StacAssetSizeTarget]
    auth: None | ServiceAuthRequest | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.service_auth_request import ServiceAuthRequest

        url = self.url

        assets = []
        for assets_item_data in self.assets:
            assets_item = assets_item_data.to_dict()
            assets.append(assets_item)

        auth: dict[str, Any] | None | Unset
        if isinstance(self.auth, Unset):
            auth = UNSET
        elif isinstance(self.auth, ServiceAuthRequest):
            auth = self.auth.to_dict()
        else:
            auth = self.auth

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "url": url,
                "assets": assets,
            }
        )
        if auth is not UNSET:
            field_dict["auth"] = auth

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.service_auth_request import ServiceAuthRequest
        from ..models.stac_asset_size_target import StacAssetSizeTarget

        d = dict(src_dict)
        url = d.pop("url")

        assets = []
        _assets = d.pop("assets")
        for assets_item_data in _assets:
            assets_item = StacAssetSizeTarget.from_dict(assets_item_data)

            assets.append(assets_item)

        def _parse_auth(data: object) -> None | ServiceAuthRequest | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                auth_type_0 = ServiceAuthRequest.from_dict(data)

                return auth_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | ServiceAuthRequest | Unset, data)

        auth = _parse_auth(d.pop("auth", UNSET))

        stac_asset_sizes_request = cls(
            url=url,
            assets=assets,
            auth=auth,
        )

        stac_asset_sizes_request.additional_properties = d
        return stac_asset_sizes_request

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
