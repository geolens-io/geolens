from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from typing import cast

if TYPE_CHECKING:
    from ..models.dataset_retention import DatasetRetention


T = TypeVar("T", bound="DatasetRetentionUpdate")


@_attrs_define
class DatasetRetentionUpdate:
    """The retention setting to store; null turns retention off.

    Attributes:
        retention (DatasetRetention | None):
    """

    retention: DatasetRetention | None
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.dataset_retention import DatasetRetention

        retention: dict[str, Any] | None
        if isinstance(self.retention, DatasetRetention):
            retention = self.retention.to_dict()
        else:
            retention = self.retention

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "retention": retention,
            }
        )

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

        dataset_retention_update = cls(
            retention=retention,
        )

        dataset_retention_update.additional_properties = d
        return dataset_retention_update

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
