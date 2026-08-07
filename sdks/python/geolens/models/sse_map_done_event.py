from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from typing import cast
from typing import Literal


T = TypeVar("T", bound="SSEMapDoneEvent")


@_attrs_define
class SSEMapDoneEvent:
    """Terminal payload for a successful streaming map-generation request.

    Attributes:
        type_ (Literal['done']):
        map_id (str):
        map_name (str):
        explanation (str):
        datasets_used (list[str]):
    """

    type_: Literal["done"]
    map_id: str
    map_name: str
    explanation: str
    datasets_used: list[str]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        type_ = self.type_

        map_id = self.map_id

        map_name = self.map_name

        explanation = self.explanation

        datasets_used = self.datasets_used

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "type": type_,
                "map_id": map_id,
                "map_name": map_name,
                "explanation": explanation,
                "datasets_used": datasets_used,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        type_ = cast(Literal["done"], d.pop("type"))
        if type_ != "done":
            raise ValueError(f"type must match const 'done', got '{type_}'")

        map_id = d.pop("map_id")

        map_name = d.pop("map_name")

        explanation = d.pop("explanation")

        datasets_used = cast(list[str], d.pop("datasets_used"))

        sse_map_done_event = cls(
            type_=type_,
            map_id=map_id,
            map_name=map_name,
            explanation=explanation,
            datasets_used=datasets_used,
        )

        sse_map_done_event.additional_properties = d
        return sse_map_done_event

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
