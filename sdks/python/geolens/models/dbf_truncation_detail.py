from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define


from typing import cast


T = TypeVar("T", bound="DbfTruncationDetail")


@_attrs_define
class DbfTruncationDetail:
    """
    Attributes:
        truncated (str):
        originals (list[str]):
    """

    truncated: str
    originals: list[str]

    def to_dict(self) -> dict[str, Any]:
        truncated = self.truncated

        originals = self.originals

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "truncated": truncated,
                "originals": originals,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        truncated = d.pop("truncated")

        originals = cast(list[str], d.pop("originals"))

        dbf_truncation_detail = cls(
            truncated=truncated,
            originals=originals,
        )

        return dbf_truncation_detail
