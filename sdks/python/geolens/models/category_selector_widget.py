from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from ..models.category_selector_widget_scope import CategorySelectorWidgetScope
from ..models.category_selector_widget_scope import check_category_selector_widget_scope
from typing import cast
from typing import Literal
from uuid import UUID

if TYPE_CHECKING:
    from ..models.category_selector_config import CategorySelectorConfig


T = TypeVar("T", bound="CategorySelectorWidget")


@_attrs_define
class CategorySelectorWidget:
    """
    Attributes:
        id (UUID): Made by the client and stable across saves.
        layer_id (UUID): A layer of the host's map.
        type_ (Literal['category_selector']):
        v (Literal[1]):
        config (CategorySelectorConfig):
        title (None | str | Unset):
        scope (CategorySelectorWidgetScope | Unset): Summarize the whole layer, or only what the map view shows.
            Default: 'layer'.
    """

    id: UUID
    layer_id: UUID
    type_: Literal["category_selector"]
    v: Literal[1]
    config: CategorySelectorConfig
    title: None | str | Unset = UNSET
    scope: CategorySelectorWidgetScope | Unset = "layer"

    def to_dict(self) -> dict[str, Any]:
        id = str(self.id)

        layer_id = str(self.layer_id)

        type_ = self.type_

        v = self.v

        config = self.config.to_dict()

        title: None | str | Unset
        if isinstance(self.title, Unset):
            title = UNSET
        else:
            title = self.title

        scope: str | Unset = UNSET
        if not isinstance(self.scope, Unset):
            scope = self.scope

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "id": id,
                "layer_id": layer_id,
                "type": type_,
                "v": v,
                "config": config,
            }
        )
        if title is not UNSET:
            field_dict["title"] = title
        if scope is not UNSET:
            field_dict["scope"] = scope

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.category_selector_config import CategorySelectorConfig

        d = dict(src_dict)
        id = UUID(d.pop("id"))

        layer_id = UUID(d.pop("layer_id"))

        type_ = cast(Literal["category_selector"], d.pop("type"))
        if type_ != "category_selector":
            raise ValueError(
                f"type must match const 'category_selector', got '{type_}'"
            )

        v = cast(Literal[1], d.pop("v"))
        if v != 1:
            raise ValueError(f"v must match const 1, got '{v}'")

        config = CategorySelectorConfig.from_dict(d.pop("config"))

        def _parse_title(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        title = _parse_title(d.pop("title", UNSET))

        _scope = d.pop("scope", UNSET)
        scope: CategorySelectorWidgetScope | Unset
        if isinstance(_scope, Unset):
            scope = UNSET
        else:
            scope = check_category_selector_widget_scope(_scope)

        category_selector_widget = cls(
            id=id,
            layer_id=layer_id,
            type_=type_,
            v=v,
            config=config,
            title=title,
            scope=scope,
        )

        return category_selector_widget
