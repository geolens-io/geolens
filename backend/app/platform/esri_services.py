"""Which ArcGIS service a WFS or OGC API Features URL names.

The one place the service kinds below are told apart from any other
server's, so imports, refreshes and previews all decide alike. ArcGIS OGC
API Features collections are read page by page by `service_items`, since
GDAL 3.10.3 keeps only the last page of one; ArcGIS WFS imports are probed
for how they page and checked against the layer's total.
"""

from typing import Literal
from urllib.parse import unquote, urlsplit

EsriServiceKind = Literal["wfs", "oapif"]


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
