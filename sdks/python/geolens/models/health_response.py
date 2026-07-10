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
        providers (HealthResponseProviders):
        status (str):
        version (str):
        build (None | str | Unset):
    """

    providers: HealthResponseProviders
    status: str
    version: str
    build: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        providers = self.providers.to_dict()

        status = self.status

        version = self.version

        build: None | str | Unset
        if isinstance(self.build, Unset):
            build = UNSET
        else:
            build = self.build

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "providers": providers,
                "status": status,
                "version": version,
            }
        )
        if build is not UNSET:
            field_dict["build"] = build

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.health_response_providers import HealthResponseProviders

        d = dict(src_dict)
        providers = HealthResponseProviders.from_dict(d.pop("providers"))

        status = d.pop("status")

        version = d.pop("version")

        def _parse_build(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        build = _parse_build(d.pop("build", UNSET))

        health_response = cls(
            providers=providers,
            status=status,
            version=version,
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
