"""Which dataset responses a shared cache may store."""


def is_publicly_cacheable(visibility: str | None, record_status: str | None) -> bool:
    """Whether a shared (auth-less) cache may store a response with a dataset's bytes.

    Only a dataset that is BOTH public AND published is safe to cache publicly.
    A public-but-unpublished dataset is an owner/admin-only preview: marking its
    responses `public` would let a shared cache replay them to later anonymous
    requests.
    """
    return visibility == "public" and record_status == "published"
