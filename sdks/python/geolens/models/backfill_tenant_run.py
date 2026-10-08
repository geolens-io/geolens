from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from ..models.backfill_tenant_run_status import BackfillTenantRunStatus
from ..models.backfill_tenant_run_status import check_backfill_tenant_run_status
from typing import cast
from uuid import UUID


T = TypeVar("T", bound="BackfillTenantRun")


@_attrs_define
class BackfillTenantRun:
    """What an all-tenant backfill request did for one other tenant.

    Attributes:
        tenant_id (UUID): The tenant the run was queued for.
        job_id (None | UUID): Identifier of the job queued in that tenant, or null when none was queued.
        status (BackfillTenantRunStatus): 'pending' when a run was queued, 'already_running' when that tenant already
            had one in flight, 'not_queued' when queueing failed.
    """

    tenant_id: UUID
    job_id: None | UUID
    status: BackfillTenantRunStatus
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        tenant_id = str(self.tenant_id)

        job_id: None | str
        if isinstance(self.job_id, UUID):
            job_id = str(self.job_id)
        else:
            job_id = self.job_id

        status: str = self.status

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "tenant_id": tenant_id,
                "job_id": job_id,
                "status": status,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        tenant_id = UUID(d.pop("tenant_id"))

        def _parse_job_id(data: object) -> None | UUID:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                job_id_type_0 = UUID(data)

                return job_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | UUID, data)

        job_id = _parse_job_id(d.pop("job_id"))

        status = check_backfill_tenant_run_status(d.pop("status"))

        backfill_tenant_run = cls(
            tenant_id=tenant_id,
            job_id=job_id,
            status=status,
        )

        backfill_tenant_run.additional_properties = d
        return backfill_tenant_run

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
