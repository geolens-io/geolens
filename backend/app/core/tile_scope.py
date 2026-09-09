"""What a tile template carries: its signed scope and its cache-key version.

One derivation for every minter and every verifier. A divergence between the
two is a silent authorization bypass rather than a test failure, so this lives
in ``core`` and is imported directly: catalog and processing both reach it
without a port, which no overlay can replace on one side only.
"""

from __future__ import annotations

from urllib.parse import urlencode

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


TILE_PUBLICATION_VERSION_PARAM = "pv"


def tile_template_params(
    tile_cache_version: int | None, publication_version: int | None
) -> dict[str, int]:
    """Return the cache-key query params an emitted tile template carries.

    ``v`` is the content version nginx's raster cache already keys on (#1372).
    ``pv`` is the publication version: a status or visibility transition rolls
    it, so a template the product emits afterwards cannot read an entry stored
    before the change (#2007). Neither can hold a credential, which is what
    makes them safe cache-key segments.

    A falsy ``v`` is omitted, keeping the unversioned form older clients send.
    ``pv`` is always present, because 0 is a real counter value.
    """
    params: dict[str, int] = {}
    if tile_cache_version:
        params["v"] = int(tile_cache_version)
    params[TILE_PUBLICATION_VERSION_PARAM] = int(publication_version or 0)
    return params


def tile_template_query(
    tile_cache_version: int | None, publication_version: int | None
) -> str:
    """:func:`tile_template_params` as the query string of a tile template."""
    return "?" + urlencode(
        tile_template_params(tile_cache_version, publication_version)
    )
