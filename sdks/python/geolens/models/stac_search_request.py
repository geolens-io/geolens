from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.stac_search_request_cloud_cover_mode_type_0 import (
    check_stac_search_request_cloud_cover_mode_type_0,
)
from ..models.stac_search_request_cloud_cover_mode_type_0 import (
    StacSearchRequestCloudCoverModeType0,
)
from typing import cast

if TYPE_CHECKING:
    from ..models.service_auth_request import ServiceAuthRequest
    from ..models.stac_next_page import StacNextPage


T = TypeVar("T", bound="StacSearchRequest")


@_attrs_define
class StacSearchRequest:
    """
    Attributes:
        url (str): STAC API root URL.
        collections (list[str] | None | Unset): Filter by collection IDs.
        bbox (list[float] | None | Unset): Bounding box filter as [west, south, east, north].
        datetime_range (None | str | Unset): Temporal filter in STAC datetime format (e.g. '2023-01-01/2023-12-31').
        limit (int | Unset): Maximum items to return. Default: 20.
        max_cloud_cover (float | None | Unset): Only items at or below this eo:cloud_cover percentage.
        cloud_cover_mode (None | StacSearchRequestCloudCoverModeType0 | Unset): How to send max_cloud_cover: 'query' for
            the STAC Query extension, 'filter' for CQL2 JSON. Pick the one the catalog lists in its landing page conformsTo.
        next_page (None | StacNextPage | Unset): The next_page of the previous response, to fetch the page after it.
            Send the same filters as the first request.
        token (None | str | Unset): Optional auth token for a protected STAC catalog. Deprecated: use the auth object
            with method bearer.
        auth (None | ServiceAuthRequest | Unset): Structured credential for a protected service. Mutually exclusive with
            the token field.
    """

    url: str
    collections: list[str] | None | Unset = UNSET
    bbox: list[float] | None | Unset = UNSET
    datetime_range: None | str | Unset = UNSET
    limit: int | Unset = 20
    max_cloud_cover: float | None | Unset = UNSET
    cloud_cover_mode: None | StacSearchRequestCloudCoverModeType0 | Unset = UNSET
    next_page: None | StacNextPage | Unset = UNSET
    token: None | str | Unset = UNSET
    auth: None | ServiceAuthRequest | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.service_auth_request import ServiceAuthRequest
        from ..models.stac_next_page import StacNextPage

        url = self.url

        collections: list[str] | None | Unset
        if isinstance(self.collections, Unset):
            collections = UNSET
        elif isinstance(self.collections, list):
            collections = self.collections

        else:
            collections = self.collections

        bbox: list[float] | None | Unset
        if isinstance(self.bbox, Unset):
            bbox = UNSET
        elif isinstance(self.bbox, list):
            bbox = self.bbox

        else:
            bbox = self.bbox

        datetime_range: None | str | Unset
        if isinstance(self.datetime_range, Unset):
            datetime_range = UNSET
        else:
            datetime_range = self.datetime_range

        limit = self.limit

        max_cloud_cover: float | None | Unset
        if isinstance(self.max_cloud_cover, Unset):
            max_cloud_cover = UNSET
        else:
            max_cloud_cover = self.max_cloud_cover

        cloud_cover_mode: None | str | Unset
        if isinstance(self.cloud_cover_mode, Unset):
            cloud_cover_mode = UNSET
        elif isinstance(self.cloud_cover_mode, str):
            cloud_cover_mode = self.cloud_cover_mode
        else:
            cloud_cover_mode = self.cloud_cover_mode

        next_page: dict[str, Any] | None | Unset
        if isinstance(self.next_page, Unset):
            next_page = UNSET
        elif isinstance(self.next_page, StacNextPage):
            next_page = self.next_page.to_dict()
        else:
            next_page = self.next_page

        token: None | str | Unset
        if isinstance(self.token, Unset):
            token = UNSET
        else:
            token = self.token

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
            }
        )
        if collections is not UNSET:
            field_dict["collections"] = collections
        if bbox is not UNSET:
            field_dict["bbox"] = bbox
        if datetime_range is not UNSET:
            field_dict["datetime_range"] = datetime_range
        if limit is not UNSET:
            field_dict["limit"] = limit
        if max_cloud_cover is not UNSET:
            field_dict["max_cloud_cover"] = max_cloud_cover
        if cloud_cover_mode is not UNSET:
            field_dict["cloud_cover_mode"] = cloud_cover_mode
        if next_page is not UNSET:
            field_dict["next_page"] = next_page
        if token is not UNSET:
            field_dict["token"] = token
        if auth is not UNSET:
            field_dict["auth"] = auth

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.service_auth_request import ServiceAuthRequest
        from ..models.stac_next_page import StacNextPage

        d = dict(src_dict)
        url = d.pop("url")

        def _parse_collections(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                collections_type_0 = cast(list[str], data)

                return collections_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        collections = _parse_collections(d.pop("collections", UNSET))

        def _parse_bbox(data: object) -> list[float] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                bbox_type_0 = cast(list[float], data)

                return bbox_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[float] | None | Unset, data)

        bbox = _parse_bbox(d.pop("bbox", UNSET))

        def _parse_datetime_range(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        datetime_range = _parse_datetime_range(d.pop("datetime_range", UNSET))

        limit = d.pop("limit", UNSET)

        def _parse_max_cloud_cover(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        max_cloud_cover = _parse_max_cloud_cover(d.pop("max_cloud_cover", UNSET))

        def _parse_cloud_cover_mode(
            data: object,
        ) -> None | StacSearchRequestCloudCoverModeType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                cloud_cover_mode_type_0 = (
                    check_stac_search_request_cloud_cover_mode_type_0(data)
                )

                return cloud_cover_mode_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | StacSearchRequestCloudCoverModeType0 | Unset, data)

        cloud_cover_mode = _parse_cloud_cover_mode(d.pop("cloud_cover_mode", UNSET))

        def _parse_next_page(data: object) -> None | StacNextPage | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                next_page_type_0 = StacNextPage.from_dict(data)

                return next_page_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | StacNextPage | Unset, data)

        next_page = _parse_next_page(d.pop("next_page", UNSET))

        def _parse_token(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        token = _parse_token(d.pop("token", UNSET))

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

        stac_search_request = cls(
            url=url,
            collections=collections,
            bbox=bbox,
            datetime_range=datetime_range,
            limit=limit,
            max_cloud_cover=max_cloud_cover,
            cloud_cover_mode=cloud_cover_mode,
            next_page=next_page,
            token=token,
            auth=auth,
        )

        stac_search_request.additional_properties = d
        return stac_search_request

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
