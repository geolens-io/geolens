from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from ..models.map_visibility import check_map_visibility
from ..models.map_visibility import MapVisibility
from typing import cast

if TYPE_CHECKING:
    from ..models.arcgis_webmap_import_request_basemap_map import (
        ArcgisWebmapImportRequestBasemapMap,
    )
    from ..models.arcgis_webmap_import_request_dataset_matches import (
        ArcgisWebmapImportRequestDatasetMatches,
    )
    from ..models.arcgis_webmap_import_request_webmap import (
        ArcgisWebmapImportRequestWebmap,
    )


T = TypeVar("T", bound="ArcgisWebmapImportRequest")


@_attrs_define
class ArcgisWebmapImportRequest:
    """
    Attributes:
        webmap (ArcgisWebmapImportRequestWebmap): The web map item data JSON, at most 1 MB serialized.
        name (None | str | Unset): Map name. Defaults to `title`.
        title (None | str | Unset): The web map item's title.
        visibility (MapVisibility | Unset):
        basemap_map (ArcgisWebmapImportRequestBasemapMap | Unset): Esri basemap URL or style URL (the first base map
            layer's `url` or `styleUrl`) to a GeoLens basemap id. An unmapped basemap falls back to the first enabled
            basemap and is reported.
        dataset_matches (ArcgisWebmapImportRequestDatasetMatches | Unset): Operational layer id to GeoLens dataset id.
            Every dataset must be one the caller can read, or the request is refused with 404. A layer with no entry is not
            imported and is listed as unmatched.
        dry_run (bool | Unset): Return the translation without creating a map. Default: False.
    """

    webmap: ArcgisWebmapImportRequestWebmap
    name: None | str | Unset = UNSET
    title: None | str | Unset = UNSET
    visibility: MapVisibility | Unset = UNSET
    basemap_map: ArcgisWebmapImportRequestBasemapMap | Unset = UNSET
    dataset_matches: ArcgisWebmapImportRequestDatasetMatches | Unset = UNSET
    dry_run: bool | Unset = False

    def to_dict(self) -> dict[str, Any]:
        webmap = self.webmap.to_dict()

        name: None | str | Unset
        if isinstance(self.name, Unset):
            name = UNSET
        else:
            name = self.name

        title: None | str | Unset
        if isinstance(self.title, Unset):
            title = UNSET
        else:
            title = self.title

        visibility: str | Unset = UNSET
        if not isinstance(self.visibility, Unset):
            visibility = self.visibility

        basemap_map: dict[str, Any] | Unset = UNSET
        if not isinstance(self.basemap_map, Unset):
            basemap_map = self.basemap_map.to_dict()

        dataset_matches: dict[str, Any] | Unset = UNSET
        if not isinstance(self.dataset_matches, Unset):
            dataset_matches = self.dataset_matches.to_dict()

        dry_run = self.dry_run

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "webmap": webmap,
            }
        )
        if name is not UNSET:
            field_dict["name"] = name
        if title is not UNSET:
            field_dict["title"] = title
        if visibility is not UNSET:
            field_dict["visibility"] = visibility
        if basemap_map is not UNSET:
            field_dict["basemap_map"] = basemap_map
        if dataset_matches is not UNSET:
            field_dict["dataset_matches"] = dataset_matches
        if dry_run is not UNSET:
            field_dict["dry_run"] = dry_run

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.arcgis_webmap_import_request_basemap_map import (
            ArcgisWebmapImportRequestBasemapMap,
        )
        from ..models.arcgis_webmap_import_request_dataset_matches import (
            ArcgisWebmapImportRequestDatasetMatches,
        )
        from ..models.arcgis_webmap_import_request_webmap import (
            ArcgisWebmapImportRequestWebmap,
        )

        d = dict(src_dict)
        webmap = ArcgisWebmapImportRequestWebmap.from_dict(d.pop("webmap"))

        def _parse_name(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        name = _parse_name(d.pop("name", UNSET))

        def _parse_title(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        title = _parse_title(d.pop("title", UNSET))

        _visibility = d.pop("visibility", UNSET)
        visibility: MapVisibility | Unset
        if isinstance(_visibility, Unset):
            visibility = UNSET
        else:
            visibility = check_map_visibility(_visibility)

        _basemap_map = d.pop("basemap_map", UNSET)
        basemap_map: ArcgisWebmapImportRequestBasemapMap | Unset
        if isinstance(_basemap_map, Unset):
            basemap_map = UNSET
        else:
            basemap_map = ArcgisWebmapImportRequestBasemapMap.from_dict(_basemap_map)

        _dataset_matches = d.pop("dataset_matches", UNSET)
        dataset_matches: ArcgisWebmapImportRequestDatasetMatches | Unset
        if isinstance(_dataset_matches, Unset):
            dataset_matches = UNSET
        else:
            dataset_matches = ArcgisWebmapImportRequestDatasetMatches.from_dict(
                _dataset_matches
            )

        dry_run = d.pop("dry_run", UNSET)

        arcgis_webmap_import_request = cls(
            webmap=webmap,
            name=name,
            title=title,
            visibility=visibility,
            basemap_map=basemap_map,
            dataset_matches=dataset_matches,
            dry_run=dry_run,
        )

        return arcgis_webmap_import_request
