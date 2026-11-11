# SPDX-License-Identifier: Apache-2.0
"""The ``import_map`` action of `geolens arcgis migrate`.

Hand-maintained. Reads a Web Map's configuration from the portal, matches its
operational layers to the datasets the run imported for the services they
point at, fills in the renderer of each layer the web map leaves to its source,
and has GeoLens translate it into a map. The layer-to-map-layer ids
GeoLens returns are kept in the item's state, and the loss report is written
next to the state file. A rerun translates a web map the portal changed again,
into the same map, while the map is as this command left it.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import tempfile
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from datetime import UTC, datetime
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
from .arcgis_migrate_refresh import KEEP_GEOLENS
from .arcgis_migrate_session import (
    GeoLens,
    GeoLensError,
    ItemFailed,
    ItemResult,
    MigrationContext,
    StopRun,
    WriteRaced,
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
_UNMATCHED_NOTE = "layer(s) not imported"
_LOST_NOTE = "part(s) of the web map were not carried over"
_NO_VIEW_NOTE = (
    "the web map no longer has an initial view; the GeoLens map keeps its view"
)
_NEEDS_NEWER = (
    "the web map changed in the portal, and re-translating needs GeoLens and the "
    "geolens package 1.30 or newer; upgrade them or update the map by hand"
)
_UNREADABLE_NOTE = (
    "layers not translated again because this account can't read their "
    "datasets, so their map layers were left as they are"
)
# How many layers a map may hold, as PUT /maps/{id} caps them.
_MAX_LAYERS = 200
# What a map's notes may hold, as PUT /maps/{id} caps them.
_MAP_NOTES_MAX = 50_000
_NOTES_CUT = "... more entries in the CLI report"
# The notes _finish_loss writes, which a new translation replaces.
_LOSS_NOTE = re.compile(rf"\d+ ({re.escape(_UNMATCHED_NOTE)}|{re.escape(_LOST_NOTE)})")


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


def _sourced_layers(
    ctx: MigrationContext, webmap: Mapping[str, Any]
) -> Iterator[tuple[str, Mapping[str, Any], bool, str, ItemState | None]]:
    """The operational layers of items, as (layer id, layer, whether the item
    is a hosted view standing in for its parent, plan item id of the source,
    that item's state), for the layers the server translates.
    An unsupported layer is dropped before its id is reserved, and the server
    keeps the first supported layer of an id."""
    seen: set[str] = set()
    for layer in _walk(webmap.get("operationalLayers")):
        layer_id, item_id = layer.get("id"), layer.get("itemId")
        if not _translatable(layer):
            continue
        if not isinstance(layer_id, str) or layer_id in seen:
            continue
        seen.add(layer_id)
        if not isinstance(item_id, str):
            continue
        parent = ctx.aliases.get(item_id)
        source_id = parent or item_id
        yield layer_id, layer, parent is not None, source_id, ctx.items.get(source_id)


def match_datasets(ctx: MigrationContext, webmap: Mapping[str, Any]) -> dict[str, str]:
    """Operational layer id -> dataset id, for the layers whose item the run
    imported."""
    matches: dict[str, str] = {}
    for layer_id, layer, aliased, _, source in _sourced_layers(ctx, webmap):
        if len(matches) >= _MAX_MATCHES:
            break
        if source is None or source.status not in FINISHED:
            continue
        dataset = _dataset_for(layer, source, aliased=aliased)
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
        and isinstance(path := inventory.get(item["id"], {}).get("thumbnail"), str)
        and _safe_relative(path) is not None
    }


def get_map(geolens: GeoLens, map_id: str) -> Any:
    from geolens.api.maps import get_map_endpoint_maps_map_id_get as get

    return geolens.call(get.sync_detailed, map_id=UUID(map_id))


def map_state(found: Any) -> dict[str, str]:
    """What a later run compares to tell whether GeoLens changed a map."""
    return {"owner": str(found.created_by), "updated_at": found.updated_at.isoformat()}


def no_baseline(map_id: str) -> str:
    return (
        f"map {map_id} has no recorded baseline, so a change made in GeoLens "
        "can't be ruled out; update it by hand, or rerun after checking it"
    )


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
    """Write a loss report an earlier run left pending, translate a web map
    the portal changed since it was last read into its GeoLens map again, and
    give a map with no thumbnail the item's.

    Returns why the map may not match its portal item: gone from GeoLens,
    shared differently than the plan says in a way its groups can't settle,
    changed in GeoLens, with no way to tell, or its loss report unwritten."""
    unwritten = _resume_loss(ctx, item["id"], entry) if entry.pending_loss else None
    return [*([unwritten] if unwritten else []), *_check_map(ctx, item, entry)]


def _check_map(
    ctx: MigrationContext, item: Mapping[str, Any], entry: ItemState
) -> list[str]:
    problem, found = _map_problem(ctx, item, entry)
    if problem:
        return [problem]
    problems = []
    if unwritten := _settle_write(ctx, item["id"], entry, found):
        problems.append(unwritten)
    _drop_gone_rows(ctx, entry, found)
    if ctx.portal is None:
        problems.append(
            "the run can't read this web map from the portal to check it for changes"
        )
        return problems
    try:
        info = ctx.portal.client.get_json(f"content/items/{item['id']}")
    except PortalError as exc:
        _stop_if_token_refused(exc)
        problems.append(f"reading the web map to check it for changes failed, {exc}")
        return problems
    if found.thumbnail_url or isinstance(info, dict):
        entry.notes = [
            *(note for note in entry.notes if not note.startswith(_THUMBNAIL_NOTE)),
            *(
                []
                if found.thumbnail_url
                else carry_thumbnail(ctx, item["id"], info, entry.map_id)
            ),
        ]
    modified = _modified(info)
    recorded = whole_number(entry.portal_modified)
    if modified is None:
        problems.append("the portal doesn't say when the web map last changed")
    elif recorded is None:
        problems.append(
            "the state doesn't record when the web map was read for its import, so "
            "a change since can't be ruled out; compare the GeoLens map by hand"
        )
    # A translation that left layers out or owes some is tried again until
    # none is.
    elif modified > recorded or entry.skipped_layers or entry.pending_layers:
        if problem := _translate_again(ctx, item, entry, found, modified):
            problems.append(problem)
    if owed := entry.owed_reason():
        problems.append(owed)
    return problems


def _translate_again(
    ctx: MigrationContext,
    item: Mapping[str, Any],
    entry: ItemState,
    found: Any,
    modified: int,
) -> str | None:
    """Translate the changed web map into its GeoLens map in place; why it
    wasn't, or None.

    Only a map as this command last left it is written, and the save names the
    ``updated_at`` recorded then, so GeoLens refuses it after any edit made
    since. A translated layer keeps the map layer made for its operational
    layer.
    """
    from geolens.api.maps import (
        import_arcgis_webmap_endpoint_maps_import_arcgis_webmap_post as import_webmap,
        update_map_endpoint_maps_map_id_put as put_map,
    )
    from geolens.models.map_update import MapUpdate

    try:
        from geolens.models.arcgis_translated_view import ArcgisTranslatedView
    except ImportError:
        return _NEEDS_NEWER
    seen = entry.map_snapshot
    if seen is None:
        return (
            "the web map changed in the portal, and the state doesn't record how "
            "this command left its GeoLens map; update the map by hand"
        )
    if map_state(found) != seen:
        changed = datetime.fromtimestamp(modified / 1000, UTC).isoformat()
        return (
            f"the web map changed in the portal (modified at {changed}), and its "
            "GeoLens map was changed in GeoLens since the last run (updated at "
            f"{found.updated_at.isoformat()}); it was left as it is. {KEEP_GEOLENS}"
        )
    try:
        webmap = _fetch(ctx, item["id"])
        matches = match_datasets(ctx, webmap)
        # GeoLens refuses a translation naming a dataset the caller can't
        # read, and keeps the map layers it hides from the caller.
        readable = _readable_matches(ctx, matches)
        body = _import_body(ctx, item, webmap, dry_run=True, matches=readable)
        with long_request_timeout(ctx.geolens.client):
            result = ctx.geolens.call(
                import_webmap.sync_detailed, expected=201, body=body
            )
    except (ItemFailed, GeoLensError) as exc:
        return f"translating the changed web map again failed, {exc}"
    # An older SDK leaves fields it doesn't know out of the model.
    sources = getattr(result, "layer_sources", None)
    if (
        not isinstance(getattr(result, "view", None), ArcgisTranslatedView)
        or not isinstance(getattr(result, "notes", None), str)
        or not isinstance(sources, list)
        or len(sources) != len(result.layers)
    ):
        return _NEEDS_NEWER
    translated = [
        {
            **layer.to_dict(),
            **({"id": entry.layer_ids[s]} if s in entry.layer_ids else {}),
        }
        for layer, s in zip(result.layers, sources)
    ]
    kept = _kept_rows(entry, found, set(matches) - set(readable))
    pairs = list(zip(sources, translated))
    # A save holds every layer it names and the rows it keeps hidden from the
    # saver, within the map's cap; the translation gives up its last layers.
    # Leaving out a layer with a hidden row keeps that row, so each cut is
    # counted again.
    room = len(pairs)
    while (
        room
        and room + len(kept) + _hidden_rows(entry, found, [s for s, _ in pairs[:room]])
        > _MAX_LAYERS
    ):
        room -= 1
    pairs, capped = pairs[:room], pairs[room:]
    capped_losses = [
        {
            "path": f"operationalLayers[id={source}]",
            "kind": "layer_cap",
            "detail": layer.get("display_name") or source,
        }
        for source, layer in capped
    ]
    sources, layers = _with_kept_rows(pairs, kept, _layer_order(webmap))
    # A save skips a null center or zoom, since clients send null for a camera
    # they didn't read, so the map keeps its last view and the notes say so.
    kept_view = None in (
        result.view.center_lng,
        result.view.center_lat,
        result.view.zoom,
    )
    notes = _fit_notes(
        result.notes
        + "".join(
            f"\n- {c['path']}: {c['kind']} ({c['detail']})" for c in capped_losses
        ),
        f"\n- {_NO_VIEW_NOTE}" if kept_view else "",
    )
    update = {
        **result.view.to_dict(),
        # An unrotated web map leaves the bearing unset, which the save would
        # skip and so keep an earlier rotation; without a view at all the map
        # keeps its rotation with its view.
        "bearing": result.view.bearing if kept_view else result.view.bearing or 0.0,
        "notes": notes,
        "layers": layers,
        "expected_updated_at": seen["updated_at"],
    }
    skipped = sorted(set(matches) - set(readable))
    place = _layer_order(webmap)
    after = {
        "sources": sources,
        "sent_ids": [layer.get("id") for layer in layers],
        "style_nulls": [_null_styles(layer) for layer in layers],
        "sent_datasets": [str(layer.get("dataset_id")) for layer in layers],
        "server_version": _server_version(ctx),
        "readable": sorted(str(row.id) for row in getattr(found, "layers", None) or []),
        "skipped": skipped,
        "kept_view": kept_view,
        "modified": modified,
        "listed": sorted(place),
        "unimported": _unimported(ctx, webmap, matches),
        "pending_loss": _pending_loss(result, capped_losses),
    }
    # Recorded before the save, so a rerun can tell a save whose answer was
    # lost from an edit made in GeoLens.
    entry.pending_write = {
        **_write_fingerprint(
            update,
            found,
            entry.layer_styles,
            entry.layer_ids.values(),
            _geometries(ctx, layers),
            after["server_version"],
        ),
        "after": after,
    }
    ctx.save()
    try:
        saved = ctx.geolens.write(
            put_map.sync_detailed,
            during="the web map was translated again",
            map_id=UUID(entry.map_id or ""),
            body=MapUpdate.from_dict(update),
        )
    except WriteRaced as exc:
        entry.pending_write = None
        return str(exc)
    except GeoLensError as exc:
        # Only a refusal proves nothing was written.
        if exc.status < 500:
            entry.pending_write = None
        return f"saving the web map's new translation failed, {exc}"
    _record_write(entry, after, saved)
    return _resume_loss(ctx, item["id"], entry)


def _record_write(entry: ItemState, after: Mapping[str, Any], saved: Any) -> None:
    """Record what the item's state holds once the translation *after*
    describes is saved as the map *saved*."""
    entry.map_snapshot = map_state(saved)
    entry.skipped_layers = list(after["skipped"])
    entry.notes = [
        *(
            n
            for n in entry.notes
            if n != _NO_VIEW_NOTE and not n.startswith(_UNREADABLE_NOTE)
        ),
        *([_NO_VIEW_NOTE] if after["kept_view"] else []),
        *(
            [f"{_UNREADABLE_NOTE}: {', '.join(after['skipped'])}"]
            if after["skipped"]
            else []
        ),
    ]
    entry.layer_ids = _saved_layer_ids(
        entry.layer_ids,
        after["sent_ids"],
        after["sources"],
        set(after["readable"]),
        [str(layer.id) for layer in getattr(saved, "layers", None) or []],
    )
    entry.portal_modified = after["modified"]
    nulls = {
        entry.layer_ids[source]: null
        for source, null in zip(after["sources"], after["style_nulls"])
        if source in entry.layer_ids
    }
    entry.layer_styles = _filled_styles(saved, nulls, after["server_version"])
    saved_rows = getattr(saved, "layers", None) or []
    entry.row_datasets = {
        **{
            row: ds
            for row, ds in entry.row_datasets.items()
            if row in entry.layer_ids.values()
        },
        **{
            sent: ds
            for sent, ds in zip(after["sent_ids"], after["sent_datasets"])
            if sent
        },
        **{str(layer.id): str(layer.dataset_id) for layer in saved_rows},
    }
    entry.pending_layers = _owed_layers(
        after["unimported"], entry.layer_ids, after["listed"], after["sources"]
    )
    entry.pending_loss = after["pending_loss"]
    entry.loss_report_path = None
    entry.pending_write = None


def _style_inputs(dataset_id: Any, geometry: Any, version: Any) -> dict[str, Any]:
    """What a save reads to fill in a style: the dataset, and the server's
    version, whose defaults can change between releases."""
    return {"dataset_id": str(dataset_id), "geometry": geometry, "version": version}


def _server_version(ctx: MigrationContext) -> str | None:
    """The GeoLens version, read once; None when it can't be read."""
    from geolens.api.health import health_health_get as health

    if ctx.server_version is None:
        try:
            ctx.server_version = ctx.geolens.call(health.sync_detailed).version
        except GeoLensError:
            return None
        except typer.Exit as exc:
            # How the SDK call reports a timeout or network failure.
            if exc.exit_code != EXIT_NETWORK:
                raise
            return None
    return ctx.server_version


def _geometries(
    ctx: MigrationContext, layers: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Dataset id -> its geometry type, for the datasets of the layers that
    send a style null. A dataset that can't be read is left out."""
    from geolens.api.datasets import get_single_dataset_datasets_dataset_id_get as get
    from geolens.types import Unset

    found: dict[str, Any] = {}
    for dataset_id in {str(row["dataset_id"]) for row in layers if _null_styles(row)}:
        try:
            dataset = ctx.geolens.call(get.sync_detailed, dataset_id=UUID(dataset_id))
        except (GeoLensError, ValueError):
            continue
        geometry = getattr(dataset, "geometry_type", None)
        found[dataset_id] = None if isinstance(geometry, Unset) else geometry
    return found


def _null_styles(layer: Mapping[str, Any]) -> list[str]:
    """The styles a layer sends null or leaves out, which the save fills in."""
    return [key for key in _SERVER_FILLED if layer.get(key) is None]


def _filled_styles(
    saved: Any, nulls: Mapping[str, Sequence[str]], version: str | None
) -> dict[str, dict[str, Any]]:
    """Map layer id -> the styles the server holds for it, and which of them
    the save that left them sent null (*nulls*). Only a value filled in from
    null is the one a later null send fills in again."""
    rows = [layer.to_dict() for layer in getattr(saved, "layers", None) or []]
    return {
        str(row["id"]): {
            "values": {k: row.get(k) for k in _SERVER_FILLED},
            "null_sent": list(nulls.get(str(row["id"]), [])),
            "inputs": _style_inputs(
                row.get("dataset_id"), row.get("dataset_geometry_type"), version
            ),
        }
        for row in rows
    }


def _drop_gone_rows(ctx: MigrationContext, entry: ItemState, found: Any) -> None:
    """Forget the map layer recorded for an operational layer whose row the
    map no longer lists though its dataset is readable now: a save hides a row
    only while its dataset is unreadable, so the row was deleted."""
    from geolens.api.datasets import get_single_dataset_datasets_dataset_id_get as get

    shown = {str(row.id) for row in getattr(found, "layers", None) or []}
    for source, row in list(entry.layer_ids.items()):
        dataset_id = entry.row_datasets.get(row)
        if row in shown or dataset_id is None:
            continue
        try:
            ctx.geolens.call(get.sync_detailed, dataset_id=UUID(dataset_id))
        except (GeoLensError, ValueError):
            continue
        del entry.layer_ids[source]
        entry.row_datasets.pop(row, None)
        if source in entry.pending_layers:
            entry.pending_layers.remove(source)


def _unimported(
    ctx: MigrationContext, webmap: Mapping[str, Any], matches: Mapping[str, str]
) -> list[str]:
    """The translatable operational layers *matches* leaves out whose service
    the plan imports and the run hasn't finished. A layer of an unsupported,
    skipped or external source is reported, never retried."""
    return sorted(
        layer_id
        for layer_id, _, _, source_id, source in _sourced_layers(ctx, webmap)
        if layer_id not in matches
        and source_id in ctx.importable
        and (
            source is None
            or source.status not in FINISHED
            or source.exported_not_imported()
        )
    )


def _owed_layers(
    unimported: Sequence[str],
    layer_ids: Mapping[str, str],
    listed: Collection[str],
    sources: Collection[str],
) -> list[str]:
    """The operational layers a translation still owes the web map: the
    *unimported* ones, and those whose map layer the save left in place,
    hidden from the run, though the portal no longer lists them."""
    return sorted(
        {
            *unimported,
            *(s for s in layer_ids if s not in listed and s not in sources),
        }
    )


# Response fields that move or derive from others without anyone editing the
# map: the save's own timestamp, the layers (compared apart), and the names and
# images computed from other rows.
_DERIVED_MAP_KEYS = frozenset(
    {
        "layers",
        "layer_count",
        "updated_at",
        "thumbnail_url",
        "og_image_url",
        "forked_from_name",
        "created_by_username",
    }
)


_UNKNOWN = object()


# The layer fields a save fills in from the dataset when they are sent null.
_SERVER_FILLED = ("paint", "layout", "style_config", "layer_type")


def _canonical(value: Any) -> Any:
    """*value* with whole floats as ints, so 1 and 1.0 hash alike."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_canonical(v) for v in value]
    return value


def _digest(shape: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(_canonical(shape), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _stored_shape(data: Mapping[str, Any], keys: Mapping[str, Any]) -> dict[str, Any]:
    """What a stored map holds for the fields a save sent: its map-level
    fields, and its layers in draw order, ids and sort order aside."""
    rows = sorted(data.get("layers") or [], key=lambda row: row.get("sort_order") or 0)
    return {
        "map": {key: data.get(key) for key in keys["map"]},
        "layers": [
            {key: row.get(key) for key in row_keys}
            for row, row_keys in zip(rows, keys["layers"])
        ],
        "count": len(rows),
    }


def _write_fingerprint(
    update: Mapping[str, Any],
    before: Any,
    styles: Mapping[str, Mapping[str, Any]],
    hidden_candidates: Collection[str],
    geometries: Mapping[str, Any],
    version: str | None,
) -> dict[str, Any]:
    """A fingerprint of the map a save leaves, and the fields it covers: the
    ones the save sends, and every other field of the map as *before* has it,
    which includes a field sent null. A style sent
    null is filled in by the save; it is covered by the value *styles* records
    for the layer when that save also sent it null, and the save is
    *unverified* otherwise."""
    sent = {
        key: value
        for key, value in update.items()
        if key not in ("layers", "expected_updated_at") and value is not None
    }
    sent.update(
        (key, value)
        for key, value in before.to_dict().items()
        if key not in sent and key not in _DERIVED_MAP_KEYS
    )
    rows: list[dict[str, Any]] = []
    # No read shows a row hidden from the run, so a save that keeps one can't
    # be told from an edit to it.
    readable = {str(row.id) for row in getattr(before, "layers", None) or []}
    unverified = any(layer_id not in readable for layer_id in hidden_candidates)
    for layer in update["layers"]:
        # A new layer's id is only known to the answer.
        row = {
            key: value
            for key, value in layer.items()
            if key != "sort_order" and (key != "id" or value)
        }
        recorded = styles.get(str(layer.get("id") or ""))
        nulls = _null_styles(layer)
        # A recorded default holds only for the dataset it was made from, and
        # the default outline only while the paint is null as well.
        current = _style_inputs(
            layer.get("dataset_id"),
            geometries.get(str(layer.get("dataset_id")), _UNKNOWN),
            _UNKNOWN if version is None else version,
        )
        for key in nulls:
            reusable = (
                recorded is not None
                and recorded.get("inputs") == current
                and key in recorded["null_sent"]
                and (
                    key != "style_config"
                    or "paint" in nulls
                    and "paint" in recorded["null_sent"]
                )
            )
            if reusable:
                row[key] = recorded["values"][key]
            else:
                row.pop(key, None)
                unverified = True
        rows.append(row)
    keys = {"map": sorted(sent), "layers": [sorted(row) for row in rows]}
    shape = {"map": sent, "layers": rows, "count": len(rows)}
    return {"fingerprint": _digest(shape), "keys": keys, "unverified": unverified}


def _settle_write(
    ctx: MigrationContext, item_id: str, entry: ItemState, found: Any
) -> str | None:
    """Settle a save whose outcome the state never recorded; why its loss
    report wasn't written, or None.

    The map the state records is as it was, so the save never committed; or it
    changed, and it is taken as the save's own only when it still holds
    everything the save sent. Anything else is an edit made in GeoLens, which
    the map's next translation reports.
    """
    pending = entry.pending_write
    if pending is None:
        return None
    entry.pending_write = None
    if (
        map_state(found) != entry.map_snapshot
        and not pending.get("unverified")
        and pending.get("fingerprint")
        == _digest(_stored_shape(found.to_dict(), pending["keys"]))
    ):
        _record_write(entry, pending["after"], found)
        return _resume_loss(ctx, item_id, entry)
    return None


# What PUT /maps/{id} takes of a map layer.
_LAYER_INPUT_KEYS = frozenset(
    {
        "id",
        "dataset_id",
        "sort_order",
        "visible",
        "opacity",
        "paint",
        "layout",
        "layer_type",
        "display_name",
        "filter",
        "label_config",
        "popup_config",
        "style_config",
        "show_in_legend",
    }
)


def _hidden_rows(entry: ItemState, before: Any, sending: Sequence[str]) -> int:
    """How many recorded map layers the saver couldn't read *before* the save
    and the save doesn't name, which it keeps."""
    readable = {str(row.id) for row in getattr(before, "layers", None) or []}
    return sum(
        1
        for source, layer_id in entry.layer_ids.items()
        if layer_id not in readable and source not in sending
    )


def _kept_rows(
    entry: ItemState, before: Any, skipped: set[str]
) -> dict[str, dict[str, Any]]:
    """The map layers recorded for the *skipped* operational layers that the
    saver could read *before* the save, as a save sends them unchanged; a
    full save deletes a readable row it doesn't name."""
    rows = {str(row.id): row for row in getattr(before, "layers", None) or []}
    return {
        source: {
            key: value
            for key, value in rows[entry.layer_ids[source]].to_dict().items()
            if key in _LAYER_INPUT_KEYS
        }
        for source in skipped
        if entry.layer_ids.get(source) in rows
    }


def _layer_order(webmap: Mapping[str, Any]) -> dict[str, int]:
    """Operational layer id -> its place in the web map, keyed as the
    translator keys layers: the string id of a layer it translates, at its
    first such occurrence."""
    place: dict[str, int] = {}
    for n, layer in enumerate(_walk(webmap.get("operationalLayers"))):
        layer_id = layer.get("id")
        if isinstance(layer_id, str) and _translatable(layer):
            place.setdefault(layer_id, n)
    return place


def _with_kept_rows(
    translated: list[tuple[str, dict[str, Any]]],
    kept: Mapping[str, dict[str, Any]],
    place: Mapping[str, int],
) -> tuple[list[str], list[dict[str, Any]]]:
    """The layers a save sends and their operational layers: the translated
    ones in their order, each *kept* row placed where its operational layer
    stands in the web map (*place*), numbered in turn."""
    end = max(place.values(), default=0) + 1
    pairs = list(translated)
    for source, layer in sorted(kept.items(), key=lambda k: place.get(k[0], end)):
        at = place.get(source, end)
        index = next(
            (n for n, (s, _) in enumerate(pairs) if place.get(s, end) > at),
            len(pairs),
        )
        pairs.insert(index, (source, layer))
    return [source for source, _ in pairs], [
        {**layer, "sort_order": n} for n, (_, layer) in enumerate(pairs)
    ]


def _readable_matches(
    ctx: MigrationContext, matches: Mapping[str, str]
) -> dict[str, str]:
    """The *matches* whose dataset the run's account can read."""
    from geolens.api.datasets import get_single_dataset_datasets_dataset_id_get as get

    readable: dict[str, bool] = {}
    for dataset_id in set(matches.values()):
        try:
            ctx.geolens.call(get.sync_detailed, dataset_id=UUID(dataset_id))
        except GeoLensError as exc:
            if exc.status != 404:
                raise
            readable[dataset_id] = False
        else:
            readable[dataset_id] = True
    return {layer: d for layer, d in matches.items() if readable[d]}


def _fit_notes(notes: str, tail: str) -> str:
    """*notes* with *tail* after them, the loss lines cut to whole lines when
    both don't fit in a map's notes."""
    if len(notes) + len(tail) > _MAP_NOTES_MAX:
        cut = f"\n{_NOTES_CUT}"
        notes = notes[: _MAP_NOTES_MAX - len(tail) - len(cut)].rsplit("\n", 1)[0] + cut
    return notes + tail


def _saved_layer_ids(
    recorded: Mapping[str, str],
    sent_ids: Sequence[str | None],
    sources: Sequence[str],
    readable: Collection[str],
    listed: Sequence[str],
) -> dict[str, str]:
    """Operational layer id -> the map layer the save left for it.

    *sent_ids* are the ids the save named, one per source; *readable* the map
    layers the saver could read before it; *listed* the rows its answer lists.

    A layer sent with an id the answer lists keeps it. Every other row the
    answer lists is one the save created: for each layer sent without an id,
    and for each sent with one that no longer named a row when the counts say
    so; otherwise a sent id the answer leaves out names a row hidden from the
    saver, which keeps it. Created rows pair by position, and none is
    recorded when the counts fit neither case. A recorded layer this save
    didn't send keeps its entry only while the saver couldn't read it in the
    map *before* the save, since the save keeps such a row and deletes the
    rest.
    """
    ids = {
        source: layer_id
        for source, layer_id in recorded.items()
        if source not in sources and layer_id not in readable
    }
    updated = {
        source: sent
        for sent, source in zip(sent_ids, sources)
        if sent is not None and sent in listed
    }
    ids.update(updated)
    created = [i for i in listed if i not in updated.values()]
    unpaired = [source for source in sources if source not in updated]
    idless = [s for sent, s in zip(sent_ids, sources) if not sent]
    if len(created) == len(unpaired):
        ids.update(zip(unpaired, created))
    elif len(created) == len(idless):
        # Every id the answer left out still names its row, hidden from the
        # saver; only the layers sent without one were created.
        ids.update(
            (s, sent) for sent, s in zip(sent_ids, sources) if sent and s not in updated
        )
        ids.update(zip(idless, created))
    return ids


def _resume_loss(ctx: MigrationContext, item_id: str, entry: ItemState) -> str | None:
    """Write the pending loss report and give the item its notes in place of
    the earlier translation's; why it wasn't written, or None."""
    try:
        _finish_loss(ctx, item_id, entry, replace_notes=True)
    except ItemFailed as exc:
        return f"{exc}; a rerun tries again"
    return None


def _remove_loss(ctx: MigrationContext, item_id: str) -> None:
    """Remove an earlier loss report, which a translation with no losses
    leaves out of date."""
    if ctx.export_dir is None:
        return
    try:
        (ctx.export_dir.parent / LOSS_DIRNAME / f"{item_id}.json").unlink(
            missing_ok=True
        )
    except OSError as exc:
        raise ItemFailed(
            f"removing the earlier loss report failed: {exc.strerror or exc}"
        ) from None


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


def _import_body(
    ctx: MigrationContext,
    item: Mapping[str, Any],
    webmap: dict[str, Any],
    *,
    dry_run: bool = False,
    matches: Mapping[str, str] | None = None,
) -> Any:
    """The import request for *webmap*, its layers matched to the run's
    datasets (or to *matches*) and their source styling filled in."""
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

    if matches is None:
        matches = match_datasets(ctx, webmap)
    fill_source_styling(ctx, webmap, matches)
    title = item["target"]["title"] or item["title"]
    visibility = item["target"]["visibility"]
    return ArcgisWebmapImportRequest(
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
        dry_run=dry_run,
    )


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

    info = _read_item(ctx, item["id"])
    webmap = _fetch(ctx, item["id"])
    matches = match_datasets(ctx, webmap)
    body = _import_body(ctx, item, webmap, matches=matches)
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
    # Recorded with the map, so a retry after a later step fails compares the
    # map with the import's, never with what someone made of it meanwhile.
    entry.map_snapshot = map_state(result.map_)
    entry.portal_modified = _modified(info)
    entry.layer_ids = {
        k: str(v) for k, v in result.layer_ids.additional_properties.items()
    }
    entry.layer_styles = _filled_styles(result.map_, {}, _server_version(ctx))
    entry.row_datasets = {
        str(row.id): str(row.dataset_id)
        for row in getattr(result.map_, "layers", None) or []
    }
    # A layer of a source the plan imports but the run hasn't finished is added
    # by a later rerun, though the web map itself doesn't change.
    entry.pending_layers = _unimported(ctx, webmap, matches)
    # Kept in the state until the loss report file is written, so a failed
    # write is finished on the rerun instead of dropping the losses.
    entry.pending_loss = _pending_loss(result)
    ctx.save()
    thumbnail_notes = carry_thumbnail(ctx, item["id"], info, entry.map_id)
    finished = _finish_loss(ctx, item["id"], entry)
    finished.notes.extend(thumbnail_notes)
    return finished


def _pending_loss(
    result: Any, extra: Sequence[Mapping[str, str]] = ()
) -> dict[str, Any]:
    """The translation's loss report, with *extra* losses added to it."""
    report = result.loss_report.to_dict()
    report["items"] = [*report.get("items", []), *extra]
    summary = dict(report.get("summary") or {})
    for loss in extra:
        summary[loss["kind"]] = summary.get(loss["kind"], 0) + 1
    report["summary"] = summary
    return {
        "loss_report": report,
        "unmatched_layers": [layer.to_dict() for layer in result.unmatched_layers],
    }


def _finish_loss(
    ctx: MigrationContext,
    item_id: str,
    entry: ItemState,
    *,
    replace_notes: bool = False,
) -> ItemResult:
    """Write the pending loss report, or remove an earlier one when nothing
    was lost, and with *replace_notes* give the item the report's notes in
    place of an earlier translation's. The report stays pending until all of
    that is done, so a rerun finishes what a failure or interruption left."""
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
            f"{len(unmatched)} {_UNMATCHED_NOTE}: {shown}"
            + (f" and {more} more" if more > 0 else "")
        )
    lost = payload.get("loss_report", {}).get("items", [])
    if lost:
        notes.append(f"{len(lost)} {_LOST_NOTE}")
    if lost or unmatched:
        entry.loss_report_path = _write_loss(ctx, item_id, payload)
    else:
        _remove_loss(ctx, item_id)
    if replace_notes:
        entry.notes = [*(n for n in entry.notes if not _LOSS_NOTE.match(n)), *notes]
    entry.pending_loss = None
    ctx.save()
    return ItemResult(status=DONE, notes=notes)
