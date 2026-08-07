from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define


from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.dbf_truncation_detail import DbfTruncationDetail


T = TypeVar("T", bound="DbfTruncationCollisionWarning")


@_attrs_define
class DbfTruncationCollisionWarning:
    """
    Attributes:
        kind (Literal['dbf_truncation_collision']):
        details (list[DbfTruncationDetail]):
    """

    kind: Literal["dbf_truncation_collision"]
    details: list[DbfTruncationDetail]

    def to_dict(self) -> dict[str, Any]:
        kind = self.kind

        details = []
        for details_item_data in self.details:
            details_item = details_item_data.to_dict()
            details.append(details_item)

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "kind": kind,
                "details": details,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.dbf_truncation_detail import DbfTruncationDetail

        d = dict(src_dict)
        kind = cast(Literal["dbf_truncation_collision"], d.pop("kind"))
        if kind != "dbf_truncation_collision":
            raise ValueError(
                f"kind must match const 'dbf_truncation_collision', got '{kind}'"
            )

        details = []
        _details = d.pop("details")
        for details_item_data in _details:
            details_item = DbfTruncationDetail.from_dict(details_item_data)

            details.append(details_item)

        dbf_truncation_collision_warning = cls(
            kind=kind,
            details=details,
        )

        return dbf_truncation_collision_warning
