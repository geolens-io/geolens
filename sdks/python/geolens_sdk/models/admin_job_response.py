from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from ..models.admin_job_response_status import AdminJobResponseStatus
from ..models.admin_job_response_status import check_admin_job_response_status
from dateutil.parser import isoparse
from typing import cast
from uuid import UUID
import datetime

if TYPE_CHECKING:
    from ..models.admin_job_response_user_metadata_type_0 import (
        AdminJobResponseUserMetadataType0,
    )


T = TypeVar("T", bound="AdminJobResponse")


@_attrs_define
class AdminJobResponse:
    """
    Attributes:
        completed_at (datetime.datetime | None): Timestamp when the job finished (success or failure).
        created_at (datetime.datetime): Timestamp when the job was queued.
        created_by (None | UUID): ID of the user who initiated the job.
        dataset_id (None | UUID): ID of the dataset created by this job, if completed successfully.
        error_message (None | str): Error details if the job failed.
        id (UUID): Unique ingestion job identifier.
        source_filename (None | str): Original filename of the uploaded file, if applicable.
        started_at (datetime.datetime | None): Timestamp when the worker began processing the job.
        status (AdminJobResponseStatus): Current job status: 'pending', 'running', 'complete', 'failed', or 'cancelled'.
        user_metadata (AdminJobResponseUserMetadataType0 | None): User-supplied metadata captured at upload time (title,
            summary, tags, etc.).
        username (None | str): Username of the user who initiated the job.
    """

    completed_at: datetime.datetime | None
    created_at: datetime.datetime
    created_by: None | UUID
    dataset_id: None | UUID
    error_message: None | str
    id: UUID
    source_filename: None | str
    started_at: datetime.datetime | None
    status: AdminJobResponseStatus
    user_metadata: AdminJobResponseUserMetadataType0 | None
    username: None | str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.admin_job_response_user_metadata_type_0 import (
            AdminJobResponseUserMetadataType0,
        )

        completed_at: None | str
        if isinstance(self.completed_at, datetime.datetime):
            completed_at = self.completed_at.isoformat()
        else:
            completed_at = self.completed_at

        created_at = self.created_at.isoformat()

        created_by: None | str
        if isinstance(self.created_by, UUID):
            created_by = str(self.created_by)
        else:
            created_by = self.created_by

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

        user_metadata: dict[str, Any] | None
        if isinstance(self.user_metadata, AdminJobResponseUserMetadataType0):
            user_metadata = self.user_metadata.to_dict()
        else:
            user_metadata = self.user_metadata

        username: None | str
        username = self.username

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "completed_at": completed_at,
                "created_at": created_at,
                "created_by": created_by,
                "dataset_id": dataset_id,
                "error_message": error_message,
                "id": id,
                "source_filename": source_filename,
                "started_at": started_at,
                "status": status,
                "user_metadata": user_metadata,
                "username": username,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.admin_job_response_user_metadata_type_0 import (
            AdminJobResponseUserMetadataType0,
        )

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

        def _parse_created_by(data: object) -> None | UUID:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                created_by_type_0 = UUID(data)

                return created_by_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | UUID, data)

        created_by = _parse_created_by(d.pop("created_by"))

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

        status = check_admin_job_response_status(d.pop("status"))

        def _parse_user_metadata(
            data: object,
        ) -> AdminJobResponseUserMetadataType0 | None:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                user_metadata_type_0 = AdminJobResponseUserMetadataType0.from_dict(data)

                return user_metadata_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(AdminJobResponseUserMetadataType0 | None, data)

        user_metadata = _parse_user_metadata(d.pop("user_metadata"))

        def _parse_username(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        username = _parse_username(d.pop("username"))

        admin_job_response = cls(
            completed_at=completed_at,
            created_at=created_at,
            created_by=created_by,
            dataset_id=dataset_id,
            error_message=error_message,
            id=id,
            source_filename=source_filename,
            started_at=started_at,
            status=status,
            user_metadata=user_metadata,
            username=username,
        )

        admin_job_response.additional_properties = d
        return admin_job_response

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
