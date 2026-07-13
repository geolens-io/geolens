from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="StacItemProperties")


@_attrs_define
class StacItemProperties:
    """Core STAC Item properties plus extension-defined fields.

    Attributes:
        datetime_ (None | str): Item timestamp, or null when a temporal interval is supplied.
        description (None | str | Unset): Human-readable item description.
        end_datetime (None | str | Unset): End of the item's temporal interval.
        start_datetime (None | str | Unset): Start of the item's temporal interval.
        title (None | str | Unset): Human-readable item title.
    """

    datetime_: None | str
    description: None | str | Unset = UNSET
    end_datetime: None | str | Unset = UNSET
    start_datetime: None | str | Unset = UNSET
    title: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        datetime_: None | str
        datetime_ = self.datetime_

        description: None | str | Unset
        if isinstance(self.description, Unset):
            description = UNSET
        else:
            description = self.description

        end_datetime: None | str | Unset
        if isinstance(self.end_datetime, Unset):
            end_datetime = UNSET
        else:
            end_datetime = self.end_datetime

        start_datetime: None | str | Unset
        if isinstance(self.start_datetime, Unset):
            start_datetime = UNSET
        else:
            start_datetime = self.start_datetime

        title: None | str | Unset
        if isinstance(self.title, Unset):
            title = UNSET
        else:
            title = self.title

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "datetime": datetime_,
            }
        )
        if description is not UNSET:
            field_dict["description"] = description
        if end_datetime is not UNSET:
            field_dict["end_datetime"] = end_datetime
        if start_datetime is not UNSET:
            field_dict["start_datetime"] = start_datetime
        if title is not UNSET:
            field_dict["title"] = title

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_datetime_(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        datetime_ = _parse_datetime_(d.pop("datetime"))

        def _parse_description(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        description = _parse_description(d.pop("description", UNSET))

        def _parse_end_datetime(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        end_datetime = _parse_end_datetime(d.pop("end_datetime", UNSET))

        def _parse_start_datetime(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        start_datetime = _parse_start_datetime(d.pop("start_datetime", UNSET))

        def _parse_title(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        title = _parse_title(d.pop("title", UNSET))

        stac_item_properties = cls(
            datetime_=datetime_,
            description=description,
            end_datetime=end_datetime,
            start_datetime=start_datetime,
            title=title,
        )

        stac_item_properties.additional_properties = d
        return stac_item_properties

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
