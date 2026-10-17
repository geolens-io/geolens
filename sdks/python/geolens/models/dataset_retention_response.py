from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from dateutil.parser import isoparse
from typing import cast
import datetime

if TYPE_CHECKING:
    from ..models.dataset_retention import DatasetRetention


T = TypeVar("T", bound="DatasetRetentionResponse")


@_attrs_define
class DatasetRetentionResponse:
    """
    Attributes:
        retention (DatasetRetention | None):
        rows_past_cutoff (int): Rows currently older than the cutoff, which the next retention run deletes. 0 when
            retention is off.
        cutoff (datetime.datetime | None | Unset): Rows older than this are past retention; null when off.
    """

    retention: DatasetRetention | None
    rows_past_cutoff: int
    cutoff: datetime.datetime | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.dataset_retention import DatasetRetention

        retention: dict[str, Any] | None
        if isinstance(self.retention, DatasetRetention):
            retention = self.retention.to_dict()
        else:
            retention = self.retention

        rows_past_cutoff = self.rows_past_cutoff

        cutoff: None | str | Unset
        if isinstance(self.cutoff, Unset):
            cutoff = UNSET
        elif isinstance(self.cutoff, datetime.datetime):
            cutoff = self.cutoff.isoformat()
        else:
            cutoff = self.cutoff

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "retention": retention,
                "rows_past_cutoff": rows_past_cutoff,
            }
        )
        if cutoff is not UNSET:
            field_dict["cutoff"] = cutoff

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.dataset_retention import DatasetRetention

        d = dict(src_dict)

        def _parse_retention(data: object) -> DatasetRetention | None:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                retention_type_0 = DatasetRetention.from_dict(data)

                return retention_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(DatasetRetention | None, data)

        retention = _parse_retention(d.pop("retention"))

        rows_past_cutoff = d.pop("rows_past_cutoff")

        def _parse_cutoff(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                cutoff_type_0 = isoparse(data)

                return cutoff_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        cutoff = _parse_cutoff(d.pop("cutoff", UNSET))

        dataset_retention_response = cls(
            retention=retention,
            rows_past_cutoff=rows_past_cutoff,
            cutoff=cutoff,
        )

        dataset_retention_response.additional_properties = d
        return dataset_retention_response

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
