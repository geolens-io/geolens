from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.layer_info_kind import check_layer_info_kind
from ..models.layer_info_kind import LayerInfoKind
from typing import cast


T = TypeVar("T", bound="LayerInfo")


@_attrs_define
class LayerInfo:
    """
    Attributes:
        name (str): Internal layer identifier used by the source service.
        title (None | str | Unset): Human-readable layer title from the service capabilities.
        geometry_type (None | str | Unset): Detected geometry type for the layer.
        feature_count (int | None | Unset): Total feature count if reported by the service.
        layer_type (str | Unset): Layer kind: 'layer' (spatial) or 'table' (non-spatial attribute table). Default:
            'layer'.
        source_layer_type (None | str | Unset): ArcGIS sub-layer type as the service reports it, for example 'Feature
            Layer', 'Table', 'Group Layer', 'Raster Layer' or 'Annotation Layer'. Null for other service types.
        parent_layer_id (int | None | Unset): ArcGIS ID of the group layer that contains this layer, if any.
        importable (bool | Unset): False when the layer holds no features (ArcGIS composite, raster and annotation
            layers) and a preview of it is refused with 'unsupported_layer_type'. Default: True.
        layer_id (int | None | str | Unset): Numeric or string layer ID used by ArcGIS services.
        object_id_field (None | str | Unset): ArcGIS object ID field name, used for stable pagination.
        kind (LayerInfoKind | Unset): Backend-classified layer kind. 'vector' = point/line/polygon feature data.
            'raster' = imagery/coverage. Classified as 'raster' when geometry_type contains 'raster', the adapter is STAC,
            the layer declares coverage_format or bands, or one of its links has a media type of image/*. Everything else,
            including a layer with no geometry_type at all, defaults to 'vector'. Default: 'vector'.
    """

    name: str
    title: None | str | Unset = UNSET
    geometry_type: None | str | Unset = UNSET
    feature_count: int | None | Unset = UNSET
    layer_type: str | Unset = "layer"
    source_layer_type: None | str | Unset = UNSET
    parent_layer_id: int | None | Unset = UNSET
    importable: bool | Unset = True
    layer_id: int | None | str | Unset = UNSET
    object_id_field: None | str | Unset = UNSET
    kind: LayerInfoKind | Unset = "vector"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        name = self.name

        title: None | str | Unset
        if isinstance(self.title, Unset):
            title = UNSET
        else:
            title = self.title

        geometry_type: None | str | Unset
        if isinstance(self.geometry_type, Unset):
            geometry_type = UNSET
        else:
            geometry_type = self.geometry_type

        feature_count: int | None | Unset
        if isinstance(self.feature_count, Unset):
            feature_count = UNSET
        else:
            feature_count = self.feature_count

        layer_type = self.layer_type

        source_layer_type: None | str | Unset
        if isinstance(self.source_layer_type, Unset):
            source_layer_type = UNSET
        else:
            source_layer_type = self.source_layer_type

        parent_layer_id: int | None | Unset
        if isinstance(self.parent_layer_id, Unset):
            parent_layer_id = UNSET
        else:
            parent_layer_id = self.parent_layer_id

        importable = self.importable

        layer_id: int | None | str | Unset
        if isinstance(self.layer_id, Unset):
            layer_id = UNSET
        else:
            layer_id = self.layer_id

        object_id_field: None | str | Unset
        if isinstance(self.object_id_field, Unset):
            object_id_field = UNSET
        else:
            object_id_field = self.object_id_field

        kind: str | Unset = UNSET
        if not isinstance(self.kind, Unset):
            kind = self.kind

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "name": name,
            }
        )
        if title is not UNSET:
            field_dict["title"] = title
        if geometry_type is not UNSET:
            field_dict["geometry_type"] = geometry_type
        if feature_count is not UNSET:
            field_dict["feature_count"] = feature_count
        if layer_type is not UNSET:
            field_dict["layer_type"] = layer_type
        if source_layer_type is not UNSET:
            field_dict["source_layer_type"] = source_layer_type
        if parent_layer_id is not UNSET:
            field_dict["parent_layer_id"] = parent_layer_id
        if importable is not UNSET:
            field_dict["importable"] = importable
        if layer_id is not UNSET:
            field_dict["layer_id"] = layer_id
        if object_id_field is not UNSET:
            field_dict["object_id_field"] = object_id_field
        if kind is not UNSET:
            field_dict["kind"] = kind

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        name = d.pop("name")

        def _parse_title(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        title = _parse_title(d.pop("title", UNSET))

        def _parse_geometry_type(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        geometry_type = _parse_geometry_type(d.pop("geometry_type", UNSET))

        def _parse_feature_count(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        feature_count = _parse_feature_count(d.pop("feature_count", UNSET))

        layer_type = d.pop("layer_type", UNSET)

        def _parse_source_layer_type(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        source_layer_type = _parse_source_layer_type(d.pop("source_layer_type", UNSET))

        def _parse_parent_layer_id(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        parent_layer_id = _parse_parent_layer_id(d.pop("parent_layer_id", UNSET))

        importable = d.pop("importable", UNSET)

        def _parse_layer_id(data: object) -> int | None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | str | Unset, data)

        layer_id = _parse_layer_id(d.pop("layer_id", UNSET))

        def _parse_object_id_field(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        object_id_field = _parse_object_id_field(d.pop("object_id_field", UNSET))

        _kind = d.pop("kind", UNSET)
        kind: LayerInfoKind | Unset
        if isinstance(_kind, Unset):
            kind = UNSET
        else:
            kind = check_layer_info_kind(_kind)

        layer_info = cls(
            name=name,
            title=title,
            geometry_type=geometry_type,
            feature_count=feature_count,
            layer_type=layer_type,
            source_layer_type=source_layer_type,
            parent_layer_id=parent_layer_id,
            importable=importable,
            layer_id=layer_id,
            object_id_field=object_id_field,
            kind=kind,
        )

        layer_info.additional_properties = d
        return layer_info

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
