from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from uuid import UUID

if TYPE_CHECKING:
    from ..models.backfill_tenant_run import BackfillTenantRun


T = TypeVar("T", bound="BackfillResponse")


@_attrs_define
class BackfillResponse:
    """Acknowledgement that a backfill run was queued.

    The response carries no counts because the work runs asynchronously. Poll
    ``GET /jobs/{job_id}`` for status.

        Attributes:
            job_id (UUID): Identifier of the queued backfill job; poll /jobs/{job_id}.
            status (str): 'pending' when this request queued job_id. 'already_running' when an all_tenants request found a
                run in flight in the calling tenant; job_id is then that run.
            other_tenants (list[BackfillTenantRun] | Unset): Runs queued for the other tenants by an all_tenants request in
                a multi-tenant deployment. Empty otherwise.
    """

    job_id: UUID
    status: str
    other_tenants: list[BackfillTenantRun] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        job_id = str(self.job_id)

        status = self.status

        other_tenants: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.other_tenants, Unset):
            other_tenants = []
            for other_tenants_item_data in self.other_tenants:
                other_tenants_item = other_tenants_item_data.to_dict()
                other_tenants.append(other_tenants_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "job_id": job_id,
                "status": status,
            }
        )
        if other_tenants is not UNSET:
            field_dict["other_tenants"] = other_tenants

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.backfill_tenant_run import BackfillTenantRun

        d = dict(src_dict)
        job_id = UUID(d.pop("job_id"))

        status = d.pop("status")

        _other_tenants = d.pop("other_tenants", UNSET)
        other_tenants: list[BackfillTenantRun] | Unset = UNSET
        if _other_tenants is not UNSET:
            other_tenants = []
            for other_tenants_item_data in _other_tenants:
                other_tenants_item = BackfillTenantRun.from_dict(
                    other_tenants_item_data
                )

                other_tenants.append(other_tenants_item)

        backfill_response = cls(
            job_id=job_id,
            status=status,
            other_tenants=other_tenants,
        )

        backfill_response.additional_properties = d
        return backfill_response

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
