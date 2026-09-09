from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from dateutil.parser import isoparse
from typing import cast
from uuid import UUID
import datetime


T = TypeVar("T", bound="BackfillRunProgress")


@_attrs_define
class BackfillRunProgress:
    """The embedding backfill run currently holding the single run slot.

    Attributes:
        job_id (UUID): Identifier of the run in flight.
        status (str): Job status: 'pending' or 'running'.
        records_processed (int): Records the run has embedded so far.
        records_total (int | None | Unset): Records the run will embed in total. Null until the run has selected its
            records.
        started_at (datetime.datetime | None | Unset): When a worker picked the run up.
        heartbeat_at (datetime.datetime | None | Unset): Last time the running worker renewed its lease.
    """

    job_id: UUID
    status: str
    records_processed: int
    records_total: int | None | Unset = UNSET
    started_at: datetime.datetime | None | Unset = UNSET
    heartbeat_at: datetime.datetime | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        job_id = str(self.job_id)

        status = self.status

        records_processed = self.records_processed

        records_total: int | None | Unset
        if isinstance(self.records_total, Unset):
            records_total = UNSET
        else:
            records_total = self.records_total

        started_at: None | str | Unset
        if isinstance(self.started_at, Unset):
            started_at = UNSET
        elif isinstance(self.started_at, datetime.datetime):
            started_at = self.started_at.isoformat()
        else:
            started_at = self.started_at

        heartbeat_at: None | str | Unset
        if isinstance(self.heartbeat_at, Unset):
            heartbeat_at = UNSET
        elif isinstance(self.heartbeat_at, datetime.datetime):
            heartbeat_at = self.heartbeat_at.isoformat()
        else:
            heartbeat_at = self.heartbeat_at

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "job_id": job_id,
                "status": status,
                "records_processed": records_processed,
            }
        )
        if records_total is not UNSET:
            field_dict["records_total"] = records_total
        if started_at is not UNSET:
            field_dict["started_at"] = started_at
        if heartbeat_at is not UNSET:
            field_dict["heartbeat_at"] = heartbeat_at

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        job_id = UUID(d.pop("job_id"))

        status = d.pop("status")

        records_processed = d.pop("records_processed")

        def _parse_records_total(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        records_total = _parse_records_total(d.pop("records_total", UNSET))

        def _parse_started_at(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                started_at_type_0 = isoparse(data)

                return started_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        started_at = _parse_started_at(d.pop("started_at", UNSET))

        def _parse_heartbeat_at(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                heartbeat_at_type_0 = isoparse(data)

                return heartbeat_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        heartbeat_at = _parse_heartbeat_at(d.pop("heartbeat_at", UNSET))

        backfill_run_progress = cls(
            job_id=job_id,
            status=status,
            records_processed=records_processed,
            records_total=records_total,
            started_at=started_at,
            heartbeat_at=heartbeat_at,
        )

        backfill_run_progress.additional_properties = d
        return backfill_run_progress

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
