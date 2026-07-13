from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import Literal, cast


T = TypeVar("T", bound="ConnectorIngestResponse")


@_attrs_define
class ConnectorIngestResponse:
    """
    Attributes:
        job_id (str): API-safe opaque handle for the dispatched ingest job.
        status (Literal['queued'] | Unset):  Default: 'queued'.
    """

    job_id: str
    status: Literal["queued"] | Unset = "queued"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        job_id = self.job_id

        status = self.status

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "job_id": job_id,
            }
        )
        if status is not UNSET:
            field_dict["status"] = status

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        job_id = d.pop("job_id")

        status = cast(Literal["queued"] | Unset, d.pop("status", UNSET))
        if status != "queued" and not isinstance(status, Unset):
            raise ValueError(f"status must match const 'queued', got '{status}'")

        connector_ingest_response = cls(
            job_id=job_id,
            status=status,
        )

        connector_ingest_response.additional_properties = d
        return connector_ingest_response

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
