from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.map_groups_update_confirm_type_0 import (
    check_map_groups_update_confirm_type_0,
)
from ..models.map_groups_update_confirm_type_0 import MapGroupsUpdateConfirmType0
from typing import cast
from uuid import UUID


T = TypeVar("T", bound="MapGroupsUpdate")


@_attrs_define
class MapGroupsUpdate:
    """
    Attributes:
        group_ids (list[UUID]): Every group the map is shared with afterwards; an empty list unshares it. An owner may
            add only groups they belong to, and an admin any group.
        confirm (MapGroupsUpdateConfirmType0 | None | Unset): Required when the map would become restricted with layers
            some of its new groups can't read; without it the request answers 409 and lists them. `share_datasets` also
            shares each such dataset the caller may share with the groups that lack it; `map_only` leaves those layers
            hidden from them.
    """

    group_ids: list[UUID]
    confirm: MapGroupsUpdateConfirmType0 | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        group_ids = []
        for group_ids_item_data in self.group_ids:
            group_ids_item = str(group_ids_item_data)
            group_ids.append(group_ids_item)

        confirm: None | str | Unset
        if isinstance(self.confirm, Unset):
            confirm = UNSET
        elif isinstance(self.confirm, str):
            confirm = self.confirm
        else:
            confirm = self.confirm

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "group_ids": group_ids,
            }
        )
        if confirm is not UNSET:
            field_dict["confirm"] = confirm

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        group_ids = []
        _group_ids = d.pop("group_ids")
        for group_ids_item_data in _group_ids:
            group_ids_item = UUID(group_ids_item_data)

            group_ids.append(group_ids_item)

        def _parse_confirm(data: object) -> MapGroupsUpdateConfirmType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                confirm_type_0 = check_map_groups_update_confirm_type_0(data)

                return confirm_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(MapGroupsUpdateConfirmType0 | None | Unset, data)

        confirm = _parse_confirm(d.pop("confirm", UNSET))

        map_groups_update = cls(
            group_ids=group_ids,
            confirm=confirm,
        )

        map_groups_update.additional_properties = d
        return map_groups_update

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
