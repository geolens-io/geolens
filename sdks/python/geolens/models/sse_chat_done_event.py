from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from typing import Literal, cast


T = TypeVar("T", bound="SSEChatDoneEvent")


@_attrs_define
class SSEChatDoneEvent:
    """Terminal payload for a successful streaming chat request.

    Attributes:
        explanation (str):
        type_ (Literal['done']):
    """

    explanation: str
    type_: Literal["done"]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        explanation = self.explanation

        type_ = self.type_

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "explanation": explanation,
                "type": type_,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        explanation = d.pop("explanation")

        type_ = cast(Literal["done"], d.pop("type"))
        if type_ != "done":
            raise ValueError(f"type must match const 'done', got '{type_}'")

        sse_chat_done_event = cls(
            explanation=explanation,
            type_=type_,
        )

        sse_chat_done_event.additional_properties = d
        return sse_chat_done_event

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
