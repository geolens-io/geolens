"""A map's dashboard: an ordered list of widgets on the map's layers.

The dashboard has no access model of its own. A reader sees the widgets on the
layers the map response shows them, and a save keeps, where they were, the
stored widgets on layers the editor can't read and the ones this server can't
parse.
"""

import uuid
from collections.abc import Collection, Mapping
from typing import Annotated, Any, Literal, get_args

from fastapi import HTTPException, status
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
)

from app.modules.catalog.widgets.schemas import (
    BarChartWidget,
    IndicatorWidget,
    KeptWidget,
    read_stored,
    to_store,
    upgrade,
)

DASHBOARD_CONFIG_VERSION = 1
MAX_DASHBOARD_WIDGETS = 50
# The dashboard types clients register. A stored widget of another type is set
# aside and put back on save, like one this server can't parse, so a client
# that can't show it never drops it by leaving it out.
_Registered = IndicatorWidget | BarChartWidget
_ACCEPTED = get_args(_Registered)
AcceptedWidget = Annotated[
    _Registered,
    Field(discriminator="type"),
    BeforeValidator(upgrade),
]
_REFUSED = "Some dashboard widgets can't be saved on this map"


class DashboardConfigInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = DASHBOARD_CONFIG_VERSION
    widgets: list[AcceptedWidget] = Field(
        default_factory=list,
        max_length=MAX_DASHBOARD_WIDGETS,
        description=(
            "Widgets in panel order. Each names a layer of this map that you "
            "can read. Stored widgets you can't see are kept in place."
        ),
    )

    @field_validator("widgets")
    @classmethod
    def _unique_ids(cls, widgets: list[Any]) -> list[Any]:
        ids = [widget.id for widget in widgets]
        if len(set(ids)) != len(ids):
            raise ValueError("widget ids must be unique")
        return widgets


class DashboardConfig(BaseModel):
    version: int
    widgets: list[AcceptedWidget] = Field(
        description="The widgets on layers this response shows, in panel order."
    )


def _stored_widgets(stored: Any) -> list[Any]:
    widgets = stored.get("widgets") if isinstance(stored, dict) else None
    return widgets if isinstance(widgets, list) else []


def _stored_version(stored: Any) -> int:
    version = stored.get("version") if isinstance(stored, dict) else None
    return version if type(version) is int else DASHBOARD_CONFIG_VERSION


def _parsed(raw: Any) -> Any | None:
    widgets = read_stored([raw], "dashboard").widgets
    return widgets[0] if widgets else None


def _raw_id(raw: Any) -> str | None:
    """The id of a stored widget this server can't parse, as a parsed id reads."""
    try:
        return str(uuid.UUID(str(raw["id"])))
    except (KeyError, TypeError, ValueError):
        return None


def render_dashboard(
    stored: Any, layer_ids: Collection[uuid.UUID | str]
) -> DashboardConfig | None:
    """The stored dashboard as a reader sees it: only widgets on ``layer_ids``.

    None when no widget is left to show.
    """
    shown = {str(layer_id) for layer_id in layer_ids}
    widgets = [
        widget
        for widget in read_stored(_stored_widgets(stored), "dashboard").widgets
        if isinstance(widget, _ACCEPTED) and str(widget.layer_id) in shown
    ]
    if not widgets:
        return None
    return DashboardConfig(version=_stored_version(stored), widgets=widgets)


def merge_dashboard(
    sent: DashboardConfigInput | None,
    stored: Any,
    *,
    layer_ids: Collection[uuid.UUID],
    hidden_layer_ids: Collection[uuid.UUID],
) -> dict[str, Any] | None:
    """The dashboard to store for a save; ``sent=None`` removes what the editor sees.

    ``layer_ids`` are the map's layers after the save and ``hidden_layer_ids``
    those among them whose dataset the editor can't read.

    A stored widget on a hidden layer, or one the editor's client can't show,
    goes back next to the widget stored before it. A stored widget on a layer
    the map no longer has is dropped. A sent widget
    must be on a readable layer and may not reuse the id of a widget that goes
    back unseen (422). The result holds at most
    ``MAX_DASHBOARD_WIDGETS`` widgets (422).
    """
    if _stored_version(stored) > DASHBOARD_CONFIG_VERSION:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This dashboard was saved by a newer version of GeoLens and "
                "can't be changed here."
            ),
        )
    sent_widgets = sent.widgets if sent is not None else []
    known = {str(layer_id) for layer_id in layer_ids}
    hidden = {str(layer_id) for layer_id in hidden_layer_ids}
    readable = known - hidden

    kept: list[KeptWidget] = []
    locked_ids: set[str] = set()
    shown_before: list[str] = []
    for raw in _stored_widgets(stored):
        widget = _parsed(raw)
        if widget is not None:
            layer_id = str(widget.layer_id)
            if layer_id not in known:
                continue
            if layer_id in readable and isinstance(widget, _ACCEPTED):
                shown_before.append(str(widget.id))
                continue
            locked_ids.add(str(widget.id))
        else:
            unseen_id = _raw_id(raw)
            if unseen_id is not None:
                locked_ids.add(unseen_id)
        kept.append(KeptWidget(tuple(reversed(shown_before)), raw))

    refused = sorted(
        str(w.id)
        for w in sent_widgets
        if str(w.layer_id) not in readable or str(w.id) in locked_ids
    )
    if refused:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"message": _REFUSED, "widget_ids": refused},
        )
    if sent is None and not kept:
        return None
    widgets = to_store(sent_widgets, kept)
    if len(widgets) > MAX_DASHBOARD_WIDGETS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"A dashboard holds at most {MAX_DASHBOARD_WIDGETS} widgets",
        )
    return {"version": DASHBOARD_CONFIG_VERSION, "widgets": widgets}


def drop_repointed(stored: Any, repointed_layer_ids: Collection[uuid.UUID]) -> Any:
    """``stored`` without the widgets on layers a save moved to another dataset.

    Their columns belong to the old dataset. A dashboard a newer server saved
    comes back as stored.
    """
    repointed = {str(layer_id) for layer_id in repointed_layer_ids}
    if not repointed or _stored_version(stored) > DASHBOARD_CONFIG_VERSION:
        return stored
    widgets = _stored_widgets(stored)
    remaining = []
    for raw in widgets:
        widget = _parsed(raw)
        if widget is None or str(widget.layer_id) not in repointed:
            remaining.append(raw)
    if len(remaining) == len(widgets):
        return stored
    return {"version": DASHBOARD_CONFIG_VERSION, "widgets": remaining}


def fork_dashboard(
    stored: Any, copied_layers: Mapping[uuid.UUID, uuid.UUID]
) -> dict[str, Any] | None:
    """The dashboard for a copy of the map, by source layer id -> copied layer id.

    Widgets on layers that weren't copied are dropped, and so are stored items
    this server can't parse, since it can't tell which layers they name. A
    dashboard a newer server saved isn't copied.
    """
    if not isinstance(stored, dict) or _stored_version(stored) != (
        DASHBOARD_CONFIG_VERSION
    ):
        return None
    widgets = []
    for widget in read_stored(_stored_widgets(stored), "dashboard").widgets:
        copied = copied_layers.get(widget.layer_id)
        if copied is not None:
            widgets.append(widget.model_copy(update={"layer_id": copied}))
    return {
        "version": DASHBOARD_CONFIG_VERSION,
        "widgets": [widget.model_dump(mode="json") for widget in widgets],
    }
