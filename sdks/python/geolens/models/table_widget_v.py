from typing import Literal, cast

TableWidgetV = Literal[1, 2]

TABLE_WIDGET_V_VALUES: set[TableWidgetV] = {
    1,
    2,
}


def check_table_widget_v(value: int) -> TableWidgetV:
    if value in TABLE_WIDGET_V_VALUES:
        return cast(TableWidgetV, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {TABLE_WIDGET_V_VALUES!r}"
    )
