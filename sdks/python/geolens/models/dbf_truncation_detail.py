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
        originals (list[str]):
        truncated (str):
    """

    originals: list[str]
    truncated: str

    def to_dict(self) -> dict[str, Any]:
        originals = self.originals

        truncated = self.truncated

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "originals": originals,
                "truncated": truncated,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        originals = cast(list[str], d.pop("originals"))

        truncated = d.pop("truncated")

        dbf_truncation_detail = cls(
            originals=originals,
            truncated=truncated,
        )

        return dbf_truncation_detail
