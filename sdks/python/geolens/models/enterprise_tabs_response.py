from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from typing import cast


T = TypeVar("T", bound="EnterpriseTabsResponse")


@_attrs_define
class EnterpriseTabsResponse:
    """Response for GET /settings/enterprise-tabs/.

    Canonical enterprise-only Settings tab keys (Phase 279 / ADMIN-03 / M-03).
    Read by the frontend AdminSidebar to decide which tabs to hide in
    community editions. The backend ``_require_enterprise_for_key`` gate
    consults the same source set, eliminating drift between the two
    sources of truth.

        Attributes:
            tabs (list[str]): Tab keys (e.g. 'branding', 'appearance') restricted to enterprise editions. Sorted
                alphabetically for stable client-side comparison.
    """

    tabs: list[str]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        tabs = self.tabs

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "tabs": tabs,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        tabs = cast(list[str], d.pop("tabs"))

        enterprise_tabs_response = cls(
            tabs=tabs,
        )

        enterprise_tabs_response.additional_properties = d
        return enterprise_tabs_response

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
