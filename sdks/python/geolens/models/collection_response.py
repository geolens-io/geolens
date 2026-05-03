from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from dateutil.parser import isoparse
from typing import cast
from uuid import UUID
import datetime


T = TypeVar("T", bound="CollectionResponse")


@_attrs_define
class CollectionResponse:
    """
    Attributes:
        created_at (datetime.datetime):
        created_by (None | UUID):
        dataset_count (int):
        description (None | str):
        id (UUID):
        name (str):
        updated_at (datetime.datetime):
        extent_bbox (list[float] | None | Unset):
        temporal_end (datetime.date | None | Unset):
        temporal_start (datetime.date | None | Unset):
    """

    created_at: datetime.datetime
    created_by: None | UUID
    dataset_count: int
    description: None | str
    id: UUID
    name: str
    updated_at: datetime.datetime
    extent_bbox: list[float] | None | Unset = UNSET
    temporal_end: datetime.date | None | Unset = UNSET
    temporal_start: datetime.date | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        created_at = self.created_at.isoformat()

        created_by: None | str
        if isinstance(self.created_by, UUID):
            created_by = str(self.created_by)
        else:
            created_by = self.created_by

        dataset_count = self.dataset_count

        description: None | str
        description = self.description

        id = str(self.id)

        name = self.name

        updated_at = self.updated_at.isoformat()

        extent_bbox: list[float] | None | Unset
        if isinstance(self.extent_bbox, Unset):
            extent_bbox = UNSET
        elif isinstance(self.extent_bbox, list):
            extent_bbox = self.extent_bbox

        else:
            extent_bbox = self.extent_bbox

        temporal_end: None | str | Unset
        if isinstance(self.temporal_end, Unset):
            temporal_end = UNSET
        elif isinstance(self.temporal_end, datetime.date):
            temporal_end = self.temporal_end.isoformat()
        else:
            temporal_end = self.temporal_end

        temporal_start: None | str | Unset
        if isinstance(self.temporal_start, Unset):
            temporal_start = UNSET
        elif isinstance(self.temporal_start, datetime.date):
            temporal_start = self.temporal_start.isoformat()
        else:
            temporal_start = self.temporal_start

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "created_at": created_at,
                "created_by": created_by,
                "dataset_count": dataset_count,
                "description": description,
                "id": id,
                "name": name,
                "updated_at": updated_at,
            }
        )
        if extent_bbox is not UNSET:
            field_dict["extent_bbox"] = extent_bbox
        if temporal_end is not UNSET:
            field_dict["temporal_end"] = temporal_end
        if temporal_start is not UNSET:
            field_dict["temporal_start"] = temporal_start

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        created_at = isoparse(d.pop("created_at"))

        def _parse_created_by(data: object) -> None | UUID:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                created_by_type_0 = UUID(data)

                return created_by_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | UUID, data)

        created_by = _parse_created_by(d.pop("created_by"))

        dataset_count = d.pop("dataset_count")

        def _parse_description(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        description = _parse_description(d.pop("description"))

        id = UUID(d.pop("id"))

        name = d.pop("name")

        updated_at = isoparse(d.pop("updated_at"))

        def _parse_extent_bbox(data: object) -> list[float] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                extent_bbox_type_0 = cast(list[float], data)

                return extent_bbox_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[float] | None | Unset, data)

        extent_bbox = _parse_extent_bbox(d.pop("extent_bbox", UNSET))

        def _parse_temporal_end(data: object) -> datetime.date | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                temporal_end_type_0 = isoparse(data).date()

                return temporal_end_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.date | None | Unset, data)

        temporal_end = _parse_temporal_end(d.pop("temporal_end", UNSET))

        def _parse_temporal_start(data: object) -> datetime.date | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                temporal_start_type_0 = isoparse(data).date()

                return temporal_start_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.date | None | Unset, data)

        temporal_start = _parse_temporal_start(d.pop("temporal_start", UNSET))

        collection_response = cls(
            created_at=created_at,
            created_by=created_by,
            dataset_count=dataset_count,
            description=description,
            id=id,
            name=name,
            updated_at=updated_at,
            extent_bbox=extent_bbox,
            temporal_end=temporal_end,
            temporal_start=temporal_start,
        )

        collection_response.additional_properties = d
        return collection_response

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
