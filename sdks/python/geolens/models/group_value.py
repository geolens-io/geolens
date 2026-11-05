from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="GroupValue")


@_attrs_define
class GroupValue:
    """
    Attributes:
        key (bool | float | int | None | str): The column's value. A number JSON cannot carry exactly, such as an
            integer beyond 2^53 or NaN, comes back as text.
        value (float | int | None | str): Exact for count, sum, min and max, as for a key; avg is a float. With `stats`,
            the first statistic's value.
        values (list[float | int | None | str] | None | Unset): Present with `stats`: each one's value in order. Exact
            for count, sum, min and max, as for a key; avg is a float.
    """

    key: bool | float | int | None | str
    value: float | int | None | str
    values: list[float | int | None | str] | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        key: bool | float | int | None | str
        key = self.key

        value: float | int | None | str
        value = self.value

        values: list[float | int | None | str] | None | Unset
        if isinstance(self.values, Unset):
            values = UNSET
        elif isinstance(self.values, list):
            values = []
            for values_type_0_item_data in self.values:
                values_type_0_item: float | int | None | str
                values_type_0_item = values_type_0_item_data
                values.append(values_type_0_item)

        else:
            values = self.values

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "key": key,
                "value": value,
            }
        )
        if values is not UNSET:
            field_dict["values"] = values

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

        def _parse_values(
            data: object,
        ) -> list[float | int | None | str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                values_type_0 = []
                _values_type_0 = data
                for values_type_0_item_data in _values_type_0:

                    def _parse_values_type_0_item(
                        data: object,
                    ) -> float | int | None | str:
                        if data is None:
                            return data
                        return cast(float | int | None | str, data)

                    values_type_0_item = _parse_values_type_0_item(
                        values_type_0_item_data
                    )

                    values_type_0.append(values_type_0_item)

                return values_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[float | int | None | str] | None | Unset, data)

        values = _parse_values(d.pop("values", UNSET))

        group_value = cls(
            key=key,
            value=value,
            values=values,
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
