"""GeoJSON response models following OGC API Features conventions."""

from typing import Any, Literal

from pydantic import BaseModel


class GeoJSONGeometry(BaseModel):
    """A GeoJSON geometry object (RFC 7946)."""

    type: str  # "Point", "MultiPoint", "LineString", "Polygon", etc.
    coordinates: list[Any]


class GeoJSONGeometryCollection(BaseModel):
    """A GeoJSON GeometryCollection (RFC 7946 §3.1.8).

    fix(#430 codex r9): carries ``geometries`` instead of ``coordinates``, so
    it needs its own model — only generic-GEOMETRY datasets accept it on write
    (enforced in the service), and any stored collection must serialize back
    out on read.
    """

    type: Literal["GeometryCollection"]
    geometries: list[GeoJSONGeometry]


# Discriminated by the Literal type on the collection variant; plain geometries
# keep their exact prior wire shape.
GeoJSONGeometryLike = GeoJSONGeometryCollection | GeoJSONGeometry


class GeoJSONFeature(BaseModel):
    """A single GeoJSON Feature."""

    type: Literal["Feature"] = "Feature"
    id: int
    geometry: GeoJSONGeometryLike | None = None
    properties: dict


class Link(BaseModel):
    rel: str
    href: str
    type: str


class GeoJSONFeatureCollection(BaseModel):
    """A GeoJSON FeatureCollection with OGC API Features pagination fields."""

    type: Literal["FeatureCollection"] = "FeatureCollection"
    numberMatched: int
    numberReturned: int
    features: list[GeoJSONFeature]
    links: list[Link]


# ---------------------------------------------------------------------------
# Write operation schemas
# ---------------------------------------------------------------------------


class FeatureCreate(BaseModel):
    """GeoJSON-style feature for insertion."""

    geometry: GeoJSONGeometryLike
    properties: dict | None = None


class FeatureReplace(BaseModel):
    """Full feature replacement (PUT semantics)."""

    geometry: GeoJSONGeometryLike  # Required for full replacement
    properties: dict  # Required — set fields to null explicitly


class FeatureUpdate(BaseModel):
    """Partial feature update (PATCH semantics)."""

    geometry: GeoJSONGeometryLike | None = None
    properties: dict | None = None
