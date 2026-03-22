"""GeoJSON response models following OGC API Features conventions."""

from typing import Literal

from pydantic import BaseModel


class GeoJSONFeature(BaseModel):
    """A single GeoJSON Feature."""

    type: Literal["Feature"] = "Feature"
    id: int
    geometry: dict | None = None
    properties: dict


class GeoJSONFeatureCollection(BaseModel):
    """A GeoJSON FeatureCollection with OGC API Features pagination fields."""

    type: Literal["FeatureCollection"] = "FeatureCollection"
    numberMatched: int
    numberReturned: int
    features: list[GeoJSONFeature]
    links: list[dict]


# ---------------------------------------------------------------------------
# Write operation schemas
# ---------------------------------------------------------------------------


class FeatureCreate(BaseModel):
    """GeoJSON-style feature for insertion."""

    geometry: dict  # GeoJSON geometry object
    properties: dict | None = None


class FeatureReplace(BaseModel):
    """Full feature replacement (PUT semantics)."""

    geometry: dict  # Required for full replacement
    properties: dict  # Required — set fields to null explicitly


class FeatureUpdate(BaseModel):
    """Partial feature update (PATCH semantics)."""

    geometry: dict | None = None
    properties: dict | None = None
