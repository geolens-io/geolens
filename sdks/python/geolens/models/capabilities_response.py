from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from typing import cast

if TYPE_CHECKING:
    from ..models.capabilities_auth import CapabilitiesAuth
    from ..models.capabilities_basemap import CapabilitiesBasemap
    from ..models.capabilities_me import CapabilitiesMe
    from ..models.capabilities_rate_limits import CapabilitiesRateLimits
    from ..models.capabilities_server import CapabilitiesServer
    from ..models.capabilities_upload import CapabilitiesUpload
    from ..models.feature_flags_response import FeatureFlagsResponse


T = TypeVar("T", bound="CapabilitiesResponse")


@_attrs_define
class CapabilitiesResponse:
    """
    Attributes:
        server (CapabilitiesServer):
        publish_contract (int): Version of the publish contract the server speaks.
        auth (CapabilitiesAuth):
        upload (CapabilitiesUpload | None): Upload limits. Present only with credentials.
        basemaps (list[CapabilitiesBasemap]): Enabled basemaps whose provider key, if any, is configured.
        flags (FeatureFlagsResponse): Public feature flags readable by any authenticated user.
        status_order (list[str]): Dataset workflow statuses, from first to last.
        rate_limits (CapabilitiesRateLimits):
        me (CapabilitiesMe | None): The caller's account. Present only with credentials.
    """

    server: CapabilitiesServer
    publish_contract: int
    auth: CapabilitiesAuth
    upload: CapabilitiesUpload | None
    basemaps: list[CapabilitiesBasemap]
    flags: FeatureFlagsResponse
    status_order: list[str]
    rate_limits: CapabilitiesRateLimits
    me: CapabilitiesMe | None
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.capabilities_me import CapabilitiesMe
        from ..models.capabilities_upload import CapabilitiesUpload

        server = self.server.to_dict()

        publish_contract = self.publish_contract

        auth = self.auth.to_dict()

        upload: dict[str, Any] | None
        if isinstance(self.upload, CapabilitiesUpload):
            upload = self.upload.to_dict()
        else:
            upload = self.upload

        basemaps = []
        for basemaps_item_data in self.basemaps:
            basemaps_item = basemaps_item_data.to_dict()
            basemaps.append(basemaps_item)

        flags = self.flags.to_dict()

        status_order = self.status_order

        rate_limits = self.rate_limits.to_dict()

        me: dict[str, Any] | None
        if isinstance(self.me, CapabilitiesMe):
            me = self.me.to_dict()
        else:
            me = self.me

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "server": server,
                "publish_contract": publish_contract,
                "auth": auth,
                "upload": upload,
                "basemaps": basemaps,
                "flags": flags,
                "status_order": status_order,
                "rate_limits": rate_limits,
                "me": me,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.capabilities_auth import CapabilitiesAuth
        from ..models.capabilities_basemap import CapabilitiesBasemap
        from ..models.capabilities_me import CapabilitiesMe
        from ..models.capabilities_rate_limits import CapabilitiesRateLimits
        from ..models.capabilities_server import CapabilitiesServer
        from ..models.capabilities_upload import CapabilitiesUpload
        from ..models.feature_flags_response import FeatureFlagsResponse

        d = dict(src_dict)
        server = CapabilitiesServer.from_dict(d.pop("server"))

        publish_contract = d.pop("publish_contract")

        auth = CapabilitiesAuth.from_dict(d.pop("auth"))

        def _parse_upload(data: object) -> CapabilitiesUpload | None:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                upload_type_0 = CapabilitiesUpload.from_dict(data)

                return upload_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(CapabilitiesUpload | None, data)

        upload = _parse_upload(d.pop("upload"))

        basemaps = []
        _basemaps = d.pop("basemaps")
        for basemaps_item_data in _basemaps:
            basemaps_item = CapabilitiesBasemap.from_dict(basemaps_item_data)

            basemaps.append(basemaps_item)

        flags = FeatureFlagsResponse.from_dict(d.pop("flags"))

        status_order = cast(list[str], d.pop("status_order"))

        rate_limits = CapabilitiesRateLimits.from_dict(d.pop("rate_limits"))

        def _parse_me(data: object) -> CapabilitiesMe | None:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                me_type_0 = CapabilitiesMe.from_dict(data)

                return me_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(CapabilitiesMe | None, data)

        me = _parse_me(d.pop("me"))

        capabilities_response = cls(
            server=server,
            publish_contract=publish_contract,
            auth=auth,
            upload=upload,
            basemaps=basemaps,
            flags=flags,
            status_order=status_order,
            rate_limits=rate_limits,
            me=me,
        )

        capabilities_response.additional_properties = d
        return capabilities_response

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
