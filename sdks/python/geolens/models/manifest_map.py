from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from ..models.manifest_map_styling import check_manifest_map_styling
from ..models.manifest_map_styling import ManifestMapStyling
from ..models.manifest_map_visibility_type_0 import check_manifest_map_visibility_type_0
from ..models.manifest_map_visibility_type_0 import ManifestMapVisibilityType0
from typing import cast

if TYPE_CHECKING:
    from ..models.manifest_loss_report import ManifestLossReport
    from ..models.manifest_map_layer import ManifestMapLayer
    from ..models.manifest_map_view import ManifestMapView


T = TypeVar("T", bound="ManifestMap")


@_attrs_define
class ManifestMap:
    """
    Attributes:
        key (str): Stable map identity key, unique across the server. A key on a map the caller can't edit answers A050.
        name (str):
        layers (list[ManifestMapLayer]):
        description (None | str | Unset):
        view (ManifestMapView | None | Unset):
        basemap_style (None | str | Unset): A basemap id from GET /capabilities.
        styling (ManifestMapStyling | Unset): Whether a republish replaces the map's styling: its view, basemap and its
            keyed layers' paint, layout, style, labels, popup, filter, opacity, visible flag and name. `replace` always
            does. `keep` never does, and keeps keyed layers the manifest no longer lists. `replace_if_unedited` does unless
            styling it would write was edited in GeoLens since the last publish that replaced it, and answers info A070 when
            it keeps it. A view or basemap edit counts only when the manifest sends a `view` or `basemap_style` that would
            overwrite it. A kept layer keeps its dataset too, with warning A073 when the manifest names another. Name,
            description, notes, visibility and new layers are applied in every mode, and a new map takes the manifest's
            styling. Default: 'replace_if_unedited'.
        thumbnail (None | str | Unset): A PNG or JPEG data URI, stored as the map's thumbnail once the map is written,
            with the thumbnail upload's checks, when the manifest's styling is applied. A publish that keeps the styling
            leaves the map's thumbnail as it is. One the storage step refuses or can't store is warning A072, and the map
            stays published.
        loss_report (ManifestLossReport | None | Unset): Written, one line per item, in a block at the top of the map's
            notes, above a `---` line. A republish replaces the leading block only when it is exactly a block some publish
            of this map wrote; all other text is kept whole. Left out when the styling is kept, and cut to what fits the
            notes limit. When the notes leave no room for the block, none is written, and an earlier publish's block is
            removed if the notes start with one; the rest of the notes is untouched (info A071).
        visibility (ManifestMapVisibilityType0 | None | Unset): Who can see the map. Omitted on create the map is
            private; omitted on update the current level is kept.
    """

    key: str
    name: str
    layers: list[ManifestMapLayer]
    description: None | str | Unset = UNSET
    view: ManifestMapView | None | Unset = UNSET
    basemap_style: None | str | Unset = UNSET
    styling: ManifestMapStyling | Unset = "replace_if_unedited"
    thumbnail: None | str | Unset = UNSET
    loss_report: ManifestLossReport | None | Unset = UNSET
    visibility: ManifestMapVisibilityType0 | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.manifest_loss_report import ManifestLossReport
        from ..models.manifest_map_view import ManifestMapView

        key = self.key

        name = self.name

        layers = []
        for layers_item_data in self.layers:
            layers_item = layers_item_data.to_dict()
            layers.append(layers_item)

        description: None | str | Unset
        if isinstance(self.description, Unset):
            description = UNSET
        else:
            description = self.description

        view: dict[str, Any] | None | Unset
        if isinstance(self.view, Unset):
            view = UNSET
        elif isinstance(self.view, ManifestMapView):
            view = self.view.to_dict()
        else:
            view = self.view

        basemap_style: None | str | Unset
        if isinstance(self.basemap_style, Unset):
            basemap_style = UNSET
        else:
            basemap_style = self.basemap_style

        styling: str | Unset = UNSET
        if not isinstance(self.styling, Unset):
            styling = self.styling

        thumbnail: None | str | Unset
        if isinstance(self.thumbnail, Unset):
            thumbnail = UNSET
        else:
            thumbnail = self.thumbnail

        loss_report: dict[str, Any] | None | Unset
        if isinstance(self.loss_report, Unset):
            loss_report = UNSET
        elif isinstance(self.loss_report, ManifestLossReport):
            loss_report = self.loss_report.to_dict()
        else:
            loss_report = self.loss_report

        visibility: None | str | Unset
        if isinstance(self.visibility, Unset):
            visibility = UNSET
        elif isinstance(self.visibility, str):
            visibility = self.visibility
        else:
            visibility = self.visibility

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "key": key,
                "name": name,
                "layers": layers,
            }
        )
        if description is not UNSET:
            field_dict["description"] = description
        if view is not UNSET:
            field_dict["view"] = view
        if basemap_style is not UNSET:
            field_dict["basemap_style"] = basemap_style
        if styling is not UNSET:
            field_dict["styling"] = styling
        if thumbnail is not UNSET:
            field_dict["thumbnail"] = thumbnail
        if loss_report is not UNSET:
            field_dict["loss_report"] = loss_report
        if visibility is not UNSET:
            field_dict["visibility"] = visibility

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.manifest_loss_report import ManifestLossReport
        from ..models.manifest_map_layer import ManifestMapLayer
        from ..models.manifest_map_view import ManifestMapView

        d = dict(src_dict)
        key = d.pop("key")

        name = d.pop("name")

        layers = []
        _layers = d.pop("layers")
        for layers_item_data in _layers:
            layers_item = ManifestMapLayer.from_dict(layers_item_data)

            layers.append(layers_item)

        def _parse_description(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        description = _parse_description(d.pop("description", UNSET))

        def _parse_view(data: object) -> ManifestMapView | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                view_type_0 = ManifestMapView.from_dict(data)

                return view_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ManifestMapView | None | Unset, data)

        view = _parse_view(d.pop("view", UNSET))

        def _parse_basemap_style(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        basemap_style = _parse_basemap_style(d.pop("basemap_style", UNSET))

        _styling = d.pop("styling", UNSET)
        styling: ManifestMapStyling | Unset
        if isinstance(_styling, Unset):
            styling = UNSET
        else:
            styling = check_manifest_map_styling(_styling)

        def _parse_thumbnail(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        thumbnail = _parse_thumbnail(d.pop("thumbnail", UNSET))

        def _parse_loss_report(data: object) -> ManifestLossReport | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                loss_report_type_0 = ManifestLossReport.from_dict(data)

                return loss_report_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ManifestLossReport | None | Unset, data)

        loss_report = _parse_loss_report(d.pop("loss_report", UNSET))

        def _parse_visibility(
            data: object,
        ) -> ManifestMapVisibilityType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                visibility_type_0 = check_manifest_map_visibility_type_0(data)

                return visibility_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ManifestMapVisibilityType0 | None | Unset, data)

        visibility = _parse_visibility(d.pop("visibility", UNSET))

        manifest_map = cls(
            key=key,
            name=name,
            layers=layers,
            description=description,
            view=view,
            basemap_style=basemap_style,
            styling=styling,
            thumbnail=thumbnail,
            loss_report=loss_report,
            visibility=visibility,
        )

        return manifest_map
