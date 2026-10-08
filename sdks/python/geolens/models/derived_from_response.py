from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from dateutil.parser import isoparse
from typing import cast
from uuid import UUID
import datetime

if TYPE_CHECKING:
    from ..models.derived_from_response_params import DerivedFromResponseParams
    from ..models.derived_from_response_source_filter_type_0 import (
        DerivedFromResponseSourceFilterType0,
    )


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
            source_filter (DerivedFromResponseSourceFilterType0 | None | Unset): CQL2-JSON filter that selected the source
                features, or null when the whole source dataset was used
    """

    dataset_id: UUID
    operation: str
    params: DerivedFromResponseParams
    created_at: datetime.datetime
    source_filter: DerivedFromResponseSourceFilterType0 | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.derived_from_response_source_filter_type_0 import (
            DerivedFromResponseSourceFilterType0,
        )

        dataset_id = str(self.dataset_id)

        operation = self.operation

        params = self.params.to_dict()

        created_at = self.created_at.isoformat()

        source_filter: dict[str, Any] | None | Unset
        if isinstance(self.source_filter, Unset):
            source_filter = UNSET
        elif isinstance(self.source_filter, DerivedFromResponseSourceFilterType0):
            source_filter = self.source_filter.to_dict()
        else:
            source_filter = self.source_filter

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
        if source_filter is not UNSET:
            field_dict["source_filter"] = source_filter

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.derived_from_response_params import DerivedFromResponseParams
        from ..models.derived_from_response_source_filter_type_0 import (
            DerivedFromResponseSourceFilterType0,
        )

        d = dict(src_dict)
        dataset_id = UUID(d.pop("dataset_id"))

        operation = d.pop("operation")

        params = DerivedFromResponseParams.from_dict(d.pop("params"))

        created_at = isoparse(d.pop("created_at"))

        def _parse_source_filter(
            data: object,
        ) -> DerivedFromResponseSourceFilterType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                source_filter_type_0 = DerivedFromResponseSourceFilterType0.from_dict(
                    data
                )

                return source_filter_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(DerivedFromResponseSourceFilterType0 | None | Unset, data)

        source_filter = _parse_source_filter(d.pop("source_filter", UNSET))

        derived_from_response = cls(
            dataset_id=dataset_id,
            operation=operation,
            params=params,
            created_at=created_at,
            source_filter=source_filter,
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
