from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from dateutil.parser import isoparse
from uuid import UUID
import datetime


T = TypeVar("T", bound="CreateLayerResponse")


@_attrs_define
class CreateLayerResponse:
    """
    Attributes:
        id (UUID): Dataset ID of the created layer
        title (str): Display name
        table_name (str): PostGIS table name in the data schema
        geometry_type (str): OGC geometry type
        feature_count (int): Number of features (0 for new layers)
        visibility (str): Visibility level: private, internal, or public
        created_at (datetime.datetime): Creation timestamp
    """

    id: UUID
    title: str
    table_name: str
    geometry_type: str
    feature_count: int
    visibility: str
    created_at: datetime.datetime
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = str(self.id)

        title = self.title

        table_name = self.table_name

        geometry_type = self.geometry_type

        feature_count = self.feature_count

        visibility = self.visibility

        created_at = self.created_at.isoformat()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "title": title,
                "table_name": table_name,
                "geometry_type": geometry_type,
                "feature_count": feature_count,
                "visibility": visibility,
                "created_at": created_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = UUID(d.pop("id"))

        title = d.pop("title")

        table_name = d.pop("table_name")

        geometry_type = d.pop("geometry_type")

        feature_count = d.pop("feature_count")

        visibility = d.pop("visibility")

        created_at = isoparse(d.pop("created_at"))

        create_layer_response = cls(
            id=id,
            title=title,
            table_name=table_name,
            geometry_type=geometry_type,
            feature_count=feature_count,
            visibility=visibility,
            created_at=created_at,
        )

        create_layer_response.additional_properties = d
        return create_layer_response

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
