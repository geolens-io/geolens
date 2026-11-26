"""A map's bookmarks: named areas a viewer can jump to, in display order."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.core.text import normalize_nfc

MAX_MAP_BOOKMARKS = 100


class MapBookmark(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
    ] = Field(description="Bookmark name")
    extent: list[float] = Field(
        min_length=4,
        max_length=4,
        description=(
            "[west, south, east, north] in EPSG:4326. A west greater than east "
            "means the area crosses the antimeridian."
        ),
    )
    bearing: float | None = Field(
        default=None,
        ge=-180,
        le=180,
        allow_inf_nan=False,
        description="Map rotation in degrees",
    )
    pitch: float | None = Field(
        default=None,
        ge=0,
        le=85,
        allow_inf_nan=False,
        description="Map tilt in degrees (0-85)",
    )

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, v: object) -> object:
        return normalize_nfc(v) if isinstance(v, str) else v

    @field_validator("extent")
    @classmethod
    def extent_in_range(cls, v: list[float]) -> list[float]:
        west, south, east, north = v
        if not all(-180 <= x <= 180 for x in (west, east)):
            raise ValueError("west and east must be between -180 and 180")
        if not all(-90 <= y <= 90 for y in (south, north)):
            raise ValueError("south and north must be between -90 and 90")
        if south > north:
            raise ValueError("south must not exceed north")
        return v


def stored_bookmarks(bookmarks: list[MapBookmark] | None) -> list[dict] | None:
    """The JSON a map row keeps; an empty list is stored as none."""
    if not bookmarks:
        return None
    return [b.model_dump(mode="json") for b in bookmarks]
