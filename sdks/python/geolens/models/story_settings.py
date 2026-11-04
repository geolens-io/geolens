from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from ..models.story_settings_layout import check_story_settings_layout
from ..models.story_settings_layout import StorySettingsLayout
from ..models.story_settings_panel_position import check_story_settings_panel_position
from ..models.story_settings_panel_position import StorySettingsPanelPosition
from ..models.story_settings_theme import check_story_settings_theme
from ..models.story_settings_theme import StorySettingsTheme


T = TypeVar("T", bound="StorySettings")


@_attrs_define
class StorySettings:
    """
    Attributes:
        navigation (bool | Unset): Show the chapter navigation bar. Default: False.
        layout (StorySettingsLayout | Unset): Chapter panel beside the map or floating over it. Default: 'side'.
        panel_position (StorySettingsPanelPosition | Unset): Where a floating panel sits. Default: 'left'.
        theme (StorySettingsTheme | Unset): Reader page theme; follow uses the reader's. Default: 'follow'.
    """

    navigation: bool | Unset = False
    layout: StorySettingsLayout | Unset = "side"
    panel_position: StorySettingsPanelPosition | Unset = "left"
    theme: StorySettingsTheme | Unset = "follow"

    def to_dict(self) -> dict[str, Any]:
        navigation = self.navigation

        layout: str | Unset = UNSET
        if not isinstance(self.layout, Unset):
            layout = self.layout

        panel_position: str | Unset = UNSET
        if not isinstance(self.panel_position, Unset):
            panel_position = self.panel_position

        theme: str | Unset = UNSET
        if not isinstance(self.theme, Unset):
            theme = self.theme

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if navigation is not UNSET:
            field_dict["navigation"] = navigation
        if layout is not UNSET:
            field_dict["layout"] = layout
        if panel_position is not UNSET:
            field_dict["panel_position"] = panel_position
        if theme is not UNSET:
            field_dict["theme"] = theme

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        navigation = d.pop("navigation", UNSET)

        _layout = d.pop("layout", UNSET)
        layout: StorySettingsLayout | Unset
        if isinstance(_layout, Unset):
            layout = UNSET
        else:
            layout = check_story_settings_layout(_layout)

        _panel_position = d.pop("panel_position", UNSET)
        panel_position: StorySettingsPanelPosition | Unset
        if isinstance(_panel_position, Unset):
            panel_position = UNSET
        else:
            panel_position = check_story_settings_panel_position(_panel_position)

        _theme = d.pop("theme", UNSET)
        theme: StorySettingsTheme | Unset
        if isinstance(_theme, Unset):
            theme = UNSET
        else:
            theme = check_story_settings_theme(_theme)

        story_settings = cls(
            navigation=navigation,
            layout=layout,
            panel_position=panel_position,
            theme=theme,
        )

        return story_settings
