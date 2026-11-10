"""Requests and results of the aggregate endpoint, one model per operation."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ModelWrapValidatorHandler,
    PrivateAttr,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
    model_validator,
)

from app.modules.catalog.features.service import parse_bbox

_MAX_ITEMS = 50
_MAX_ROWS = 100

StatName = Literal["count", "sum", "avg", "min", "max"]
ColumnName = Annotated[str, Field(min_length=1, max_length=63)]
Scalar = str | int | float | bool | None


class _AggregateBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filter: dict[str, Any] | None = Field(
        None,
        description="CQL2-JSON filter, as the OGC API Features `filter` accepts.",
    )
    bbox: list[float] | None = Field(
        None,
        min_length=4,
        max_length=4,
        description=(
            "Map view `[west, south, east, north]` in WGS 84; west greater than "
            "east crosses the antimeridian. Omit for the whole layer."
        ),
    )

    @field_validator("bbox")
    @classmethod
    def _valid_bbox(cls, value: list[float] | None) -> list[float] | None:
        return None if value is None else parse_bbox(value)


class CountRequest(_AggregateBase):
    op: Literal["count"]


class StatsRequest(_AggregateBase):
    op: Literal["stats"]
    column: ColumnName
    stats: list[StatName] = Field(min_length=1, max_length=5)

    @field_validator("stats")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class ValueCountsRequest(_AggregateBase):
    op: Literal["value_counts"]
    column: ColumnName
    limit: int = Field(10, ge=1, le=_MAX_ITEMS)


class HistogramRequest(_AggregateBase):
    op: Literal["histogram"]
    column: ColumnName
    bins: int = Field(10, ge=1, le=_MAX_ITEMS)


class GroupStat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stat: StatName
    column: ColumnName | None = Field(
        None,
        description=(
            "The numeric column `stat` reads. Optional for `count`, which then"
            " counts rows, and otherwise counts the column's non-null values."
        ),
    )

    @model_validator(mode="after")
    def _column_for_stat(self) -> GroupStat:
        if self.stat != "count" and self.column is None:
            raise ValueError(f"stat {self.stat!r} needs a column")
        return self


class GroupByRequest(_AggregateBase):
    op: Literal["group_by"]
    group_column: ColumnName
    stat: StatName | None = Field(None, description="One statistic; or give `stats`.")
    column: ColumnName | None = Field(
        None, description="The numeric column `stat` reads; omit for `count`."
    )
    stats: list[GroupStat] | None = Field(
        None,
        min_length=1,
        max_length=5,
        description="Statistics returned as each group's `values`, in this order.",
    )
    date_bucket: Literal["day", "week", "month", "year"] | None = Field(
        None,
        description=(
            "Group a date or timestamp column by the UTC day, Monday-first week,"
            " month or year it falls in."
        ),
    )
    sort_by: Literal["group"] | Annotated[int, Field(ge=0)] | None = Field(
        None,
        description=(
            "Order and keep groups by a statistic's index in `stats` (0 with"
            " `stat`) or by `group`. Defaults to the first statistic, or to"
            " the group with `date_bucket`."
        ),
    )
    sort: Literal["asc", "desc"] | None = Field(
        None,
        description="Defaults to `desc`, or `asc` with `date_bucket`.",
    )
    limit: int = Field(10, ge=1, le=_MAX_ITEMS)

    # The single-statistic form, whose groups carry no `values`.
    _single: bool = PrivateAttr(False)

    @model_validator(mode="wrap")
    @classmethod
    def _one_list(cls, data: Any, handler: ModelWrapValidatorHandler) -> GroupByRequest:
        """Read either form as one `stats` list, with the order's defaults set."""
        if not isinstance(data, dict):
            return handler(data)
        data = dict(data)
        single = data.get("stats") is None
        if not single:
            if data.get("stat") is not None or data.get("column") is not None:
                raise ValueError("group_by takes `stat` and `column`, or `stats`")
        elif data.get("stat") is None:
            raise ValueError("group_by needs `stat` or `stats`")
        else:
            stat = data.pop("stat")
            column = data.pop("column", None)
            # The single form counts rows even when it names a column.
            data["stats"] = [
                {"stat": stat, "column": None if stat == "count" else column}
            ]
        bucketed = data.get("date_bucket") is not None
        if data.get("sort_by") is None:
            data["sort_by"] = "group" if bucketed else 0
        if data.get("sort") is None:
            data["sort"] = "asc" if bucketed else "desc"
        request = handler(data)
        if isinstance(request.sort_by, int) and request.sort_by >= len(request.stats):
            raise ValueError(f"sort_by {request.sort_by} names no statistic")
        request._single = single
        return request


class RowsRequest(_AggregateBase):
    op: Literal["rows"]
    columns: list[ColumnName] = Field(min_length=1, max_length=20)
    sort_column: ColumnName | None = Field(
        None,
        description=(
            "Order rows by this column with nulls last, then by gid; omit to"
            " order by gid."
        ),
    )
    sort: Literal["asc", "desc"] = "asc"
    limit: int = Field(25, ge=1, le=_MAX_ROWS)
    cursor: str | None = Field(
        None,
        max_length=256,
        description="The previous page's `next_cursor`, under the same sort.",
    )

    @field_validator("columns")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


AggregateRequest = Annotated[
    CountRequest
    | StatsRequest
    | ValueCountsRequest
    | HistogramRequest
    | GroupByRequest
    | RowsRequest,
    Field(discriminator="op"),
]


class CountResult(BaseModel):
    count: int


class StatsResult(BaseModel):
    """The requested statistics; one over no rows is null.

    ``sum``, ``min`` and ``max`` are exact: a number when JSON can carry it
    exactly, else text. ``avg`` is a float, or text for NaN and infinity.
    """

    count: int | None = None
    sum: int | float | str | None = None
    avg: float | str | None = None
    min: int | float | str | None = None
    max: int | float | str | None = None


_EXACT_KEY = (
    "The column's value. A number JSON cannot carry exactly, such as an integer "
    "beyond 2^53 or NaN, comes back as text."
)


class ValueCount(BaseModel):
    value: Scalar = Field(description=_EXACT_KEY)
    count: int


class ValueCountsResult(BaseModel):
    values: list[ValueCount] = Field(description="Most frequent first.")
    other_count: int = Field(description="Rows whose value is not listed.")


class HistogramBin(BaseModel):
    lower: float
    upper: float
    count: int


class HistogramResult(BaseModel):
    bins: list[HistogramBin] = Field(
        description=(
            "Equal-width bins over the finite values, empty with none. Unless"
            " whole_numbers is true, a bin holds its lower edge but not its upper"
            " one, and the last bin holds both."
        )
    )
    whole_numbers: bool = Field(
        False,
        description=(
            "Whether each bin holds the whole numbers from its lower edge to one"
            " below its upper edge. Only an integer column has whole-number bins,"
            " and only while every edge is a safe JavaScript integer; they may"
            " then number fewer than requested, and the last may be narrower."
        ),
    )


def _omit_unset(*names: str):
    """A serializer that leaves out ``names`` unless they were set."""

    def serialize(self: BaseModel, handler: SerializerFunctionWrapHandler):
        data = handler(self)
        for name in names:
            if name not in self.model_fields_set:
                data.pop(name, None)
        return data

    return model_serializer(mode="wrap")(serialize)


_STAT_VALUE = "Exact for count, sum, min and max, as for a key; avg is a float."


class GroupValue(BaseModel):
    key: Scalar = Field(description=_EXACT_KEY)
    value: float | int | str | None = Field(
        description=f"{_STAT_VALUE} With `stats`, the first statistic's value."
    )
    values: list[float | int | str | None] | None = Field(
        None,
        description=f"Present with `stats`: each one's value in order. {_STAT_VALUE}",
    )

    _serialize = _omit_unset("values")


class GroupByResult(BaseModel):
    groups: list[GroupValue] = Field(
        description="In the requested order; by default the largest value first."
    )
    truncated: bool = Field(
        False, description="Whether more groups matched than `limit` lists."
    )


class AggregateRow(BaseModel):
    gid: int | str = Field(
        description="The feature's id; text at or beyond 2^53, as for a value."
    )
    values: dict[str, Scalar] = Field(description=f"By column. {_EXACT_KEY}")
    bbox: list[float] | None = Field(
        None,
        description=(
            "Present only when the dataset has geometry: the feature's"
            " `[west, south, east, north]` in WGS 84, or null without a shape."
        ),
    )

    _serialize = _omit_unset("bbox")


class RowsResult(BaseModel):
    rows: list[AggregateRow]
    next_cursor: str | None = Field(description="Pass as `cursor` for the next page.")
    has_more: bool


class _ResponseBase(BaseModel):
    approximate: Literal[False] = Field(
        False, description="Always false: a view too wide to count exactly is refused."
    )
    cached: bool


class CountResponse(_ResponseBase):
    op: Literal["count"]
    result: CountResult


class StatsResponse(_ResponseBase):
    op: Literal["stats"]
    result: StatsResult


class ValueCountsResponse(_ResponseBase):
    op: Literal["value_counts"]
    result: ValueCountsResult


class HistogramResponse(_ResponseBase):
    op: Literal["histogram"]
    result: HistogramResult


class GroupByResponse(_ResponseBase):
    op: Literal["group_by"]
    result: GroupByResult


class RowsResponse(_ResponseBase):
    op: Literal["rows"]
    result: RowsResult


# Keyed on ``op`` so a client's generated parser picks the result by operation.
AggregateResponse = Annotated[
    CountResponse
    | StatsResponse
    | ValueCountsResponse
    | HistogramResponse
    | GroupByResponse
    | RowsResponse,
    Field(discriminator="op"),
]
_RESPONSES: dict[str, type[_ResponseBase]] = {
    "count": CountResponse,
    "stats": StatsResponse,
    "value_counts": ValueCountsResponse,
    "histogram": HistogramResponse,
    "group_by": GroupByResponse,
    "rows": RowsResponse,
}


def _respond(op: str, result: Any, *, cached: bool) -> AggregateResponse:
    return _RESPONSES[op].model_validate({"op": op, "result": result, "cached": cached})
