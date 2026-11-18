from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define


from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.zm_dropped_detail import ZmDroppedDetail


T = TypeVar("T", bound="ZmDroppedWarning")


@_attrs_define
class ZmDroppedWarning:
    """
    Attributes:
        kind (Literal['zm_dropped']):
        details (ZmDroppedDetail): How many features were stored without the Z or M values they had.

            A source whose geometries mix dimensions is stored in 2D, so the features
            that had Z or M lose those values; X and Y are unchanged.
    """

    kind: Literal["zm_dropped"]
    details: ZmDroppedDetail

    def to_dict(self) -> dict[str, Any]:
        kind = self.kind

        details = self.details.to_dict()

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
        from ..models.zm_dropped_detail import ZmDroppedDetail

        d = dict(src_dict)
        kind = cast(Literal["zm_dropped"], d.pop("kind"))
        if kind != "zm_dropped":
            raise ValueError(f"kind must match const 'zm_dropped', got '{kind}'")

        details = ZmDroppedDetail.from_dict(d.pop("details"))

        zm_dropped_warning = cls(
            kind=kind,
            details=details,
        )

        return zm_dropped_warning
