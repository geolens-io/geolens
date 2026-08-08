from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from uuid import UUID


T = TypeVar("T", bound="DatasetRefreshResponse")


@_attrs_define
class DatasetRefreshResponse:
    """Accepted dispatch of a refresh run.

    Returns the run id as well as the job id: the run is the durable history
    row (``GET /datasets/{id}/refresh-runs``) and outlives the job, which the
    retention purge eventually removes.

        Attributes:
            run_id (UUID):
            job_id (UUID):
            dataset_id (UUID):
            origin_kind (str): The origin this refresh re-pulled from
            trigger (str): api for this endpoint; cli for the CLI door
            message (str):
            status (str | Unset):  Default: 'pending'.
    """

    run_id: UUID
    job_id: UUID
    dataset_id: UUID
    origin_kind: str
    trigger: str
    message: str
    status: str | Unset = "pending"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        run_id = str(self.run_id)

        job_id = str(self.job_id)

        dataset_id = str(self.dataset_id)

        origin_kind = self.origin_kind

        trigger = self.trigger

        message = self.message

        status = self.status

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "run_id": run_id,
                "job_id": job_id,
                "dataset_id": dataset_id,
                "origin_kind": origin_kind,
                "trigger": trigger,
                "message": message,
            }
        )
        if status is not UNSET:
            field_dict["status"] = status

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        run_id = UUID(d.pop("run_id"))

        job_id = UUID(d.pop("job_id"))

        dataset_id = UUID(d.pop("dataset_id"))

        origin_kind = d.pop("origin_kind")

        trigger = d.pop("trigger")

        message = d.pop("message")

        status = d.pop("status", UNSET)

        dataset_refresh_response = cls(
            run_id=run_id,
            job_id=job_id,
            dataset_id=dataset_id,
            origin_kind=origin_kind,
            trigger=trigger,
            message=message,
            status=status,
        )

        dataset_refresh_response.additional_properties = d
        return dataset_refresh_response

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
