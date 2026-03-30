"""GeoJSON response models following OGC API Features conventions."""

from typing import Literal

from pydantic import BaseModel


class GeoJSONGeometry(BaseModel):
    """A GeoJSON geometry object (RFC 7946)."""

    type: str  # "Point", "MultiPoint", "LineString", "Polygon", etc.
    coordinates: list


class GeoJSONFeature(BaseModel):
    """A single GeoJSON Feature."""

    type: Literal["Feature"] = "Feature"
    id: int
    geometry: GeoJSONGeometry | None = None
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

    geometry: GeoJSONGeometry
    properties: dict | None = None


class FeatureReplace(BaseModel):
    """Full feature replacement (PUT semantics)."""

    geometry: GeoJSONGeometry  # Required for full replacement
    properties: dict  # Required — set fields to null explicitly


class FeatureUpdate(BaseModel):
    """Partial feature update (PATCH semantics)."""

    geometry: GeoJSONGeometry | None = None
    properties: dict | None = None
