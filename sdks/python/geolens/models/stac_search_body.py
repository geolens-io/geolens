from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.stac_search_body_intersects_type_0 import (
        StacSearchBodyIntersectsType0,
    )


T = TypeVar("T", bound="StacSearchBody")


@_attrs_define
class StacSearchBody:
    """JSON body for POST /search.

    Attributes:
        bbox (list[float] | None | Unset):
        collections (list[str] | None | Unset):
        datetime_ (None | str | Unset):
        ids (list[str] | None | Unset):
        intersects (None | StacSearchBodyIntersectsType0 | Unset):
        limit (int | Unset):  Default: 10.
        offset (int | Unset):  Default: 0.
    """

    bbox: list[float] | None | Unset = UNSET
    collections: list[str] | None | Unset = UNSET
    datetime_: None | str | Unset = UNSET
    ids: list[str] | None | Unset = UNSET
    intersects: None | StacSearchBodyIntersectsType0 | Unset = UNSET
    limit: int | Unset = 10
    offset: int | Unset = 0
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.stac_search_body_intersects_type_0 import (
            StacSearchBodyIntersectsType0,
        )

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

        datetime_: None | str | Unset
        if isinstance(self.datetime_, Unset):
            datetime_ = UNSET
        else:
            datetime_ = self.datetime_

        ids: list[str] | None | Unset
        if isinstance(self.ids, Unset):
            ids = UNSET
        elif isinstance(self.ids, list):
            ids = self.ids

        else:
            ids = self.ids

        intersects: dict[str, Any] | None | Unset
        if isinstance(self.intersects, Unset):
            intersects = UNSET
        elif isinstance(self.intersects, StacSearchBodyIntersectsType0):
            intersects = self.intersects.to_dict()
        else:
            intersects = self.intersects

        limit = self.limit

        offset = self.offset

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if bbox is not UNSET:
            field_dict["bbox"] = bbox
        if collections is not UNSET:
            field_dict["collections"] = collections
        if datetime_ is not UNSET:
            field_dict["datetime"] = datetime_
        if ids is not UNSET:
            field_dict["ids"] = ids
        if intersects is not UNSET:
            field_dict["intersects"] = intersects
        if limit is not UNSET:
            field_dict["limit"] = limit
        if offset is not UNSET:
            field_dict["offset"] = offset

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.stac_search_body_intersects_type_0 import (
            StacSearchBodyIntersectsType0,
        )

        d = dict(src_dict)

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

        def _parse_datetime_(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        datetime_ = _parse_datetime_(d.pop("datetime", UNSET))

        def _parse_ids(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                ids_type_0 = cast(list[str], data)

                return ids_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        ids = _parse_ids(d.pop("ids", UNSET))

        def _parse_intersects(
            data: object,
        ) -> None | StacSearchBodyIntersectsType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                intersects_type_0 = StacSearchBodyIntersectsType0.from_dict(data)

                return intersects_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | StacSearchBodyIntersectsType0 | Unset, data)

        intersects = _parse_intersects(d.pop("intersects", UNSET))

        limit = d.pop("limit", UNSET)

        offset = d.pop("offset", UNSET)

        stac_search_body = cls(
            bbox=bbox,
            collections=collections,
            datetime_=datetime_,
            ids=ids,
            intersects=intersects,
            limit=limit,
            offset=offset,
        )

        stac_search_body.additional_properties = d
        return stac_search_body

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
