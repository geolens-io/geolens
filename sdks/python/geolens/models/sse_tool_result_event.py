from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from typing import Literal, cast


T = TypeVar("T", bound="SSEToolResultEvent")


@_attrs_define
class SSEToolResultEvent:
    """Progress payload emitted when an AI tool finishes.

    Attributes:
        type_ (Literal['tool_result']):
        tool (str):
        success (bool):
    """

    type_: Literal["tool_result"]
    tool: str
    success: bool
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        type_ = self.type_

        tool = self.tool

        success = self.success

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "type": type_,
                "tool": tool,
                "success": success,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        type_ = cast(Literal["tool_result"], d.pop("type"))
        if type_ != "tool_result":
            raise ValueError(f"type must match const 'tool_result', got '{type_}'")

        tool = d.pop("tool")

        success = d.pop("success")

        sse_tool_result_event = cls(
            type_=type_,
            tool=tool,
            success=success,
        )

        sse_tool_result_event.additional_properties = d
        return sse_tool_result_event

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
