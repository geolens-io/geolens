from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from typing import cast
from typing import Literal
from uuid import UUID

if TYPE_CHECKING:
    from ..models.button_config import ButtonConfig


T = TypeVar("T", bound="ButtonWidget")


@_attrs_define
class ButtonWidget:
    """
    Attributes:
        id (UUID): Made by the client and stable across saves.
        type_ (Literal['button']):
        v (Literal[1]):
        config (ButtonConfig):
        title (None | str | Unset):
    """

    id: UUID
    type_: Literal["button"]
    v: Literal[1]
    config: ButtonConfig
    title: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        id = str(self.id)

        type_ = self.type_

        v = self.v

        config = self.config.to_dict()

        title: None | str | Unset
        if isinstance(self.title, Unset):
            title = UNSET
        else:
            title = self.title

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "id": id,
                "type": type_,
                "v": v,
                "config": config,
            }
        )
        if title is not UNSET:
            field_dict["title"] = title

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.button_config import ButtonConfig

        d = dict(src_dict)
        id = UUID(d.pop("id"))

        type_ = cast(Literal["button"], d.pop("type"))
        if type_ != "button":
            raise ValueError(f"type must match const 'button', got '{type_}'")

        v = cast(Literal[1], d.pop("v"))
        if v != 1:
            raise ValueError(f"v must match const 1, got '{v}'")

        config = ButtonConfig.from_dict(d.pop("config"))

        def _parse_title(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        title = _parse_title(d.pop("title", UNSET))

        button_widget = cls(
            id=id,
            type_=type_,
            v=v,
            config=config,
            title=title,
        )

        return button_widget
