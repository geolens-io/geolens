"""The persisted widget instance, shared by map dashboards and story blocks.

Pydantic models and upgraders only, with no database access, so the maps and
stories domains can both import it without reaching into each other.

Every instance carries ``type`` and ``v``. Each ``(type, v)`` has one
``extra="forbid"`` model, and ``UPGRADERS`` steps older instances up to it on
read and on write. A stored instance the server can't parse (an unknown type,
a newer ``v``, a config it no longer accepts) is left out of responses and
written back unchanged on the next save; a client that sends one gets a 422.
"""

import copy
import uuid
from collections.abc import Callable, Iterable, Sequence
from typing import Annotated, Any, Literal, NamedTuple, get_args

import structlog
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    model_validator,
)

logger = structlog.stdlib.get_logger(__name__)

WidgetHost = Literal["dashboard", "story"]
# The aggregate endpoint takes column names up to PostgreSQL's 63-character limit.
ColumnName = Annotated[str, StringConstraints(min_length=1, max_length=63)]
Statistic = Literal["count", "sum", "mean", "min", "max"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Widget(_Strict):
    id: uuid.UUID = Field(description="Made by the client and stable across saves.")
    title: str | None = Field(default=None, max_length=120)


class _LayerWidget(_Widget):
    layer_id: uuid.UUID = Field(description="A layer of the host's map.")
    scope: Literal["layer", "view"] = Field(
        default="layer",
        description="Summarize the whole layer, or only what the map view shows.",
    )


def _column_only_for(stat: Statistic, column: str | None, field: str) -> None:
    if stat == "count" and column is not None:
        raise ValueError(f"{field} must be null when stat is count")
    if stat != "count" and column is None:
        raise ValueError(f"{field} is required unless stat is count")


class MarkdownConfig(_Strict):
    text: str = Field(max_length=20_000)


class ImageConfig(_Strict):
    # Left out of the stored block unless set, so a block that doesn't use
    # them keeps the shape older servers read.
    alt: (
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
        ]
        | None
    ) = Field(
        default=None,
        exclude_if=lambda alt: alt is None,
        description="Text that stands in for the image; required unless it is "
        "decorative.",
    )
    decorative: bool | None = Field(
        default=None,
        exclude_if=lambda decorative: not decorative,
        description="True when the image adds nothing a reader needs: readers get "
        "an empty alt, and `alt` may be left out.",
    )
    caption: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _alt_unless_decorative(self) -> "ImageConfig":
        if self.alt is None and not self.decorative:
            raise ValueError("alt is required unless the image is decorative")
        return self


class IndicatorConfig(_Strict):
    stat: Statistic
    column: ColumnName | None = None

    @model_validator(mode="after")
    def _column_matches_stat(self) -> "IndicatorConfig":
        _column_only_for(self.stat, self.column, "column")
        return self


class BarChartConfig(_Strict):
    column: ColumnName = Field(description="The column whose values become bars.")
    stat: Statistic = "count"
    stat_column: ColumnName | None = None
    limit: int = Field(default=10, ge=1, le=50)

    @model_validator(mode="after")
    def _stat_column_matches_stat(self) -> "BarChartConfig":
        _column_only_for(self.stat, self.stat_column, "stat_column")
        return self


class HistogramConfig(_Strict):
    column: ColumnName
    bins: int = Field(default=20, ge=2, le=50)


class CategorySelectorConfig(_Strict):
    column: ColumnName
    multiple: bool = True


class MarkdownWidget(_Widget):
    type: Literal["markdown"]
    v: Literal[1]
    config: MarkdownConfig


class ImageWidget(_Widget):
    type: Literal["image"]
    v: Literal[1]
    asset_id: uuid.UUID = Field(description="An image uploaded to the host story.")
    config: ImageConfig


class IndicatorWidget(_LayerWidget):
    type: Literal["indicator"]
    v: Literal[1]
    config: IndicatorConfig


class BarChartWidget(_LayerWidget):
    type: Literal["bar_chart"]
    v: Literal[1]
    config: BarChartConfig


class HistogramWidget(_LayerWidget):
    type: Literal["histogram"]
    v: Literal[1]
    config: HistogramConfig


class CategorySelectorWidget(_LayerWidget):
    type: Literal["category_selector"]
    v: Literal[1]
    config: CategorySelectorConfig


# (type, v) -> a function that returns the v + 1 form of a v instance. It gets
# a private copy, and the loop stamps the new ``v``.
UPGRADERS: dict[tuple[str, int], Callable[[dict[str, Any]], dict[str, Any]]] = {}


def upgrade(raw: Any) -> Any:
    """Step a known type's older instance up to its current ``v``.

    Anything else comes back as given, for validation to accept or refuse.
    """
    if not isinstance(raw, dict):
        return raw
    kind, v = raw.get("type"), raw.get("v")
    current = CURRENT_VERSIONS.get(kind) if isinstance(kind, str) else None
    if current is None or type(v) is not int or v >= current:
        return raw
    upgraded = copy.deepcopy(raw)
    while v < current:
        step = UPGRADERS.get((kind, v))
        if step is None:
            return raw
        try:
            upgraded = {**step(upgraded), "v": v + 1}
        except Exception as exc:  # broad: upgraders run on arbitrary stored JSON
            # A ValueError here becomes a ValidationError: set aside on read, 422 on write.
            raise ValueError(f"{kind} v{v} could not be upgraded") from exc
        v += 1
    return upgraded


def _unique_ids(widgets: list[Any]) -> list[Any]:
    seen: set[uuid.UUID] = set()
    for widget in widgets:
        if widget.id in seen:
            raise ValueError(f"widget id {widget.id} appears more than once")
        seen.add(widget.id)
    return widgets


DashboardWidget = Annotated[
    MarkdownWidget
    | IndicatorWidget
    | BarChartWidget
    | HistogramWidget
    | CategorySelectorWidget,
    Field(discriminator="type"),
    BeforeValidator(upgrade),
]
StoryBlock = Annotated[
    MarkdownWidget | ImageWidget,
    Field(discriminator="type"),
    BeforeValidator(upgrade),
]
DashboardWidgets = Annotated[list[DashboardWidget], AfterValidator(_unique_ids)]
StoryBlocks = Annotated[list[StoryBlock], AfterValidator(_unique_ids)]

_HOST_UNIONS: dict[WidgetHost, Any] = {
    "dashboard": DashboardWidget,
    "story": StoryBlock,
}
HOST_WIDGET_MODELS: dict[WidgetHost, tuple[type[_Widget], ...]] = {
    host: get_args(get_args(union)[0]) for host, union in _HOST_UNIONS.items()
}


def _literal(model: type[BaseModel], field: str) -> Any:
    return get_args(model.model_fields[field].annotation)[0]


CURRENT_VERSIONS: dict[str, int] = {
    _literal(model, "type"): _literal(model, "v")
    for models in HOST_WIDGET_MODELS.values()
    for model in models
}
_HOST_ADAPTERS: dict[WidgetHost, TypeAdapter[Any]] = {
    host: TypeAdapter(union) for host, union in _HOST_UNIONS.items()
}


class KeptWidget(NamedTuple):
    """A stored item the client never sees, and where it goes back on a save."""

    after: tuple[str, ...]
    """Ids of the visible instances stored before it, nearest first."""
    raw: Any


class StoredWidgets(NamedTuple):
    """Current-shape instances to return, and the stored items set aside."""

    widgets: list[Any]
    unreadable: list[KeptWidget]


def read_stored(stored: Sequence[Any] | None, host: WidgetHost) -> StoredWidgets:
    """Parse a host's stored instances, upgrading old ones and setting aside the rest.

    Never raises on stored content: after a downgrade, the database can hold
    types and versions this server has never seen.
    """
    adapter = _HOST_ADAPTERS[host]
    widgets: list[Any] = []
    unreadable: list[KeptWidget] = []
    for index, raw in enumerate(stored or ()):
        parsed = None
        try:
            parsed = adapter.validate_python(raw)
        except ValidationError:
            pass
        if parsed is not None:
            widgets.append(parsed)
        else:
            after = tuple(str(widget.id) for widget in reversed(widgets))
            unreadable.append(KeptWidget(after, raw))
            meta = raw if isinstance(raw, dict) else {}
            logger.info(
                "widget_unreadable_kept",
                host=host,
                index=index,
                widget_type=meta.get("type"),
                widget_v=meta.get("v"),
            )
    return StoredWidgets(widgets, unreadable)


def to_store(sent: Sequence[_Widget], kept: Iterable[KeptWidget]) -> list[Any]:
    """The list to persist: the client's instances plus stored ones it never saw.

    Each kept item goes back unchanged, in stored order, right after the
    nearest visible instance stored before it that the client still sends, or
    first when there is none. The client can reorder and delete around kept
    items but never delete one, so an older client can't remove a widget it
    can't parse. A sent instance with the same id replaces a kept one.
    """
    rows: list[tuple[bool, Any]] = [
        (False, widget.model_dump(mode="json")) for widget in sent
    ]
    sent_ids = {str(widget.id) for widget in sent}
    for item in kept:
        if isinstance(item.raw, dict) and str(item.raw.get("id")) in sent_ids:
            continue
        sent_positions = {
            row["id"]: i for i, (is_kept, row) in enumerate(rows) if not is_kept
        }
        anchor = next(
            (sent_positions[a] for a in item.after if a in sent_positions), -1
        )
        position = anchor + 1
        # Earlier kept items with the same anchor stay ahead of this one.
        while position < len(rows) and rows[position][0]:
            position += 1
        rows.insert(position, (True, item.raw))
    return [row for _, row in rows]
