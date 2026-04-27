from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="ServicePreviewRequest")


@_attrs_define
class ServicePreviewRequest:
    """
    Attributes:
        layer_name (str): Name of the specific layer to preview, from the probe layers list.
        service_type (str): Service type from the probe response, e.g. 'WFS 2.0.0' or 'ArcGIS FeatureServer'.
        url (str): Normalized service URL from a previous probe response.
        layer_id (int | None | str | Unset): ArcGIS layer ID, when applicable.
        layer_title (None | str | Unset): Human-readable layer title from the probe LayerInfo.
        object_id_field (None | str | Unset): ArcGIS OID field name used for orderByFields during preview pagination.
        token (None | str | Unset): Optional auth token for protected services.
    """

    layer_name: str
    service_type: str
    url: str
    layer_id: int | None | str | Unset = UNSET
    layer_title: None | str | Unset = UNSET
    object_id_field: None | str | Unset = UNSET
    token: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        layer_name = self.layer_name

        service_type = self.service_type

        url = self.url

        layer_id: int | None | str | Unset
        if isinstance(self.layer_id, Unset):
            layer_id = UNSET
        else:
            layer_id = self.layer_id

        layer_title: None | str | Unset
        if isinstance(self.layer_title, Unset):
            layer_title = UNSET
        else:
            layer_title = self.layer_title

        object_id_field: None | str | Unset
        if isinstance(self.object_id_field, Unset):
            object_id_field = UNSET
        else:
            object_id_field = self.object_id_field

        token: None | str | Unset
        if isinstance(self.token, Unset):
            token = UNSET
        else:
            token = self.token

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "layer_name": layer_name,
                "service_type": service_type,
                "url": url,
            }
        )
        if layer_id is not UNSET:
            field_dict["layer_id"] = layer_id
        if layer_title is not UNSET:
            field_dict["layer_title"] = layer_title
        if object_id_field is not UNSET:
            field_dict["object_id_field"] = object_id_field
        if token is not UNSET:
            field_dict["token"] = token

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        layer_name = d.pop("layer_name")

        service_type = d.pop("service_type")

        url = d.pop("url")

        def _parse_layer_id(data: object) -> int | None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | str | Unset, data)

        layer_id = _parse_layer_id(d.pop("layer_id", UNSET))

        def _parse_layer_title(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        layer_title = _parse_layer_title(d.pop("layer_title", UNSET))

        def _parse_object_id_field(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        object_id_field = _parse_object_id_field(d.pop("object_id_field", UNSET))

        def _parse_token(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        token = _parse_token(d.pop("token", UNSET))

        service_preview_request = cls(
            layer_name=layer_name,
            service_type=service_type,
            url=url,
            layer_id=layer_id,
            layer_title=layer_title,
            object_id_field=object_id_field,
            token=token,
        )

        service_preview_request.additional_properties = d
        return service_preview_request

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
