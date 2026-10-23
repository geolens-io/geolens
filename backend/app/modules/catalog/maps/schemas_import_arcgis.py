"""Request and response models for importing an ArcGIS web map."""

from __future__ import annotations

import json
import uuid
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.core.text import normalize_nfc as _nfc
from app.modules.catalog.maps.schemas import MapLayerInput, MapResponse, MapVisibility

MAX_WEBMAP_BYTES = 1_000_000
MAX_OPERATIONAL_LAYERS = 2000
_MAX_MATCHES = 1000
_MAX_BASEMAPS = 100


def _count_layers(layers: Any) -> int:
    """Operational layers including group members; iterative, so nesting can't recurse."""
    count = 0
    stack = [layers]
    while stack:
        current = stack.pop()
        if not isinstance(current, list):
            continue
        count += len(current)
        if count > MAX_OPERATIONAL_LAYERS:
            break
        stack.extend(item.get("layers") for item in current if isinstance(item, dict))
    return count


class ArcgisWebmapImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    webmap: dict[str, Any] = Field(
        description="The web map item data JSON, at most 1 MB serialized."
    )
    name: Annotated[str, StringConstraints(min_length=1, max_length=255)] | None = (
        Field(default=None, description="Map name. Defaults to `title`.")
    )
    title: Annotated[str, StringConstraints(min_length=1, max_length=255)] | None = (
        Field(default=None, description="The web map item's title.")
    )
    visibility: MapVisibility = Field(
        default=MapVisibility.private,
        description=(
            "Visibility of the new map: private, internal or public. A map "
            "becomes restricted by sharing it with groups afterwards."
        ),
    )
    basemap_map: dict[str, Annotated[str, StringConstraints(max_length=255)]] = Field(
        default_factory=dict,
        description=(
            "Esri basemap URL or style URL (the first base map layer's `url` or "
            "`styleUrl`) to a GeoLens basemap id. An unmapped basemap falls back to "
            "the first enabled basemap and is reported."
        ),
    )
    dataset_matches: dict[str, uuid.UUID] = Field(
        default_factory=dict,
        description=(
            "Operational layer id to GeoLens dataset id. Every dataset must be one "
            "the caller can read, or the request is refused with 404. A layer with "
            "no entry is not imported and is listed as unmatched."
        ),
    )
    dry_run: bool = Field(
        default=False,
        description="Return the translation without creating a map.",
    )

    @field_validator("name", "title", mode="before")
    @classmethod
    def _normalize_nfc(cls, v: str | None) -> str | None:
        return _nfc(v)

    @field_validator("visibility")
    @classmethod
    def _not_restricted(cls, v: MapVisibility) -> MapVisibility:
        if v == MapVisibility.restricted:
            raise ValueError("a new map can't be restricted before it has groups")
        return v

    @field_validator("webmap")
    @classmethod
    def _cap_webmap_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        size = len(json.dumps(v, separators=(",", ":"), ensure_ascii=False).encode())
        if size > MAX_WEBMAP_BYTES:
            raise ValueError(f"webmap exceeds {MAX_WEBMAP_BYTES} bytes")
        if _count_layers(v.get("operationalLayers")) > MAX_OPERATIONAL_LAYERS:
            raise ValueError(
                f"webmap has more than {MAX_OPERATIONAL_LAYERS} operational layers"
            )
        return v

    @field_validator("dataset_matches")
    @classmethod
    def _cap_matches(cls, v: dict[str, uuid.UUID]) -> dict[str, uuid.UUID]:
        if len(v) > _MAX_MATCHES:
            raise ValueError(f"at most {_MAX_MATCHES} dataset matches")
        return v

    @field_validator("basemap_map")
    @classmethod
    def _cap_basemaps(cls, v: dict[str, str]) -> dict[str, str]:
        if len(v) > _MAX_BASEMAPS:
            raise ValueError(f"at most {_MAX_BASEMAPS} basemap entries")
        return v


class ArcgisLossItem(BaseModel):
    path: str = Field(
        description="JSON path of the web map part that was not carried over."
    )
    kind: str = Field(description="Stable code for the kind of loss.")
    detail: str = Field(default="", description="Free text; not localized.")


class ArcgisLossReport(BaseModel):
    items: list[ArcgisLossItem]
    summary: dict[str, int] = Field(description="Item count per `kind`.")


class ArcgisUnmatchedLayer(BaseModel):
    layer_id: str
    title: str
    url: str
    reason: str = Field(description="`no_match` or `invalid`.")


class ArcgisWebmapImportResponse(BaseModel):
    map: MapResponse | None = Field(description="The new map; null on a dry run.")
    layers: list[MapLayerInput] = Field(
        description="The translated layers, in draw order."
    )
    layer_ids: dict[str, uuid.UUID] = Field(
        default_factory=dict,
        description=(
            "Operational layer id to the id of the map layer created for it. "
            "Layers that were not imported are absent; see `loss_report`. "
            "Empty on a dry run."
        ),
    )
    loss_report: ArcgisLossReport
    unmatched_layers: list[ArcgisUnmatchedLayer]
