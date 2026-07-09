"""GeoJSON response models following OGC API Features conventions."""

from typing import Any, Literal

from pydantic import BaseModel, model_validator


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

    Deliberately NON-recursive (codex r13, refuted): PostGIS cannot round-trip
    nested collections through the GeoJSON boundary in either direction —
    ST_GeomFromGeoJSON rejects them on write and ST_AsGeoJSON raises
    'GeoJson: geometry not supported' on read — so a recursive model could
    never receive one and would only convert the write-side 422 into a raw
    database 500. The write schemas add a raw-payload guard for a clear 422.
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


def _reject_nested_collections(data: object) -> object:
    """Raw-payload guard for GeometryCollection writes (codex r13/r14).

    Runs mode='before' so it fires ahead of union parsing:

    - r13: nested collections get a clear 422 — the non-recursive
      GeoJSONGeometryCollection would otherwise reject the nested child with
      a misleading 'coordinates: Field required'. Nesting is unsupported by
      PostGIS on both sides of the GeoJSON boundary (see the model docstring).
    - r14: a collection WITHOUT a 'geometries' array (e.g. carrying
      'coordinates' instead) would otherwise sneak through the union's broad
      GeoJSONGeometry member (type is plain str), pass the generic-dataset
      type check by map presence, and blow up inside ST_GeomFromGeoJSON as a
      raw database error.
    """
    if isinstance(data, dict):
        geometry = data.get("geometry")
        if isinstance(geometry, dict) and geometry.get("type") == "GeometryCollection":
            geometries = geometry.get("geometries")
            if not isinstance(geometries, list):
                raise ValueError("GeometryCollection requires a 'geometries' array.")
            for child in geometries:
                if (
                    isinstance(child, dict)
                    and child.get("type") == "GeometryCollection"
                ):
                    raise ValueError(
                        "Nested GeometryCollections are not supported; "
                        "flatten the collection into a single level."
                    )
    return data


class FeatureCreate(BaseModel):
    """GeoJSON-style feature for insertion."""

    geometry: GeoJSONGeometryLike
    properties: dict | None = None

    @model_validator(mode="before")
    @classmethod
    def _no_nested_collections(cls, data: object) -> object:
        return _reject_nested_collections(data)


class FeatureReplace(BaseModel):
    """Full feature replacement (PUT semantics)."""

    geometry: GeoJSONGeometryLike  # Required for full replacement
    properties: dict  # Required — set fields to null explicitly

    @model_validator(mode="before")
    @classmethod
    def _no_nested_collections(cls, data: object) -> object:
        return _reject_nested_collections(data)


class FeatureUpdate(BaseModel):
    """Partial feature update (PATCH semantics)."""

    geometry: GeoJSONGeometryLike | None = None
    properties: dict | None = None

    @model_validator(mode="before")
    @classmethod
    def _no_nested_collections(cls, data: object) -> object:
        return _reject_nested_collections(data)
