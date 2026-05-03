from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from ..models.vrt_source_health_status import check_vrt_source_health_status
from ..models.vrt_source_health_status import VrtSourceHealthStatus
from uuid import UUID


T = TypeVar("T", bound="VrtSourceHealth")


@_attrs_define
class VrtSourceHealth:
    """
    Attributes:
        dataset_id (UUID):
        status (VrtSourceHealthStatus):
        title (str):
    """

    dataset_id: UUID
    status: VrtSourceHealthStatus
    title: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        dataset_id = str(self.dataset_id)

        status: str = self.status

        title = self.title

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "dataset_id": dataset_id,
                "status": status,
                "title": title,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        dataset_id = UUID(d.pop("dataset_id"))

        status = check_vrt_source_health_status(d.pop("status"))

        title = d.pop("title")

        vrt_source_health = cls(
            dataset_id=dataset_id,
            status=status,
            title=title,
        )

        vrt_source_health.additional_properties = d
        return vrt_source_health

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
