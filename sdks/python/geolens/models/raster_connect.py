from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="RasterConnect")


@_attrs_define
class RasterConnect:
    """
    Attributes:
        tile_url (str): Titiler tile endpoint for this raster
        download_url (None | str | Unset): Direct file download URL
        s3_uri (None | str | Unset): S3 object URI, e.g. s3://bucket/key.tif
    """

    tile_url: str
    download_url: None | str | Unset = UNSET
    s3_uri: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        tile_url = self.tile_url

        download_url: None | str | Unset
        if isinstance(self.download_url, Unset):
            download_url = UNSET
        else:
            download_url = self.download_url

        s3_uri: None | str | Unset
        if isinstance(self.s3_uri, Unset):
            s3_uri = UNSET
        else:
            s3_uri = self.s3_uri

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "tile_url": tile_url,
            }
        )
        if download_url is not UNSET:
            field_dict["download_url"] = download_url
        if s3_uri is not UNSET:
            field_dict["s3_uri"] = s3_uri

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        tile_url = d.pop("tile_url")

        def _parse_download_url(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        download_url = _parse_download_url(d.pop("download_url", UNSET))

        def _parse_s3_uri(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        s3_uri = _parse_s3_uri(d.pop("s3_uri", UNSET))

        raster_connect = cls(
            tile_url=tile_url,
            download_url=download_url,
            s3_uri=s3_uri,
        )

        raster_connect.additional_properties = d
        return raster_connect

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
