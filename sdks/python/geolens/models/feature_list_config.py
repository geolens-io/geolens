from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from ..models.feature_list_config_sort import check_feature_list_config_sort
from ..models.feature_list_config_sort import FeatureListConfigSort
from typing import cast


T = TypeVar("T", bound="FeatureListConfig")


@_attrs_define
class FeatureListConfig:
    """
    Attributes:
        title_column (str):
        subtitle_column (None | str | Unset):
        sort_column (None | str | Unset):
        sort (FeatureListConfigSort | Unset):  Default: 'asc'.
        page_size (int | Unset):  Default: 25.
    """

    title_column: str
    subtitle_column: None | str | Unset = UNSET
    sort_column: None | str | Unset = UNSET
    sort: FeatureListConfigSort | Unset = "asc"
    page_size: int | Unset = 25

    def to_dict(self) -> dict[str, Any]:
        title_column = self.title_column

        subtitle_column: None | str | Unset
        if isinstance(self.subtitle_column, Unset):
            subtitle_column = UNSET
        else:
            subtitle_column = self.subtitle_column

        sort_column: None | str | Unset
        if isinstance(self.sort_column, Unset):
            sort_column = UNSET
        else:
            sort_column = self.sort_column

        sort: str | Unset = UNSET
        if not isinstance(self.sort, Unset):
            sort = self.sort

        page_size = self.page_size

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "title_column": title_column,
            }
        )
        if subtitle_column is not UNSET:
            field_dict["subtitle_column"] = subtitle_column
        if sort_column is not UNSET:
            field_dict["sort_column"] = sort_column
        if sort is not UNSET:
            field_dict["sort"] = sort
        if page_size is not UNSET:
            field_dict["page_size"] = page_size

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        title_column = d.pop("title_column")

        def _parse_subtitle_column(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        subtitle_column = _parse_subtitle_column(d.pop("subtitle_column", UNSET))

        def _parse_sort_column(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        sort_column = _parse_sort_column(d.pop("sort_column", UNSET))

        _sort = d.pop("sort", UNSET)
        sort: FeatureListConfigSort | Unset
        if isinstance(_sort, Unset):
            sort = UNSET
        else:
            sort = check_feature_list_config_sort(_sort)

        page_size = d.pop("page_size", UNSET)

        feature_list_config = cls(
            title_column=title_column,
            subtitle_column=subtitle_column,
            sort_column=sort_column,
            sort=sort,
            page_size=page_size,
        )

        return feature_list_config
