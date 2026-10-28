from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from uuid import UUID

if TYPE_CHECKING:
    from ..models.story_camera import StoryCamera
    from ..models.story_scene_layer_visibility import StorySceneLayerVisibility


T = TypeVar("T", bound="StoryScene")


@_attrs_define
class StoryScene:
    """
    Attributes:
        map_id (UUID):
        camera (StoryCamera):
        layer_visibility (StorySceneLayerVisibility | Unset): Visibility by map layer id. Layers the map no longer has
            are ignored, and a layer left out keeps its saved visibility.
    """

    map_id: UUID
    camera: StoryCamera
    layer_visibility: StorySceneLayerVisibility | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        map_id = str(self.map_id)

        camera = self.camera.to_dict()

        layer_visibility: dict[str, Any] | Unset = UNSET
        if not isinstance(self.layer_visibility, Unset):
            layer_visibility = self.layer_visibility.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "map_id": map_id,
                "camera": camera,
            }
        )
        if layer_visibility is not UNSET:
            field_dict["layer_visibility"] = layer_visibility

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.story_camera import StoryCamera
        from ..models.story_scene_layer_visibility import StorySceneLayerVisibility

        d = dict(src_dict)
        map_id = UUID(d.pop("map_id"))

        camera = StoryCamera.from_dict(d.pop("camera"))

        _layer_visibility = d.pop("layer_visibility", UNSET)
        layer_visibility: StorySceneLayerVisibility | Unset
        if isinstance(_layer_visibility, Unset):
            layer_visibility = UNSET
        else:
            layer_visibility = StorySceneLayerVisibility.from_dict(_layer_visibility)

        story_scene = cls(
            map_id=map_id,
            camera=camera,
            layer_visibility=layer_visibility,
        )

        return story_scene
