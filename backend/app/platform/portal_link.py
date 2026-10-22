"""The ArcGIS item link a dataset's origin may carry.

``item_id`` and ``portal_url`` identify the portal item a dataset was built
from. Both reach ``origin_ref`` only through :func:`resolve_portal_link`: the
link is shown to owners and admins as an outbound anchor, so a value that is
not an https portal address is dropped rather than stored. A rejected value
never fails the import, which reports it in ``losses`` instead.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import idna

PORTAL_URL_MAX_LENGTH = 2048
ITEM_ID_MAX_LENGTH = 64

LOSS_ITEM_ID_INVALID = "item_id_invalid"
LOSS_PORTAL_URL_INVALID = "portal_url_invalid"
LOSS_PORTAL_URL_DOMAIN_MISMATCH = "portal_url_domain_mismatch"
LOSS_LINK_UNSUPPORTED = "origin_link_unsupported"

# What a browser's URL parser accepts in a host after IDNA: the check below
# runs on the same characters the link will be opened with.
_HOST = re.compile(r"[a-z0-9.-]+")
# Whitespace, control characters and backslash, which Python's parser and a
# browser's read differently (a browser turns `\` into `/`).
_UNSAFE_URL_CHARS = re.compile(r"[\s\x00-\x1f\x7f\\]")

# A portal address is often given as its REST endpoint; the item page lives
# under the portal base, so the API suffix is not part of what is stored.
_PORTAL_API_SUFFIX = re.compile(r"/sharing(/rest)?/*$", re.IGNORECASE)

_ITEM_ID = re.compile(r"[0-9a-f]{32}")

# Second-level labels that sit under a two-letter country code (co.uk, com.au),
# so the registrable domain of a.example.co.uk is example.co.uk. Not the public
# suffix list: an unlisted suffix falls back to its last two labels.
_SECOND_LEVEL_LABELS = frozenset(
    {"co", "com", "org", "net", "gov", "edu", "ac", "ne", "or", "go", "gob"}
)


@dataclass(frozen=True)
class PortalLink:
    """The origin_ref fields to store and the reasons any input was dropped."""

    fields: dict[str, str] = field(default_factory=dict)
    losses: list[str] = field(default_factory=list)

    @classmethod
    def unsupported(cls, item_id: str | None, portal_url: str | None) -> PortalLink:
        """No link stored, because the import type has none to store."""
        return cls({}, [LOSS_LINK_UNSUPPORTED] if item_id or portal_url else [])


def registrable_domain(host: str) -> str:
    """The host's registrable domain; an IP address or single label is its own."""
    host = host.lower().rstrip(".")
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        pass
    else:
        return host
    labels = host.split(".")
    if len(labels) <= 2:
        return host
    keep = 3 if len(labels[-1]) == 2 and labels[-2] in _SECOND_LEVEL_LABELS else 2
    return ".".join(labels[-keep:])


def _ascii_host(host: str) -> str | None:
    """The host as a browser resolves it, lowercase ASCII; None when invalid.

    Non-transitional UTS #46, like browsers: the built-in ``idna`` codec
    (IDNA 2003) maps ``ß`` to ``ss`` and would validate a different domain
    from the one the link opens.
    """
    try:
        if ipaddress.ip_address(host):
            return host
    except ValueError:
        pass
    try:
        host = idna.encode(host, uts46=True, transitional=False).decode("ascii")
    except (idna.IDNAError, UnicodeError, ValueError):
        return None
    host = host.lower()
    return host if _HOST.fullmatch(host) else None


def _url_ascii_host(url: str) -> str | None:
    """The URL's host in the form the comparison uses, None when it has none."""
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return None
    return _ascii_host(host) if host else None


def same_registrable_domain(first_url: str, second_url: str) -> bool:
    """Whether two URLs' hosts share a registrable domain."""
    first, second = _url_ascii_host(first_url), _url_ascii_host(second_url)
    return bool(first and second) and registrable_domain(first) == registrable_domain(
        second
    )


def _check_portal_url(
    value: str, service_url: str | None
) -> tuple[str | None, str | None]:
    """``(url, None)`` as the portal base (no query, fragment or
    ``/sharing/rest`` suffix), or ``(None, loss)``."""
    if len(value) > PORTAL_URL_MAX_LENGTH:
        return None, LOSS_PORTAL_URL_INVALID
    value = value.strip()
    if _UNSAFE_URL_CHARS.search(value):
        return None, LOSS_PORTAL_URL_INVALID
    try:
        parts = urlsplit(value)
        host = parts.hostname
        port = parts.port
    except ValueError:
        return None, LOSS_PORTAL_URL_INVALID
    if parts.scheme != "https" or not host or parts.username or parts.password:
        return None, LOSS_PORTAL_URL_INVALID
    host = _ascii_host(host)
    if host is None:
        return None, LOSS_PORTAL_URL_INVALID
    if service_url is not None:
        service_host = _url_ascii_host(service_url)
        if not service_host or registrable_domain(host) != registrable_domain(
            service_host
        ):
            return None, LOSS_PORTAL_URL_DOMAIN_MISMATCH
    netloc = f"[{host}]" if ":" in host else host
    if port is not None:
        netloc = f"{netloc}:{port}"
    return f"https://{netloc}{_PORTAL_API_SUFFIX.sub('', parts.path).rstrip('/')}", None


def resolve_portal_link(
    item_id: str | None,
    portal_url: str | None,
    service_url: str | None = None,
) -> PortalLink:
    """Validate the two fields independently; ``service_url`` is the host the
    portal must share a registrable domain with, absent for a file import."""
    fields: dict[str, str] = {}
    losses: list[str] = []
    if item_id is not None:
        normalized_id = item_id.strip().lower()
        if len(item_id) <= ITEM_ID_MAX_LENGTH and _ITEM_ID.fullmatch(normalized_id):
            fields["item_id"] = normalized_id
        else:
            losses.append(LOSS_ITEM_ID_INVALID)
    if portal_url is not None:
        url, loss = _check_portal_url(portal_url, service_url)
        if url is not None:
            fields["portal_url"] = url
        if loss is not None:
            losses.append(loss)
    return PortalLink(fields, losses)
