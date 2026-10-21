from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from typing import cast

if TYPE_CHECKING:
    from ..models.capabilities_key import CapabilitiesKey


T = TypeVar("T", bound="CapabilitiesMe")


@_attrs_define
class CapabilitiesMe:
    """
    Attributes:
        username (str): Signed-in account.
        permissions (list[str]): Capabilities the account holds.
        key (CapabilitiesKey | None): Present only when the request authenticated with an API key.
        remaining_dataset_quota (int | None): Datasets the account can still create, or null when uncapped.
    """

    username: str
    permissions: list[str]
    key: CapabilitiesKey | None
    remaining_dataset_quota: int | None
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.capabilities_key import CapabilitiesKey

        username = self.username

        permissions = self.permissions

        key: dict[str, Any] | None
        if isinstance(self.key, CapabilitiesKey):
            key = self.key.to_dict()
        else:
            key = self.key

        remaining_dataset_quota: int | None
        remaining_dataset_quota = self.remaining_dataset_quota

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "username": username,
                "permissions": permissions,
                "key": key,
                "remaining_dataset_quota": remaining_dataset_quota,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.capabilities_key import CapabilitiesKey

        d = dict(src_dict)
        username = d.pop("username")

        permissions = cast(list[str], d.pop("permissions"))

        def _parse_key(data: object) -> CapabilitiesKey | None:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                key_type_0 = CapabilitiesKey.from_dict(data)

                return key_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(CapabilitiesKey | None, data)

        key = _parse_key(d.pop("key"))

        def _parse_remaining_dataset_quota(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        remaining_dataset_quota = _parse_remaining_dataset_quota(
            d.pop("remaining_dataset_quota")
        )

        capabilities_me = cls(
            username=username,
            permissions=permissions,
            key=key,
            remaining_dataset_quota=remaining_dataset_quota,
        )

        capabilities_me.additional_properties = d
        return capabilities_me

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
