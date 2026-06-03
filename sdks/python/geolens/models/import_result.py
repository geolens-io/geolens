from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


T = TypeVar("T", bound="ImportResult")


@_attrs_define
class ImportResult:
    """Summary of what was applied during an import.

    Attributes:
        oauth_created (int): Number of new OAuth providers created.
        oauth_deleted (int): Number of OAuth providers deleted (overwrite mode only).
        oauth_updated (int): Number of existing OAuth providers updated.
        settings_applied (int): Number of settings successfully updated.
        settings_skipped (int): Number of settings skipped (no change or unknown key).
    """

    oauth_created: int
    oauth_deleted: int
    oauth_updated: int
    settings_applied: int
    settings_skipped: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        oauth_created = self.oauth_created

        oauth_deleted = self.oauth_deleted

        oauth_updated = self.oauth_updated

        settings_applied = self.settings_applied

        settings_skipped = self.settings_skipped

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "oauth_created": oauth_created,
                "oauth_deleted": oauth_deleted,
                "oauth_updated": oauth_updated,
                "settings_applied": settings_applied,
                "settings_skipped": settings_skipped,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        oauth_created = d.pop("oauth_created")

        oauth_deleted = d.pop("oauth_deleted")

        oauth_updated = d.pop("oauth_updated")

        settings_applied = d.pop("settings_applied")

        settings_skipped = d.pop("settings_skipped")

        import_result = cls(
            oauth_created=oauth_created,
            oauth_deleted=oauth_deleted,
            oauth_updated=oauth_updated,
            settings_applied=settings_applied,
            settings_skipped=settings_skipped,
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
