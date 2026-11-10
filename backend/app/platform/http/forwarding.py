"""Tell a request the public edge relayed from one a service sent directly."""

from collections.abc import Mapping

FORWARDING_HEADERS = ("forwarded", "x-forwarded-for", "x-real-ip")


def came_through_proxy(headers: Mapping[str, str]) -> bool:
    """True when a proxy relayed this request.

    The edge sets these headers on every request it passes to the API, while
    Titiler and a Prometheus scrape call the API directly without them.
    """
    return any(name in headers for name in FORWARDING_HEADERS)
