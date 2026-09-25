"""Catalog record-type vocabulary shared across layers.

fix(#836): the raster-family membership check was pasted as a tuple/set
literal across modules/, processing/, and standards/ — one divergent copy is
where the next "forgot vrt_dataset" bug hides, so it's defined once here in
``core``, the only layer every other layer may import.

A tuple (not a frozenset) so SQLAlchemy ``.in_()`` renders deterministically.

``capabilities`` answers what a record type supports. A value missing from its
table gets none of the capabilities, so a new record type is refused everywhere
until it is added here.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

# Datasets backed by raster assets rather than a PostGIS feature table.
# Membership means: tiles come from TiTiler, feature reads/writes 404, and
# OGC/STAC advertise the dataset as a coverage.
RASTER_FAMILY_RECORD_TYPES: tuple[str, ...] = ("raster_dataset", "vrt_dataset")


def is_raster_family(record_type: str | None) -> bool:
    """Return True when *record_type* is a member of the raster family."""
    return record_type in RASTER_FAMILY_RECORD_TYPES


def is_table_or_raster_backed(record_type: str | None) -> bool:
    """Return True when a feature table or a raster asset holds the dataset's data.

    False for a tileset, a point cloud and any value the table doesn't know:
    each of those is a stored file served by its own endpoints.
    """
    return capabilities(record_type).feature_table or is_raster_family(record_type)


@dataclass(frozen=True, slots=True)
class RecordTypeCapabilities:
    """What the catalog serves for a dataset of one record type."""

    # A PostGIS table backs feature reads and writes, OGC items, export, rows
    # and column changes.
    feature_table: bool
    # "vector_geolens" or "raster_geolens"; None when it cannot be a map layer.
    map_layer_type: str | None
    # "vector" or "raster"; None when the dataset has no tiles.
    tile_token: str | None
    # "feature" or "coverage"; None when it is not an OGC API Features collection.
    ogc_item_type: str | None
    # Follows the feature table's geometry: re-measuring the table may move a
    # dataset between "table" and "vector_dataset".
    geometry_derived: bool


_VECTOR = RecordTypeCapabilities(
    feature_table=True,
    map_layer_type="vector_geolens",
    tile_token="vector",
    ogc_item_type="feature",
    geometry_derived=False,
)
_GEOMETRY_DERIVED = replace(_VECTOR, geometry_derived=True)
_RASTER = RecordTypeCapabilities(
    feature_table=False,
    map_layer_type="raster_geolens",
    tile_token="raster",
    ogc_item_type="coverage",
    geometry_derived=False,
)
_UNSUPPORTED = RecordTypeCapabilities(
    feature_table=False,
    map_layer_type=None,
    tile_token=None,
    ogc_item_type=None,
    geometry_derived=False,
)

# Mirrors chk_records_record_type. `map`, `service` and `collection` have no
# dataset writer; they keep the vector answers that every "not raster" branch
# gave them. A 3D Tiles tileset and a COPC point cloud have none of these
# capabilities; each is served by its own endpoints.
_CAPABILITIES: dict[str, RecordTypeCapabilities] = {
    "vector_dataset": _GEOMETRY_DERIVED,
    "raster_dataset": _RASTER,
    "vrt_dataset": _RASTER,
    "map": _VECTOR,
    "service": _VECTOR,
    "collection": _VECTOR,
    "table": _GEOMETRY_DERIVED,
    "tiles3d_dataset": _UNSUPPORTED,
    "pointcloud_dataset": _UNSUPPORTED,
}

RECORD_TYPES: tuple[str, ...] = tuple(_CAPABILITIES)

# The record types that carry a dataset row, which is what a user's dataset
# quota counts.
DATASET_RECORD_TYPES: tuple[str, ...] = (
    "vector_dataset",
    "raster_dataset",
    "vrt_dataset",
    "table",
    "tiles3d_dataset",
    "pointcloud_dataset",
)


def capabilities(record_type: str | None) -> RecordTypeCapabilities:
    """Return *record_type*'s capabilities; an unknown value has none."""
    if record_type is None:
        return _UNSUPPORTED
    return _CAPABILITIES.get(record_type, _UNSUPPORTED)
