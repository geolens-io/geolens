from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset


if TYPE_CHECKING:
    from ..models.map_style_import_warning import MapStyleImportWarning


T = TypeVar("T", bound="MapStyleImportSummary")


@_attrs_define
class MapStyleImportSummary:
    """
    Attributes:
        sources_matched (int | Unset):  Default: 0.
        sources_unsupported (int | Unset):  Default: 0.
        layers_imported (int | Unset):  Default: 0.
        layers_skipped (int | Unset):  Default: 0.
        warnings (list[MapStyleImportWarning] | Unset):
        warnings_truncated (int | Unset): Warnings produced beyond the reported list Default: 0.
    """

    sources_matched: int | Unset = 0
    sources_unsupported: int | Unset = 0
    layers_imported: int | Unset = 0
    layers_skipped: int | Unset = 0
    warnings: list[MapStyleImportWarning] | Unset = UNSET
    warnings_truncated: int | Unset = 0
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        sources_matched = self.sources_matched

        sources_unsupported = self.sources_unsupported

        layers_imported = self.layers_imported

        layers_skipped = self.layers_skipped

        warnings: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.warnings, Unset):
            warnings = []
            for warnings_item_data in self.warnings:
                warnings_item = warnings_item_data.to_dict()
                warnings.append(warnings_item)

        warnings_truncated = self.warnings_truncated

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if sources_matched is not UNSET:
            field_dict["sources_matched"] = sources_matched
        if sources_unsupported is not UNSET:
            field_dict["sources_unsupported"] = sources_unsupported
        if layers_imported is not UNSET:
            field_dict["layers_imported"] = layers_imported
        if layers_skipped is not UNSET:
            field_dict["layers_skipped"] = layers_skipped
        if warnings is not UNSET:
            field_dict["warnings"] = warnings
        if warnings_truncated is not UNSET:
            field_dict["warnings_truncated"] = warnings_truncated

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.map_style_import_warning import MapStyleImportWarning

        d = dict(src_dict)
        sources_matched = d.pop("sources_matched", UNSET)

        sources_unsupported = d.pop("sources_unsupported", UNSET)

        layers_imported = d.pop("layers_imported", UNSET)

        layers_skipped = d.pop("layers_skipped", UNSET)

        _warnings = d.pop("warnings", UNSET)
        warnings: list[MapStyleImportWarning] | Unset = UNSET
        if _warnings is not UNSET:
            warnings = []
            for warnings_item_data in _warnings:
                warnings_item = MapStyleImportWarning.from_dict(warnings_item_data)

                warnings.append(warnings_item)

        warnings_truncated = d.pop("warnings_truncated", UNSET)

        map_style_import_summary = cls(
            sources_matched=sources_matched,
            sources_unsupported=sources_unsupported,
            layers_imported=layers_imported,
            layers_skipped=layers_skipped,
            warnings=warnings,
            warnings_truncated=warnings_truncated,
        )

        map_style_import_summary.additional_properties = d
        return map_style_import_summary

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
