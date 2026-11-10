from typing import Literal, cast

TableWidgetScope = Literal["layer", "view"]

TABLE_WIDGET_SCOPE_VALUES: set[TableWidgetScope] = {
    "layer",
    "view",
}


def check_table_widget_scope(value: str) -> TableWidgetScope:
    if value in TABLE_WIDGET_SCOPE_VALUES:
        return cast(TableWidgetScope, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {TABLE_WIDGET_SCOPE_VALUES!r}"
    )
