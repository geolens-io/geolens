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
        details (list[DbfTruncationDetail]):
        kind (Literal['dbf_truncation_collision']):
    """

    details: list[DbfTruncationDetail]
    kind: Literal["dbf_truncation_collision"]

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
        from ..models.dbf_truncation_detail import DbfTruncationDetail

        d = dict(src_dict)
        details = []
        _details = d.pop("details")
        for details_item_data in _details:
            details_item = DbfTruncationDetail.from_dict(details_item_data)

            details.append(details_item)

        kind = cast(Literal["dbf_truncation_collision"], d.pop("kind"))
        if kind != "dbf_truncation_collision":
            raise ValueError(
                f"kind must match const 'dbf_truncation_collision', got '{kind}'"
            )

        dbf_truncation_collision_warning = cls(
            details=details,
            kind=kind,
        )

        return dbf_truncation_collision_warning
