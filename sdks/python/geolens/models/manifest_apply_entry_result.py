from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.manifest_apply_entry_result_action import (
    check_manifest_apply_entry_result_action,
)
from ..models.manifest_apply_entry_result_action import ManifestApplyEntryResultAction
from typing import cast
from uuid import UUID


T = TypeVar("T", bound="ManifestApplyEntryResult")


@_attrs_define
class ManifestApplyEntryResult:
    """
    Attributes:
        dataset_key (str):
        action (ManifestApplyEntryResultAction):
        message (str):
        job_id (None | Unset | UUID):
        dataset_id (None | Unset | UUID):
        errors (list[str] | Unset):
    """

    dataset_key: str
    action: ManifestApplyEntryResultAction
    message: str
    job_id: None | Unset | UUID = UNSET
    dataset_id: None | Unset | UUID = UNSET
    errors: list[str] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        dataset_key = self.dataset_key

        action: str = self.action

        message = self.message

        job_id: None | str | Unset
        if isinstance(self.job_id, Unset):
            job_id = UNSET
        elif isinstance(self.job_id, UUID):
            job_id = str(self.job_id)
        else:
            job_id = self.job_id

        dataset_id: None | str | Unset
        if isinstance(self.dataset_id, Unset):
            dataset_id = UNSET
        elif isinstance(self.dataset_id, UUID):
            dataset_id = str(self.dataset_id)
        else:
            dataset_id = self.dataset_id

        errors: list[str] | Unset = UNSET
        if not isinstance(self.errors, Unset):
            errors = self.errors

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "dataset_key": dataset_key,
                "action": action,
                "message": message,
            }
        )
        if job_id is not UNSET:
            field_dict["job_id"] = job_id
        if dataset_id is not UNSET:
            field_dict["dataset_id"] = dataset_id
        if errors is not UNSET:
            field_dict["errors"] = errors

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        dataset_key = d.pop("dataset_key")

        action = check_manifest_apply_entry_result_action(d.pop("action"))

        message = d.pop("message")

        def _parse_job_id(data: object) -> None | Unset | UUID:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                job_id_type_0 = UUID(data)

                return job_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UUID, data)

        job_id = _parse_job_id(d.pop("job_id", UNSET))

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

        errors = cast(list[str], d.pop("errors", UNSET))

        manifest_apply_entry_result = cls(
            dataset_key=dataset_key,
            action=action,
            message=message,
            job_id=job_id,
            dataset_id=dataset_id,
            errors=errors,
        )

        manifest_apply_entry_result.additional_properties = d
        return manifest_apply_entry_result

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
