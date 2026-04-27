from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define


from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.reserved_rename_detail import ReservedRenameDetail


T = TypeVar("T", bound="ReservedRenameWarning")


@_attrs_define
class ReservedRenameWarning:
    """
    Attributes:
        details (list[ReservedRenameDetail]):
        kind (Literal['reserved_rename']):
    """

    details: list[ReservedRenameDetail]
    kind: Literal["reserved_rename"]

    def to_dict(self) -> dict[str, Any]:
        details = []
        for details_item_data in self.details:
            details_item = details_item_data.to_dict()
            details.append(details_item)

        kind = self.kind

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "details": details,
                "kind": kind,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.reserved_rename_detail import ReservedRenameDetail

        d = dict(src_dict)
        details = []
        _details = d.pop("details")
        for details_item_data in _details:
            details_item = ReservedRenameDetail.from_dict(details_item_data)

            details.append(details_item)

        kind = cast(Literal["reserved_rename"], d.pop("kind"))
        if kind != "reserved_rename":
            raise ValueError(f"kind must match const 'reserved_rename', got '{kind}'")

        reserved_rename_warning = cls(
            details=details,
            kind=kind,
        )

        return reserved_rename_warning
