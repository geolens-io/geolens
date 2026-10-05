"""Which dataset responses a shared cache may store, and for how long."""

# A visibility change purges no CDN or proxy cache, so this lifetime is the
# longest an edge keeps serving a response after its data stops being public.
SHARED_CACHE_MAX_AGE = 60

_STALE_SERVING_DIRECTIVES = frozenset(
    {"s-maxage", "stale-while-revalidate", "stale-if-error"}
)


def is_publicly_cacheable(visibility: str | None, record_status: str | None) -> bool:
    """Whether a shared (auth-less) cache may store a response with a dataset's bytes.

    Only a dataset that is BOTH public AND published is safe to cache publicly.
    A public-but-unpublished dataset is an owner/admin-only preview: marking its
    responses `public` would let a shared cache replay them to later anonymous
    requests.
    """
    return visibility == "public" and record_status == "published"


def public_cache_control(max_age: int) -> str:
    """Return ``public`` Cache-Control whose shared-cache lifetime is bounded."""
    return bound_shared_cache_lifetime(f"public, max-age={max_age}")


def bound_shared_cache_lifetime(cache_control: str) -> str:
    """Cap how long a shared cache may serve a response at ``SHARED_CACHE_MAX_AGE``.

    ``s-maxage`` becomes the smallest of the cap and any ``max-age`` or
    ``s-maxage`` already present. Directives that let a shared cache serve a
    stale copy are dropped, since they would outlast the cap.
    """
    lifetime = SHARED_CACHE_MAX_AGE
    kept: list[str] = []
    for directive in cache_control.split(","):
        directive = directive.strip()
        if not directive:
            continue
        name, _, value = directive.partition("=")
        name = name.strip().lower()
        seconds = value.strip().strip('"')
        if name in ("max-age", "s-maxage") and seconds.isdigit():
            lifetime = min(lifetime, int(seconds))
        if name not in _STALE_SERVING_DIRECTIVES:
            kept.append(directive)
    kept.append(f"s-maxage={lifetime}")
    return ", ".join(kept)
