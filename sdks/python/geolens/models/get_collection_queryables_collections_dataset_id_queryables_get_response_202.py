from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset


T = TypeVar(
    "T", bound="GetCollectionQueryablesCollectionsDatasetIdQueryablesGetResponse202"
)


@_attrs_define
class GetCollectionQueryablesCollectionsDatasetIdQueryablesGetResponse202:
    """
    Attributes:
        status (str | Unset):
        job_id (str | Unset):
    """

    status: str | Unset = UNSET
    job_id: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        status = self.status

        job_id = self.job_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if status is not UNSET:
            field_dict["status"] = status
        if job_id is not UNSET:
            field_dict["job_id"] = job_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        status = d.pop("status", UNSET)

        job_id = d.pop("job_id", UNSET)

        get_collection_queryables_collections_dataset_id_queryables_get_response_202 = (
            cls(
                status=status,
                job_id=job_id,
            )
        )

        get_collection_queryables_collections_dataset_id_queryables_get_response_202.additional_properties = d
        return (
            get_collection_queryables_collections_dataset_id_queryables_get_response_202
        )

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
