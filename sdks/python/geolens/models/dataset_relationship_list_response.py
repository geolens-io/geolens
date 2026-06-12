from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.dataset_relationship_response import DatasetRelationshipResponse


T = TypeVar("T", bound="DatasetRelationshipListResponse")


@_attrs_define
class DatasetRelationshipListResponse:
    """Paginated list envelope for dataset FK relationships (GAP-033).

    Mirrors the ``{<entity>: [...], total: int}`` convention used by every other
    paginated list endpoint (e.g. AttributeMetadataListResponse,
    VrtGenerationListResponse) so callers can detect whether more pages exist.
    ``total`` is the count of *visible* relationships before skip/limit.

        Attributes:
            relationships (list[DatasetRelationshipResponse]):
            total (int):
    """

    relationships: list[DatasetRelationshipResponse]
    total: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        relationships = []
        for relationships_item_data in self.relationships:
            relationships_item = relationships_item_data.to_dict()
            relationships.append(relationships_item)

        total = self.total

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "relationships": relationships,
                "total": total,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.dataset_relationship_response import DatasetRelationshipResponse

        d = dict(src_dict)
        relationships = []
        _relationships = d.pop("relationships")
        for relationships_item_data in _relationships:
            relationships_item = DatasetRelationshipResponse.from_dict(
                relationships_item_data
            )

            relationships.append(relationships_item)

        total = d.pop("total")

        dataset_relationship_list_response = cls(
            relationships=relationships,
            total=total,
        )

        dataset_relationship_list_response.additional_properties = d
        return dataset_relationship_list_response

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
