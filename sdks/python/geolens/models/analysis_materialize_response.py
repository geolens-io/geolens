from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from uuid import UUID


T = TypeVar("T", bound="AnalysisMaterializeResponse")


@_attrs_define
class AnalysisMaterializeResponse:
    """Async materialize job handle; poll GET /jobs/{job_id} for progress.

    Attributes:
        job_id (UUID):
        status (str):
    """

    job_id: UUID
    status: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        job_id = str(self.job_id)

        status = self.status

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "job_id": job_id,
                "status": status,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        job_id = UUID(d.pop("job_id"))

        status = d.pop("status")

        analysis_materialize_response = cls(
            job_id=job_id,
            status=status,
        )

        analysis_materialize_response.additional_properties = d
        return analysis_materialize_response

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
