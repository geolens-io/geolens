from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from typing import cast


T = TypeVar("T", bound="GroupValue")


@_attrs_define
class GroupValue:
    """
    Attributes:
        key (bool | float | int | None | str): The column's value. A number JSON cannot carry exactly, such as an
            integer beyond 2^53 or NaN, comes back as text.
        value (float | int | None | str): Exact for count, sum, min and max, as for a key; avg is a float.
    """

    key: bool | float | int | None | str
    value: float | int | None | str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        key: bool | float | int | None | str
        key = self.key

        value: float | int | None | str
        value = self.value

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "key": key,
                "value": value,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_key(data: object) -> bool | float | int | None | str:
            if data is None:
                return data
            return cast(bool | float | int | None | str, data)

        key = _parse_key(d.pop("key"))

        def _parse_value(data: object) -> float | int | None | str:
            if data is None:
                return data
            return cast(float | int | None | str, data)

        value = _parse_value(d.pop("value"))

        group_value = cls(
            key=key,
            value=value,
        )

        group_value.additional_properties = d
        return group_value

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
