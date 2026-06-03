from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.manifest_contact import ManifestContact


T = TypeVar("T", bound="ManifestCatalog")


@_attrs_define
class ManifestCatalog:
    """
    Attributes:
        title (str):
        contact (ManifestContact | None | Unset):
        description (None | str | Unset):
        organization (None | str | Unset):
    """

    title: str
    contact: ManifestContact | None | Unset = UNSET
    description: None | str | Unset = UNSET
    organization: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.manifest_contact import ManifestContact

        title = self.title

        contact: dict[str, Any] | None | Unset
        if isinstance(self.contact, Unset):
            contact = UNSET
        elif isinstance(self.contact, ManifestContact):
            contact = self.contact.to_dict()
        else:
            contact = self.contact

        description: None | str | Unset
        if isinstance(self.description, Unset):
            description = UNSET
        else:
            description = self.description

        organization: None | str | Unset
        if isinstance(self.organization, Unset):
            organization = UNSET
        else:
            organization = self.organization

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "title": title,
            }
        )
        if contact is not UNSET:
            field_dict["contact"] = contact
        if description is not UNSET:
            field_dict["description"] = description
        if organization is not UNSET:
            field_dict["organization"] = organization

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.manifest_contact import ManifestContact

        d = dict(src_dict)
        title = d.pop("title")

        def _parse_contact(data: object) -> ManifestContact | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                contact_type_0 = ManifestContact.from_dict(data)

                return contact_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ManifestContact | None | Unset, data)

        contact = _parse_contact(d.pop("contact", UNSET))

        def _parse_description(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        description = _parse_description(d.pop("description", UNSET))

        def _parse_organization(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        organization = _parse_organization(d.pop("organization", UNSET))

        manifest_catalog = cls(
            title=title,
            contact=contact,
            description=description,
            organization=organization,
        )

        return manifest_catalog
