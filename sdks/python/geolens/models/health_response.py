from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.health_response_providers import HealthResponseProviders


T = TypeVar("T", bound="HealthResponse")


@_attrs_define
class HealthResponse:
    """
    Attributes:
        status (str):
        version (str):
        providers (HealthResponseProviders):
        build (None | str | Unset):
    """

    status: str
    version: str
    providers: HealthResponseProviders
    build: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        status = self.status

        version = self.version

        providers = self.providers.to_dict()

        build: None | str | Unset
        if isinstance(self.build, Unset):
            build = UNSET
        else:
            build = self.build

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "status": status,
                "version": version,
                "providers": providers,
            }
        )
        if build is not UNSET:
            field_dict["build"] = build

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.health_response_providers import HealthResponseProviders

        d = dict(src_dict)
        status = d.pop("status")

        version = d.pop("version")

        providers = HealthResponseProviders.from_dict(d.pop("providers"))

        def _parse_build(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        build = _parse_build(d.pop("build", UNSET))

        health_response = cls(
            status=status,
            version=version,
            providers=providers,
            build=build,
        )

        health_response.additional_properties = d
        return health_response

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
