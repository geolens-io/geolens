from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from uuid import UUID


T = TypeVar("T", bound="CommitResponse")


@_attrs_define
class CommitResponse:
    """
    Attributes:
        job_id (UUID): Identifier of the committed ingestion job.
        status (str): Updated job status after commit.
        message (str): Human-readable commit result.
        origin_link_loss (list[str] | Unset): Reasons the ArcGIS item link was dropped: 'item_id_invalid',
            'portal_url_invalid', 'portal_url_domain_mismatch' or 'origin_link_unsupported'. Empty when nothing was dropped.
    """

    job_id: UUID
    status: str
    message: str
    origin_link_loss: list[str] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        job_id = str(self.job_id)

        status = self.status

        message = self.message

        origin_link_loss: list[str] | Unset = UNSET
        if not isinstance(self.origin_link_loss, Unset):
            origin_link_loss = self.origin_link_loss

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "job_id": job_id,
                "status": status,
                "message": message,
            }
        )
        if origin_link_loss is not UNSET:
            field_dict["origin_link_loss"] = origin_link_loss

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        job_id = UUID(d.pop("job_id"))

        status = d.pop("status")

        message = d.pop("message")

        origin_link_loss = cast(list[str], d.pop("origin_link_loss", UNSET))

        commit_response = cls(
            job_id=job_id,
            status=status,
            message=message,
            origin_link_loss=origin_link_loss,
        )

        commit_response.additional_properties = d
        return commit_response

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
