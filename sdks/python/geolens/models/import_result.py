from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="ImportResult")


@_attrs_define
class ImportResult:
    """Summary of what was applied during an import.

    Attributes:
        settings_applied (int): Number of settings successfully updated.
        settings_skipped (int): Number of settings skipped (no change, unknown key, or restricted key not writable by
            the current runtime).
        oauth_created (int): Number of new OAuth providers created.
        oauth_updated (int): Number of existing OAuth providers updated.
        oauth_deleted (int): Number of OAuth providers deleted (overwrite mode only).
        settings_skipped_restricted (list[str] | Unset): Names of restricted setting keys that were skipped by the
            current runtime.
        oauth_accounts_deleted (int | Unset): Number of dependent OAuth account links cascade-deleted in overwrite mode.
            Default: 0.
    """

    settings_applied: int
    settings_skipped: int
    oauth_created: int
    oauth_updated: int
    oauth_deleted: int
    settings_skipped_restricted: list[str] | Unset = UNSET
    oauth_accounts_deleted: int | Unset = 0
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        settings_applied = self.settings_applied

        settings_skipped = self.settings_skipped

        oauth_created = self.oauth_created

        oauth_updated = self.oauth_updated

        oauth_deleted = self.oauth_deleted

        settings_skipped_restricted: list[str] | Unset = UNSET
        if not isinstance(self.settings_skipped_restricted, Unset):
            settings_skipped_restricted = self.settings_skipped_restricted

        oauth_accounts_deleted = self.oauth_accounts_deleted

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "settings_applied": settings_applied,
                "settings_skipped": settings_skipped,
                "oauth_created": oauth_created,
                "oauth_updated": oauth_updated,
                "oauth_deleted": oauth_deleted,
            }
        )
        if settings_skipped_restricted is not UNSET:
            field_dict["settings_skipped_restricted"] = settings_skipped_restricted
        if oauth_accounts_deleted is not UNSET:
            field_dict["oauth_accounts_deleted"] = oauth_accounts_deleted

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        settings_applied = d.pop("settings_applied")

        settings_skipped = d.pop("settings_skipped")

        oauth_created = d.pop("oauth_created")

        oauth_updated = d.pop("oauth_updated")

        oauth_deleted = d.pop("oauth_deleted")

        settings_skipped_restricted = cast(
            list[str], d.pop("settings_skipped_restricted", UNSET)
        )

        oauth_accounts_deleted = d.pop("oauth_accounts_deleted", UNSET)

        import_result = cls(
            settings_applied=settings_applied,
            settings_skipped=settings_skipped,
            oauth_created=oauth_created,
            oauth_updated=oauth_updated,
            oauth_deleted=oauth_deleted,
            settings_skipped_restricted=settings_skipped_restricted,
            oauth_accounts_deleted=oauth_accounts_deleted,
        )

        import_result.additional_properties = d
        return import_result

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
