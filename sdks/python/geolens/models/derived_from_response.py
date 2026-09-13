from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from dateutil.parser import isoparse
from uuid import UUID
import datetime

if TYPE_CHECKING:
    from ..models.derived_from_response_params import DerivedFromResponseParams


T = TypeVar("T", bound="DerivedFromResponse")


@_attrs_define
class DerivedFromResponse:
    """Provenance for an analysis output: what it came from, and how.

    ``params`` stays untyped on purpose: it is the operation's own parameter
    dictionary, so its keys differ by operation. It is also redacted for each
    requester: dataset ids that the caller cannot access are omitted.

        Attributes:
            dataset_id (UUID): The dataset this one was derived from
            operation (str): Analysis operation that produced it
            params (DerivedFromResponseParams): Operation parameters, minus any dataset reference the requester cannot
                access
            created_at (datetime.datetime):
    """

    dataset_id: UUID
    operation: str
    params: DerivedFromResponseParams
    created_at: datetime.datetime
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        dataset_id = str(self.dataset_id)

        operation = self.operation

        params = self.params.to_dict()

        created_at = self.created_at.isoformat()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "dataset_id": dataset_id,
                "operation": operation,
                "params": params,
                "created_at": created_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.derived_from_response_params import DerivedFromResponseParams

        d = dict(src_dict)
        dataset_id = UUID(d.pop("dataset_id"))

        operation = d.pop("operation")

        params = DerivedFromResponseParams.from_dict(d.pop("params"))

        created_at = isoparse(d.pop("created_at"))

        derived_from_response = cls(
            dataset_id=dataset_id,
            operation=operation,
            params=params,
            created_at=created_at,
        )

        derived_from_response.additional_properties = d
        return derived_from_response

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
