# SPDX-License-Identifier: Apache-2.0
"""Read-only inventory of an ArcGIS Online or Portal for ArcGIS organization.

Hand-maintained. Every request goes to the portal named on the command line
and nowhere else: not to GeoLens, and not to the services an item points at.
Nothing on the portal is changed. The token and password live in memory for
one run and are never written anywhere.
"""

from __future__ import annotations

import re
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from . import arcgis_report as _report
from . import output as _output
from ._sdk_helpers import (
    EXIT_AUTH,
    EXIT_GENERIC,
    EXIT_NETWORK,
    EXIT_OK,
    EXIT_SERVER,
    EXIT_USAGE,
)
from .arcgis_portal import (
    PortalClient,
    PortalError,
    Redactor,
    build_opener,
    portal_root,
    read_credentials,
    redact_json,
    sanitize_url,
)

DEFAULT_PORTAL_URL = "https://www.arcgis.com"
PAGE_SIZE = 100
DEFAULT_MAX_ITEMS = 10_000
MAX_CONCURRENCY = 4
# ArcGIS search pages through only the first 10,000 results of a query.
SEARCH_RESULT_CEILING = 10_000
MAX_DESCRIPTION_BYTES = 64 * 1024

# ArcGIS Online hosted services: services.arcgis.com, services1.arcgis.com,
# services-eu1.arcgis.com, and the same forms for tiles.
_ARCGIS_ONLINE_HOSTED = re.compile(r"(services|tiles)(-[a-z]+)?\d*\.arcgis\.com")

SUPPORTED = "supported"
PARTIAL = "partial"
UNSUPPORTED = "unsupported"
CLASSES = (SUPPORTED, PARTIAL, UNSUPPORTED)

_NO_APP_EQUIVALENT = (UNSUPPORTED, "no_equivalent_app")
_NOT_CATALOG_DATA = (UNSUPPORTED, "not_catalog_data")
_OGC_REFERENCE = (PARTIAL, "ogc_service_reference")
_DATA_FILE = (PARTIAL, "data_file_import_candidate")

# Item `type` -> (class, reason). `classify` refines Feature Service, Map
# Service and Web Mapping Application by typeKeywords.
ITEM_TYPE_CLASSES: dict[str, tuple[str, str]] = {
    "Feature Service": (SUPPORTED, "hosted_feature_layer"),
    "Map Service": (SUPPORTED, "map_service_layer_import"),
    "Web Map": (PARTIAL, "web_map_styling_needs_translation"),
    "Image Service": (UNSUPPORTED, "no_import_path"),
    "Vector Tile Service": (UNSUPPORTED, "no_import_path"),
    "Scene Service": (UNSUPPORTED, "no_scene_import"),
    "Web Scene": (UNSUPPORTED, "no_scene_import"),
    "3DTilesService": (UNSUPPORTED, "no_scene_import"),
    "WMS": _OGC_REFERENCE,
    "WFS": _OGC_REFERENCE,
    "WMTS": _OGC_REFERENCE,
    "WCS": _OGC_REFERENCE,
    "KML": _OGC_REFERENCE,
    "OGCFeatureServer": _OGC_REFERENCE,
    "Feature Collection": _DATA_FILE,
    "CSV": _DATA_FILE,
    "Shapefile": _DATA_FILE,
    "GeoJson": _DATA_FILE,
    "File Geodatabase": _DATA_FILE,
    "Web Mapping Application": _NO_APP_EQUIVALENT,
    "Web Experience": _NO_APP_EQUIVALENT,
    "Dashboard": _NO_APP_EQUIVALENT,
    "StoryMap": _NO_APP_EQUIVALENT,
    "Hub Site Application": _NO_APP_EQUIVALENT,
    "Hub Page": _NO_APP_EQUIVALENT,
    "Hub Initiative": _NO_APP_EQUIVALENT,
    "Form": _NO_APP_EQUIVALENT,
    "Workforce Project": _NO_APP_EQUIVALENT,
    "Mission": _NO_APP_EQUIVALENT,
    "Notebook": _NO_APP_EQUIVALENT,
    "Solution": _NO_APP_EQUIVALENT,
    "Data Pipeline": _NO_APP_EQUIVALENT,
    "Investigation": _NO_APP_EQUIVALENT,
    "Knowledge Studio Project": _NO_APP_EQUIVALENT,
    "GeoBIM Project": _NO_APP_EQUIVALENT,
    "Urban Model": _NO_APP_EQUIVALENT,
    "Native Application": _NO_APP_EQUIVALENT,
    "Geocoding Service": _NOT_CATALOG_DATA,
    "Geometry Service": _NOT_CATALOG_DATA,
    "Geoprocessing Service": _NOT_CATALOG_DATA,
    "Network Analysis Service": _NOT_CATALOG_DATA,
    "Workflow Manager Service": _NOT_CATALOG_DATA,
    "Pro Map": _NOT_CATALOG_DATA,
    "Map Area": _NOT_CATALOG_DATA,
    "Layer Package": _NOT_CATALOG_DATA,
    "Map Package": _NOT_CATALOG_DATA,
    "Code Attachment": _NOT_CATALOG_DATA,
}

# Only cite a dated Esri page here; an undated retirement gets "date": None.
RETIREMENTS: dict[str, dict[str, str | None]] = {
    "web_appbuilder": {
        "label": "Web AppBuilder",
        "status": "retiring",
        "date": "2027-Q2",
        "note": (
            "ArcGIS Online: no new apps from Q1 2026, no updates to existing "
            "apps from Q4 2026, apps stop working in Q2 2027. ArcGIS Enterprise "
            "11.5 is the last release that includes it."
        ),
        "source_url": "https://doc.arcgis.com/en/web-appbuilder/latest/create-apps/wab-retirement.htm",
    },
    "classic_story_maps": {
        "label": "Classic Esri Story Maps",
        "status": "retired",
        "date": "2026-Q1",
        "note": "Retired from ArcGIS Online in Q1 2026.",
        "source_url": "https://www.esri.com/en-us/arcgis/products/arcgis-storymaps/classic",
    },
}

_SERVICE_TYPES = frozenset(
    {
        "Feature Service",
        "Map Service",
        "Image Service",
        "Vector Tile Service",
        "Scene Service",
    }
)
_APP_DATA_TYPES = frozenset(
    {
        "Web Mapping Application",
        "Web Experience",
        "Dashboard",
        "StoryMap",
        "Hub Site Application",
        "Hub Page",
        "Hub Initiative",
        "Notebook",
        "Web Scene",
    }
)
# Items whose data is a web map's configuration.
_MAP_CONFIG_TYPES = frozenset({"Web Map", "Web Scene"})
_ITEM_ID = re.compile(r"[0-9A-Za-z]{32}")
_SAFE_FILENAME = re.compile(r"[A-Za-z0-9_-]{1,64}")
_WEB_MAP_TYPE = "Web Map"
# Statuses a portal answers with for members or folders the caller may not see.
_HIDDEN_STATUSES = frozenset({400, 403})
_HIDDEN_ITEM_STATUSES = frozenset({400, 401, 403, 404})
_SERVICE_LAYER_URL = re.compile(r"/(?:Feature|Map)Server/(\d+)/?$")
_WAB_KEYWORDS = frozenset({"web appbuilder", "wab2d", "wab3d"})


def classify(item: Mapping[str, Any]) -> dict[str, Any]:
    """Class, reason, retirement and hosted flag for one portal item."""
    item_type = str(item.get("type") or "")
    keywords = {str(k).lower() for k in item.get("typeKeywords") or []}
    hosted_service = "hosted service" in keywords
    retirement: str | None = None
    klass, reason = ITEM_TYPE_CLASSES.get(item_type, (UNSUPPORTED, "unknown_type"))
    if item_type == "Feature Service":
        if "view service" in keywords:
            reason = "hosted_feature_view"
        elif not hosted_service:
            reason = "non_hosted_service_reachability_external"
    elif item_type == "Map Service" and hosted_service:
        klass, reason = PARTIAL, "hosted_tile_layer_cached_only"
    elif item_type == "Web Mapping Application":
        if any("story map" in k for k in keywords):
            reason, retirement = "classic_story_map", "classic_story_maps"
        elif keywords & _WAB_KEYWORDS:
            reason, retirement = "web_appbuilder_app", "web_appbuilder"
    return {
        "class": klass,
        "reason": reason,
        "retirement": retirement,
        "hosted": hosted_service if item_type in _SERVICE_TYPES else None,
    }


def _iso_from_ms(value: Any) -> str | None:
    if not isinstance(value, int | float) or isinstance(value, bool) or value <= 0:
        return None
    try:
        stamp = datetime.fromtimestamp(value / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None
    return stamp.isoformat().replace("+00:00", "Z")


def _text(value: Any, redact: Redactor, *, cap: int | None = None) -> str | None:
    """A redacted string field, None when absent or blank.

    Redacting before cutting matters: a cut through a secret leaves a prefix
    that no longer matches it.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = redact(value)
    if cap is not None:
        text = text.encode()[:cap].decode(errors="ignore")
    return text


def _extent(value: Any) -> list[list[float]] | None:
    """``[[xmin, ymin], [xmax, ymax]]`` as the portal reports it, or None."""
    if not isinstance(value, list) or len(value) != 2:
        return None
    corners: list[list[float]] = []
    for corner in value:
        if not isinstance(corner, list) or len(corner) != 2:
            return None
        if not all(
            isinstance(n, int | float) and not isinstance(n, bool) for n in corner
        ):
            return None
        corners.append([float(n) for n in corner])
    return corners


def _spatial_reference(value: Any, redact: Redactor) -> str | None:
    if isinstance(value, dict):
        value = value.get("latestWkid") or value.get("wkid") or value.get("wkt")
    if isinstance(value, bool) or not isinstance(value, str | int) or value == "":
        return None
    return redact(str(value))


def _metadata(item: Mapping[str, Any], redact: Redactor) -> dict[str, Any]:
    """The descriptive fields of an item, from a search result or item read."""
    tags = item.get("tags")
    thumbnail = item.get("thumbnail")
    return {
        "snippet": _text(item.get("snippet"), redact),
        "description": _text(
            item.get("description"), redact, cap=MAX_DESCRIPTION_BYTES
        ),
        "tags": [redact(t) for t in tags if isinstance(t, str) and t]
        if isinstance(tags, list)
        else [],
        "access_information": _text(item.get("accessInformation"), redact),
        "license_info": _text(item.get("licenseInfo"), redact),
        "extent": _extent(item.get("extent")),
        "thumbnail": _text(thumbnail, redact),
        "spatial_reference": _spatial_reference(item.get("spatialReference"), redact),
        "culture": _text(item.get("culture"), redact),
    }


def _service_layers(item_type: str, url: str | None) -> list[dict[str, Any]]:
    """The sub-layer an item's own URL names, without asking the service."""
    if item_type not in ("Feature Service", "Map Service") or not url:
        return []
    match = _SERVICE_LAYER_URL.search(url)
    return [{"id": int(match.group(1)), "url": url}] if match else []


def _item_url(item: Mapping[str, Any], redact: Redactor) -> str | None:
    url = sanitize_url(item.get("url"))
    return redact(url) if url else None


def _classification(item: Mapping[str, Any], redact: Redactor) -> dict[str, Any]:
    """The row fields that follow from an item's type and type keywords."""
    verdict = classify(item)
    retirement_id = verdict["retirement"]
    retirement = None
    if retirement_id:
        known = RETIREMENTS[retirement_id]
        retirement = {
            "id": retirement_id,
            "status": known["status"],
            "date": known["date"],
        }
    return {
        "type_keywords": [redact(str(k)) for k in item.get("typeKeywords") or []],
        "class": verdict["class"],
        "reason": verdict["reason"],
        "retirement": retirement,
        "hosted": verdict["hosted"],
    }


def _listed_folder(item: Mapping[str, Any], redact: Redactor) -> dict[str, Any] | None:
    folder_id = item.get("ownerFolder")
    if not isinstance(folder_id, str) or not folder_id:
        return None
    return {"id": redact(folder_id), "title": None}


def _item_row(item: Mapping[str, Any], redact: Redactor) -> dict[str, Any]:
    size = item.get("size")
    item_type = str(item.get("type") or "")
    classified = _classification(item, redact)
    reads_dependencies = (
        item_type == _WEB_MAP_TYPE
        or item_type in _APP_DATA_TYPES
        or bool(_related_reads(item_type, classified["reason"]))
    )
    dependencies_status = "pending" if reads_dependencies else "not_applicable"
    url = _item_url(item, redact)
    return {
        "id": str(item.get("id") or ""),
        "type": item_type,
        "title": redact(str(item.get("title") or "")),
        "owner": str(item.get("owner") or ""),
        "sharing": {"access": str(item.get("access") or "private"), "groups": None},
        "size_bytes": size
        if isinstance(size, int) and not isinstance(size, bool) and size >= 0
        else None,
        "created": _iso_from_ms(item.get("created")),
        "modified": _iso_from_ms(item.get("modified")),
        "url": url,
        **classified,
        "dependencies_status": dependencies_status,
        **_metadata(item, redact),
        "folder": _listed_folder(item, redact),
        "groups": None,
        "owner_full_name": None,
        "owner_email": None,
        "layers": _service_layers(item_type, url),
        "data_saved": False,
    }


@dataclass
class Inventory:
    portal: dict[str, Any]
    auth: dict[str, Any]
    scope: dict[str, Any]
    items: list[dict[str, Any]] = field(default_factory=list)
    dependencies: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    folder_titles: dict[str, str] = field(default_factory=dict)
    truncated: bool = False
    search_ceiling: bool = False
    abort: PortalError | None = None
    # When the reading started, by the portal's clock; None when it gave none.
    started_at: str | None = None


def _pages(
    client: PortalClient, path: str, params: dict[str, Any], key: str
) -> Iterator[tuple[list[Any], dict]]:
    start = 1
    while True:
        page = client.get_json(path, {**params, "num": PAGE_SIZE, "start": start})
        rows = page.get(key)
        next_start = page.get("nextStart")
        if not isinstance(rows, list):
            raise PortalError(
                f"{path} returned no '{key}' list at start={start}", kind="invalid"
            )
        if (
            not isinstance(next_start, int)
            or isinstance(next_start, bool)
            or (next_start != -1 and next_start <= start)
        ):
            raise PortalError(
                f"{path} returned no usable 'nextStart' at start={start}",
                kind="invalid",
            )
        yield rows, page
        if next_start == -1:
            return
        start = next_start


def _has_next(page: Mapping[str, Any]) -> bool:
    next_start = page.get("nextStart")
    return isinstance(next_start, int) and next_start > 0


def _at_search_ceiling(page: Mapping[str, Any], rows: list[Any]) -> bool:
    """Whether a search page reaches the server's result ceiling.

    At the ceiling the last page still says ``nextStart: -1`` and ``total``
    is capped, so neither proves the listing is complete.
    """
    total, start = page.get("total"), page.get("start")
    if isinstance(total, int) and total >= SEARCH_RESULT_CEILING:
        return True
    return isinstance(start, int) and start + len(rows) - 1 >= SEARCH_RESULT_CEILING


def _list_items(
    client: PortalClient, inv: Inventory, max_items: int
) -> Iterator[tuple[dict[str, Any], str | None]]:
    """Raw items for the scope with the folder each was listed in (user scope
    only), deduplicated, stopping at *max_items*.

    User scope reads the root folder first; its ``folders`` list names the
    other folders to page through and their titles.
    """
    if inv.scope["mode"] == "org":
        org_query = {
            "q": f"orgid:{inv.scope['org_id']}",
            "sortField": "modified",
            "sortOrder": "desc",
        }
        listings = [("search", org_query, "results", None)]
    else:
        user_path = f"content/users/{quote(inv.scope['owner'], safe='')}"
        listings = [(user_path, {}, "items", None)]
    seen: set[str] = set()
    position = 0
    while position < len(listings):
        path, params, key, folder_id = listings[position]
        position += 1
        for rows, page in _pages(client, path, params, key):
            if path == "search" and _at_search_ceiling(page, rows):
                inv.search_ceiling = True
            folders = page.get("folders")
            if inv.scope["mode"] == "user" and len(listings) == 1:
                if isinstance(folders, list):
                    for f in folders:
                        if not isinstance(f, dict) or not f.get("id"):
                            continue
                        fid = str(f["id"])
                        if isinstance(f.get("title"), str):
                            inv.folder_titles[client._redact(fid)] = client._redact(
                                f["title"]
                            )
                        listings.append(
                            (f"{path}/{quote(fid, safe='')}", {}, "items", fid)
                        )
            for raw in rows:
                if not isinstance(raw, dict) or not raw.get("id"):
                    continue
                if str(raw["id"]) in seen:
                    continue
                if len(seen) >= max_items:
                    inv.truncated = True
                    return
                seen.add(str(raw["id"]))
                yield raw, folder_id
            if len(seen) >= max_items and (_has_next(page) or position < len(listings)):
                inv.truncated = True
                return


def _hosted_by_url(url: str | None, portal: Mapping[str, Any]) -> bool | None:
    """Whether a layer URL is the organization's hosted service, or None when
    the URL can't tell.

    ArcGIS Online hosts only on its own service hosts, so any other host is
    external. An Enterprise hosting server can sit on any host; its services
    live in the ``Hosted`` folder, and anything else is unknown.
    """
    if not url:
        return None
    parts = urlsplit(url)
    if portal["kind"] == "online":
        return bool(_ARCGIS_ONLINE_HOSTED.fullmatch((parts.hostname or "").lower()))
    return True if "/rest/services/hosted/" in parts.path.lower() else None


def _dependency(
    from_id: str,
    to_id: Any,
    raw_url: Any,
    *,
    role: str,
    layer_type: Any,
    layer_id: Any,
    title: Any,
    order: int,
    index: Mapping[str, dict[str, Any]],
    portal: Mapping[str, Any],
) -> dict[str, Any]:
    to_id = str(to_id) if isinstance(to_id, str) and to_id else None
    url = sanitize_url(raw_url)
    target = index.get(to_id) if to_id else None
    return {
        "from_id": from_id,
        "to_id": to_id,
        "to_url": url,
        "role": role,
        "layer_type": str(layer_type) if layer_type else None,
        "layer_id": str(layer_id) if layer_id is not None else None,
        "title": str(title) if title else None,
        "order": order,
        "hosted": target["hosted"] if target else _hosted_by_url(url, portal),
        "resolved": target is not None,
        "external": False if target else None,
    }


def _layer_url(layer: Mapping[str, Any]) -> Any:
    """The layer's service, style, tile template or WMTS URL, first found."""
    wmts = layer.get("wmtsInfo")
    return (
        layer.get("url")
        or layer.get("styleUrl")
        or layer.get("templateUrl")
        or (wmts.get("url") if isinstance(wmts, dict) else None)
    )


def web_map_dependencies(
    item_id: str,
    data: Mapping[str, Any],
    index: Mapping[str, dict[str, Any]],
    portal: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Layer, basemap and table references of one web map, in map order."""
    rows: list[dict[str, Any]] = []

    def own_row(layer: Mapping[str, Any], role: str) -> dict[str, Any]:
        return _dependency(
            item_id,
            layer.get("itemId"),
            _layer_url(layer),
            role=role,
            layer_type=layer.get("layerType"),
            layer_id=layer.get("id"),
            title=layer.get("title"),
            order=len(rows),
            index=index,
            portal=portal,
        )

    def walk(layers: Any, role: str) -> None:
        if not isinstance(layers, list):
            return
        for layer in layers:
            if not isinstance(layer, dict):
                continue
            if layer.get("layerType") == "GroupLayer" and isinstance(
                layer.get("layers"), list
            ):
                # A registered group layer is an item of its own.
                if layer.get("itemId") or _layer_url(layer):
                    rows.append(own_row(layer, role))
                walk(layer["layers"], role)
                continue
            rows.append(own_row(layer, role))
            sublayers = layer.get("layers")
            for sub in sublayers if isinstance(sublayers, list) else []:
                # A map or tiled map service sublayer can name its own query
                # service; layer_id "<parent>/<sublayer>" ties it to the parent.
                if not isinstance(sub, dict) or not (
                    sub.get("layerItemId") or sub.get("layerUrl")
                ):
                    continue
                ids = (layer.get("id"), sub.get("id"))
                rows.append(
                    _dependency(
                        item_id,
                        sub.get("layerItemId"),
                        sub.get("layerUrl"),
                        role=role,
                        layer_type=layer.get("layerType"),
                        layer_id="/".join(str(i) for i in ids if i is not None) or None,
                        title=sub.get("name") or sub.get("title"),
                        order=len(rows),
                        index=index,
                        portal=portal,
                    )
                )

    walk(data.get("operationalLayers"), "operational_layer")
    basemap = data.get("baseMap")
    if isinstance(basemap, dict):
        walk(basemap.get("baseMapLayers"), "basemap")
        walk(basemap.get("groundLayers"), "basemap")
        walk(basemap.get("elevationLayers"), "basemap")
    walk(data.get("tables"), "table")
    ground = data.get("ground")
    if isinstance(ground, dict):
        walk(ground.get("layers"), "basemap")
    return rows


_APP_MAP_SOURCE_TYPES = frozenset({"WEB_MAP", "WEB_SCENE"})


def _config_text(value: Any, field: str) -> str:
    """A config string field, "" when absent; any other type is malformed."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"'{field}' is a {type(value).__name__}, not a string")
    return value


_AppRef = tuple[str | None, str | None, str, str, str | None]


def _story_references(data: Mapping[str, Any], add: Callable[..., None]) -> bool:
    """Web maps a StoryMap's map nodes point at, through its resources."""
    nodes, resources = data.get("nodes"), data.get("resources")
    if not isinstance(nodes, dict) or not isinstance(resources, dict):
        return False
    for node in nodes.values():
        if not isinstance(node, dict) or node.get("type") != "webmap":
            continue
        node_data = node.get("data")
        resource = (
            resources.get(node_data.get("map")) if isinstance(node_data, dict) else None
        )
        if not isinstance(resource, dict):
            # Raised so the item becomes an error row, not a quietly short list.
            raise ValueError("a map node points at a resource the story lacks")
        if resource.get("type") == "webmap":
            map_data = resource.get("data")
            if (
                not isinstance(map_data, dict)
                or not isinstance(map_data.get("itemId"), str)
                or not map_data["itemId"]
            ):
                raise ValueError("a story's web map resource names no item")
            add(
                map_data.get("itemId"),
                map_data.get("itemType") or "Web Map",
                "app_web_map",
            )
    return True


def _hub_references(data: Mapping[str, Any], add: Callable[..., None]) -> bool:
    """Items a Hub site or page embeds in its layout cards."""
    values = data.get("values")
    layout = values.get("layout") if isinstance(values, dict) else None
    sections = layout.get("sections") if isinstance(layout, dict) else None
    if not isinstance(sections, list):
        return False
    for section in sections:
        rows = section.get("rows") if isinstance(section, dict) else None
        for row in rows if isinstance(rows, list) else []:
            cards = row.get("cards") if isinstance(row, dict) else None
            for card in cards if isinstance(cards, list) else []:
                component = card.get("component") if isinstance(card, dict) else None
                settings = (
                    component.get("settings") if isinstance(component, dict) else None
                )
                if not isinstance(settings, dict):
                    continue
                kind = component.get("name")
                for key in ("itemId", "mobileItemId"):
                    add(settings.get(key), kind, "app_embedded_item")
    return True


def _app_references(data: Mapping[str, Any]) -> list[_AppRef] | None:
    """(item id, URL, kind, role, layer id) from the documented app config
    keys, or None if none of those keys is present.

    Maps an app opens are ``app_web_map``; layers it reads directly, such as a
    dashboard chart's dataset or an Experience Builder feature layer source,
    are ``app_data_source`` with their layer id. A data source may name its
    service by URL alone, so a reference needs an item id or a URL.
    """
    found: list[_AppRef] = []
    recognized = False

    def add(
        ref: Any, kind: Any, role: str, layer_id: Any = None, url: Any = None
    ) -> None:
        item_id = ref if isinstance(ref, str) and ref else None
        clean_url = sanitize_url(url)
        if item_id is None and clean_url is None:
            return
        layer = (
            None if layer_id is None or isinstance(layer_id, bool) else str(layer_id)
        )
        found.append((item_id, clean_url, _config_text(kind, "type"), role, layer))

    def add_source(source: Mapping[str, Any]) -> None:
        add(
            source.get("itemId"),
            source.get("type"),
            "app_data_source",
            source.get("layerId"),
            source.get("url"),
        )

    values = data.get("values")
    if isinstance(values, dict) and "webmap" in values:
        recognized = True
        webmaps = values["webmap"]
        for ref in webmaps if isinstance(webmaps, list) else [webmaps]:
            add(ref, "webmap", "app_web_map")
    app_map = data.get("map")
    if isinstance(app_map, dict) and "itemId" in app_map:
        recognized = True
        add(app_map["itemId"], "webmap", "app_web_map")
    sources = data.get("dataSources")
    nested = data.get("dataSource")
    if not isinstance(sources, dict) and isinstance(nested, dict):
        sources = nested.get("dataSources")
    if isinstance(sources, dict):
        recognized = True
        for source in sources.values():
            if not isinstance(source, dict):
                continue
            if _config_text(source.get("type"), "type") in _APP_MAP_SOURCE_TYPES:
                add(source.get("itemId"), source.get("type"), "app_web_map")
            else:
                add_source(source)
            children = source.get("childDataSourceJsons")
            for child in children.values() if isinstance(children, dict) else []:
                if isinstance(child, dict):
                    add_source(child)
    widgets = data.get("widgets")
    desktop = data.get("desktopView")
    if not isinstance(widgets, list) and isinstance(desktop, dict):
        widgets = desktop.get("widgets")
    mobile = data.get("mobileView")
    mobile_widgets = mobile.get("widgets") if isinstance(mobile, dict) else None
    if isinstance(widgets, list):
        recognized = True
        for widget in [*widgets, *(mobile_widgets or [])]:
            if not isinstance(widget, dict):
                continue
            add(widget.get("itemId"), widget.get("type"), "app_web_map")
            datasets = widget.get("datasets")
            for dataset in datasets if isinstance(datasets, list) else []:
                source = (
                    dataset.get("dataSource") if isinstance(dataset, dict) else None
                )
                if isinstance(source, dict):
                    add_source(source)
    recognized = _story_references(data, add) or recognized
    recognized = _hub_references(data, add) or recognized
    if not recognized:
        return None
    unique: dict[tuple[str | None, str | None, str, str | None], _AppRef] = {}
    for item_id, url, kind, role, layer in found:
        unique.setdefault(
            (item_id, url, role, layer), (item_id, url, kind, role, layer)
        )
    return list(unique.values())


def _is_web_map(data: Mapping[str, Any]) -> bool:
    """Whether *data* has a web map's structure: ``baseMap`` is required by the spec."""
    layers = data.get("operationalLayers")
    return isinstance(data.get("baseMap"), dict) and (
        layers is None or isinstance(layers, list)
    )


def _extract_dependencies(
    row: Mapping[str, Any],
    data: Mapping[str, Any],
    index: Mapping[str, dict[str, Any]],
    portal: Mapping[str, Any],
) -> tuple[str, list[dict[str, Any]]]:
    """(dependencies_status, dependency rows) for one item's data."""
    if row["type"] in _MAP_CONFIG_TYPES:
        return "parsed", web_map_dependencies(row["id"], data, index, portal)
    refs = _app_references(data)
    if refs is None:
        return "unparsed", []
    return "parsed", [
        _dependency(
            row["id"],
            ref,
            url,
            role=role,
            layer_type=kind,
            layer_id=layer_id,
            title=None,
            order=order,
            index=index,
            portal=portal,
        )
        for order, (ref, url, kind, role, layer_id) in enumerate(refs)
    ]


def _detach(exc: BaseException) -> None:
    """Drop an error's traceback and chained errors.

    Their frames hold the response bytes that failed, and the results keep
    every item's error until the report is built.
    """
    exc.__traceback__ = None
    exc.__context__ = None
    exc.__cause__ = None


def _related_reads(item_type: str, reason: str) -> list[tuple[str, str, str]]:
    """(relationship type, direction, role) of the related-item reads an item
    needs: a view's source service, a hosted layer's source file, a survey's
    results service."""
    if reason == "hosted_feature_view":
        return [("Service2Service", "reverse", "view_parent")]
    if reason == "hosted_feature_layer":
        return [("Service2Data", "forward", "published_from")]
    if item_type == "Form":
        return [("Survey2Service", "forward", "survey_results")]
    return []


def _related_dependencies(
    row: Mapping[str, Any],
    response: Mapping[str, Any],
    role: str,
    index: Mapping[str, dict[str, Any]],
    portal: Mapping[str, Any],
    first_order: int,
) -> list[dict[str, Any]]:
    related = response.get("relatedItems")
    rows: list[dict[str, Any]] = []
    for item in related if isinstance(related, list) else []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        rows.append(
            _dependency(
                row["id"],
                item["id"],
                item.get("url"),
                role=role,
                layer_type=item.get("type"),
                layer_id=None,
                title=item.get("title"),
                order=first_order + len(rows),
                index=index,
                portal=portal,
            )
        )
    return rows


def _scan_item_ids(data: Any) -> list[str]:
    """Item ids under ``itemId`` or ``webmap`` keys, and ``id`` in objects
    typed ``webmap``, in first-seen document order."""
    found: dict[str, None] = {}
    # Each entry is (key, value, whether the parent object is typed webmap),
    # so scalars and containers are visited in the order they appear.
    stack: list[tuple[str | None, Any, bool]] = [(None, data, False)]
    while stack:
        key, node, typed = stack.pop()
        if isinstance(node, list):
            stack.extend((None, item, False) for item in reversed(node))
        elif isinstance(node, dict):
            is_typed = str(node.get("type") or "").lower() == "webmap"
            stack.extend((k, v, is_typed) for k, v in reversed(list(node.items())))
        elif (
            isinstance(node, str)
            and _ITEM_ID.fullmatch(node)
            and (key in ("itemId", "webmap") or (key == "id" and typed))
        ):
            found.setdefault(node, None)
    return list(found)


@dataclass
class _DepResult:
    status: str = "not_fetched"
    dependencies: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    auth: PortalError | None = None
    saved: bool = False


# Reads that carry no usable JSON are an app's normal state, not a failure.
_UNREADABLE_KINDS = frozenset({"empty"})
# Item types registered by URL alone, which legitimately have no data.
_URL_ONLY_TYPES = frozenset({"Web Mapping Application"})
# Item types whose data is legitimately not a JSON document.
_NON_JSON_TYPES = frozenset({"Notebook"})


def _collect_dependencies(
    client: PortalClient,
    inv: Inventory,
    concurrency: int,
    *,
    read_all: bool = False,
    sidecar_dir: Path | None = None,
) -> None:
    """Read each web map's and app's data and related items, and keep only
    its dependency rows.

    Each worker reduces the item's configuration to rows before returning,
    so at most *concurrency* full configurations are held at once. With
    *sidecar_dir* the redacted configuration is written to disk first.
    """
    index = {row["id"]: row for row in inv.items}
    reads_data = {
        row["id"]
        for row in inv.items
        if row["type"] == _WEB_MAP_TYPE or row["type"] in _APP_DATA_TYPES
    }
    best_effort = (
        {row["id"] for row in inv.items if row["id"] not in reads_data}
        if read_all
        else set()
    )
    targets = [
        row
        for row in inv.items
        if row["dependencies_status"] == "pending" or row["id"] in best_effort
    ]
    stop = threading.Event()

    def read_data(row: dict[str, Any], out: _DepResult) -> str | None:
        """The status of one item's data read; None when it stopped the run."""
        path = f"content/items/{quote(row['id'], safe='')}/data"
        is_map = row["type"] in _MAP_CONFIG_TYPES
        lenient = row["id"] in best_effort
        try:
            data = client.get_json(
                path,
                array_ok=lenient,
                # The portal answers a notebook's data with a redirect on its own host.
                follow_same_host=row["type"] in _NON_JSON_TYPES,
            )
        except PortalError as exc:
            _detach(exc)
            if exc.kind == "auth":
                stop.set()
                out.auth = exc
                return None
            if exc.kind == "redirect":
                # A file item's data is a download, which is never followed.
                if lenient:
                    return "not_applicable"
                exc = client._error(
                    f"{path} answered with a redirect (HTTP {exc.http_status}); "
                    "redirects are refused, so this item's data was not read.",
                    kind="redirect",
                    http_status=exc.http_status,
                )
            # An app registered only by URL has no data; a web map always has
            # a configuration, so an empty one is a failed read.
            not_json_ok = lenient or row["type"] in _NON_JSON_TYPES
            tolerated = (
                (
                    exc.kind in _UNREADABLE_KINDS
                    and (lenient or row["type"] in _URL_ONLY_TYPES)
                )
                or (not_json_ok and exc.kind == "not_json")
                or (lenient and exc.kind == "invalid")
            )
            if not is_map and tolerated:
                return "unparsed"
            out.errors.append(_error_row(row["id"], "item_data", exc))
            return "error"
        if sidecar_dir is not None and not lenient:
            out.saved = _write_sidecar(sidecar_dir, row, data, client._redact, out)
        if is_map and not _is_web_map(data):
            message = f"{path} is not a web map configuration"
            out.errors.append(
                _error_row(row["id"], "item_data", PortalError(message, kind="invalid"))
            )
            return "error"
        try:
            if lenient:
                ids = _scan_item_ids(data)
                status, dependencies = "unparsed", []
                if ids:
                    status = "parsed"
                    dependencies = [
                        _dependency(
                            row["id"],
                            i,
                            None,
                            role="referenced_item",
                            layer_type=None,
                            layer_id=None,
                            title=None,
                            order=n,
                            index=index,
                            portal=inv.portal,
                        )
                        for n, i in enumerate(ids)
                    ]
            else:
                status, dependencies = _extract_dependencies(
                    row, data, index, inv.portal
                )
        except (TypeError, ValueError, AttributeError, KeyError, IndexError) as exc:
            # One corrupt configuration must not sink the whole inventory.
            message = (
                f"{path} has a malformed configuration: {type(exc).__name__}: {exc}"
            )
            out.errors.append(
                _error_row(
                    row["id"], "item_data", client._error(message, kind="invalid")
                )
            )
            return "error"
        out.dependencies.extend(dependencies)
        return status

    def fetch(row: dict[str, Any]) -> _DepResult:
        out = _DepResult()
        if stop.is_set():
            return out
        status = None
        if row["id"] in reads_data or row["id"] in best_effort:
            status = read_data(row, out)
            if out.auth is not None:
                return out
        related_ok = True
        related_reads = _related_reads(row["type"], row["reason"])
        base = f"content/items/{quote(row['id'], safe='')}/relatedItems"
        for relationship, direction, role in related_reads:
            try:
                response = client.get_json(
                    base, {"relationshipType": relationship, "direction": direction}
                )
            except PortalError as exc:
                _detach(exc)
                if exc.kind == "auth":
                    stop.set()
                    out.auth = exc
                    return out
                out.errors.append(_error_row(row["id"], "related", exc))
                related_ok = False
                continue
            listed = response.get("relatedItems")
            if not isinstance(listed, list) or not all(
                isinstance(i, dict) and isinstance(i.get("id"), str) and i["id"]
                for i in listed
            ):
                malformed = PortalError(
                    f"{base} returned no usable relatedItems list", kind="invalid"
                )
                out.errors.append(_error_row(row["id"], "related", malformed))
                related_ok = False
                continue
            out.dependencies.extend(
                _related_dependencies(
                    row, response, role, index, inv.portal, len(out.dependencies)
                )
            )
        if not related_ok or status == "error":
            out.status = "error"
        elif related_reads:
            out.status = "parsed"
        else:
            out.status = status or "parsed"
        return out

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for row, out in zip(targets, pool.map(fetch, targets), strict=True):
            row["dependencies_status"] = out.status
            row["data_saved"] = out.saved
            inv.dependencies.extend(out.dependencies)
            inv.errors.extend(out.errors)
            if out.auth is not None:
                inv.abort = inv.abort or out.auth


def _write_sidecar(
    directory: Path,
    row: Mapping[str, Any],
    data: Any,
    redact: Redactor,
    out: _DepResult,
) -> bool:
    if not _SAFE_FILENAME.fullmatch(row["id"]):
        return False
    folder = "webmaps" if row["type"] == _WEB_MAP_TYPE else "apps"
    try:
        _report.write_sidecar(directory, folder, row["id"], redact_json(data, redact))
    except OSError as exc:
        message = redact(f"could not write the {folder} sidecar: {exc}")
        out.errors.append(
            {
                "item_id": row["id"],
                "phase": "item_data",
                "http_status": None,
                "message": message,
            }
        )
        return False
    return True


# Row fields the item's own record decides, over a possibly stale search result.
_DETAIL_KEYS = (
    "type",
    "dependencies_status",
    "size_bytes",
    "created",
    "modified",
    "url",
    "type_keywords",
    "class",
    "reason",
    "retirement",
    "hosted",
    "snippet",
    "description",
    "tags",
    "access_information",
    "license_info",
    "extent",
    "thumbnail",
    "spatial_reference",
    "culture",
    "layers",
)
# Kept from the search result when the item's record leaves them blank.
_DETAIL_REQUIRED_KEYS = ("title", "owner")
# Size of the window of item reads in flight and awaiting their merge.
_DETAIL_WINDOW = 64


@dataclass
class _Details:
    """What one item's metadata reads produced, reduced to small values."""

    fresh: dict[str, Any] | None = None
    groups: list[dict[str, Any]] | None = None
    errors: list[dict[str, Any]] = field(default_factory=list)
    auth: PortalError | None = None


def _error_row(key: str, phase: str, exc: PortalError) -> dict[str, Any]:
    return {
        "item_id": key,
        "phase": phase,
        "http_status": exc.http_status,
        "message": str(exc),
    }


def _item_groups(data: Mapping[str, Any], redact: Redactor) -> list[dict[str, Any]]:
    """Groups an item is shared with, from the admin, member and other lists."""
    groups: dict[str, dict[str, Any]] = {}
    for key in ("admin", "member", "other"):
        listed = data.get(key)
        for group in listed if isinstance(listed, list) else []:
            if not isinstance(group, dict) or not group.get("id"):
                continue
            access = group.get("access")
            group_id = redact(str(group["id"]))
            groups.setdefault(
                group_id,
                {
                    "id": group_id,
                    "title": redact(str(group.get("title") or "")),
                    "access": redact(access) if isinstance(access, str) else None,
                },
            )
    return list(groups.values())


def _collect_details(
    client: PortalClient, inv: Inventory, concurrency: int, read_groups: bool
) -> None:
    """Read each item's own record and group sharing into its row.

    A failed read leaves that item's search-result fields in place and adds
    an error row; only a rejected token stops the run.
    """
    stop = threading.Event()

    def fetch(row: dict[str, Any]) -> _Details:
        out = _Details()
        if stop.is_set():
            return out
        base = f"content/items/{quote(row['id'], safe='')}"
        for phase, path in (("item_details", base), ("item_groups", f"{base}/groups")):
            if phase == "item_groups" and not read_groups:
                break
            try:
                data = client.get_json(path)
            except PortalError as exc:
                _detach(exc)
                if exc.kind == "auth":
                    stop.set()
                    out.auth = exc
                    return out
                out.errors.append(_error_row(row["id"], phase, exc))
                continue
            if phase == "item_details":
                out.fresh = _item_row(
                    {**data, "id": row["id"], "type": data.get("type") or row["type"]},
                    client._redact,
                )
            else:
                out.groups = _item_groups(data, client._redact)
        return out

    # Reads run a window at a time and each result is merged as it arrives,
    # so finished descriptions are not held beside the rows they replace.
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for start in range(0, len(inv.items), _DETAIL_WINDOW):
            rows = inv.items[start : start + _DETAIL_WINDOW]
            for row, out in zip(rows, pool.map(fetch, rows), strict=True):
                _merge_details(inv, row, out)
    for row in inv.items:
        folder = row["folder"]
        if folder and folder["title"] is None:
            folder["title"] = inv.folder_titles.get(folder["id"])


def _merge_details(inv: Inventory, row: dict[str, Any], out: _Details) -> None:
    fresh = out.fresh
    if fresh is not None:
        for key in _DETAIL_KEYS:
            row[key] = fresh[key]
        for key in _DETAIL_REQUIRED_KEYS:
            row[key] = fresh[key] or row[key]
        row["sharing"]["access"] = fresh["sharing"]["access"]
        # The user-scope listing names the folder it read; an organization
        # search can be stale, so the item's own record wins there.
        if inv.scope["mode"] == "org":
            row["folder"] = fresh["folder"]
        elif fresh["folder"] and not row["folder"]:
            row["folder"] = fresh["folder"]
    if out.groups is not None:
        row["groups"] = out.groups
        row["sharing"]["groups"] = [g["id"] for g in out.groups]
    inv.errors.extend(out.errors)
    if out.auth is not None:
        inv.abort = inv.abort or out.auth


@dataclass
class _Owner:
    full_name: str | None = None
    email: str | None = None
    folders: dict[str, str] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    auth: PortalError | None = None


def _collect_owners(client: PortalClient, inv: Inventory, concurrency: int) -> None:
    """Read each distinct owner's name and email once, and in organization
    scope the folder titles of owners whose folders are known only by id.

    A portal that hides members or another user's folders answers with a
    client error; that leaves the values null without an error row.
    """
    owners = sorted({row["owner"] for row in inv.items if row["owner"]})
    untitled = {
        row["owner"]
        for row in inv.items
        if row["folder"] and row["folder"]["title"] is None
    }

    stop = threading.Event()

    def fetch(owner: str) -> _Owner:
        out = _Owner()
        if stop.is_set():
            return out
        name = quote(owner, safe="")
        reads = [("owner", f"community/users/{name}", {})]
        if owner in untitled:
            reads.append(("folders", f"content/users/{name}", {"num": 1}))
        for phase, path, params in reads:
            try:
                data = client.get_json(path, params)
            except PortalError as exc:
                _detach(exc)
                if exc.kind == "auth":
                    stop.set()
                    out.auth = exc
                    return out
                if exc.http_status not in _HIDDEN_STATUSES:
                    out.errors.append(_error_row(owner, phase, exc))
                continue
            if phase == "owner":
                out.full_name = _text(data.get("fullName"), client._redact)
                out.email = _text(data.get("email"), client._redact)
            else:
                folders = data.get("folders")
                for f in folders if isinstance(folders, list) else []:
                    if isinstance(f, dict) and f.get("id") and f.get("title"):
                        out.folders[client._redact(str(f["id"]))] = client._redact(
                            str(f["title"])
                        )
        return out

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = dict(zip(owners, pool.map(fetch, owners), strict=True))

    for row in inv.items:
        out = results.get(row["owner"])
        if out is None:
            continue
        row["owner_full_name"] = out.full_name
        row["owner_email"] = out.email
        folder = row["folder"]
        if folder and folder["title"] is None:
            folder["title"] = out.folders.get(folder["id"])
    for out in results.values():
        inv.errors.extend(out.errors)
        if out.auth is not None:
            inv.abort = inv.abort or out.auth


def external_by_url(url: str | None, portal: Mapping[str, Any]) -> bool | None:
    """Whether a service URL lies outside the organization's own services."""
    if not url:
        return None
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host == (urlsplit(portal["url"]).hostname or "").lower():
        return False
    if portal["kind"] == "online":
        org = portal["org_id"] or ""
        if not org or not _ARCGIS_ONLINE_HOSTED.fullmatch(host):
            return True if org else None
        # Organization ids are case-sensitive; the rest of the path isn't.
        return not any(
            parts.path.startswith(prefix)
            and parts.path[len(prefix) :].lower().startswith("arcgis/rest/services/")
            for prefix in (f"/{org}/", f"/tiles/{org}/")
        )
    # A federated server sits on any host and publishes in any folder, and the
    # inventory doesn't know the federation, so a host other than the portal's
    # can't be called foreign.
    return None


def _resolve_external(client: PortalClient, inv: Inventory, concurrency: int) -> None:
    """Mark each dependency that points at another organization's content.

    An unresolved item id gets one ``/content/items`` read, cached for the
    run, because search results omit ``orgId``. An item the account can't read
    falls back to its URL, and with no URL stays unknown. Only a client error
    counts as "can't read"; a timeout or server failure is an error row.
    """
    own_org = inv.portal["org_id"]
    ids = sorted(
        {d["to_id"] for d in inv.dependencies if d["to_id"] and not d["resolved"]}
    )
    stop = threading.Event()
    anonymous = inv.auth["mode"] == "anonymous"

    def fatal(exc: PortalError) -> bool:
        # A 401 on a lookup of someone else's item means "not visible to
        # you"; a rejected token is the run's own failure.
        return exc.kind == "auth" and exc.http_status != 401 and not anonymous

    def fetch(item_id: str) -> tuple[str | None, PortalError | None]:
        if stop.is_set():
            return None, None
        try:
            data = client.get_json(f"content/items/{quote(item_id, safe='')}")
        except PortalError as exc:
            _detach(exc)
            if fatal(exc):
                stop.set()
            return None, exc
        org = data.get("orgId")
        return (org if isinstance(org, str) and org else None), None

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = dict(zip(ids, pool.map(fetch, ids), strict=True))
    orgs = {item_id: org for item_id, (org, _) in results.items()}
    for item_id, (_, failure) in results.items():
        if failure is None:
            continue
        if fatal(failure):
            inv.abort = inv.abort or failure
        elif failure.http_status not in _HIDDEN_ITEM_STATUSES:
            inv.errors.append(_error_row(client._redact(item_id), "external", failure))
    for dep in inv.dependencies:
        if dep["resolved"]:
            continue
        org = orgs.get(dep["to_id"])
        if org and own_org:
            dep["external"] = org != own_org
        else:
            dep["external"] = external_by_url(dep["to_url"], inv.portal)


def _redact_dependencies(inv: Inventory, redact: Redactor) -> None:
    """Redact the portal-supplied text of every dependency row.

    This runs last because the ids in these rows address later requests.
    """
    for dep in inv.dependencies:
        for key in ("to_id", "to_url", "layer_type", "layer_id", "title"):
            if isinstance(dep[key], str):
                dep[key] = redact(dep[key])


def _signed_in_user(info: Mapping[str, Any]) -> str | None:
    user = info.get("user")
    name = user.get("username") if isinstance(user, dict) else None
    return name if isinstance(name, str) and name else None


def _signed_in_role(info: Mapping[str, Any]) -> str | None:
    user = info.get("user")
    role = user.get("role") if isinstance(user, dict) else None
    return role if isinstance(role, str) and role else None


def _portal_time(header: str | None) -> str | None:
    """An HTTP Date header as an ISO time, or None."""
    try:
        when = parsedate_to_datetime(header) if header else None
    except (TypeError, ValueError):
        return None
    if when is None or when.tzinfo is None:
        return None
    return when.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _mark_not_fetched(inv: Inventory) -> None:
    for row in inv.items:
        if row["dependencies_status"] == "pending":
            row["dependencies_status"] = "not_fetched"


def run_inventory(
    client: PortalClient,
    *,
    auth_mode: str,
    scope: str,
    max_items: int,
    concurrency: int,
    read_groups: bool = True,
    read_all_item_data: bool = False,
    sidecar_dir: Path | None = None,
) -> Inventory:
    """List, classify, read item metadata and resolve dependencies.

    A failure reading ``portals/self`` raises ``PortalError``. Any later
    listing failure, or a rejected token while reading item data, stops the
    run and is recorded as ``Inventory.abort``; everything gathered so far is
    kept for a partial report.
    """
    info = client.get_json("portals/self")
    started_at = _portal_time(client.server_date)
    username = _signed_in_user(info)
    # A server or web tier that ignores the header answers anonymously
    # rather than with a 499, so a token without an identity gets one
    # form-field retry before it counts as rejected.
    if auth_mode != "anonymous" and not username and client.switch_to_form_token():
        info = client.get_json("portals/self")
        username = _signed_in_user(info)
    org_id = info.get("id") if isinstance(info.get("id"), str) else None
    portal = {
        "url": client.root,
        "kind": "enterprise" if info.get("isPortal") else "online",
        "version": str(info["currentVersion"]) if info.get("currentVersion") else None,
        "org_id": org_id,
        "name": str(info["name"]) if info.get("name") else None,
    }
    if auth_mode != "anonymous" and not username:
        raise PortalError(
            "the portal answered without a signed-in user, so the credentials "
            "were ignored or rejected. Nothing was listed, so no public-only "
            "report is written; check the token or sign-in.",
            kind="auth",
        )
    if scope == "org" and not org_id:
        raise PortalError(
            "the portal did not report an organization id. Use the "
            "organization's own URL (https://<org>.maps.arcgis.com, or "
            "https://<host>/portal for ArcGIS Enterprise).",
            kind="usage",
        )
    inv = Inventory(
        portal=portal,
        auth={"mode": auth_mode, "user": username, "role": _signed_in_role(info)},
        scope={
            "mode": scope,
            "owner": username if scope == "user" else None,
            "org_id": org_id if scope == "org" else None,
        },
        started_at=started_at,
    )
    try:
        for raw, folder_id in _list_items(client, inv, max_items):
            row = _item_row(raw, client._redact)
            if folder_id:
                row["folder"] = {"id": client._redact(folder_id), "title": None}
            inv.items.append(row)
    except PortalError as exc:
        inv.abort = exc
        _mark_not_fetched(inv)
        return inv
    # An anonymous caller sees no private groups, so its list would read as
    # "shared with nothing" rather than "unknown".
    _collect_details(client, inv, concurrency, read_groups and auth_mode != "anonymous")
    if inv.abort is None:
        _collect_owners(client, inv, concurrency)
    if inv.abort is not None:
        _mark_not_fetched(inv)
        return inv
    _collect_dependencies(
        client,
        inv,
        concurrency,
        read_all=read_all_item_data,
        sidecar_dir=sidecar_dir,
    )
    if inv.abort is None:
        _resolve_external(client, inv, concurrency)
    _redact_dependencies(inv, client._redact)
    return inv


class InventoryScope(str, Enum):
    user = "user"
    org = "org"


@dataclass
class InventoryOptions:
    portal_url: str
    token: str | None
    token_stdin: bool
    username: str | None
    password_stdin: bool
    scope: str
    max_items: int
    concurrency: int
    output_dir: Path | None
    strict: bool
    allow_insecure_http: bool
    json_mode: bool
    read_groups: bool = True
    read_all_item_data: bool = False


class _UsageError(Exception):
    pass


_EXIT_BY_KIND = {
    "auth": EXIT_AUTH,
    "network": EXIT_NETWORK,
    "server": EXIT_SERVER,
    "redirect": EXIT_USAGE,
    "usage": EXIT_USAGE,
}


def _portal_root(url: str, allow_insecure_http: bool) -> str:
    try:
        return portal_root(url, allow_insecure_http)
    except ValueError as exc:
        raise _UsageError(str(exc)) from None


def _resolve_credentials(opts: InventoryOptions) -> tuple[str, str | None, str | None]:
    """(auth mode, token, password)."""
    try:
        token, password = read_credentials(
            opts.token, opts.token_stdin, opts.username, opts.password_stdin
        )
    except ValueError as exc:
        raise _UsageError(str(exc)) from None
    if token is not None:
        return "token", token, None
    if opts.username:
        return "generateToken", None, password
    if opts.scope == "user":
        raise _UsageError(
            "--scope user needs a signed-in user: pass --token, ARCGIS_TOKEN, "
            "--token-stdin or --username, or use --scope org to list public items"
        )
    return "anonymous", None, None


def _tool_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("geolens-cli")
    except PackageNotFoundError:
        return "0.0.0+dev"


def _emit(fmt: _output.Formatter, opts: InventoryOptions, report: dict) -> None:
    markdown = _report.render_markdown(report)
    if opts.output_dir is not None:
        json_path, md_path = _report.write_report_files(
            opts.output_dir, report, markdown
        )
        fmt.success(f"Wrote {json_path} and {md_path}")
    elif opts.json_mode:
        fmt.json(report)
    else:
        sys.stdout.write(markdown)
        sys.stdout.flush()


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _clock() -> float:
    return time.monotonic()


def _iso_now() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


def run_cli(fmt: _output.Formatter, opts: InventoryOptions) -> int:
    """Run ``geolens arcgis inventory`` and return its exit code."""
    redact = Redactor()
    try:
        return _run(fmt, opts, redact)
    except (
        Exception
    ) as exc:  # broad: last guard so a traceback can't print a credential
        fmt.error(redact(f"unexpected error: {type(exc).__name__}: {exc}"))
        return EXIT_GENERIC


def _run(fmt: _output.Formatter, opts: InventoryOptions, redact: Redactor) -> int:
    try:
        if not 1 <= opts.concurrency <= MAX_CONCURRENCY:
            raise _UsageError(f"--concurrency must be between 1 and {MAX_CONCURRENCY}")
        if opts.max_items < 1:
            raise _UsageError("--max-items must be at least 1")
        root = _portal_root(opts.portal_url, opts.allow_insecure_http)
        auth_mode, token, password = _resolve_credentials(opts)
    except _UsageError as exc:
        fmt.error(str(exc))
        return EXIT_USAGE
    redact.add(token)
    redact.add(password)

    client = PortalClient(
        root,
        opener=build_opener(),
        redact=redact,
        token=token,
        sleep=_sleep,
        clock=_clock,
        on_request=lambda method, path: fmt.debug(redact(f"{method} {path}")),
    )
    started_at_local = _iso_now()
    try:
        if password is not None and opts.username:
            client.generate_token(opts.username, password)
        inv = run_inventory(
            client,
            auth_mode=auth_mode,
            scope=opts.scope,
            max_items=opts.max_items,
            concurrency=opts.concurrency,
            read_groups=opts.read_groups,
            read_all_item_data=opts.read_all_item_data,
            sidecar_dir=opts.output_dir,
        )
    except PortalError as exc:
        fmt.error(str(exc))
        return _EXIT_BY_KIND.get(exc.kind, EXIT_GENERIC)

    report = _report.build_report(
        inv,
        tool_version=_tool_version(),
        generated_at=_iso_now(),
        started_at_local=started_at_local,
        max_items=opts.max_items,
        retirements=RETIREMENTS,
        classes=CLASSES,
    )
    _emit(fmt, opts, report)
    if inv.abort is not None:
        hint = (
            " The token was rejected mid-run (it may have expired); rerun with a fresh token."
            if inv.abort.kind == "auth"
            else ""
        )
        fmt.error(f"inventory stopped early, report is partial: {inv.abort}.{hint}")
        return _EXIT_BY_KIND.get(inv.abort.kind, EXIT_GENERIC)
    if inv.errors and opts.strict:
        fmt.error(f"{len(inv.errors)} read(s) failed (--strict)")
        return EXIT_GENERIC
    return EXIT_OK
