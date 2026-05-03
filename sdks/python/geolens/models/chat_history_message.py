from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from ..models.chat_history_message_role import ChatHistoryMessageRole
from ..models.chat_history_message_role import check_chat_history_message_role


T = TypeVar("T", bound="ChatHistoryMessage")


@_attrs_define
class ChatHistoryMessage:
    """A single message in the conversation history.

    Attributes:
        content (str):
        role (ChatHistoryMessageRole):
    """

    content: str
    role: ChatHistoryMessageRole
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        content = self.content

        role: str = self.role

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "content": content,
                "role": role,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        content = d.pop("content")

        role = check_chat_history_message_role(d.pop("role"))

        chat_history_message = cls(
            content=content,
            role=role,
        )

        chat_history_message.additional_properties = d
        return chat_history_message

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
