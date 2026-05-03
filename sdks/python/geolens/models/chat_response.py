from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.chat_action import ChatAction


T = TypeVar("T", bound="ChatResponse")


@_attrs_define
class ChatResponse:
    """
    Attributes:
        actions (list[ChatAction]):
        explanation (str):
    """

    actions: list[ChatAction]
    explanation: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        actions = []
        for actions_item_data in self.actions:
            actions_item = actions_item_data.to_dict()
            actions.append(actions_item)

        explanation = self.explanation

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "actions": actions,
                "explanation": explanation,
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

        explanation = d.pop("explanation")

        chat_response = cls(
            actions=actions,
            explanation=explanation,
        )

        chat_response.additional_properties = d
        return chat_response

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
