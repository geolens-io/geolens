from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


T = TypeVar("T", bound="ArcGISSignInRequest")


@_attrs_define
class ArcGISSignInRequest:
    """Portal address plus the credentials one generateToken call needs.

    No character policy on the two credential fields, deliberately. They are
    form-encoded into the outbound body, which percent-escapes every value,
    so neither a control character nor a separator can smuggle a second field
    into the request the way one can into a header line. The length bounds
    are here to keep an absurd body from reaching the portal at all.

        Attributes:
            portal_url (str): ArcGIS portal URL, for example https://your-org.maps.arcgis.com. The /sharing/rest base is
                accepted too.
            username (str): ArcGIS account name to sign in with.
            password (str): Password for that ArcGIS account.
    """

    portal_url: str
    username: str
    password: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        portal_url = self.portal_url

        username = self.username

        password = self.password

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "portal_url": portal_url,
                "username": username,
                "password": password,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        portal_url = d.pop("portal_url")

        username = d.pop("username")

        password = d.pop("password")

        arc_gis_sign_in_request = cls(
            portal_url=portal_url,
            username=username,
            password=password,
        )

        arc_gis_sign_in_request.additional_properties = d
        return arc_gis_sign_in_request

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
