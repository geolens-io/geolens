from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="RelatedDatasetItem")


@_attrs_define
class RelatedDatasetItem:
    """
    Attributes:
        geometry_type (None | str):
        id (str):
        name (str):
        similarity (float): Cosine similarity score (0-1)
        band_count (int | None | Unset):
        feature_count (int | None | Unset):
        record_type (None | str | Unset):
    """

    geometry_type: None | str
    id: str
    name: str
    similarity: float
    band_count: int | None | Unset = UNSET
    feature_count: int | None | Unset = UNSET
    record_type: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        geometry_type: None | str
        geometry_type = self.geometry_type

        id = self.id

        name = self.name

        similarity = self.similarity

        band_count: int | None | Unset
        if isinstance(self.band_count, Unset):
            band_count = UNSET
        else:
            band_count = self.band_count

        feature_count: int | None | Unset
        if isinstance(self.feature_count, Unset):
            feature_count = UNSET
        else:
            feature_count = self.feature_count

        record_type: None | str | Unset
        if isinstance(self.record_type, Unset):
            record_type = UNSET
        else:
            record_type = self.record_type

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "geometry_type": geometry_type,
                "id": id,
                "name": name,
                "similarity": similarity,
            }
        )
        if band_count is not UNSET:
            field_dict["band_count"] = band_count
        if feature_count is not UNSET:
            field_dict["feature_count"] = feature_count
        if record_type is not UNSET:
            field_dict["record_type"] = record_type

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_geometry_type(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        geometry_type = _parse_geometry_type(d.pop("geometry_type"))

        id = d.pop("id")

        name = d.pop("name")

        similarity = d.pop("similarity")

        def _parse_band_count(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        band_count = _parse_band_count(d.pop("band_count", UNSET))

        def _parse_feature_count(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        feature_count = _parse_feature_count(d.pop("feature_count", UNSET))

        def _parse_record_type(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        record_type = _parse_record_type(d.pop("record_type", UNSET))

        related_dataset_item = cls(
            geometry_type=geometry_type,
            id=id,
            name=name,
            similarity=similarity,
            band_count=band_count,
            feature_count=feature_count,
            record_type=record_type,
        )

        related_dataset_item.additional_properties = d
        return related_dataset_item

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
