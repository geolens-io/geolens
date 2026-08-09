"""Which ``dataset_assets`` keys may appear in an API response.

fix(#1290 review). The allowlist was introduced next to the search/STAC
serializer, which protected that path and no other — and `GET /datasets/{id}`
builds its ``stac_assets`` straight off the ORM rows, so the archived original's
href, filename and size leaked to any viewer of a public dataset.

That is the enumerate-paths-then-one-boundary shape: the fix is not a second
copy of the filter at the second path, it is one boundary every path crosses.
Three places turn ``dataset_assets`` rows into API payloads — the dataset detail
serializer, the STAC item endpoint, and the search bulk enrichment — and all
three now consult this module, either directly or through
``_build_stac_assets``, which is the only builder that applies it.

It is an ALLOWLIST. Listing what is public means a key added for internal
bookkeeping is private until someone deliberately publishes it, rather than
public until someone remembers to hide it. The first such key was
``archived_original:<hash>``: the pre-conversion upload kept when a COG
conversion was lossy, which is the higher-fidelity copy the conversion
deliberately replaced, and which on a published S3 deployment
``resolve_asset_url`` would hand out as a live presigned download.
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
