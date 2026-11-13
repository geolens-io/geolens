"""Which ArcGIS service a WFS or OGC API Features source is.

The one place the service kinds below are told apart from any other
server's, so imports, refreshes and previews all decide alike. ArcGIS OGC
API Features collections are read page by page by `service_items`, since
GDAL 3.10.3 keeps only the last page of one; ArcGIS WFS imports are probed
for how they page and checked against the layer's total.

A URL that names the service decides on its own. Behind a redirect, a
vanity path or a reverse proxy, `esri_evidence` decides from what the
service answered instead.
"""

from collections.abc import Iterable
from typing import Literal
from urllib.parse import unquote, urlsplit

EsriServiceKind = Literal["wfs", "oapif"]

# What recognised a service, strongest first: the submitted URL, the URL
# a redirect ended on, a URL the service's own document advertises for
# itself, then a member or value only ArcGIS writes.
EsriEvidence = Literal["url", "redirect", "advertised", "marker"]

# Links an OGC API document gives for itself or its own pages, so an ArcGIS
# path in one names the service. Read here only, never followed.
_SELF_RELS = frozenset({"self", "alternate", "next", "prev", "items"})

# Output formats ArcGIS lists in WFS capabilities and no other server does.
_ESRI_WFS_FORMATS = frozenset({"esrigeojson", "esrigeojson+zip", "esrigeojson+gzip"})


def esri_service_kind(url: str | None) -> EsriServiceKind | None:
    """``"wfs"`` when the path's last segment is ``WFSServer``, ``"oapif"``
    when one of its segments is ``OGCFeatureServer``, else None.

    The path is percent-decoded and lowercased, and empty segments (a
    trailing or doubled slash) are dropped. The query and fragment are not
    read.
    """
    if not url:
        return None
    segments = [s for s in unquote(urlsplit(url).path).lower().split("/") if s]
    if segments and segments[-1] == "wfsserver":
        return "wfs"
    if "ogcfeatureserver" in segments:
        return "oapif"
    return None


def _named_kind(href: str | None) -> EsriServiceKind | None:
    """`esri_service_kind`, with an address that doesn't parse naming nothing."""
    try:
        return esri_service_kind(href)
    except ValueError:
        return None


def esri_evidence(
    kind: EsriServiceKind,
    url: str | None,
    *,
    final_url: str | None = None,
    advertised: Iterable[str] = (),
    marker: bool = False,
) -> EsriEvidence | None:
    """What shows ``url`` is an ArcGIS service of ``kind``, or None.

    ``final_url`` is where a read of the service ended after redirects,
    ``advertised`` the hrefs its own document gives for itself (an OGC API
    page's self, next and items links, a WFS's operation endpoints), and
    ``marker`` whether that document carries something only ArcGIS writes.
    """
    if _named_kind(url) == kind:
        return "url"
    if _named_kind(final_url) == kind:
        return "redirect"
    if any(_named_kind(href) == kind for href in advertised):
        return "advertised"
    return "marker" if marker else None


def oapif_self_hrefs(document: object) -> list[str]:
    """The hrefs an OGC API document's links give for itself or its pages."""
    links = document.get("links") if isinstance(document, dict) else None
    return [
        link["href"]
        for link in (links if isinstance(links, list) else [])
        if isinstance(link, dict)
        and link.get("rel") in _SELF_RELS
        and isinstance(link.get("href"), str)
    ]


def oapif_page_is_esri(document: object) -> bool:
    """Whether an OGC API items page carries ArcGIS's top-level
    ``properties.exceededTransferLimit``, which it sets on a page the
    collection doesn't fit in."""
    if not isinstance(document, dict):
        return False
    properties = document.get("properties")
    return isinstance(properties, dict) and isinstance(
        properties.get("exceededTransferLimit"), bool
    )


def wfs_format_is_esri(value: str | None) -> bool:
    """Whether a WFS capabilities value names an ArcGIS-only output format."""
    return (value or "").strip().lower() in _ESRI_WFS_FORMATS
