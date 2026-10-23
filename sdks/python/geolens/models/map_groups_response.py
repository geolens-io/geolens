from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.map_visibility import check_map_visibility
from ..models.map_visibility import MapVisibility
from uuid import UUID

if TYPE_CHECKING:
    from ..models.group_ref import GroupRef
    from ..models.map_layer_access_gap import MapLayerAccessGap


T = TypeVar("T", bound="MapGroupsResponse")


@_attrs_define
class MapGroupsResponse:
    """
    Attributes:
        visibility (MapVisibility): Who may read a map. A response names `restricted` only to a client
            that sends `X-GeoLens-Map-Visibility: restricted`; any other client
            reads a restricted map as `private`.
        groups (list[GroupRef]): The sharing groups the map is shared with, by name.
        shared_dataset_ids (list[UUID] | Unset): Datasets this request shared with the map's new groups.
        hidden_layers (list[MapLayerAccessGap] | Unset): Layers that some of the map's new groups still can't read; the
            same shape a 409 lists under `detail.layers`.
    """

    visibility: MapVisibility
    groups: list[GroupRef]
    shared_dataset_ids: list[UUID] | Unset = UNSET
    hidden_layers: list[MapLayerAccessGap] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        visibility: str = self.visibility

        groups = []
        for groups_item_data in self.groups:
            groups_item = groups_item_data.to_dict()
            groups.append(groups_item)

        shared_dataset_ids: list[str] | Unset = UNSET
        if not isinstance(self.shared_dataset_ids, Unset):
            shared_dataset_ids = []
            for shared_dataset_ids_item_data in self.shared_dataset_ids:
                shared_dataset_ids_item = str(shared_dataset_ids_item_data)
                shared_dataset_ids.append(shared_dataset_ids_item)

        hidden_layers: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.hidden_layers, Unset):
            hidden_layers = []
            for hidden_layers_item_data in self.hidden_layers:
                hidden_layers_item = hidden_layers_item_data.to_dict()
                hidden_layers.append(hidden_layers_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "visibility": visibility,
                "groups": groups,
            }
        )
        if shared_dataset_ids is not UNSET:
            field_dict["shared_dataset_ids"] = shared_dataset_ids
        if hidden_layers is not UNSET:
            field_dict["hidden_layers"] = hidden_layers

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.group_ref import GroupRef
        from ..models.map_layer_access_gap import MapLayerAccessGap

        d = dict(src_dict)
        visibility = check_map_visibility(d.pop("visibility"))

        groups = []
        _groups = d.pop("groups")
        for groups_item_data in _groups:
            groups_item = GroupRef.from_dict(groups_item_data)

            groups.append(groups_item)

        _shared_dataset_ids = d.pop("shared_dataset_ids", UNSET)
        shared_dataset_ids: list[UUID] | Unset = UNSET
        if _shared_dataset_ids is not UNSET:
            shared_dataset_ids = []
            for shared_dataset_ids_item_data in _shared_dataset_ids:
                shared_dataset_ids_item = UUID(shared_dataset_ids_item_data)

                shared_dataset_ids.append(shared_dataset_ids_item)

        _hidden_layers = d.pop("hidden_layers", UNSET)
        hidden_layers: list[MapLayerAccessGap] | Unset = UNSET
        if _hidden_layers is not UNSET:
            hidden_layers = []
            for hidden_layers_item_data in _hidden_layers:
                hidden_layers_item = MapLayerAccessGap.from_dict(
                    hidden_layers_item_data
                )

                hidden_layers.append(hidden_layers_item)

        map_groups_response = cls(
            visibility=visibility,
            groups=groups,
            shared_dataset_ids=shared_dataset_ids,
            hidden_layers=hidden_layers,
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
