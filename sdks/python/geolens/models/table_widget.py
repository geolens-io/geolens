from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from ..models.table_widget_scope import check_table_widget_scope
from ..models.table_widget_scope import TableWidgetScope
from ..models.table_widget_v import check_table_widget_v
from ..models.table_widget_v import TableWidgetV
from typing import cast
from typing import Literal
from uuid import UUID

if TYPE_CHECKING:
    from ..models.table_config import TableConfig


T = TypeVar("T", bound="TableWidget")


@_attrs_define
class TableWidget:
    """
    Attributes:
        id (UUID): Made by the client and stable across saves.
        layer_id (UUID): A layer of the host's map.
        type_ (Literal['table']):
        v (TableWidgetV):
        config (TableConfig):
        title (None | str | Unset):
        scope (TableWidgetScope | Unset): Summarize the whole layer, or only what the map view shows. Default: 'layer'.
        filter_ (list[Any] | None | Unset): Count only the features this MapLibre filter expression keeps, on top of the
            layer's own filter. It takes the conditions the filter editor writes: comparisons, value lists, contains, `has`
            and is-empty tests on columns named with `get`, joined by `all` or `any`, or the legacy forms of those. Each
            column must be one of the layer's. Needs the type's filter version; left out, the widget covers what its layer
            shows.
    """

    id: UUID
    layer_id: UUID
    type_: Literal["table"]
    v: TableWidgetV
    config: TableConfig
    title: None | str | Unset = UNSET
    scope: TableWidgetScope | Unset = "layer"
    filter_: list[Any] | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        id = str(self.id)

        layer_id = str(self.layer_id)

        type_ = self.type_

        v: int = self.v

        config = self.config.to_dict()

        title: None | str | Unset
        if isinstance(self.title, Unset):
            title = UNSET
        else:
            title = self.title

        scope: str | Unset = UNSET
        if not isinstance(self.scope, Unset):
            scope = self.scope

        filter_: list[Any] | None | Unset
        if isinstance(self.filter_, Unset):
            filter_ = UNSET
        elif isinstance(self.filter_, list):
            filter_ = self.filter_

        else:
            filter_ = self.filter_

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
        if filter_ is not UNSET:
            field_dict["filter"] = filter_

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.table_config import TableConfig

        d = dict(src_dict)
        id = UUID(d.pop("id"))

        layer_id = UUID(d.pop("layer_id"))

        type_ = cast(Literal["table"], d.pop("type"))
        if type_ != "table":
            raise ValueError(f"type must match const 'table', got '{type_}'")

        v = check_table_widget_v(d.pop("v"))

        config = TableConfig.from_dict(d.pop("config"))

        def _parse_title(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        title = _parse_title(d.pop("title", UNSET))

        _scope = d.pop("scope", UNSET)
        scope: TableWidgetScope | Unset
        if isinstance(_scope, Unset):
            scope = UNSET
        else:
            scope = check_table_widget_scope(_scope)

        def _parse_filter_(data: object) -> list[Any] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                filter_type_0 = cast(list[Any], data)

                return filter_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[Any] | None | Unset, data)

        filter_ = _parse_filter_(d.pop("filter", UNSET))

        table_widget = cls(
            id=id,
            layer_id=layer_id,
            type_=type_,
            v=v,
            config=config,
            title=title,
            scope=scope,
            filter_=filter_,
        )

        return table_widget
