from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.fan_out_layer_result_status import check_fan_out_layer_result_status
from ..models.fan_out_layer_result_status import FanOutLayerResultStatus
from typing import cast
from uuid import UUID


T = TypeVar("T", bound="FanOutLayerResult")


@_attrs_define
class FanOutLayerResult:
    """Per-layer outcome from the fan-out commit operation.

    Attributes:
        layer_name (str): Layer name from the request.
        status (FanOutLayerResultStatus): 'queued' if the task was dispatched; 'failed' if an error occurred.
        dataset_id (None | Unset | UUID): ID of the new Dataset record created for this layer. Null on failure.
        error (None | str | Unset): User-safe error description when status='failed'. Never contains internal file
            paths.
        new_job_id (None | Unset | UUID): ID of the cloned IngestJob queued for this layer. Null on failure.
    """

    layer_name: str
    status: FanOutLayerResultStatus
    dataset_id: None | Unset | UUID = UNSET
    error: None | str | Unset = UNSET
    new_job_id: None | Unset | UUID = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        layer_name = self.layer_name

        status: str = self.status

        dataset_id: None | str | Unset
        if isinstance(self.dataset_id, Unset):
            dataset_id = UNSET
        elif isinstance(self.dataset_id, UUID):
            dataset_id = str(self.dataset_id)
        else:
            dataset_id = self.dataset_id

        error: None | str | Unset
        if isinstance(self.error, Unset):
            error = UNSET
        else:
            error = self.error

        new_job_id: None | str | Unset
        if isinstance(self.new_job_id, Unset):
            new_job_id = UNSET
        elif isinstance(self.new_job_id, UUID):
            new_job_id = str(self.new_job_id)
        else:
            new_job_id = self.new_job_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "layer_name": layer_name,
                "status": status,
            }
        )
        if dataset_id is not UNSET:
            field_dict["dataset_id"] = dataset_id
        if error is not UNSET:
            field_dict["error"] = error
        if new_job_id is not UNSET:
            field_dict["new_job_id"] = new_job_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        layer_name = d.pop("layer_name")

        status = check_fan_out_layer_result_status(d.pop("status"))

        def _parse_dataset_id(data: object) -> None | Unset | UUID:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                dataset_id_type_0 = UUID(data)

                return dataset_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UUID, data)

        dataset_id = _parse_dataset_id(d.pop("dataset_id", UNSET))

        def _parse_error(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        error = _parse_error(d.pop("error", UNSET))

        def _parse_new_job_id(data: object) -> None | Unset | UUID:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                new_job_id_type_0 = UUID(data)

                return new_job_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UUID, data)

        new_job_id = _parse_new_job_id(d.pop("new_job_id", UNSET))

        fan_out_layer_result = cls(
            layer_name=layer_name,
            status=status,
            dataset_id=dataset_id,
            error=error,
            new_job_id=new_job_id,
        )

        fan_out_layer_result.additional_properties = d
        return fan_out_layer_result

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
