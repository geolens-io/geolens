from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from typing import Literal, cast


T = TypeVar("T", bound="SSEToolStartEvent")


@_attrs_define
class SSEToolStartEvent:
    """Progress payload emitted when an AI tool starts.

    Attributes:
        type_ (Literal['tool_start']):
        tool (str):
        label (str):
    """

    type_: Literal["tool_start"]
    tool: str
    label: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        type_ = self.type_

        tool = self.tool

        label = self.label

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "type": type_,
                "tool": tool,
                "label": label,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        type_ = cast(Literal["tool_start"], d.pop("type"))
        if type_ != "tool_start":
            raise ValueError(f"type must match const 'tool_start', got '{type_}'")

        tool = d.pop("tool")

        label = d.pop("label")

        sse_tool_start_event = cls(
            type_=type_,
            tool=tool,
            label=label,
        )

        sse_tool_start_event.additional_properties = d
        return sse_tool_start_event

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
