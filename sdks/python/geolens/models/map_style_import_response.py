from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.map_response import MapResponse
    from ..models.map_style_import_summary import MapStyleImportSummary


T = TypeVar("T", bound="MapStyleImportResponse")


@_attrs_define
class MapStyleImportResponse:
    """
    Attributes:
        map_ (MapResponse):
        summary (MapStyleImportSummary):
    """

    map_: MapResponse
    summary: MapStyleImportSummary
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        map_ = self.map_.to_dict()

        summary = self.summary.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "map": map_,
                "summary": summary,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.map_response import MapResponse
        from ..models.map_style_import_summary import MapStyleImportSummary

        d = dict(src_dict)
        map_ = MapResponse.from_dict(d.pop("map"))

        summary = MapStyleImportSummary.from_dict(d.pop("summary"))

        map_style_import_response = cls(
            map_=map_,
            summary=summary,
        )

        map_style_import_response.additional_properties = d
        return map_style_import_response

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
