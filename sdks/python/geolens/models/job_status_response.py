from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.job_status_response_status import check_job_status_response_status
from ..models.job_status_response_status import JobStatusResponseStatus
from dateutil.parser import isoparse
from typing import cast
from uuid import UUID
import datetime

if TYPE_CHECKING:
    from ..models.dbf_truncation_collision_warning import DbfTruncationCollisionWarning
    from ..models.job_status_response_temporal_parse_errors import (
        JobStatusResponseTemporalParseErrors,
    )
    from ..models.reserved_rename_warning import ReservedRenameWarning


T = TypeVar("T", bound="JobStatusResponse")


@_attrs_define
class JobStatusResponse:
    """
    Attributes:
        completed_at (datetime.datetime | None):
        created_at (datetime.datetime):
        dataset_id (None | UUID):
        error_message (None | str):
        id (UUID):
        source_filename (None | str):
        started_at (datetime.datetime | None):
        status (JobStatusResponseStatus):
        archive_failed (bool | Unset):  Default: False.
        temporal_parse_errors (JobStatusResponseTemporalParseErrors | Unset):
        warning_message (None | str | Unset):
        warnings (list[DbfTruncationCollisionWarning | ReservedRenameWarning] | Unset):
    """

    completed_at: datetime.datetime | None
    created_at: datetime.datetime
    dataset_id: None | UUID
    error_message: None | str
    id: UUID
    source_filename: None | str
    started_at: datetime.datetime | None
    status: JobStatusResponseStatus
    archive_failed: bool | Unset = False
    temporal_parse_errors: JobStatusResponseTemporalParseErrors | Unset = UNSET
    warning_message: None | str | Unset = UNSET
    warnings: list[DbfTruncationCollisionWarning | ReservedRenameWarning] | Unset = (
        UNSET
    )
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.reserved_rename_warning import ReservedRenameWarning

        completed_at: None | str
        if isinstance(self.completed_at, datetime.datetime):
            completed_at = self.completed_at.isoformat()
        else:
            completed_at = self.completed_at

        created_at = self.created_at.isoformat()

        dataset_id: None | str
        if isinstance(self.dataset_id, UUID):
            dataset_id = str(self.dataset_id)
        else:
            dataset_id = self.dataset_id

        error_message: None | str
        error_message = self.error_message

        id = str(self.id)

        source_filename: None | str
        source_filename = self.source_filename

        started_at: None | str
        if isinstance(self.started_at, datetime.datetime):
            started_at = self.started_at.isoformat()
        else:
            started_at = self.started_at

        status: str = self.status

        archive_failed = self.archive_failed

        temporal_parse_errors: dict[str, Any] | Unset = UNSET
        if not isinstance(self.temporal_parse_errors, Unset):
            temporal_parse_errors = self.temporal_parse_errors.to_dict()

        warning_message: None | str | Unset
        if isinstance(self.warning_message, Unset):
            warning_message = UNSET
        else:
            warning_message = self.warning_message

        warnings: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.warnings, Unset):
            warnings = []
            for warnings_item_data in self.warnings:
                warnings_item: dict[str, Any]
                if isinstance(warnings_item_data, ReservedRenameWarning):
                    warnings_item = warnings_item_data.to_dict()
                else:
                    warnings_item = warnings_item_data.to_dict()

                warnings.append(warnings_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "completed_at": completed_at,
                "created_at": created_at,
                "dataset_id": dataset_id,
                "error_message": error_message,
                "id": id,
                "source_filename": source_filename,
                "started_at": started_at,
                "status": status,
            }
        )
        if archive_failed is not UNSET:
            field_dict["archive_failed"] = archive_failed
        if temporal_parse_errors is not UNSET:
            field_dict["temporal_parse_errors"] = temporal_parse_errors
        if warning_message is not UNSET:
            field_dict["warning_message"] = warning_message
        if warnings is not UNSET:
            field_dict["warnings"] = warnings

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.dbf_truncation_collision_warning import (
            DbfTruncationCollisionWarning,
        )
        from ..models.job_status_response_temporal_parse_errors import (
            JobStatusResponseTemporalParseErrors,
        )
        from ..models.reserved_rename_warning import ReservedRenameWarning

        d = dict(src_dict)

        def _parse_completed_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                completed_at_type_0 = isoparse(data)

                return completed_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        completed_at = _parse_completed_at(d.pop("completed_at"))

        created_at = isoparse(d.pop("created_at"))

        def _parse_dataset_id(data: object) -> None | UUID:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                dataset_id_type_0 = UUID(data)

                return dataset_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | UUID, data)

        dataset_id = _parse_dataset_id(d.pop("dataset_id"))

        def _parse_error_message(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        error_message = _parse_error_message(d.pop("error_message"))

        id = UUID(d.pop("id"))

        def _parse_source_filename(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        source_filename = _parse_source_filename(d.pop("source_filename"))

        def _parse_started_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                started_at_type_0 = isoparse(data)

                return started_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        started_at = _parse_started_at(d.pop("started_at"))

        status = check_job_status_response_status(d.pop("status"))

        archive_failed = d.pop("archive_failed", UNSET)

        _temporal_parse_errors = d.pop("temporal_parse_errors", UNSET)
        temporal_parse_errors: JobStatusResponseTemporalParseErrors | Unset
        if isinstance(_temporal_parse_errors, Unset):
            temporal_parse_errors = UNSET
        else:
            temporal_parse_errors = JobStatusResponseTemporalParseErrors.from_dict(
                _temporal_parse_errors
            )

        def _parse_warning_message(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        warning_message = _parse_warning_message(d.pop("warning_message", UNSET))

        _warnings = d.pop("warnings", UNSET)
        warnings: (
            list[DbfTruncationCollisionWarning | ReservedRenameWarning] | Unset
        ) = UNSET
        if _warnings is not UNSET:
            warnings = []
            for warnings_item_data in _warnings:

                def _parse_warnings_item(
                    data: object,
                ) -> DbfTruncationCollisionWarning | ReservedRenameWarning:
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        warnings_item_type_0 = ReservedRenameWarning.from_dict(data)

                        return warnings_item_type_0
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    if not isinstance(data, dict):
                        raise TypeError()
                    warnings_item_type_1 = DbfTruncationCollisionWarning.from_dict(data)

                    return warnings_item_type_1

                warnings_item = _parse_warnings_item(warnings_item_data)

                warnings.append(warnings_item)

        job_status_response = cls(
            completed_at=completed_at,
            created_at=created_at,
            dataset_id=dataset_id,
            error_message=error_message,
            id=id,
            source_filename=source_filename,
            started_at=started_at,
            status=status,
            archive_failed=archive_failed,
            temporal_parse_errors=temporal_parse_errors,
            warning_message=warning_message,
            warnings=warnings,
        )

        job_status_response.additional_properties = d
        return job_status_response

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
