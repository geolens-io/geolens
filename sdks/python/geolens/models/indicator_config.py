from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

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
    """

    stat: IndicatorConfigStat
    column: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        stat: str = self.stat

        column: None | str | Unset
        if isinstance(self.column, Unset):
            column = UNSET
        else:
            column = self.column

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "stat": stat,
            }
        )
        if column is not UNSET:
            field_dict["column"] = column

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

        indicator_config = cls(
            stat=stat,
            column=column,
        )

        return indicator_config
