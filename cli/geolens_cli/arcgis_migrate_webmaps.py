# SPDX-License-Identifier: Apache-2.0
"""The ``import_map`` action of `geolens arcgis migrate`.

Hand-maintained. Reads a Web Map's configuration from the portal, matches its
operational layers to the datasets the run imported for the services they
point at, fills in the renderer of each layer the web map leaves to its source,
and has GeoLens translate it into a map. The layer-to-map-layer ids
GeoLens returns are kept in the item's state, and the loss report is written
next to the state file.
"""

from __future__ import annotations

import base64
import json
import re
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit
from uuid import UUID

import typer

from . import arcgis_report as _report
from ._sdk_helpers import EXIT_NETWORK, long_request_timeout
from .arcgis_migrate_export import _modified, _safe_relative, _stop_if_token_refused
from .arcgis_migrate_files import JOB_KEY
from .arcgis_migrate_layers import _trusted
from .arcgis_migrate_session import (
    GeoLens,
    GeoLensError,
    ItemFailed,
    ItemResult,
    MigrationContext,
    StopRun,
)
from .arcgis_plan import IMPORT_MAP
from .arcgis_migrate_state import DONE, EXISTS, FINISHED, ItemState, whole_number
from .arcgis_portal import PortalError, redact_json, sanitize_url

LOSS_DIRNAME = "webmap-loss"
_ITEM_ID = re.compile(r"[0-9A-Za-z]{32}")
_TRAILING_LAYER = re.compile(r"/(\d+)/?$")
_MAX_NOTE_LAYERS = 5
_TOKEN_STATUSES = (498, 499)
# The server refuses a request with over 1,000 matches. It applies its own
# per-map layer limit after validating each layer, so it chooses among them.
_MAX_MATCHES = 1000
# The layer types the server translates; its translator is the source.
_FEATURE_LAYER_TYPES = ("ArcGISFeatureLayer", "FeatureLayer")
_THUMBNAIL_TYPES = {b"\x89PNG\r\n\x1a\n": "image/png", b"\xff\xd8\xff": "image/jpeg"}
# The most image bytes whose data URI fits ThumbnailUploadRequest.data_uri's
# max_length of 100,000 characters.
_THUMBNAIL_MAX_BYTES = (100_000 - len("data:image/jpeg;base64,")) // 4 * 3
_THUMBNAIL_NOTE = "the web map's thumbnail was not carried over"


def _walk(layers: Any) -> list[Mapping[str, Any]]:
    """Operational layers in the order the server reads them: depth first,
    group members in place of their group. Entries that aren't objects are
    skipped."""
    found: list[Mapping[str, Any]] = []
    stack = [iter(layers if isinstance(layers, list) else [])]
    while stack:
        for layer in stack[-1]:
            if not isinstance(layer, dict):
                continue
            if layer.get("layerType") == "GroupLayer":
                members = layer.get("layers")
                stack.append(iter(members if isinstance(members, list) else []))
                break
            found.append(layer)
        else:
            stack.pop()
    return found


def _translatable(layer: Mapping[str, Any]) -> bool:
    """Whether the server translates *layer* rather than dropping it as an
    unsupported type, before it looks at the layer's id."""
    if layer.get("featureCollection") is not None:
        return False
    layer_type = layer.get("layerType")
    if isinstance(layer_type, str) and layer_type in _FEATURE_LAYER_TYPES:
        return True
    url = layer.get("url")
    return (
        layer_type is None and isinstance(url, str) and "/FeatureServer" in url[:2000]
    )


def _dataset_for(
    layer: Mapping[str, Any], source: ItemState, *, aliased: bool = False
) -> str | None:
    """The dataset imported for *layer*, or None when the item holds no
    unambiguous one."""
    url = layer.get("url")
    try:
        path = urlsplit(url).path if isinstance(url, str) else ""
    except ValueError:
        return None
    sub = _TRAILING_LAYER.search(path)
    if sub and aliased:
        # A hosted view numbers its layers on its own, and nothing the run
        # recorded ties a view layer to the parent's.
        return None
    if sub:
        # An index the run imported no dataset for is another layer's, not
        # the sole dataset's.
        found = source.layer_datasets.get(sub.group(1))
        if found is None and sub.group(1) == "0" and JOB_KEY in source.layer_datasets:
            # A single-layer file has one layer, which a web map calls 0.
            return source.layer_datasets[JOB_KEY]
        return found
    if len(source.dataset_ids) == 1:
        return source.dataset_ids[0]
    return None


def match_datasets(ctx: MigrationContext, webmap: Mapping[str, Any]) -> dict[str, str]:
    """Operational layer id -> dataset id, for the layers whose item the run
    imported."""
    matches: dict[str, str] = {}
    seen: set[str] = set()
    for layer in _walk(webmap.get("operationalLayers")):
        layer_id, item_id = layer.get("id"), layer.get("itemId")
        if len(matches) >= _MAX_MATCHES:
            break
        # An unsupported layer is dropped before its id is reserved, and the
        # server keeps the first supported layer of an id.
        if not _translatable(layer):
            continue
        if not isinstance(layer_id, str) or layer_id in seen:
            continue
        seen.add(layer_id)
        if not isinstance(item_id, str):
            continue
        parent = ctx.aliases.get(item_id)
        source = ctx.items.get(parent or item_id)
        if source is None or source.status not in FINISHED:
            continue
        dataset = _dataset_for(layer, source, aliased=parent is not None)
        if dataset:
            matches[layer_id] = dataset
    return matches


def _read_object(read: Callable[[], Any], *, portal: bool = False) -> dict[str, Any]:
    """*read*'s JSON object, or an empty one when it fails: missing styling
    leaves a layer with GeoLens's default rather than failing the map. A
    portal read the token is refused on stops the run instead."""
    try:
        data = read()
    except PortalError as exc:
        if portal:
            _stop_if_token_refused(exc)
        return {}
    return data if isinstance(data, dict) else {}


def _item_drawing(
    ctx: MigrationContext, item_id: Any, index: str, cache: dict[str, dict[str, Any]]
) -> Any:
    """The drawing info saved on the layer's item for service layer *index*."""
    if not isinstance(item_id, str) or not _ITEM_ID.fullmatch(item_id):
        return None
    if item_id not in cache:
        cache[item_id] = _read_object(
            lambda: ctx.portal.client.get_json(f"content/items/{item_id}/data"),
            portal=True,
        )
    layers = cache[item_id].get("layers")
    for entry in layers if isinstance(layers, list) else []:
        if isinstance(entry, dict) and str(entry.get("id")) == index:
            definition = entry.get("layerDefinition")
            return (
                definition.get("drawingInfo") if isinstance(definition, dict) else None
            )
    return None


def fill_source_styling(
    ctx: MigrationContext, webmap: dict[str, Any], matches: Mapping[str, str]
) -> None:
    """Give each matched layer that the web map leaves to its source the
    renderer ArcGIS draws it with: the one saved on its layer item, else the
    service layer's own. The service is read only on a host trusted with the
    token, as for the import."""
    items: dict[str, dict[str, Any]] = {}
    services: dict[str, dict[str, Any]] = {}
    for layer in _walk(webmap.get("operationalLayers")):
        definition = layer.get("layerDefinition")
        definition = definition if isinstance(definition, dict) else {}
        drawing = definition.get("drawingInfo")
        drawing = drawing if isinstance(drawing, dict) else {}
        url = sanitize_url(layer.get("url"))
        sub = _TRAILING_LAYER.search(urlsplit(url).path) if url else None
        if (
            not isinstance(layer.get("id"), str)
            or layer["id"] not in matches
            or drawing.get("renderer")
            or sub is None
        ):
            continue
        source = _item_drawing(ctx, layer.get("itemId"), sub.group(1), items)
        if not isinstance(source, dict) or not source.get("renderer"):
            if not _trusted(ctx, url):
                continue
            if url not in services:
                services[url] = _read_object(
                    lambda: ctx.portal.client.get_service_json(url)
                )
            source = services[url].get("drawingInfo")
        if not isinstance(source, dict) or not isinstance(source.get("renderer"), dict):
            continue
        filled = redact_json(
            {k: source[k] for k in ("renderer", "transparency") if k in source},
            ctx.redact,
        )
        layer["layerDefinition"] = {
            **definition,
            "drawingInfo": {**filled, **drawing, "renderer": filled["renderer"]},
        }


def _basemap_entries(
    ctx: MigrationContext, webmap: Mapping[str, Any]
) -> dict[str, str]:
    """The plan's basemap mapping for this web map's first basemap layer; the
    server reads no other entry and caps how many a request may carry."""
    base = webmap.get("baseMap")
    layers = base.get("baseMapLayers") if isinstance(base, dict) else None
    first = layers[0] if isinstance(layers, list) and layers else None
    if not isinstance(first, dict):
        return {}
    # The plan's keys have no query or userinfo; the server looks the web
    # map's own URL up, so the request is keyed by that.
    return {
        key: ctx.basemap_map[plain]
        for key in (first.get("url"), first.get("styleUrl"))
        if isinstance(key, str)
        and (plain := sanitize_url(key)) is not None
        and plain in ctx.basemap_map
    }


def _fetch(ctx: MigrationContext, item_id: str) -> dict[str, Any]:
    if ctx.portal is None:
        raise ItemFailed("the run can't read this item from the portal")
    try:
        data = ctx.portal.client.get_json(f"content/items/{item_id}/data")
    except PortalError as exc:
        if exc.http_status in _TOKEN_STATUSES:
            raise StopRun(
                f"the portal refused the ArcGIS token ({exc}); it may have "
                "expired. Rerun with a fresh token to resume."
            ) from None
        raise ItemFailed(f"reading the web map failed, {exc}") from None
    if not isinstance(data, dict):
        raise ItemFailed("the web map's data is not a JSON object")
    # A layer URL can carry a stored token, which must not reach GeoLens.
    return redact_json(data, ctx.redact)


def _read_item(ctx: MigrationContext, item_id: str) -> Mapping[str, Any]:
    """The portal item, or an empty one when it can't be read."""
    if ctx.portal is None:
        return {}
    try:
        info = ctx.portal.client.get_json(f"content/items/{item_id}")
    except PortalError as exc:
        _stop_if_token_refused(exc)
        return {}
    return info if isinstance(info, dict) else {}


class _NoThumbnail(Exception):
    """Why the item's thumbnail isn't carried over."""


def _thumbnail_data_uri(ctx: MigrationContext, item_id: str, path: Any) -> str:
    """The item's thumbnail as a data URI GeoLens takes."""
    if not isinstance(path, str) or not path:
        raise _NoThumbnail("the web map has none")
    if ctx.portal is None or _safe_relative(path) is None:
        raise _NoThumbnail("its path can't be read from the portal")
    try:
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / "thumbnail"
            ctx.portal.client.download(
                f"content/items/{item_id}/info/{quote(path)}",
                dest,
                _THUMBNAIL_MAX_BYTES,
            )
            image = dest.read_bytes()
    except PortalError as exc:
        if exc.kind == "too_large":
            raise _NoThumbnail("it is larger than GeoLens takes") from None
        raise _NoThumbnail(f"reading it failed, {exc}") from None
    except OSError as exc:
        raise _NoThumbnail(
            f"reading it failed: {exc.strerror or type(exc).__name__}"
        ) from None
    media = next(
        (t for magic, t in _THUMBNAIL_TYPES.items() if image.startswith(magic)), None
    )
    if media is None:
        raise _NoThumbnail("it is not a PNG or JPEG image")
    return f"data:{media};base64,{base64.b64encode(image).decode()}"


def carry_thumbnail(
    ctx: MigrationContext, item_id: str, info: Mapping[str, Any], map_id: str
) -> list[str]:
    """Upload the portal item's thumbnail to the GeoLens map, which has none.

    A thumbnail never fails the item; the note says why it wasn't uploaded.
    """
    from geolens.api.maps import upload_thumbnail_maps_map_id_thumbnail_put as upload
    from geolens.models.thumbnail_upload_request import ThumbnailUploadRequest

    try:
        data_uri = _thumbnail_data_uri(ctx, item_id, info.get("thumbnail"))
        ctx.geolens.call(
            upload.sync_detailed,
            expected=204,
            map_id=UUID(map_id),
            body=ThumbnailUploadRequest(data_uri=data_uri),
        )
    except _NoThumbnail as exc:
        return [f"{_THUMBNAIL_NOTE}: {exc}"]
    except GeoLensError as exc:
        return [f"{_THUMBNAIL_NOTE}: uploading it failed, {exc}"]
    except typer.Exit as exc:
        # How the SDK call reports a timeout or network failure.
        if exc.exit_code != EXIT_NETWORK:
            raise
        return [f"{_THUMBNAIL_NOTE}: uploading it failed on the network"]
    return []


def thumbnail_dry_run_notes(
    to_run: Sequence[Mapping[str, Any]],
    inventory: Mapping[str, Mapping[str, Any]],
    states: Mapping[str, ItemState],
) -> dict[str, list[str]]:
    """What a run would do with the thumbnail of each web map it would create."""
    return {
        item["id"]: ["would upload the web map's thumbnail to the new GeoLens map"]
        for item in to_run
        if item["action"] == IMPORT_MAP
        and not (item["id"] in states and states[item["id"]].map_id)
        and inventory.get(item["id"], {}).get("thumbnail")
    }


def get_map(geolens: GeoLens, map_id: str) -> Any:
    from geolens.api.maps import get_map_endpoint_maps_map_id_get as get

    return geolens.call(get.sync_detailed, map_id=UUID(map_id))


def map_state(found: Any) -> dict[str, str]:
    """What a later run compares to tell whether GeoLens changed a map."""
    return {"owner": str(found.created_by), "updated_at": found.updated_at.isoformat()}


def map_visibility(found: Any) -> str:
    return str(getattr(found.visibility, "value", found.visibility))


def _map_problem(
    ctx: MigrationContext, item: Mapping[str, Any], entry: ItemState
) -> tuple[str | None, Any]:
    """Why the GeoLens map recorded for the item doesn't stand as migrated:
    gone, unreadable, owned by someone else than it was handed to, or with a
    visibility other than the plan's that its groups can't settle, and the map
    when it could be read. A rerun changes only a map's groups and a missing
    thumbnail, so any other difference is reported for the operator."""
    gone = "the migrated map is gone from GeoLens"
    if not entry.map_id:
        return gone, None
    try:
        found = get_map(ctx.geolens, entry.map_id)
    except ValueError:
        return gone, None
    except GeoLensError as exc:
        if exc.status == 404:
            return gone, None
        return f"reading the migrated map from GeoLens failed, {exc}", None
    if entry.owner_id and str(found.created_by) != entry.owner_id:
        return (
            "the GeoLens map's owner changed in GeoLens since this command handed "
            "it over; check who should own it"
        ), found
    wanted = item["target"]["visibility"]
    current = map_visibility(found)
    # Between private and restricted the map's groups decide, which sharing
    # the item brings up to date afterwards.
    if current != wanted and not {current, wanted} <= {"private", "restricted"}:
        return (
            f"the plan gives the web map visibility {wanted} but the GeoLens map "
            f"is {current}; set it by hand or rerun with the plan matching"
        ), found
    return None, found


def refresh_map(
    ctx: MigrationContext, item: Mapping[str, Any], entry: ItemState
) -> list[str]:
    """Why a migrated web map may not match its portal item: gone from
    GeoLens, shared differently than the plan says in a way its groups can't
    settle, changed in the portal since it was read for the import, or with no
    way to tell. A web map isn't translated again; the operator updates the
    GeoLens map. A map with no thumbnail gets the item's."""
    problem, found = _map_problem(ctx, item, entry)
    if problem:
        return [problem]
    if ctx.portal is None:
        return [
            "the run can't read this web map from the portal to check it for changes"
        ]
    try:
        info = ctx.portal.client.get_json(f"content/items/{item['id']}")
    except PortalError as exc:
        _stop_if_token_refused(exc)
        return [f"reading the web map to check it for changes failed, {exc}"]
    if isinstance(info, dict) and not found.thumbnail_url:
        entry.notes = [
            *(note for note in entry.notes if not note.startswith(_THUMBNAIL_NOTE)),
            *carry_thumbnail(ctx, item["id"], info, entry.map_id),
        ]
    modified = _modified(info)
    if modified is None:
        return ["the portal doesn't say when the web map last changed"]
    recorded = whole_number(entry.portal_modified)
    if recorded is None:
        return [
            "the state doesn't record when the web map was read for its import, so "
            "a change since can't be ruled out; compare the GeoLens map by hand"
        ]
    if modified > recorded:
        return [
            "the web map changed in the portal since it was migrated; web maps "
            "aren't translated again, so update the GeoLens map by hand"
        ]
    return []


def _write_loss(ctx: MigrationContext, item_id: str, report: Any) -> str:
    if ctx.export_dir is None:
        raise ItemFailed("the run has no folder for the loss report")
    folder = ctx.export_dir.parent
    path = Path(LOSS_DIRNAME) / f"{item_id}.json"
    text = json.dumps(redact_json(report, ctx.redact), indent=2, sort_keys=True)
    try:
        (folder / LOSS_DIRNAME).mkdir(parents=True, exist_ok=True)
        _report.write_private(folder / path, text + "\n")
    except OSError as exc:
        raise ItemFailed(
            f"writing the loss report failed: {exc.strerror or type(exc).__name__}"
        ) from None
    return path.as_posix()


def import_map(
    ctx: MigrationContext, item: Mapping[str, Any], entry: ItemState
) -> ItemResult:
    """Create the GeoLens map for a Web Map item; a map the state already
    holds is kept rather than imported again."""
    if entry.map_id:
        if entry.pending_loss is not None:
            return _finish_loss(ctx, item["id"], entry)
        return ItemResult(status=EXISTS, notes=list(entry.notes))
    if not _ITEM_ID.fullmatch(item["id"]):
        raise ItemFailed("the item id is not an ArcGIS item id")

    from geolens.api.maps import (
        import_arcgis_webmap_endpoint_maps_import_arcgis_webmap_post as import_webmap,
    )
    from geolens.models.arcgis_webmap_import_request import ArcgisWebmapImportRequest
    from geolens.models.arcgis_webmap_import_request_basemap_map import (
        ArcgisWebmapImportRequestBasemapMap,
    )
    from geolens.models.arcgis_webmap_import_request_dataset_matches import (
        ArcgisWebmapImportRequestDatasetMatches,
    )
    from geolens.models.arcgis_webmap_import_request_webmap import (
        ArcgisWebmapImportRequestWebmap,
    )
    from geolens.models.map_visibility import check_map_visibility

    info = _read_item(ctx, item["id"])
    webmap = _fetch(ctx, item["id"])
    matches = match_datasets(ctx, webmap)
    fill_source_styling(ctx, webmap, matches)
    title = item["target"]["title"] or item["title"]
    visibility = item["target"]["visibility"]
    body = ArcgisWebmapImportRequest(
        webmap=ArcgisWebmapImportRequestWebmap.from_dict(webmap),
        name=title[:255],
        title=item["title"][:255],
        # A new map can't be restricted before it has groups; sharing it
        # with them afterwards makes it restricted.
        visibility=check_map_visibility(
            "private" if visibility == "restricted" else visibility
        ),
        basemap_map=ArcgisWebmapImportRequestBasemapMap.from_dict(
            _basemap_entries(ctx, webmap)
        ),
        dataset_matches=ArcgisWebmapImportRequestDatasetMatches.from_dict(matches),
    )
    try:
        with long_request_timeout(ctx.geolens.client):
            result = ctx.geolens.call(
                import_webmap.sync_detailed,
                expected=201,
                body=body,
            )
    except GeoLensError as exc:
        raise ItemFailed(f"the web map import failed, {exc}") from None

    entry.map_id = str(result.map_.id)
    entry.portal_modified = _modified(info)
    entry.layer_ids = {
        k: str(v) for k, v in result.layer_ids.additional_properties.items()
    }
    # Kept in the state until the loss report file is written, so a failed
    # write is finished on the rerun instead of dropping the losses.
    entry.pending_loss = {
        "loss_report": result.loss_report.to_dict(),
        "unmatched_layers": [layer.to_dict() for layer in result.unmatched_layers],
    }
    ctx.save()
    thumbnail_notes = carry_thumbnail(ctx, item["id"], info, entry.map_id)
    finished = _finish_loss(ctx, item["id"], entry)
    finished.notes.extend(thumbnail_notes)
    return finished


def _finish_loss(ctx: MigrationContext, item_id: str, entry: ItemState) -> ItemResult:
    payload = entry.pending_loss or {}
    notes: list[str] = []
    unmatched = [
        layer.get("title") or layer.get("layer_id")
        for layer in payload.get("unmatched_layers", [])
    ]
    if unmatched:
        shown = ", ".join(unmatched[:_MAX_NOTE_LAYERS])
        more = len(unmatched) - _MAX_NOTE_LAYERS
        notes.append(
            f"{len(unmatched)} layer(s) not imported: {shown}"
            + (f" and {more} more" if more > 0 else "")
        )
    lost = payload.get("loss_report", {}).get("items", [])
    if lost:
        notes.append(f"{len(lost)} part(s) of the web map were not carried over")
    if lost or unmatched:
        entry.loss_report_path = _write_loss(ctx, item_id, payload)
    entry.pending_loss = None
    ctx.save()
    return ItemResult(status=DONE, notes=notes)
