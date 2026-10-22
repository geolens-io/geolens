from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.service_auth_request import ServiceAuthRequest


T = TypeVar("T", bound="ServicePreviewRequest")


@_attrs_define
class ServicePreviewRequest:
    """
    Attributes:
        url (str): Normalized service URL from a previous probe response.
        service_type (str): Service type from the probe response, e.g. 'WFS 2.0.0' or 'ArcGIS FeatureServer'.
        layer_name (str): Name of the specific layer to preview, from the probe layers list.
        layer_title (None | str | Unset): Human-readable layer title from the probe LayerInfo.
        layer_id (int | None | str | Unset): ArcGIS layer ID, when applicable.
        token (None | str | Unset): Optional auth token for protected services. Deprecated: use the auth object with
            method bearer.
        object_id_field (None | str | Unset): ArcGIS OID field name used for orderByFields during preview pagination.
        auth (None | ServiceAuthRequest | Unset): Structured credential for a protected service. Mutually exclusive with
            the token field.
        item_id (None | str | Unset): ArcGIS portal item ID the layer was published from, at most 64 characters (longer
            is refused with 422). Stored as provenance when it is 32 hex characters, otherwise dropped and reported in
            origin_link_loss. Dropped for a non-ArcGIS service type.
        portal_url (None | str | Unset): ArcGIS portal address for the item link, at most 2048 characters (longer is
            refused with 422). Stored only when it is https and shares a registrable domain with the service URL, otherwise
            dropped and reported in origin_link_loss.
    """

    url: str
    service_type: str
    layer_name: str
    layer_title: None | str | Unset = UNSET
    layer_id: int | None | str | Unset = UNSET
    token: None | str | Unset = UNSET
    object_id_field: None | str | Unset = UNSET
    auth: None | ServiceAuthRequest | Unset = UNSET
    item_id: None | str | Unset = UNSET
    portal_url: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.service_auth_request import ServiceAuthRequest

        url = self.url

        service_type = self.service_type

        layer_name = self.layer_name

        layer_title: None | str | Unset
        if isinstance(self.layer_title, Unset):
            layer_title = UNSET
        else:
            layer_title = self.layer_title

        layer_id: int | None | str | Unset
        if isinstance(self.layer_id, Unset):
            layer_id = UNSET
        else:
            layer_id = self.layer_id

        token: None | str | Unset
        if isinstance(self.token, Unset):
            token = UNSET
        else:
            token = self.token

        object_id_field: None | str | Unset
        if isinstance(self.object_id_field, Unset):
            object_id_field = UNSET
        else:
            object_id_field = self.object_id_field

        auth: dict[str, Any] | None | Unset
        if isinstance(self.auth, Unset):
            auth = UNSET
        elif isinstance(self.auth, ServiceAuthRequest):
            auth = self.auth.to_dict()
        else:
            auth = self.auth

        item_id: None | str | Unset
        if isinstance(self.item_id, Unset):
            item_id = UNSET
        else:
            item_id = self.item_id

        portal_url: None | str | Unset
        if isinstance(self.portal_url, Unset):
            portal_url = UNSET
        else:
            portal_url = self.portal_url

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "url": url,
                "service_type": service_type,
                "layer_name": layer_name,
            }
        )
        if layer_title is not UNSET:
            field_dict["layer_title"] = layer_title
        if layer_id is not UNSET:
            field_dict["layer_id"] = layer_id
        if token is not UNSET:
            field_dict["token"] = token
        if object_id_field is not UNSET:
            field_dict["object_id_field"] = object_id_field
        if auth is not UNSET:
            field_dict["auth"] = auth
        if item_id is not UNSET:
            field_dict["item_id"] = item_id
        if portal_url is not UNSET:
            field_dict["portal_url"] = portal_url

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.service_auth_request import ServiceAuthRequest

        d = dict(src_dict)
        url = d.pop("url")

        service_type = d.pop("service_type")

        layer_name = d.pop("layer_name")

        def _parse_layer_title(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        layer_title = _parse_layer_title(d.pop("layer_title", UNSET))

        def _parse_layer_id(data: object) -> int | None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | str | Unset, data)

        layer_id = _parse_layer_id(d.pop("layer_id", UNSET))

        def _parse_token(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        token = _parse_token(d.pop("token", UNSET))

        def _parse_object_id_field(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        object_id_field = _parse_object_id_field(d.pop("object_id_field", UNSET))

        def _parse_auth(data: object) -> None | ServiceAuthRequest | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                auth_type_0 = ServiceAuthRequest.from_dict(data)

                return auth_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | ServiceAuthRequest | Unset, data)

        auth = _parse_auth(d.pop("auth", UNSET))

        def _parse_item_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        item_id = _parse_item_id(d.pop("item_id", UNSET))

        def _parse_portal_url(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        portal_url = _parse_portal_url(d.pop("portal_url", UNSET))

        service_preview_request = cls(
            url=url,
            service_type=service_type,
            layer_name=layer_name,
            layer_title=layer_title,
            layer_id=layer_id,
            token=token,
            object_id_field=object_id_field,
            auth=auth,
            item_id=item_id,
            portal_url=portal_url,
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
