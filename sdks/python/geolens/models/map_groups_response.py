from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from ..models.map_visibility import check_map_visibility
from ..models.map_visibility import MapVisibility

if TYPE_CHECKING:
    from ..models.group_ref import GroupRef


T = TypeVar("T", bound="MapGroupsResponse")


@_attrs_define
class MapGroupsResponse:
    """
    Attributes:
        visibility (MapVisibility): Who may read a map. A response names `restricted` only to a client
            that sends `X-GeoLens-Map-Visibility: restricted`; any other client
            reads a restricted map as `private`.
        groups (list[GroupRef]): The sharing groups the map is shared with, by name.
    """

    visibility: MapVisibility
    groups: list[GroupRef]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        visibility: str = self.visibility

        groups = []
        for groups_item_data in self.groups:
            groups_item = groups_item_data.to_dict()
            groups.append(groups_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "visibility": visibility,
                "groups": groups,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.group_ref import GroupRef

        d = dict(src_dict)
        visibility = check_map_visibility(d.pop("visibility"))

        groups = []
        _groups = d.pop("groups")
        for groups_item_data in _groups:
            groups_item = GroupRef.from_dict(groups_item_data)

            groups.append(groups_item)

        map_groups_response = cls(
            visibility=visibility,
            groups=groups,
        )

        map_groups_response.additional_properties = d
        return map_groups_response

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
