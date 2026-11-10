"""The cache identity and entry of a vector tile, shared by the tile route and the seeder."""

import uuid

# Pins the vector tile SQL and the entry layout below. A new value makes
# entries an older release wrote, or reads, unreachable across a deploy.
_VECTOR_ENTRY_FORMAT = "mvt2"

# Gzip output starts with 0x1f 0x8b, so this prefix can't be mistaken for a
# tile, and the empty sentinel stays empty.
_SAMPLED_PREFIX = b"S"


def generation_table_key(
    table_name: str,
    dataset_id: uuid.UUID,
    publication_version: int,
    tile_cache_version: int,
) -> str:
    """Table segment, the generation that makes a reused name safe, and the
    versions that make a superseded entry unreachable.

    A cache key of the table name alone would let the next dataset to draw
    ``roads`` read the previous one's cached bytes under its own visibility.
    Keying on the dataset id (a UUID, never reissued) makes that read
    impossible rather than merely short-lived, without relying on freed
    names being retired.

    The publication version rolls on a status or visibility transition, so
    bytes cached while the dataset was public and published stop being
    reachable then rather than serving out the TTL. The content version does
    the same for a table swap, which runs in the worker and cannot purge an
    in-memory cache in this process.

    Position is load-bearing: every segment goes AFTER the table name so the
    ``tile:{table}:*`` patterns in ``invalidate_table`` still match every
    key for a table, whichever dataset wrote it.
    """
    return (
        f"{table_name}:ds{dataset_id.hex}:p{publication_version}:v{tile_cache_version}"
    )


def tile_cache_key(
    table_name: str,
    dataset_id: uuid.UUID,
    publication_version: int,
    tile_cache_version: int,
    tenant_id: str | None,
) -> str:
    """The table segment a vector tile is cached under.

    Multi-tenant mode puts the tenant id in front so two tenants sharing a
    table name never share a cached tile; single-tenant mode has no prefix.
    """
    generation = generation_table_key(
        table_name, dataset_id, publication_version, tile_cache_version
    )
    key = f"{generation}:{_VECTOR_ENTRY_FORMAT}"
    return f"{tenant_id}:{key}" if tenant_id is not None else key


def tile_cache_entry(compressed: bytes, *, sampled: bool) -> bytes:
    """The cached form of gzip tile bytes, carrying whether the cap sampled them."""
    return _SAMPLED_PREFIX + compressed if sampled else compressed


def read_tile_cache_entry(entry: bytes) -> tuple[bytes, bool]:
    """The gzip tile bytes and sampled flag a ``tile_cache_entry`` holds."""
    if entry.startswith(_SAMPLED_PREFIX):
        return entry[len(_SAMPLED_PREFIX) :], True
    return entry, False
