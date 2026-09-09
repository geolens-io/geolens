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


# The vector tile routes a stored distribution row can name. A raster row is
# never stored: ``published_distributions`` synthesizes that entry per request.
_STORED_TILE_TEMPLATE_PREFIXES = ("/tiles/data.", "/tiles/clusters/data.")


def republished_tile_url(url: str, publication_version: int | None) -> str:
    """Return a stored tile template carrying the CURRENT publication version.

    A ``record_distributions`` row is written once at ingest, so it cannot hold
    a value that rolls (#2007). A feed republishes the row's template with the
    dataset's counter instead of as stored, which is the same reason the raster
    template is synthesized per request rather than persisted.

    Any other URL, including an operator's own link to another service, is
    returned untouched. Other query params on the row survive; a stale ``pv``
    on it does not.
    """
    base, _, query = url.partition("?")
    if not base.startswith(_STORED_TILE_TEMPLATE_PREFIXES):
        return url
    # Split raw rather than decoding: a shared cache reads the name the same
    # way, so a stale `pv` is dropped by exactly the spelling that would key it.
    kept = [
        pair
        for pair in query.split("&")
        if pair and pair.split("=", 1)[0].lower() != TILE_PUBLICATION_VERSION_PARAM
    ]
    kept += [
        f"{name}={value}"
        for name, value in tile_template_params(None, publication_version).items()
    ]
    return f"{base}?{'&'.join(kept)}"
