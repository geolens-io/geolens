from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.stac_import_result import StacImportResult


T = TypeVar("T", bound="StacImportResponse")


@_attrs_define
class StacImportResponse:
    """
    Attributes:
        results (list[StacImportResult]): Per-item import results.
        created (int): Number of datasets created.
        skipped (int): Number of items skipped (duplicates).
        errors (int): Number of items that failed.
    """

    results: list[StacImportResult]
    created: int
    skipped: int
    errors: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        results = []
        for results_item_data in self.results:
            results_item = results_item_data.to_dict()
            results.append(results_item)

        created = self.created

        skipped = self.skipped

        errors = self.errors

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "results": results,
                "created": created,
                "skipped": skipped,
                "errors": errors,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.stac_import_result import StacImportResult

        d = dict(src_dict)
        results = []
        _results = d.pop("results")
        for results_item_data in _results:
            results_item = StacImportResult.from_dict(results_item_data)

            results.append(results_item)

        created = d.pop("created")

        skipped = d.pop("skipped")

        errors = d.pop("errors")

        stac_import_response = cls(
            results=results,
            created=created,
            skipped=skipped,
            errors=errors,
        )

        stac_import_response.additional_properties = d
        return stac_import_response

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
