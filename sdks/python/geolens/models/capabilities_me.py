from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.capabilities_database_connection import CapabilitiesDatabaseConnection
    from ..models.capabilities_key import CapabilitiesKey
    from ..models.group_ref import GroupRef


T = TypeVar("T", bound="CapabilitiesMe")


@_attrs_define
class CapabilitiesMe:
    """
    Attributes:
        username (str): Signed-in account.
        permissions (list[str]): Capabilities the account holds.
        key (CapabilitiesKey | None): Present only when the request authenticated with an API key.
        remaining_dataset_quota (int | None): Datasets the account can still create, or null when uncapped.
        database_connections (list[CapabilitiesDatabaseConnection] | Unset): Database connections the deployment
            configures, listed only for an account that can create datasets.
        groups (list[GroupRef] | Unset): The sharing groups the account may share with, by name: the ones it belongs to,
            or every group for an admin. A publish key shares as its owner without the admin role. The ids go in a publish
            manifest's `groups`.
    """

    username: str
    permissions: list[str]
    key: CapabilitiesKey | None
    remaining_dataset_quota: int | None
    database_connections: list[CapabilitiesDatabaseConnection] | Unset = UNSET
    groups: list[GroupRef] | Unset = UNSET
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

        database_connections: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.database_connections, Unset):
            database_connections = []
            for database_connections_item_data in self.database_connections:
                database_connections_item = database_connections_item_data.to_dict()
                database_connections.append(database_connections_item)

        groups: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.groups, Unset):
            groups = []
            for groups_item_data in self.groups:
                groups_item = groups_item_data.to_dict()
                groups.append(groups_item)

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
        if database_connections is not UNSET:
            field_dict["database_connections"] = database_connections
        if groups is not UNSET:
            field_dict["groups"] = groups

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.capabilities_database_connection import (
            CapabilitiesDatabaseConnection,
        )
        from ..models.capabilities_key import CapabilitiesKey
        from ..models.group_ref import GroupRef

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

        _database_connections = d.pop("database_connections", UNSET)
        database_connections: list[CapabilitiesDatabaseConnection] | Unset = UNSET
        if _database_connections is not UNSET:
            database_connections = []
            for database_connections_item_data in _database_connections:
                database_connections_item = CapabilitiesDatabaseConnection.from_dict(
                    database_connections_item_data
                )

                database_connections.append(database_connections_item)

        _groups = d.pop("groups", UNSET)
        groups: list[GroupRef] | Unset = UNSET
        if _groups is not UNSET:
            groups = []
            for groups_item_data in _groups:
                groups_item = GroupRef.from_dict(groups_item_data)

                groups.append(groups_item)

        capabilities_me = cls(
            username=username,
            permissions=permissions,
            key=key,
            remaining_dataset_quota=remaining_dataset_quota,
            database_connections=database_connections,
            groups=groups,
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
