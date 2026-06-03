from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from typing import cast

if TYPE_CHECKING:
    from ..models.bulk_delete_layers_failure import BulkDeleteLayersFailure


T = TypeVar("T", bound="BulkDeleteLayersResponse")


@_attrs_define
class BulkDeleteLayersResponse:
    """Response body for POST /maps/{map_id}/layers/bulk-delete.

    Attributes:
        deleted (list[str]):
        failed (list[BulkDeleteLayersFailure]):
    """

    deleted: list[str]
    failed: list[BulkDeleteLayersFailure]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        deleted = self.deleted

        failed = []
        for failed_item_data in self.failed:
            failed_item = failed_item_data.to_dict()
            failed.append(failed_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "deleted": deleted,
                "failed": failed,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.bulk_delete_layers_failure import BulkDeleteLayersFailure

        d = dict(src_dict)
        deleted = cast(list[str], d.pop("deleted"))

        failed = []
        _failed = d.pop("failed")
        for failed_item_data in _failed:
            failed_item = BulkDeleteLayersFailure.from_dict(failed_item_data)

            failed.append(failed_item)

        bulk_delete_layers_response = cls(
            deleted=deleted,
            failed=failed,
        )

        bulk_delete_layers_response.additional_properties = d
        return bulk_delete_layers_response

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
