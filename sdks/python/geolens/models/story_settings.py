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
from ..models.story_settings_transition import check_story_settings_transition
from ..models.story_settings_transition import StorySettingsTransition


T = TypeVar("T", bound="StorySettings")


@_attrs_define
class StorySettings:
    """
    Attributes:
        navigation (bool | Unset): Show the chapter navigation bar. Default: False.
        layout (StorySettingsLayout | Unset): Chapter panel beside the map or floating over it. Default: 'side'.
        panel_position (StorySettingsPanelPosition | Unset): Where a floating panel sits. Default: 'left'.
        theme (StorySettingsTheme | Unset): Reader page theme; follow uses the reader's. Default: 'follow'.
        transition (StorySettingsTransition | Unset): How the map moves into a chapter whose scene sets no transition.
            Default: 'fly'.
    """

    navigation: bool | Unset = False
    layout: StorySettingsLayout | Unset = "side"
    panel_position: StorySettingsPanelPosition | Unset = "left"
    theme: StorySettingsTheme | Unset = "follow"
    transition: StorySettingsTransition | Unset = "fly"

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

        transition: str | Unset = UNSET
        if not isinstance(self.transition, Unset):
            transition = self.transition

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
        if transition is not UNSET:
            field_dict["transition"] = transition

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

        _transition = d.pop("transition", UNSET)
        transition: StorySettingsTransition | Unset
        if isinstance(_transition, Unset):
            transition = UNSET
        else:
            transition = check_story_settings_transition(_transition)

        story_settings = cls(
            navigation=navigation,
            layout=layout,
            panel_position=panel_position,
            theme=theme,
            transition=transition,
        )

        return story_settings
