from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from uuid import UUID


T = TypeVar("T", bound="PresignedUploadResponse")


@_attrs_define
class PresignedUploadResponse:
    """
    Attributes:
        job_id (UUID): Identifier of the ingestion job created for this upload.
        s3_key (str): Object key in the S3 bucket where the file will be stored.
        urls (list[str]): One presigned PUT URL per part. Single-element list for single-part uploads.
        part_size (int | None | Unset): Byte size of each part in a multipart upload.
        upload_id (None | str | Unset): S3 multipart upload ID, set only for multipart uploads.
    """

    job_id: UUID
    s3_key: str
    urls: list[str]
    part_size: int | None | Unset = UNSET
    upload_id: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        job_id = str(self.job_id)

        s3_key = self.s3_key

        urls = self.urls

        part_size: int | None | Unset
        if isinstance(self.part_size, Unset):
            part_size = UNSET
        else:
            part_size = self.part_size

        upload_id: None | str | Unset
        if isinstance(self.upload_id, Unset):
            upload_id = UNSET
        else:
            upload_id = self.upload_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "job_id": job_id,
                "s3_key": s3_key,
                "urls": urls,
            }
        )
        if part_size is not UNSET:
            field_dict["part_size"] = part_size
        if upload_id is not UNSET:
            field_dict["upload_id"] = upload_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        job_id = UUID(d.pop("job_id"))

        s3_key = d.pop("s3_key")

        urls = cast(list[str], d.pop("urls"))

        def _parse_part_size(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        part_size = _parse_part_size(d.pop("part_size", UNSET))

        def _parse_upload_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        upload_id = _parse_upload_id(d.pop("upload_id", UNSET))

        presigned_upload_response = cls(
            job_id=job_id,
            s3_key=s3_key,
            urls=urls,
            part_size=part_size,
            upload_id=upload_id,
        )

        presigned_upload_response.additional_properties = d
        return presigned_upload_response

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
