from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from uuid import UUID


T = TypeVar("T", bound="VrtCreateResponse")


@_attrs_define
class VrtCreateResponse:
    """
    Attributes:
        job_id (UUID): Identifier of the asynchronous VRT creation job.
        message (str): Human-readable acceptance message.
        status (str | Unset): Initial job status. Always 'accepted' on creation. Default: 'accepted'.
    """

    job_id: UUID
    message: str
    status: str | Unset = "accepted"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        job_id = str(self.job_id)

        message = self.message

        status = self.status

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "job_id": job_id,
                "message": message,
            }
        )
        if status is not UNSET:
            field_dict["status"] = status

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        job_id = UUID(d.pop("job_id"))

        message = d.pop("message")

        status = d.pop("status", UNSET)

        vrt_create_response = cls(
            job_id=job_id,
            message=message,
            status=status,
        )

        vrt_create_response.additional_properties = d
        return vrt_create_response

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
