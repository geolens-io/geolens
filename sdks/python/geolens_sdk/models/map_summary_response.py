from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.map_visibility import check_map_visibility
from ..models.map_visibility import MapVisibility
from dateutil.parser import isoparse
from typing import cast
from uuid import UUID
import datetime


T = TypeVar("T", bound="MapSummaryResponse")


@_attrs_define
class MapSummaryResponse:
    """
    Attributes:
        created_at (datetime.datetime):
        description (None | str):
        id (UUID):
        layer_count (int):
        name (str):
        updated_at (datetime.datetime):
        visibility (MapVisibility):
        created_by_username (None | str | Unset):
        thumbnail_url (None | str | Unset):
    """

    created_at: datetime.datetime
    description: None | str
    id: UUID
    layer_count: int
    name: str
    updated_at: datetime.datetime
    visibility: MapVisibility
    created_by_username: None | str | Unset = UNSET
    thumbnail_url: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        created_at = self.created_at.isoformat()

        description: None | str
        description = self.description

        id = str(self.id)

        layer_count = self.layer_count

        name = self.name

        updated_at = self.updated_at.isoformat()

        visibility: str = self.visibility

        created_by_username: None | str | Unset
        if isinstance(self.created_by_username, Unset):
            created_by_username = UNSET
        else:
            created_by_username = self.created_by_username

        thumbnail_url: None | str | Unset
        if isinstance(self.thumbnail_url, Unset):
            thumbnail_url = UNSET
        else:
            thumbnail_url = self.thumbnail_url

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "created_at": created_at,
                "description": description,
                "id": id,
                "layer_count": layer_count,
                "name": name,
                "updated_at": updated_at,
                "visibility": visibility,
            }
        )
        if created_by_username is not UNSET:
            field_dict["created_by_username"] = created_by_username
        if thumbnail_url is not UNSET:
            field_dict["thumbnail_url"] = thumbnail_url

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        created_at = isoparse(d.pop("created_at"))

        def _parse_description(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        description = _parse_description(d.pop("description"))

        id = UUID(d.pop("id"))

        layer_count = d.pop("layer_count")

        name = d.pop("name")

        updated_at = isoparse(d.pop("updated_at"))

        visibility = check_map_visibility(d.pop("visibility"))

        def _parse_created_by_username(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        created_by_username = _parse_created_by_username(
            d.pop("created_by_username", UNSET)
        )

        def _parse_thumbnail_url(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        thumbnail_url = _parse_thumbnail_url(d.pop("thumbnail_url", UNSET))

        map_summary_response = cls(
            created_at=created_at,
            description=description,
            id=id,
            layer_count=layer_count,
            name=name,
            updated_at=updated_at,
            visibility=visibility,
            created_by_username=created_by_username,
            thumbnail_url=thumbnail_url,
        )

        map_summary_response.additional_properties = d
        return map_summary_response

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
