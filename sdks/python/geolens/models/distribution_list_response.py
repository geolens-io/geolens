from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.distribution_response import DistributionResponse


T = TypeVar("T", bound="DistributionListResponse")


@_attrs_define
class DistributionListResponse:
    """
    Attributes:
        distributions (list[DistributionResponse]):
        total (int):
    """

    distributions: list[DistributionResponse]
    total: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        distributions = []
        for distributions_item_data in self.distributions:
            distributions_item = distributions_item_data.to_dict()
            distributions.append(distributions_item)

        total = self.total

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "distributions": distributions,
                "total": total,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.distribution_response import DistributionResponse

        d = dict(src_dict)
        distributions = []
        _distributions = d.pop("distributions")
        for distributions_item_data in _distributions:
            distributions_item = DistributionResponse.from_dict(distributions_item_data)

            distributions.append(distributions_item)

        total = d.pop("total")

        distribution_list_response = cls(
            distributions=distributions,
            total=total,
        )

        distribution_list_response.additional_properties = d
        return distribution_list_response

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
