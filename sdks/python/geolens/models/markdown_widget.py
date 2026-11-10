from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from typing import cast
from typing import Literal
from uuid import UUID

if TYPE_CHECKING:
    from ..models.markdown_config import MarkdownConfig


T = TypeVar("T", bound="MarkdownWidget")


@_attrs_define
class MarkdownWidget:
    """
    Attributes:
        id (UUID): Made by the client and stable across saves.
        type_ (Literal['markdown']):
        v (Literal[1]):
        config (MarkdownConfig):
        title (None | str | Unset):
    """

    id: UUID
    type_: Literal["markdown"]
    v: Literal[1]
    config: MarkdownConfig
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
        from ..models.markdown_config import MarkdownConfig

        d = dict(src_dict)
        id = UUID(d.pop("id"))

        type_ = cast(Literal["markdown"], d.pop("type"))
        if type_ != "markdown":
            raise ValueError(f"type must match const 'markdown', got '{type_}'")

        v = cast(Literal[1], d.pop("v"))
        if v != 1:
            raise ValueError(f"v must match const 1, got '{v}'")

        config = MarkdownConfig.from_dict(d.pop("config"))

        def _parse_title(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        title = _parse_title(d.pop("title", UNSET))

        markdown_widget = cls(
            id=id,
            type_=type_,
            v=v,
            config=config,
            title=title,
        )

        return markdown_widget
