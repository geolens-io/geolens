from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from typing import cast
from uuid import UUID

if TYPE_CHECKING:
    from ..models.button_widget import ButtonWidget
    from ..models.carousel_widget import CarouselWidget
    from ..models.embed_widget import EmbedWidget
    from ..models.gallery_widget import GalleryWidget
    from ..models.image_widget import ImageWidget
    from ..models.markdown_widget import MarkdownWidget
    from ..models.separator_widget import SeparatorWidget
    from ..models.story_scene import StoryScene
    from ..models.video_widget import VideoWidget


T = TypeVar("T", bound="StoryChapterInput")


@_attrs_define
class StoryChapterInput:
    """
    Attributes:
        id (UUID): Made by the client and stable across saves.
        title (None | str | Unset):
        scene (None | StoryScene | Unset):
        scene_hidden (bool | Unset): Send back as read to keep a scene on a map you can't read; with it false, a chapter
            without a scene loses its stored one. Default: False.
        blocks (list[ButtonWidget | CarouselWidget | EmbedWidget | GalleryWidget | ImageWidget | MarkdownWidget |
            SeparatorWidget | VideoWidget] | Unset):
    """

    id: UUID
    title: None | str | Unset = UNSET
    scene: None | StoryScene | Unset = UNSET
    scene_hidden: bool | Unset = False
    blocks: (
        list[
            ButtonWidget
            | CarouselWidget
            | EmbedWidget
            | GalleryWidget
            | ImageWidget
            | MarkdownWidget
            | SeparatorWidget
            | VideoWidget
        ]
        | Unset
    ) = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.button_widget import ButtonWidget
        from ..models.carousel_widget import CarouselWidget
        from ..models.embed_widget import EmbedWidget
        from ..models.gallery_widget import GalleryWidget
        from ..models.image_widget import ImageWidget
        from ..models.markdown_widget import MarkdownWidget
        from ..models.separator_widget import SeparatorWidget
        from ..models.story_scene import StoryScene

        id = str(self.id)

        title: None | str | Unset
        if isinstance(self.title, Unset):
            title = UNSET
        else:
            title = self.title

        scene: dict[str, Any] | None | Unset
        if isinstance(self.scene, Unset):
            scene = UNSET
        elif isinstance(self.scene, StoryScene):
            scene = self.scene.to_dict()
        else:
            scene = self.scene

        scene_hidden = self.scene_hidden

        blocks: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.blocks, Unset):
            blocks = []
            for blocks_item_data in self.blocks:
                blocks_item: dict[str, Any]
                if isinstance(blocks_item_data, MarkdownWidget):
                    blocks_item = blocks_item_data.to_dict()
                elif isinstance(blocks_item_data, ImageWidget):
                    blocks_item = blocks_item_data.to_dict()
                elif isinstance(blocks_item_data, GalleryWidget):
                    blocks_item = blocks_item_data.to_dict()
                elif isinstance(blocks_item_data, CarouselWidget):
                    blocks_item = blocks_item_data.to_dict()
                elif isinstance(blocks_item_data, ButtonWidget):
                    blocks_item = blocks_item_data.to_dict()
                elif isinstance(blocks_item_data, SeparatorWidget):
                    blocks_item = blocks_item_data.to_dict()
                elif isinstance(blocks_item_data, EmbedWidget):
                    blocks_item = blocks_item_data.to_dict()
                else:
                    blocks_item = blocks_item_data.to_dict()

                blocks.append(blocks_item)

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "id": id,
            }
        )
        if title is not UNSET:
            field_dict["title"] = title
        if scene is not UNSET:
            field_dict["scene"] = scene
        if scene_hidden is not UNSET:
            field_dict["scene_hidden"] = scene_hidden
        if blocks is not UNSET:
            field_dict["blocks"] = blocks

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.button_widget import ButtonWidget
        from ..models.carousel_widget import CarouselWidget
        from ..models.embed_widget import EmbedWidget
        from ..models.gallery_widget import GalleryWidget
        from ..models.image_widget import ImageWidget
        from ..models.markdown_widget import MarkdownWidget
        from ..models.separator_widget import SeparatorWidget
        from ..models.story_scene import StoryScene
        from ..models.video_widget import VideoWidget

        d = dict(src_dict)
        id = UUID(d.pop("id"))

        def _parse_title(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        title = _parse_title(d.pop("title", UNSET))

        def _parse_scene(data: object) -> None | StoryScene | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                scene_type_0 = StoryScene.from_dict(data)

                return scene_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | StoryScene | Unset, data)

        scene = _parse_scene(d.pop("scene", UNSET))

        scene_hidden = d.pop("scene_hidden", UNSET)

        _blocks = d.pop("blocks", UNSET)
        blocks: (
            list[
                ButtonWidget
                | CarouselWidget
                | EmbedWidget
                | GalleryWidget
                | ImageWidget
                | MarkdownWidget
                | SeparatorWidget
                | VideoWidget
            ]
            | Unset
        ) = UNSET
        if _blocks is not UNSET:
            blocks = []
            for blocks_item_data in _blocks:

                def _parse_blocks_item(
                    data: object,
                ) -> (
                    ButtonWidget
                    | CarouselWidget
                    | EmbedWidget
                    | GalleryWidget
                    | ImageWidget
                    | MarkdownWidget
                    | SeparatorWidget
                    | VideoWidget
                ):
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        blocks_item_type_0 = MarkdownWidget.from_dict(data)

                        return blocks_item_type_0
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        blocks_item_type_1 = ImageWidget.from_dict(data)

                        return blocks_item_type_1
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        blocks_item_type_2 = GalleryWidget.from_dict(data)

                        return blocks_item_type_2
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        blocks_item_type_3 = CarouselWidget.from_dict(data)

                        return blocks_item_type_3
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        blocks_item_type_4 = ButtonWidget.from_dict(data)

                        return blocks_item_type_4
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        blocks_item_type_5 = SeparatorWidget.from_dict(data)

                        return blocks_item_type_5
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        blocks_item_type_6 = EmbedWidget.from_dict(data)

                        return blocks_item_type_6
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    if not isinstance(data, dict):
                        raise TypeError()
                    blocks_item_type_7 = VideoWidget.from_dict(data)

                    return blocks_item_type_7

                blocks_item = _parse_blocks_item(blocks_item_data)

                blocks.append(blocks_item)

        story_chapter_input = cls(
            id=id,
            title=title,
            scene=scene,
            scene_hidden=scene_hidden,
            blocks=blocks,
        )

        return story_chapter_input
