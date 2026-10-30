from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset


T = TypeVar("T", bound="CategorySelectorConfig")


@_attrs_define
class CategorySelectorConfig:
    """
    Attributes:
        column (str):
        multiple (bool | Unset):  Default: True.
    """

    column: str
    multiple: bool | Unset = True

    def to_dict(self) -> dict[str, Any]:
        column = self.column

        multiple = self.multiple

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "column": column,
            }
        )
        if multiple is not UNSET:
            field_dict["multiple"] = multiple

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        column = d.pop("column")

        multiple = d.pop("multiple", UNSET)

        category_selector_config = cls(
            column=column,
            multiple=multiple,
        )

        return category_selector_config
