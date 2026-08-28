from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from typing import Literal
from uuid import UUID


T = TypeVar("T", bound="JobCancelResponse")


@_attrs_define
class JobCancelResponse:
    """Outcome of ``POST /jobs/{id}/cancel`` (#1677).

    ``run_id`` is the ``dataset_refresh_runs`` row this cancel finalized, when
    the job had one bound (refreshes and reuploads do; plain imports don't).
    ``already`` is True when the job was cancelled before this request — the
    repeat is idempotent and nothing was written.

        Attributes:
            id (UUID):
            status (Literal['cancelled']):
            run_id (None | UUID):
            already (bool | Unset):  Default: False.
    """

    id: UUID
    status: Literal["cancelled"]
    run_id: None | UUID
    already: bool | Unset = False
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = str(self.id)

        status = self.status

        run_id: None | str
        if isinstance(self.run_id, UUID):
            run_id = str(self.run_id)
        else:
            run_id = self.run_id

        already = self.already

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "status": status,
                "run_id": run_id,
            }
        )
        if already is not UNSET:
            field_dict["already"] = already

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = UUID(d.pop("id"))

        status = cast(Literal["cancelled"], d.pop("status"))
        if status != "cancelled":
            raise ValueError(f"status must match const 'cancelled', got '{status}'")

        def _parse_run_id(data: object) -> None | UUID:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                run_id_type_0 = UUID(data)

                return run_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | UUID, data)

        run_id = _parse_run_id(d.pop("run_id"))

        already = d.pop("already", UNSET)

        job_cancel_response = cls(
            id=id,
            status=status,
            run_id=run_id,
            already=already,
        )

        job_cancel_response.additional_properties = d
        return job_cancel_response

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
