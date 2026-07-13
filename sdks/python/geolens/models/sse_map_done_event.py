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
        datasets_used (list[str]):
        explanation (str):
        map_id (str):
        map_name (str):
        type_ (Literal['done']):
    """

    datasets_used: list[str]
    explanation: str
    map_id: str
    map_name: str
    type_: Literal["done"]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        datasets_used = self.datasets_used

        explanation = self.explanation

        map_id = self.map_id

        map_name = self.map_name

        type_ = self.type_

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "datasets_used": datasets_used,
                "explanation": explanation,
                "map_id": map_id,
                "map_name": map_name,
                "type": type_,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        datasets_used = cast(list[str], d.pop("datasets_used"))

        explanation = d.pop("explanation")

        map_id = d.pop("map_id")

        map_name = d.pop("map_name")

        type_ = cast(Literal["done"], d.pop("type"))
        if type_ != "done":
            raise ValueError(f"type must match const 'done', got '{type_}'")

        sse_map_done_event = cls(
            datasets_used=datasets_used,
            explanation=explanation,
            map_id=map_id,
            map_name=map_name,
            type_=type_,
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
