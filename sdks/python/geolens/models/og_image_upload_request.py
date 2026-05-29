from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


T = TypeVar("T", bound="OgImageUploadRequest")


@_attrs_define
class OgImageUploadRequest:
    """JSON body for PUT /maps/{map_id}/og-image/ (SHARE-08 Path A).

    Accepts a base64 data URI up to 750 KB (as a string). This generous
    ceiling accommodates a 1200x630 JPEG at quality 0.85, which encodes
    to roughly 150-400 KB raw and ~200-540 KB as a base64 string.

    - ``min_length=22``: same floor as ThumbnailUploadRequest — rejects
      empty/clearly-malformed URIs without false-positives.
    - ``max_length=750_000``: ~562 KB decoded — generous for 1200x630 JPEG.
      DO NOT raise ThumbnailUploadRequest.max_length to match this value;
      the 100KB thumbnail cap is a locked contract (Phase 254 / D-03).

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

        og_image_upload_request = cls(
            data_uri=data_uri,
        )

        og_image_upload_request.additional_properties = d
        return og_image_upload_request

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
