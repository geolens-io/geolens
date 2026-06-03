from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


T = TypeVar("T", bound="ThumbnailUploadRequest")


@_attrs_define
class ThumbnailUploadRequest:
    """JSON body for PUT /maps/{map_id}/thumbnail/.

    Replaces a previous text/plain body shape that openapi-python-client
    could not parse (would silently skip endpoint). See Phase 254 / SDK-01.

    Phase 254 IN-02: ``data_uri`` carries explicit length bounds so
    Pydantic surfaces a 422 with field-level detail (better SDK-consumer
    UX than a generic 400) and the OpenAPI schema documents the limit.
    The router still validates the ``data:image/`` prefix and base64
    encoding; those are content-shape checks Pydantic length cannot
    cover.

    - ``min_length=22``: a minimal valid prefix is ``data:image/x;base64,``
      (20 chars) plus at least one payload byte (e.g.,
      ``data:image/x;base64,XX``). Use 22 as a pragmatic floor that
      rejects empty / clearly-malformed values without false-positives
      on the smallest legitimate payloads.
    - ``max_length=100_000``: matches the previous router-side 100KB cap.

        Attributes:
            data_uri (str):
    """

    data_uri: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data_uri = self.data_uri

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "data_uri": data_uri,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        data_uri = d.pop("data_uri")

        thumbnail_upload_request = cls(
            data_uri=data_uri,
        )

        thumbnail_upload_request.additional_properties = d
        return thumbnail_upload_request

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
