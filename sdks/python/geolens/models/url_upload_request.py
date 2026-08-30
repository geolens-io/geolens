from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="UrlUploadRequest")


@_attrs_define
class UrlUploadRequest:
    """Request body for the URL variant of upload (feat #1705).

    The server fetches the file itself (SSRF-validated, size-capped) and
    stages it exactly like a direct upload — preview and commit take over
    unchanged.

        Attributes:
            url (str): HTTP(S) URL of the file to import. The server validates the URL against SSRF, downloads it with the
                configured size cap, and stages it like a direct upload.
            filename (None | str | Unset): Filename override for URLs whose path does not end in the actual file name (e.g.
                download links keyed by query id). Must carry an allowed extension. Defaults to the URL path's basename.
    """

    url: str
    filename: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        url = self.url

        filename: None | str | Unset
        if isinstance(self.filename, Unset):
            filename = UNSET
        else:
            filename = self.filename

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "url": url,
            }
        )
        if filename is not UNSET:
            field_dict["filename"] = filename

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        url = d.pop("url")

        def _parse_filename(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        filename = _parse_filename(d.pop("filename", UNSET))

        url_upload_request = cls(
            url=url,
            filename=filename,
        )

        url_upload_request.additional_properties = d
        return url_upload_request

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
