from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from ..models.separator_config_style import check_separator_config_style
from ..models.separator_config_style import SeparatorConfigStyle


T = TypeVar("T", bound="SeparatorConfig")


@_attrs_define
class SeparatorConfig:
    """
    Attributes:
        style (SeparatorConfigStyle | Unset): A thin line, or a larger empty gap. Default: 'line'.
    """

    style: SeparatorConfigStyle | Unset = "line"

    def to_dict(self) -> dict[str, Any]:
        style: str | Unset = UNSET
        if not isinstance(self.style, Unset):
            style = self.style

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if style is not UNSET:
            field_dict["style"] = style

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        _style = d.pop("style", UNSET)
        style: SeparatorConfigStyle | Unset
        if isinstance(_style, Unset):
            style = UNSET
        else:
            style = check_separator_config_style(_style)

        separator_config = cls(
            style=style,
        )

        return separator_config
