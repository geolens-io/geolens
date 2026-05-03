from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="StacSearchRequest")


@_attrs_define
class StacSearchRequest:
    """
    Attributes:
        url (str): STAC API root URL.
        bbox (list[float] | None | Unset): Bounding box filter as [west, south, east, north].
        collections (list[str] | None | Unset): Filter by collection IDs.
        datetime_range (None | str | Unset): Temporal filter in STAC datetime format (e.g. '2023-01-01/2023-12-31').
        limit (int | Unset): Maximum items to return. Default: 20.
    """

    url: str
    bbox: list[float] | None | Unset = UNSET
    collections: list[str] | None | Unset = UNSET
    datetime_range: None | str | Unset = UNSET
    limit: int | Unset = 20
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        url = self.url

        bbox: list[float] | None | Unset
        if isinstance(self.bbox, Unset):
            bbox = UNSET
        elif isinstance(self.bbox, list):
            bbox = self.bbox

        else:
            bbox = self.bbox

        collections: list[str] | None | Unset
        if isinstance(self.collections, Unset):
            collections = UNSET
        elif isinstance(self.collections, list):
            collections = self.collections

        else:
            collections = self.collections

        datetime_range: None | str | Unset
        if isinstance(self.datetime_range, Unset):
            datetime_range = UNSET
        else:
            datetime_range = self.datetime_range

        limit = self.limit

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "url": url,
            }
        )
        if bbox is not UNSET:
            field_dict["bbox"] = bbox
        if collections is not UNSET:
            field_dict["collections"] = collections
        if datetime_range is not UNSET:
            field_dict["datetime_range"] = datetime_range
        if limit is not UNSET:
            field_dict["limit"] = limit

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        url = d.pop("url")

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

        def _parse_datetime_range(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        datetime_range = _parse_datetime_range(d.pop("datetime_range", UNSET))

        limit = d.pop("limit", UNSET)

        stac_search_request = cls(
            url=url,
            bbox=bbox,
            collections=collections,
            datetime_range=datetime_range,
            limit=limit,
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
