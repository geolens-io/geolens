from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define


from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.mercator_clip_detail import MercatorClipDetail


T = TypeVar("T", bound="MercatorClipWarning")


@_attrs_define
class MercatorClipWarning:
    """
    Attributes:
        kind (Literal['mercator_clip']):
        details (MercatorClipDetail): fix(#888): how much geometry the Web Mercator clamp destroyed.

            The clamp is a box, not a latitude cutoff: longitude -180 to 180 and
            latitude -85.06 to 85.06. Either bound can be the one that cost the user
            geometry, so clients must not present this as a latitude-only problem
            (fix(#899 codex r1)).

            ``dropped_features`` lost their geometry entirely (a valid point at lat
            -89.95 becomes ``MULTIPOINT EMPTY``); ``clipped_features`` survived in
            reduced form.
    """

    kind: Literal["mercator_clip"]
    details: MercatorClipDetail

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
        from ..models.mercator_clip_detail import MercatorClipDetail

        d = dict(src_dict)
        kind = cast(Literal["mercator_clip"], d.pop("kind"))
        if kind != "mercator_clip":
            raise ValueError(f"kind must match const 'mercator_clip', got '{kind}'")

        details = MercatorClipDetail.from_dict(d.pop("details"))

        mercator_clip_warning = cls(
            kind=kind,
            details=details,
        )

        return mercator_clip_warning
