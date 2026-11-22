from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.manifest_map_result_action import check_manifest_map_result_action
from ..models.manifest_map_result_action import ManifestMapResultAction
from ..models.manifest_map_result_styling_type_0 import (
    check_manifest_map_result_styling_type_0,
)
from ..models.manifest_map_result_styling_type_0 import ManifestMapResultStylingType0
from typing import cast
from uuid import UUID

if TYPE_CHECKING:
    from ..models.manifest_message import ManifestMessage
    from ..models.manifest_removed_layer import ManifestRemovedLayer


T = TypeVar("T", bound="ManifestMapResult")


@_attrs_define
class ManifestMapResult:
    """
    Attributes:
        map_key (str):
        action (ManifestMapResultAction): What apply did, or in a dry run would do, with the map. A map with an error
            message is `error`, and nothing was written for it.
        map_id (None | Unset | UUID): The map the key names, when the caller may edit it, or the map an apply created.
        messages (list[ManifestMessage] | Unset):
        visibility (None | str | Unset): Who can see the map after the apply, or in a dry run would. Null for a map in
            error.
        styling (ManifestMapResultStylingType0 | None | Unset): `applied` when the manifest's styling replaced the
            map's, `kept` when the map kept its own. Null for a map in error.
        removed_layers (list[ManifestRemovedLayer] | Unset): Keyed layers the manifest no longer lists and the caller
            can read, removed from the map (info A059). Their datasets stay. One on a dataset the caller can't read stays on
            the map.
    """

    map_key: str
    action: ManifestMapResultAction
    map_id: None | Unset | UUID = UNSET
    messages: list[ManifestMessage] | Unset = UNSET
    visibility: None | str | Unset = UNSET
    styling: ManifestMapResultStylingType0 | None | Unset = UNSET
    removed_layers: list[ManifestRemovedLayer] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        map_key = self.map_key

        action: str = self.action

        map_id: None | str | Unset
        if isinstance(self.map_id, Unset):
            map_id = UNSET
        elif isinstance(self.map_id, UUID):
            map_id = str(self.map_id)
        else:
            map_id = self.map_id

        messages: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.messages, Unset):
            messages = []
            for messages_item_data in self.messages:
                messages_item = messages_item_data.to_dict()
                messages.append(messages_item)

        visibility: None | str | Unset
        if isinstance(self.visibility, Unset):
            visibility = UNSET
        else:
            visibility = self.visibility

        styling: None | str | Unset
        if isinstance(self.styling, Unset):
            styling = UNSET
        elif isinstance(self.styling, str):
            styling = self.styling
        else:
            styling = self.styling

        removed_layers: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.removed_layers, Unset):
            removed_layers = []
            for removed_layers_item_data in self.removed_layers:
                removed_layers_item = removed_layers_item_data.to_dict()
                removed_layers.append(removed_layers_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "map_key": map_key,
                "action": action,
            }
        )
        if map_id is not UNSET:
            field_dict["map_id"] = map_id
        if messages is not UNSET:
            field_dict["messages"] = messages
        if visibility is not UNSET:
            field_dict["visibility"] = visibility
        if styling is not UNSET:
            field_dict["styling"] = styling
        if removed_layers is not UNSET:
            field_dict["removed_layers"] = removed_layers

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.manifest_message import ManifestMessage
        from ..models.manifest_removed_layer import ManifestRemovedLayer

        d = dict(src_dict)
        map_key = d.pop("map_key")

        action = check_manifest_map_result_action(d.pop("action"))

        def _parse_map_id(data: object) -> None | Unset | UUID:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                map_id_type_0 = UUID(data)

                return map_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UUID, data)

        map_id = _parse_map_id(d.pop("map_id", UNSET))

        _messages = d.pop("messages", UNSET)
        messages: list[ManifestMessage] | Unset = UNSET
        if _messages is not UNSET:
            messages = []
            for messages_item_data in _messages:
                messages_item = ManifestMessage.from_dict(messages_item_data)

                messages.append(messages_item)

        def _parse_visibility(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        visibility = _parse_visibility(d.pop("visibility", UNSET))

        def _parse_styling(
            data: object,
        ) -> ManifestMapResultStylingType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                styling_type_0 = check_manifest_map_result_styling_type_0(data)

                return styling_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ManifestMapResultStylingType0 | None | Unset, data)

        styling = _parse_styling(d.pop("styling", UNSET))

        _removed_layers = d.pop("removed_layers", UNSET)
        removed_layers: list[ManifestRemovedLayer] | Unset = UNSET
        if _removed_layers is not UNSET:
            removed_layers = []
            for removed_layers_item_data in _removed_layers:
                removed_layers_item = ManifestRemovedLayer.from_dict(
                    removed_layers_item_data
                )

                removed_layers.append(removed_layers_item)

        manifest_map_result = cls(
            map_key=map_key,
            action=action,
            map_id=map_id,
            messages=messages,
            visibility=visibility,
            styling=styling,
            removed_layers=removed_layers,
        )

        manifest_map_result.additional_properties = d
        return manifest_map_result

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
