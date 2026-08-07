from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from typing import Literal, cast


T = TypeVar("T", bound="SSETokenEvent")


@_attrs_define
class SSETokenEvent:
    """Token payload carried by a ``token`` server-sent event.

    Attributes:
        type_ (Literal['token']):
        text (str):
    """

    type_: Literal["token"]
    text: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        type_ = self.type_

        text = self.text

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "type": type_,
                "text": text,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        type_ = cast(Literal["token"], d.pop("type"))
        if type_ != "token":
            raise ValueError(f"type must match const 'token', got '{type_}'")

        text = d.pop("text")

        sse_token_event = cls(
            type_=type_,
            text=text,
        )

        sse_token_event.additional_properties = d
        return sse_token_event

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
