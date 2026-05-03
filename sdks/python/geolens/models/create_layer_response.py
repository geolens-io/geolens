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
        created_at (datetime.datetime): Creation timestamp
        feature_count (int): Number of features (0 for new layers)
        geometry_type (str): OGC geometry type
        id (UUID): Dataset ID of the created layer
        table_name (str): PostGIS table name in the data schema
        title (str): Display name
        visibility (str): Visibility level: private, internal, or public
    """

    created_at: datetime.datetime
    feature_count: int
    geometry_type: str
    id: UUID
    table_name: str
    title: str
    visibility: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        created_at = self.created_at.isoformat()

        feature_count = self.feature_count

        geometry_type = self.geometry_type

        id = str(self.id)

        table_name = self.table_name

        title = self.title

        visibility = self.visibility

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "created_at": created_at,
                "feature_count": feature_count,
                "geometry_type": geometry_type,
                "id": id,
                "table_name": table_name,
                "title": title,
                "visibility": visibility,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        created_at = isoparse(d.pop("created_at"))

        feature_count = d.pop("feature_count")

        geometry_type = d.pop("geometry_type")

        id = UUID(d.pop("id"))

        table_name = d.pop("table_name")

        title = d.pop("title")

        visibility = d.pop("visibility")

        create_layer_response = cls(
            created_at=created_at,
            feature_count=feature_count,
            geometry_type=geometry_type,
            id=id,
            table_name=table_name,
            title=title,
            visibility=visibility,
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
