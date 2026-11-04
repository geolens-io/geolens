from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from ..models.indicator_config_comparison_type_0 import (
    check_indicator_config_comparison_type_0,
)
from ..models.indicator_config_comparison_type_0 import IndicatorConfigComparisonType0
from ..models.indicator_config_stat import check_indicator_config_stat
from ..models.indicator_config_stat import IndicatorConfigStat
from typing import cast


T = TypeVar("T", bound="IndicatorConfig")


@_attrs_define
class IndicatorConfig:
    """
    Attributes:
        stat (IndicatorConfigStat):
        column (None | str | Unset):
        reference (float | None | Unset): A fixed number to compare the value with. The indicator shows the difference
            from it.
        reference_label (None | str | Unset): A short name for the reference, such as `Target`. Needs `reference`.
        higher_is_better (bool | None | Unset): Whether a value above the reference is the good outcome. Absent means
            true.
        comparison (IndicatorConfigComparisonType0 | None | Unset): Show the difference as a `value`, a `percent`
            change, or `both`. Absent means `both`.
    """

    stat: IndicatorConfigStat
    column: None | str | Unset = UNSET
    reference: float | None | Unset = UNSET
    reference_label: None | str | Unset = UNSET
    higher_is_better: bool | None | Unset = UNSET
    comparison: IndicatorConfigComparisonType0 | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        stat: str = self.stat

        column: None | str | Unset
        if isinstance(self.column, Unset):
            column = UNSET
        else:
            column = self.column

        reference: float | None | Unset
        if isinstance(self.reference, Unset):
            reference = UNSET
        else:
            reference = self.reference

        reference_label: None | str | Unset
        if isinstance(self.reference_label, Unset):
            reference_label = UNSET
        else:
            reference_label = self.reference_label

        higher_is_better: bool | None | Unset
        if isinstance(self.higher_is_better, Unset):
            higher_is_better = UNSET
        else:
            higher_is_better = self.higher_is_better

        comparison: None | str | Unset
        if isinstance(self.comparison, Unset):
            comparison = UNSET
        elif isinstance(self.comparison, str):
            comparison = self.comparison
        else:
            comparison = self.comparison

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "stat": stat,
            }
        )
        if column is not UNSET:
            field_dict["column"] = column
        if reference is not UNSET:
            field_dict["reference"] = reference
        if reference_label is not UNSET:
            field_dict["reference_label"] = reference_label
        if higher_is_better is not UNSET:
            field_dict["higher_is_better"] = higher_is_better
        if comparison is not UNSET:
            field_dict["comparison"] = comparison

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        stat = check_indicator_config_stat(d.pop("stat"))

        def _parse_column(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        column = _parse_column(d.pop("column", UNSET))

        def _parse_reference(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        reference = _parse_reference(d.pop("reference", UNSET))

        def _parse_reference_label(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        reference_label = _parse_reference_label(d.pop("reference_label", UNSET))

        def _parse_higher_is_better(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        higher_is_better = _parse_higher_is_better(d.pop("higher_is_better", UNSET))

        def _parse_comparison(
            data: object,
        ) -> IndicatorConfigComparisonType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                comparison_type_0 = check_indicator_config_comparison_type_0(data)

                return comparison_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(IndicatorConfigComparisonType0 | None | Unset, data)

        comparison = _parse_comparison(d.pop("comparison", UNSET))

        indicator_config = cls(
            stat=stat,
            column=column,
            reference=reference,
            reference_label=reference_label,
            higher_is_better=higher_is_better,
            comparison=comparison,
        )

        return indicator_config
