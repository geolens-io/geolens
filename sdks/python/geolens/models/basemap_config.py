from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from ..models.basemap_label_mode import BasemapLabelMode
from ..models.basemap_label_mode import check_basemap_label_mode
from ..models.basemap_land_water_tone import BasemapLandWaterTone
from ..models.basemap_land_water_tone import check_basemap_land_water_tone
from ..models.basemap_relief_contrast import BasemapReliefContrast
from ..models.basemap_relief_contrast import check_basemap_relief_contrast
from ..models.basemap_sublayer_visibility import BasemapSublayerVisibility
from ..models.basemap_sublayer_visibility import check_basemap_sublayer_visibility
from typing import cast


T = TypeVar("T", bound="BasemapConfig")


@_attrs_define
class BasemapConfig:
    """
    Attributes:
        boundary_visibility (BasemapSublayerVisibility | Unset):
        building_visibility (bool | Unset): Whether supported building/3D building basemap layers are shown. Default:
            True.
        label_mode (BasemapLabelMode | Unset):
        land_water_tone (BasemapLandWaterTone | Unset):
        relief_contrast (BasemapReliefContrast | None | Unset): Optional contrast hint for relief-oriented basemap
            styling.
        road_visibility (BasemapSublayerVisibility | Unset):
    """

    boundary_visibility: BasemapSublayerVisibility | Unset = UNSET
    building_visibility: bool | Unset = True
    label_mode: BasemapLabelMode | Unset = UNSET
    land_water_tone: BasemapLandWaterTone | Unset = UNSET
    relief_contrast: BasemapReliefContrast | None | Unset = UNSET
    road_visibility: BasemapSublayerVisibility | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        boundary_visibility: str | Unset = UNSET
        if not isinstance(self.boundary_visibility, Unset):
            boundary_visibility = self.boundary_visibility

        building_visibility = self.building_visibility

        label_mode: str | Unset = UNSET
        if not isinstance(self.label_mode, Unset):
            label_mode = self.label_mode

        land_water_tone: str | Unset = UNSET
        if not isinstance(self.land_water_tone, Unset):
            land_water_tone = self.land_water_tone

        relief_contrast: None | str | Unset
        if isinstance(self.relief_contrast, Unset):
            relief_contrast = UNSET
        elif isinstance(self.relief_contrast, str):
            relief_contrast = self.relief_contrast
        else:
            relief_contrast = self.relief_contrast

        road_visibility: str | Unset = UNSET
        if not isinstance(self.road_visibility, Unset):
            road_visibility = self.road_visibility

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if boundary_visibility is not UNSET:
            field_dict["boundary_visibility"] = boundary_visibility
        if building_visibility is not UNSET:
            field_dict["building_visibility"] = building_visibility
        if label_mode is not UNSET:
            field_dict["label_mode"] = label_mode
        if land_water_tone is not UNSET:
            field_dict["land_water_tone"] = land_water_tone
        if relief_contrast is not UNSET:
            field_dict["relief_contrast"] = relief_contrast
        if road_visibility is not UNSET:
            field_dict["road_visibility"] = road_visibility

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        _boundary_visibility = d.pop("boundary_visibility", UNSET)
        boundary_visibility: BasemapSublayerVisibility | Unset
        if isinstance(_boundary_visibility, Unset):
            boundary_visibility = UNSET
        else:
            boundary_visibility = check_basemap_sublayer_visibility(
                _boundary_visibility
            )

        building_visibility = d.pop("building_visibility", UNSET)

        _label_mode = d.pop("label_mode", UNSET)
        label_mode: BasemapLabelMode | Unset
        if isinstance(_label_mode, Unset):
            label_mode = UNSET
        else:
            label_mode = check_basemap_label_mode(_label_mode)

        _land_water_tone = d.pop("land_water_tone", UNSET)
        land_water_tone: BasemapLandWaterTone | Unset
        if isinstance(_land_water_tone, Unset):
            land_water_tone = UNSET
        else:
            land_water_tone = check_basemap_land_water_tone(_land_water_tone)

        def _parse_relief_contrast(
            data: object,
        ) -> BasemapReliefContrast | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                relief_contrast_type_0 = check_basemap_relief_contrast(data)

                return relief_contrast_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(BasemapReliefContrast | None | Unset, data)

        relief_contrast = _parse_relief_contrast(d.pop("relief_contrast", UNSET))

        _road_visibility = d.pop("road_visibility", UNSET)
        road_visibility: BasemapSublayerVisibility | Unset
        if isinstance(_road_visibility, Unset):
            road_visibility = UNSET
        else:
            road_visibility = check_basemap_sublayer_visibility(_road_visibility)

        basemap_config = cls(
            boundary_visibility=boundary_visibility,
            building_visibility=building_visibility,
            label_mode=label_mode,
            land_water_tone=land_water_tone,
            relief_contrast=relief_contrast,
            road_visibility=road_visibility,
        )

        return basemap_config
