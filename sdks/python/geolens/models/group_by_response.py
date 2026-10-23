from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.group_by_result import GroupByResult


T = TypeVar("T", bound="GroupByResponse")


@_attrs_define
class GroupByResponse:
    """
    Attributes:
        cached (bool):
        op (Literal['group_by']):
        result (GroupByResult):
        approximate (bool | Unset): Always false: a view too wide to count exactly is refused. Default: False.
    """

    cached: bool
    op: Literal["group_by"]
    result: GroupByResult
    approximate: bool | Unset = False
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        cached = self.cached

        op = self.op

        result = self.result.to_dict()

        approximate = self.approximate

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "cached": cached,
                "op": op,
                "result": result,
            }
        )
        if approximate is not UNSET:
            field_dict["approximate"] = approximate

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.group_by_result import GroupByResult

        d = dict(src_dict)
        cached = d.pop("cached")

        op = cast(Literal["group_by"], d.pop("op"))
        if op != "group_by":
            raise ValueError(f"op must match const 'group_by', got '{op}'")

        result = GroupByResult.from_dict(d.pop("result"))

        approximate = d.pop("approximate", UNSET)

        group_by_response = cls(
            cached=cached,
            op=op,
            result=result,
            approximate=approximate,
        )

        group_by_response.additional_properties = d
        return group_by_response

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
