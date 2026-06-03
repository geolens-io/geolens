from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define


T = TypeVar("T", bound="ReservedRenameDetail")


@_attrs_define
class ReservedRenameDetail:
    """
    Attributes:
        original (str):
        renamed (str):
    """

    original: str
    renamed: str

    def to_dict(self) -> dict[str, Any]:
        original = self.original

        renamed = self.renamed

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "original": original,
                "renamed": renamed,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        original = d.pop("original")

        renamed = d.pop("renamed")

        reserved_rename_detail = cls(
            original=original,
            renamed=renamed,
        )

        return reserved_rename_detail
