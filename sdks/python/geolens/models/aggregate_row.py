from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.aggregate_row_values import AggregateRowValues


T = TypeVar("T", bound="AggregateRow")


@_attrs_define
class AggregateRow:
    """
    Attributes:
        gid (int):
        values (AggregateRowValues): By column. The column's value. A number JSON cannot carry exactly, such as an
            integer beyond 2^53 or NaN, comes back as text.
        bbox (list[float] | None | Unset): Present only when the dataset has geometry: the feature's `[west, south,
            east, north]` in WGS 84, or null without a shape.
    """

    gid: int
    values: AggregateRowValues
    bbox: list[float] | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        gid = self.gid

        values = self.values.to_dict()

        bbox: list[float] | None | Unset
        if isinstance(self.bbox, Unset):
            bbox = UNSET
        elif isinstance(self.bbox, list):
            bbox = self.bbox

        else:
            bbox = self.bbox

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "gid": gid,
                "values": values,
            }
        )
        if bbox is not UNSET:
            field_dict["bbox"] = bbox

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.aggregate_row_values import AggregateRowValues

        d = dict(src_dict)
        gid = d.pop("gid")

        values = AggregateRowValues.from_dict(d.pop("values"))

        def _parse_bbox(data: object) -> list[float] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                bbox_type_0 = cast(list[float], data)

                return bbox_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[float] | None | Unset, data)

        bbox = _parse_bbox(d.pop("bbox", UNSET))

        aggregate_row = cls(
            gid=gid,
            values=values,
            bbox=bbox,
        )

        aggregate_row.additional_properties = d
        return aggregate_row

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
