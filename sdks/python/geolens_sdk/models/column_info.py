from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.column_info_stats_type_0 import ColumnInfoStatsType0


T = TypeVar("T", bound="ColumnInfo")


@_attrs_define
class ColumnInfo:
    """Describes a single column in a dataset's attribute table.

    Attributes:
        name (str):
        type_ (str):
        domain_type (None | str | Unset):
        sample_values (list[Any] | None | Unset):
        semantic_role (None | str | Unset):
        stats (ColumnInfoStatsType0 | None | Unset):
    """

    name: str
    type_: str
    domain_type: None | str | Unset = UNSET
    sample_values: list[Any] | None | Unset = UNSET
    semantic_role: None | str | Unset = UNSET
    stats: ColumnInfoStatsType0 | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.column_info_stats_type_0 import ColumnInfoStatsType0

        name = self.name

        type_ = self.type_

        domain_type: None | str | Unset
        if isinstance(self.domain_type, Unset):
            domain_type = UNSET
        else:
            domain_type = self.domain_type

        sample_values: list[Any] | None | Unset
        if isinstance(self.sample_values, Unset):
            sample_values = UNSET
        elif isinstance(self.sample_values, list):
            sample_values = self.sample_values

        else:
            sample_values = self.sample_values

        semantic_role: None | str | Unset
        if isinstance(self.semantic_role, Unset):
            semantic_role = UNSET
        else:
            semantic_role = self.semantic_role

        stats: dict[str, Any] | None | Unset
        if isinstance(self.stats, Unset):
            stats = UNSET
        elif isinstance(self.stats, ColumnInfoStatsType0):
            stats = self.stats.to_dict()
        else:
            stats = self.stats

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "name": name,
                "type": type_,
            }
        )
        if domain_type is not UNSET:
            field_dict["domain_type"] = domain_type
        if sample_values is not UNSET:
            field_dict["sample_values"] = sample_values
        if semantic_role is not UNSET:
            field_dict["semantic_role"] = semantic_role
        if stats is not UNSET:
            field_dict["stats"] = stats

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.column_info_stats_type_0 import ColumnInfoStatsType0

        d = dict(src_dict)
        name = d.pop("name")

        type_ = d.pop("type")

        def _parse_domain_type(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        domain_type = _parse_domain_type(d.pop("domain_type", UNSET))

        def _parse_sample_values(data: object) -> list[Any] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                sample_values_type_0 = cast(list[Any], data)

                return sample_values_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[Any] | None | Unset, data)

        sample_values = _parse_sample_values(d.pop("sample_values", UNSET))

        def _parse_semantic_role(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        semantic_role = _parse_semantic_role(d.pop("semantic_role", UNSET))

        def _parse_stats(data: object) -> ColumnInfoStatsType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                stats_type_0 = ColumnInfoStatsType0.from_dict(data)

                return stats_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ColumnInfoStatsType0 | None | Unset, data)

        stats = _parse_stats(d.pop("stats", UNSET))

        column_info = cls(
            name=name,
            type_=type_,
            domain_type=domain_type,
            sample_values=sample_values,
            semantic_role=semantic_role,
            stats=stats,
        )

        column_info.additional_properties = d
        return column_info

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
