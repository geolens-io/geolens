"""Catalog record-type vocabulary shared across layers.

fix(#836): the raster-family membership check (``record_type in
("raster_dataset", "vrt_dataset")``) was pasted as a tuple/set literal across
modules/, processing/, and standards/. One divergent copy is where the next
"forgot vrt_dataset" bug hides, so the family is defined once here. ``core``
is the only layer every other layer may import, which is why the vocabulary
lives here rather than in the catalog domain.

A tuple (not a frozenset) so SQLAlchemy ``.in_()`` renders deterministically
and iteration order is stable.
"""

from __future__ import annotations

# Datasets backed by raster assets rather than a PostGIS feature table.
# Membership means: tiles come from TiTiler, feature reads/writes 404, and
# OGC/STAC advertise the dataset as a coverage.
RASTER_FAMILY_RECORD_TYPES: tuple[str, ...] = ("raster_dataset", "vrt_dataset")


def is_raster_family(record_type: str | None) -> bool:
    """Return True when *record_type* is a member of the raster family."""
    return record_type in RASTER_FAMILY_RECORD_TYPES
