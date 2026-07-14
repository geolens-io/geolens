from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.chat_action import ChatAction


T = TypeVar("T", bound="SSEActionsEvent")


@_attrs_define
class SSEActionsEvent:
    """Validated map-edit actions produced by streaming chat.

    Attributes:
        actions (list[ChatAction]):
        type_ (Literal['actions']):
    """

    actions: list[ChatAction]
    type_: Literal["actions"]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        actions = []
        for actions_item_data in self.actions:
            actions_item = actions_item_data.to_dict()
            actions.append(actions_item)

        type_ = self.type_

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "actions": actions,
                "type": type_,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.chat_action import ChatAction

        d = dict(src_dict)
        actions = []
        _actions = d.pop("actions")
        for actions_item_data in _actions:
            actions_item = ChatAction.from_dict(actions_item_data)

            actions.append(actions_item)

        type_ = cast(Literal["actions"], d.pop("type"))
        if type_ != "actions":
            raise ValueError(f"type must match const 'actions', got '{type_}'")

        sse_actions_event = cls(
            actions=actions,
            type_=type_,
        )

        sse_actions_event.additional_properties = d
        return sse_actions_event

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
