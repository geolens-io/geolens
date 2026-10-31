from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset


T = TypeVar("T", bound="ButtonConfig")


@_attrs_define
class ButtonConfig:
    """
    Attributes:
        label (str):
        url (str): An http or https address; any other scheme is refused.
        new_tab (bool | Unset): Open the link in a new tab. Default: False.
    """

    label: str
    url: str
    new_tab: bool | Unset = False

    def to_dict(self) -> dict[str, Any]:
        label = self.label

        url = self.url

        new_tab = self.new_tab

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "label": label,
                "url": url,
            }
        )
        if new_tab is not UNSET:
            field_dict["new_tab"] = new_tab

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        label = d.pop("label")

        url = d.pop("url")

        new_tab = d.pop("new_tab", UNSET)

        button_config = cls(
            label=label,
            url=url,
            new_tab=new_tab,
        )

        return button_config
