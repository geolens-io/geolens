from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from uuid import UUID

if TYPE_CHECKING:
    from ..models.bulk_delete_result_item_shared_maps_type_0_item import (
        BulkDeleteResultItemSharedMapsType0Item,
    )


T = TypeVar("T", bound="BulkDeleteResultItem")


@_attrs_define
class BulkDeleteResultItem:
    """
    Attributes:
        dataset_id (UUID):
        status (str):
        detail (None | str | Unset):
        code (None | str | Unset):
        shared_maps (list[BulkDeleteResultItemSharedMapsType0Item] | None | Unset): The owner's shared maps that refused
            this item, as `{"id", "name"}` pairs, on a `dataset_in_shared_maps` error. Null otherwise.
    """

    dataset_id: UUID
    status: str
    detail: None | str | Unset = UNSET
    code: None | str | Unset = UNSET
    shared_maps: list[BulkDeleteResultItemSharedMapsType0Item] | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        dataset_id = str(self.dataset_id)

        status = self.status

        detail: None | str | Unset
        if isinstance(self.detail, Unset):
            detail = UNSET
        else:
            detail = self.detail

        code: None | str | Unset
        if isinstance(self.code, Unset):
            code = UNSET
        else:
            code = self.code

        shared_maps: list[dict[str, Any]] | None | Unset
        if isinstance(self.shared_maps, Unset):
            shared_maps = UNSET
        elif isinstance(self.shared_maps, list):
            shared_maps = []
            for shared_maps_type_0_item_data in self.shared_maps:
                shared_maps_type_0_item = shared_maps_type_0_item_data.to_dict()
                shared_maps.append(shared_maps_type_0_item)

        else:
            shared_maps = self.shared_maps

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "dataset_id": dataset_id,
                "status": status,
            }
        )
        if detail is not UNSET:
            field_dict["detail"] = detail
        if code is not UNSET:
            field_dict["code"] = code
        if shared_maps is not UNSET:
            field_dict["shared_maps"] = shared_maps

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.bulk_delete_result_item_shared_maps_type_0_item import (
            BulkDeleteResultItemSharedMapsType0Item,
        )

        d = dict(src_dict)
        dataset_id = UUID(d.pop("dataset_id"))

        status = d.pop("status")

        def _parse_detail(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        detail = _parse_detail(d.pop("detail", UNSET))

        def _parse_code(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        code = _parse_code(d.pop("code", UNSET))

        def _parse_shared_maps(
            data: object,
        ) -> list[BulkDeleteResultItemSharedMapsType0Item] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                shared_maps_type_0 = []
                _shared_maps_type_0 = data
                for shared_maps_type_0_item_data in _shared_maps_type_0:
                    shared_maps_type_0_item = (
                        BulkDeleteResultItemSharedMapsType0Item.from_dict(
                            shared_maps_type_0_item_data
                        )
                    )

                    shared_maps_type_0.append(shared_maps_type_0_item)

                return shared_maps_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(
                list[BulkDeleteResultItemSharedMapsType0Item] | None | Unset, data
            )

        shared_maps = _parse_shared_maps(d.pop("shared_maps", UNSET))

        bulk_delete_result_item = cls(
            dataset_id=dataset_id,
            status=status,
            detail=detail,
            code=code,
            shared_maps=shared_maps,
        )

        bulk_delete_result_item.additional_properties = d
        return bulk_delete_result_item

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
