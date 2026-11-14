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
from typing import Annotated, Any, ClassVar, Literal, NamedTuple, get_args

import structlog
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from app.core.config import validate_privacy_url_shape
from app.modules.catalog.maps.filter_grammar import bounded_filter, filter_columns
from app.platform.story_frames import (
    MAX_FRAME_URL_LENGTH,
    frame_url_host,
    validate_frame_url,
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


def _widget_filter(value: list[Any] | None) -> list[Any] | None:
    """A layer filter whose columns can all be named, so a save can check them."""
    normalized = bounded_filter(value)
    if normalized is not None:
        filter_columns(normalized)
    return normalized


class _LayerWidget(_Widget):
    # The version that may carry ``filter``; one without a filter stores at
    # ``_base_v``, so older clients still read it.
    _FILTER_V: ClassVar[int] = 2

    layer_id: uuid.UUID = Field(description="A layer of the host's map.")
    scope: Literal["layer", "view"] = Field(
        default="layer",
        description="Summarize the whole layer, or only what the map view shows.",
    )
    filter: Annotated[list[Any] | None, AfterValidator(_widget_filter)] = Field(
        default=None,
        exclude_if=lambda v: v is None,
        description="Count only the features this MapLibre filter expression "
        "keeps, in the form a layer's `filter` takes, on top of the layer's "
        "own filter. Each column it names must be one of the layer's, named "
        "directly rather than computed. Needs "
        "the type's filter version; left out, the widget covers what its "
        "layer shows.",
    )

    def _base_v(self) -> int:
        return 1

    @model_validator(mode="after")
    def _stamp_version(self) -> "_LayerWidget":
        self.v = self._FILTER_V if self.filter is not None else self._base_v()
        return self


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


MAX_GALLERY_IMAGES = 12


class GalleryImage(ImageConfig):
    asset_id: uuid.UUID = Field(description="An image uploaded to the host story.")


class ButtonConfig(_Strict):
    label: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
    ]
    url: Annotated[
        str,
        StringConstraints(max_length=2048),
        AfterValidator(validate_privacy_url_shape),
    ] = Field(description="An http or https address; any other scheme is refused.")
    new_tab: StrictBool = Field(
        default=False, description="Open the link in a new tab."
    )


class FrameConfig(_Strict):
    url: Annotated[
        str,
        StringConstraints(max_length=MAX_FRAME_URL_LENGTH),
        AfterValidator(validate_frame_url),
    ] = Field(
        description="An https address on a host an admin approved for stories. "
        "Stored as given and never fetched by the server."
    )
    title: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ] = Field(description="Names the frame for screen readers.")


class SeparatorConfig(_Strict):
    style: Literal["line", "gap"] = Field(
        default="line", description="A thin line, or a larger empty gap."
    )


_INDICATOR_REFERENCE_KEYS = frozenset(
    {"reference", "reference_label", "higher_is_better", "comparison"}
)


class IndicatorConfig(_Strict):
    # The reference options are left out while at their defaults, so an
    # indicator without a reference keeps the shape older clients read.
    stat: Statistic
    column: ColumnName | None = None
    reference: float | None = Field(
        exclude_if=lambda v: v is None,
        default=None,
        strict=True,
        allow_inf_nan=False,
        description="A fixed number to compare the value with. The indicator "
        "shows the difference from it.",
    )
    reference_label: str | None = Field(
        exclude_if=lambda v: v is None,
        default=None,
        min_length=1,
        max_length=40,
        description="A short name for the reference, such as `Target`. Needs "
        "`reference`.",
    )
    higher_is_better: bool | None = Field(
        exclude_if=lambda v: v is None,
        default=None,
        description="Whether a value above the reference is the good outcome. "
        "Absent means true.",
    )
    comparison: Literal["value", "percent", "both"] | None = Field(
        exclude_if=lambda v: v is None,
        default=None,
        description="Show the difference as a `value`, a `percent` change, or "
        "`both`. Absent means `both`.",
    )

    @model_validator(mode="after")
    def _column_matches_stat(self) -> "IndicatorConfig":
        _column_only_for(self.stat, self.column, "column")
        if self.reference is None and self.reference_label is not None:
            raise ValueError("reference_label needs a reference")
        return self


class BarChartConfig(_Strict):
    # The options added with chart modes are left out while at their defaults,
    # so a plain category chart keeps the shape older clients read.
    mode: Literal["category", "by_feature", "by_fields", "date"] = Field(
        exclude_if=lambda v: v == "category",
        default="category",
        description="`category`: one bar per value of `column`. `by_feature`: one "
        "bar per feature, labelled by `label_column`, sized by `value_column`. "
        "`by_fields`: one bar per name in `fields`, each showing `stat` of that "
        "field. `date`: `column` grouped by `date_bucket`.",
    )
    column: ColumnName | None = Field(
        default=None,
        description="The column whose values become bars (`category` and `date`).",
    )
    stat: Statistic = "count"
    stat_column: ColumnName | None = None
    limit: int = Field(default=10, ge=1, le=50)
    label_column: ColumnName | None = Field(
        exclude_if=lambda v: v is None,
        default=None,
        description="`by_feature`: the field that labels each bar.",
    )
    value_column: ColumnName | None = Field(
        exclude_if=lambda v: v is None,
        default=None,
        description="`by_feature`: the numeric field that sizes each bar.",
    )
    sort: Literal["asc", "desc"] = Field(
        exclude_if=lambda v: v == "desc",
        default="desc",
        description="`by_feature`: bar order by value.",
    )
    fields: list[ColumnName] = Field(
        exclude_if=lambda v: not v,
        default_factory=list,
        max_length=20,
        description="`by_fields`: the numeric fields to chart, one bar each.",
    )
    date_bucket: Literal["day", "week", "month", "year"] | None = Field(
        exclude_if=lambda v: v is None,
        default=None,
        description="`date`: the span each bar covers.",
    )
    use_layer_colors: bool = Field(
        exclude_if=lambda v: v is True,
        default=True,
        description="`category`: colour bars as the layer does when `column` is its "
        "style column.",
    )

    @model_validator(mode="after")
    def _fields_match_mode(self) -> "BarChartConfig":
        if self.mode in ("category", "date") and self.column is None:
            raise ValueError(f"column is required when mode is {self.mode}")
        if self.mode == "by_feature":
            if self.label_column is None or self.value_column is None:
                raise ValueError(
                    "label_column and value_column are required when mode is by_feature"
                )
        if self.mode == "by_fields":
            if not self.fields:
                raise ValueError("fields is required when mode is by_fields")
            if len(set(self.fields)) != len(self.fields):
                raise ValueError("fields must not repeat a name")
        if self.mode == "date" and self.date_bucket is None:
            raise ValueError("date_bucket is required when mode is date")
        if self.mode in ("category", "date"):
            _column_only_for(self.stat, self.stat_column, "stat_column")
        stray = {
            "column": self.column is not None
            and self.mode in ("by_feature", "by_fields"),
            "label_column": self.label_column is not None and self.mode != "by_feature",
            "value_column": self.value_column is not None and self.mode != "by_feature",
            "stat_column": self.stat_column is not None
            and self.mode in ("by_feature", "by_fields"),
            "sort": self.sort != "desc" and self.mode != "by_feature",
            "fields": bool(self.fields) and self.mode != "by_fields",
            "date_bucket": self.date_bucket is not None and self.mode != "date",
            "use_layer_colors": not self.use_layer_colors and self.mode != "category",
        }
        for name, set_ in stray.items():
            if set_:
                raise ValueError(f"{name} does not apply when mode is {self.mode}")
        return self


class PieChartConfig(_Strict):
    column: ColumnName = Field(description="The column whose values become slices.")
    stat: Statistic = "count"
    stat_column: ColumnName | None = None
    limit: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Slices beyond this many are merged into Other.",
    )
    use_layer_colors: bool = Field(
        default=True,
        description="Colour slices as the layer does when `column` is its style column.",
    )

    @model_validator(mode="after")
    def _stat_column_matches_stat(self) -> "PieChartConfig":
        _column_only_for(self.stat, self.stat_column, "stat_column")
        return self


class FeatureListConfig(_Strict):
    title_column: ColumnName
    subtitle_column: ColumnName | None = None
    sort_column: ColumnName | None = None
    sort: Literal["asc", "desc"] = "asc"
    page_size: int = Field(default=25, ge=10, le=100)


class TableStat(_Strict):
    stat: Statistic
    column: ColumnName | None = None

    @model_validator(mode="after")
    def _column_matches_stat(self) -> "TableStat":
        _column_only_for(self.stat, self.column, "column")
        return self


class TableConfig(_Strict):
    group_column: ColumnName
    stats: list[TableStat] = Field(min_length=1, max_length=5)
    sort_by: int | None = Field(
        default=None,
        description="The index in `stats` of the statistic to sort by; leave it "
        "out to sort by the group value.",
    )
    sort: Literal["asc", "desc"] = "desc"
    limit: int = Field(default=10, ge=1, le=50)

    @model_validator(mode="after")
    def _sort_by_names_a_stat(self) -> "TableConfig":
        if self.sort_by is not None and not 0 <= self.sort_by < len(self.stats):
            raise ValueError("sort_by must be an index into stats")
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


class GalleryConfig(_Strict):
    images: list[GalleryImage] = Field(
        min_length=1,
        max_length=MAX_GALLERY_IMAGES,
        description="Images uploaded to the host story, in reading order.",
    )


class GalleryWidget(_Widget):
    type: Literal["gallery"]
    v: Literal[1]
    config: GalleryConfig


class CarouselWidget(_Widget):
    type: Literal["carousel"]
    v: Literal[1]
    config: GalleryConfig


class EmbedWidget(_Widget):
    type: Literal["embed"]
    v: Literal[1]
    config: FrameConfig


class VideoWidget(_Widget):
    type: Literal["video"]
    v: Literal[1]
    config: FrameConfig


class ButtonWidget(_Widget):
    type: Literal["button"]
    v: Literal[1]
    config: ButtonConfig


class SeparatorWidget(_Widget):
    type: Literal["separator"]
    v: Literal[1]
    config: SeparatorConfig


class IndicatorWidget(_LayerWidget):
    _FILTER_V: ClassVar[int] = 3
    type: Literal["indicator"]
    # v2 is an indicator with reference options and v3 one with a filter; a
    # client that reads only older versions leaves it as stored.
    v: Literal[1, 2, 3] = Field(
        description="`3` with a `filter`, else `2` when the config sets any "
        "reference option, else `1`. An older `v` that sets one is refused."
    )
    config: IndicatorConfig

    def _base_v(self) -> int:
        sent = self.config.model_fields_set & _INDICATOR_REFERENCE_KEYS
        return 2 if sent else 1


class BarChartWidget(_LayerWidget):
    _FILTER_V: ClassVar[int] = 3
    type: Literal["bar_chart"]
    # v1 is a plain category chart, v2 any other option and v3 a filter, which
    # older clients and servers set aside instead of misreading.
    v: Literal[1, 2, 3]
    config: BarChartConfig

    def _base_v(self) -> int:
        plain = self.config.mode == "category" and self.config.use_layer_colors
        return 1 if plain else 2


class PieChartWidget(_LayerWidget):
    type: Literal["pie_chart"]
    v: Literal[1, 2]
    config: PieChartConfig


class FeatureListWidget(_LayerWidget):
    type: Literal["feature_list"]
    v: Literal[1, 2]
    config: FeatureListConfig


class TableWidget(_LayerWidget):
    type: Literal["table"]
    v: Literal[1, 2]
    config: TableConfig


class HistogramWidget(_LayerWidget):
    type: Literal["histogram"]
    v: Literal[1, 2]
    config: HistogramConfig


class CategorySelectorWidget(_LayerWidget):
    type: Literal["category_selector"]
    v: Literal[1, 2]
    config: CategorySelectorConfig


def _indicator_v1_to_v2(widget: dict[str, Any]) -> dict[str, Any]:
    config = widget.get("config")
    if isinstance(config, dict) and config.keys() & _INDICATOR_REFERENCE_KEYS:
        raise ValueError("reference options need indicator version 2")
    return widget


def _refuse_filter(widget: dict[str, Any]) -> dict[str, Any]:
    if widget.get("filter"):
        raise ValueError("a filter needs the type's filter version")
    return widget


# (type, v) -> a function that returns the v + 1 form of a v instance. It gets
# a private copy, and the loop stamps the new ``v``.
UPGRADERS: dict[tuple[str, int], Callable[[dict[str, Any]], dict[str, Any]]] = {
    ("bar_chart", 1): lambda widget: widget,
    ("indicator", 1): lambda widget: _indicator_v1_to_v2(widget),
    ("indicator", 2): _refuse_filter,
    ("bar_chart", 2): _refuse_filter,
    ("pie_chart", 1): _refuse_filter,
    ("feature_list", 1): _refuse_filter,
    ("table", 1): _refuse_filter,
    ("histogram", 1): _refuse_filter,
    ("category_selector", 1): _refuse_filter,
}


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
    | PieChartWidget
    | FeatureListWidget
    | TableWidget
    | HistogramWidget
    | CategorySelectorWidget,
    Field(discriminator="type"),
    BeforeValidator(upgrade),
]
StoryBlock = Annotated[
    MarkdownWidget
    | ImageWidget
    | GalleryWidget
    | CarouselWidget
    | ButtonWidget
    | SeparatorWidget
    | EmbedWidget
    | VideoWidget,
    Field(discriminator="type"),
    BeforeValidator(upgrade),
]


def block_asset_ids(block: Any) -> set[uuid.UUID]:
    """The story images a story block shows."""
    if isinstance(block, ImageWidget):
        return {block.asset_id}
    if isinstance(block, GalleryWidget | CarouselWidget):
        return {image.asset_id for image in block.config.images}
    return set()


def block_frame_host(block: Any) -> str | None:
    """The host an embed or video block frames; None for any other block."""
    if isinstance(block, EmbedWidget | VideoWidget):
        return frame_url_host(block.config.url)
    return None


def block_with_assets_renamed(block: Any, names: dict[uuid.UUID, uuid.UUID]) -> Any:
    """``block`` pointing at the images in ``names``, or None when none of its
    images are there. A gallery keeps the images that were copied."""
    if isinstance(block, ImageWidget):
        if block.asset_id not in names:
            return None
        return block.model_copy(update={"asset_id": names[block.asset_id]})
    if isinstance(block, GalleryWidget | CarouselWidget):
        images = [
            image.model_copy(update={"asset_id": names[image.asset_id]})
            for image in block.config.images
            if image.asset_id in names
        ]
        if not images:
            return None
        return block.model_copy(update={"config": GalleryConfig(images=images)})
    return block


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
    _literal(model, "type"): max(get_args(model.model_fields["v"].annotation))
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
