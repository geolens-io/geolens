from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.bulk_delete_result_item import BulkDeleteResultItem


T = TypeVar("T", bound="BulkDeleteResponse")


@_attrs_define
class BulkDeleteResponse:
    """
    Attributes:
        deleted (int):
        errors (int):
        results (list[BulkDeleteResultItem]):
    """

    deleted: int
    errors: int
    results: list[BulkDeleteResultItem]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        deleted = self.deleted

        errors = self.errors

        results = []
        for results_item_data in self.results:
            results_item = results_item_data.to_dict()
            results.append(results_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "deleted": deleted,
                "errors": errors,
                "results": results,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.bulk_delete_result_item import BulkDeleteResultItem

        d = dict(src_dict)
        deleted = d.pop("deleted")

        errors = d.pop("errors")

        results = []
        _results = d.pop("results")
        for results_item_data in _results:
            results_item = BulkDeleteResultItem.from_dict(results_item_data)

            results.append(results_item)

        bulk_delete_response = cls(
            deleted=deleted,
            errors=errors,
            results=results,
        )

        bulk_delete_response.additional_properties = d
        return bulk_delete_response

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
