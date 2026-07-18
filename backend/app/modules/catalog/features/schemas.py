"""GeoJSON response models following OGC API Features conventions."""

import math
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, model_validator


MAX_COORDINATE_TUPLES = 100_000
MAX_COORDINATE_DEPTH = 8
MAX_GEOMETRY_COLLECTION_MEMBERS = 1_000
MAX_POSITION_DIMENSIONS = 4


def inline_json_schema(model: type[BaseModel]) -> dict:
    """``model_json_schema()`` with local ``$defs`` inlined.

    Schemas passed raw through route ``responses=`` are embedded verbatim in
    the exported OpenAPI document, where pydantic's ``#/$defs/...`` pointers
    resolve against the document root and dangle — strict consumers (docs
    generators, ref bundlers) reject the whole document. Only safe for
    non-recursive models; a recursive model raises instead of looping
    (fix(#569): cycle guard so a future self-referential model fails fast
    with a clear error at import time rather than hanging).
    """
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node: Any, expanding: frozenset[str] = frozenset()) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                name = ref.rsplit("/", 1)[-1]
                if name in expanding:
                    raise ValueError(
                        f"inline_json_schema({model.__name__}): recursive "
                        f"$ref to {name!r}; only acyclic models can be inlined"
                    )
                target = resolve(defs[name], expanding | {name})
                # Keep sibling keys (description, default) over the target's.
                extras = {
                    k: resolve(v, expanding) for k, v in node.items() if k != "$ref"
                }
                return {**target, **extras}
            return {k: resolve(v, expanding) for k, v in node.items()}
        if isinstance(node, list):
            return [resolve(item, expanding) for item in node]
        return node

    return resolve(schema)


def _coordinate_tuple_count(coordinates: object) -> int:
    """Validate a GeoJSON coordinate tree and return its position count."""
    if not isinstance(coordinates, list):
        raise ValueError("GeoJSON coordinates must be arrays.")

    count = 0
    stack: list[tuple[list[Any], int]] = [(coordinates, 0)]
    while stack:
        current, depth = stack.pop()
        if depth > MAX_COORDINATE_DEPTH:
            raise ValueError(
                f"GeoJSON coordinate nesting exceeds {MAX_COORDINATE_DEPTH} levels."
            )
        if not current:
            continue

        first = current[0]
        if isinstance(first, (int, float)) and not isinstance(first, bool):
            if not 2 <= len(current) <= MAX_POSITION_DIMENSIONS:
                raise ValueError(
                    "GeoJSON positions must contain between 2 and "
                    f"{MAX_POSITION_DIMENSIONS} numeric values."
                )
            if any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or (isinstance(value, float) and not math.isfinite(value))
                for value in current
            ):
                raise ValueError("GeoJSON positions must contain finite numbers.")
            longitude = current[0]
            latitude = current[1]
            if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
                raise ValueError(
                    "GeoJSON longitude/latitude must be within WGS84 bounds."
                )
            count += 1
            if count > MAX_COORDINATE_TUPLES:
                raise ValueError(
                    "GeoJSON geometry exceeds the "
                    f"{MAX_COORDINATE_TUPLES} coordinate limit."
                )
            continue

        for child in current:
            if not isinstance(child, list):
                raise ValueError(
                    "GeoJSON coordinate arrays may contain only positions or arrays."
                )
            stack.append((child, depth + 1))

    return count


class GeoJSONGeometry(BaseModel):
    """A GeoJSON geometry object (RFC 7946)."""

    type: Literal[
        "Point",
        "MultiPoint",
        "LineString",
        "MultiLineString",
        "Polygon",
        "MultiPolygon",
    ]
    coordinates: list[Any]


def _bounded_geometry(value: GeoJSONGeometry) -> GeoJSONGeometry:
    """Apply coordinate budgets to a geometry at the feature-write boundary."""
    _coordinate_tuple_count(value.coordinates)
    return value


BoundedGeoJSONGeometry = Annotated[
    GeoJSONGeometry,
    AfterValidator(_bounded_geometry),
]


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


def _bounded_geometry_collection(
    value: GeoJSONGeometryCollection,
) -> GeoJSONGeometryCollection:
    """Apply member and aggregate budgets at the feature-write boundary."""
    if len(value.geometries) > MAX_GEOMETRY_COLLECTION_MEMBERS:
        raise ValueError(
            "GeometryCollection exceeds the "
            f"{MAX_GEOMETRY_COLLECTION_MEMBERS} member limit."
        )
    total = sum(
        _coordinate_tuple_count(geometry.coordinates) for geometry in value.geometries
    )
    if total > MAX_COORDINATE_TUPLES:
        raise ValueError(
            f"GeometryCollection exceeds the {MAX_COORDINATE_TUPLES} coordinate limit."
        )
    return value


BoundedGeoJSONGeometryCollection = Annotated[
    GeoJSONGeometryCollection,
    AfterValidator(_bounded_geometry_collection),
]


# Discriminated by the Literal type on the collection variant; plain geometries
# keep their exact prior wire shape.
GeoJSONGeometryLike = GeoJSONGeometryCollection | GeoJSONGeometry
BoundedGeoJSONGeometryLike = BoundedGeoJSONGeometryCollection | BoundedGeoJSONGeometry


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

    geometry: BoundedGeoJSONGeometryLike
    properties: dict | None = None

    @model_validator(mode="before")
    @classmethod
    def _no_nested_collections(cls, data: object) -> object:
        return _reject_nested_collections(data)


class FeatureReplace(BaseModel):
    """Full feature replacement (PUT semantics)."""

    geometry: BoundedGeoJSONGeometryLike  # Required for full replacement
    properties: dict  # Required — set fields to null explicitly

    @model_validator(mode="before")
    @classmethod
    def _no_nested_collections(cls, data: object) -> object:
        return _reject_nested_collections(data)


class FeatureUpdate(BaseModel):
    """Partial feature update (PATCH semantics)."""

    geometry: BoundedGeoJSONGeometryLike | None = None
    properties: dict | None = None

    @model_validator(mode="before")
    @classmethod
    def _no_nested_collections(cls, data: object) -> object:
        return _reject_nested_collections(data)
