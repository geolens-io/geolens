"""Stored column names for source fields: reserved-name renames and collision suffixes.

Staging renames columns in the database and the file replacement preview
predicts the result from the source fields; both call these helpers so they
cannot disagree.
"""

import re
from collections.abc import Sequence

# Names that collide with GeoLens-internal PostGIS columns created during
# ingestion; a source attribute with one is renamed to ``src_<name>``.
RESERVED_COLUMN_NAMES: frozenset[str] = frozenset(
    {"gid", "geom", "geometry", "geom_4326", "fid", "ogc_fid"}
)


def reserved_rename_base(col_name: str) -> str:
    """The name ``rename_reserved_columns`` gives a column, before any collision suffix."""
    if ":" not in col_name:
        return f"src_{col_name}"
    # Launder to a safe name; must start with a letter or the
    # identifier validator rejects it (":id" -> "id", not "_id").
    base = re.sub(r"[^A-Za-z0-9_]", "_", col_name).strip("_")
    if not base or not base[0].isalpha():
        base = f"col_{base}" if base else "col"
    # A laundered name may hit an internal one (":geom" -> "geom") — apply
    # the reserved-name rule so staging's own geometry columns stay
    # uncontested.
    if base in RESERVED_COLUMN_NAMES:
        base = f"src_{base}"
    return base[:63]


def free_name(base: str, taken: set[str]) -> str:
    """``base``, or ``base_<n>`` for the first ``n`` from 2 that no column in ``taken`` uses."""
    target = base
    suffix = 2
    while target in taken:
        target = f"{base[:60]}_{suffix}"
        suffix += 1
    return target


def stored_column_names(source_names: Sequence[str]) -> list[str]:
    """The column names a file's source fields are stored under once it is loaded.

    ogr2ogr's PostgreSQL laundering (ASCII lowercase; ``'``, ``-`` and ``#``
    become ``_``), then the reserved-name rename walked over the whole set in
    order, so a rename that collides with another column takes the same suffix
    ``rename_reserved_columns`` gives it.
    """
    laundered = [
        "".join(
            "_" if ch in "'-#" else ch.lower() if ch.isascii() else ch for ch in name
        )
        for name in source_names
    ]
    taken = set(laundered)
    stored: list[str] = []
    for name in laundered:
        if name in RESERVED_COLUMN_NAMES or ":" in name:
            target = free_name(reserved_rename_base(name), taken)
            taken.discard(name)
            taken.add(target)
            name = target
        stored.append(name)
    return stored
