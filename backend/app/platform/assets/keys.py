"""Which ``dataset_assets`` keys may appear in an API response.

fix(#1290): an ALLOWLIST, not a blocklist — a key added for internal
bookkeeping stays private until deliberately published. Guards all three call
sites that turn ``dataset_assets`` rows into a payload (dataset detail, STAC
item, search bulk enrichment), directly or via ``_build_stac_assets``. Without
it, an internal key like ``archived_original:<hash>`` (the pre-conversion
original a lossy COG conversion keeps) leaks as a live presigned download to
any viewer of a public dataset.
"""

PUBLIC_ASSET_KEYS: frozenset[str] = frozenset(
    {"data", "vrt", "thumbnail", "overview", "metadata"}
)


def is_public_asset_key(key: str | None) -> bool:
    """True when a ``dataset_assets`` row may be serialized into a response.

    Exact membership, not a prefix test: internal keys are free to carry
    structure in their names (``archived_original:<hash>`` does) without
    anything here having to know about it.
    """
    return key in PUBLIC_ASSET_KEYS
