"""The signed scope a tile template carries.

One derivation for every minter and every verifier. A divergence between the
two is a silent authorization bypass rather than a test failure, so this lives
in ``core`` and is imported directly: catalog and processing both reach it
without a port, which no overlay can replace on one side only.
"""

from __future__ import annotations

from app.core.tenancy import tenant_bound_scope


def tile_signature_scope(resource: str, publication_version: int | None) -> str:
    """Return the signed scope binding ``resource`` to its publication version.

    ``resource`` is the dataset id for a raster template and the table name
    for a vector one. Folding in ``publication_version`` binds the capability
    to the state that granted it: a publication-status or visibility
    transition rolls that counter, so an unpublish or a move to private
    retires outstanding signatures with no read on the tile path (#1963).

    NOT ``tile_cache_version``, which also rolls on feature edits, column DDL
    and reupload; binding to it would retire every live template on an
    ordinary edit. A NULL counter reads as 0 on both sides.
    """
    return tenant_bound_scope(f"{resource}:p{int(publication_version or 0)}")
