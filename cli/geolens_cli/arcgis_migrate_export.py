# SPDX-License-Identifier: Apache-2.0
"""The ``export_only`` action of `geolens arcgis migrate`: the export bundle.

Hand-maintained. GeoLens can't host these items, so nothing is lost when the
ArcGIS subscription ends: for each one the CLI writes
``export/<type>/<item id>/`` next to the state file with ``item.json``, the
item's data (``data.json`` or the raw file), its ``resources/`` and, for a
story, a readable ``story.md``. ``export/INDEX.md`` lists every item with the
replacement note for its type. Files are written at mode 0600 and every JSON
passes through the redactor. The only host contacted is the plan's portal.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

from . import arcgis_report as _report
from .arcgis_migrate_session import ItemFailed, ItemResult, MigrationContext, StopRun
from .arcgis_migrate_state import FAILED, ItemState, MigrationState
from .arcgis_portal import PortalClient, PortalError, redact_json
from .arcgis_story_markdown import render_classic, render_storymap

EXPORT_DIRNAME = "export"
DEFAULT_CAP_MB = 200
# A JSON document up to this size is parsed, redacted and pretty-printed.
JSON_LIMIT = 32 * 1024 * 1024
_ITEM_ID = re.compile(r"[0-9a-fA-F]{32}")
_TOKEN_STATUSES = (498, 499)
# Services and similar items have no data file of their own.
ITEM_JSON_ONLY = frozenset(
    {
        "Geocoding Service",
        "Geometry Service",
        "Geoprocessing Service",
        "Network Analysis Service",
        "Workflow Manager Service",
        "Image Service",
        "Vector Tile Service",
        "Scene Service",
        "3DTilesService",
        "WMS",
        "WMTS",
        "WCS",
        "WFS",
        "KML",
        "OGCFeatureServer",
    }
)
FILENAMES = {"Form": "form.zip", "Notebook": "notebook.ipynb"}
_STORY = "Web Mapping Application"
_NO_EQUIVALENT = "No equivalent in GeoLens."
_APP_REBUILD = (
    "Rebuild as a GeoLens map with a share link or embed; widgets with no "
    "equivalent are listed in data.json."
)
NOTES: dict[str, str] = {
    "StoryMap": (
        "GeoLens has no narrative format yet. Maps carry over; the story text "
        "and images are in story.md for use in a site or docs."
    ),
    _STORY: _APP_REBUILD,
    "Web Experience": _APP_REBUILD,
    "Dashboard": (
        "Maps carry over. Indicators, charts, lists and filters have no GeoLens "
        "equivalent; the data they summarize is in the imported datasets and "
        "queryable through the API, OGC Features and the MCP server."
    ),
    "Form": (
        "Results import as a dataset. The form has no equivalent; it is saved "
        "as form.zip."
    ),
    "Hub Site Application": (
        "Rebuild on a website; GeoLens exposes DCAT-US and OGC endpoints a "
        "Hub-style site can link to."
    ),
    "Hub Page": (
        "Rebuild on a website; GeoLens exposes DCAT-US and OGC endpoints a "
        "Hub-style site can link to."
    ),
    "Web Scene": (
        "3D scenes have no equivalent. Feature layers in the scene carry over "
        "as 2D datasets; scene layers are deferred."
    ),
    "Notebook": "The notebook file is the artifact.",
    "Pro Map": "Archive only.",
    "Layer Package": "Archive only.",
    "Map Package": "Archive only.",
    "Map Area": "Archive only.",
    "Code Attachment": "Archive only.",
}
for _service in (
    "Geocoding Service",
    "Geometry Service",
    "Geoprocessing Service",
    "Network Analysis Service",
    "Workflow Manager Service",
):
    NOTES[_service] = "A service, not content."
NOTES_DEFAULT = _NO_EQUIVALENT


def replacement_note(item_type: str) -> str:
    return NOTES.get(item_type, NOTES_DEFAULT)


def _slug(item_type: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", item_type.lower()).strip("-") or "item"


class _Export:
    """One item's bundle: its folder, byte budget and what went wrong."""

    def __init__(self, client: PortalClient, folder: Path, cap: int) -> None:
        self.client = client
        self.folder = folder
        self.remaining = cap
        self.partial = False
        self.errors: list[str] = []
        self.bytes = 0

    def note_error(self, what: str, exc: PortalError) -> None:
        if exc.http_status in _TOKEN_STATUSES:
            raise StopRun(
                f"the portal refused the ArcGIS token ({exc}); it may have "
                "expired. Rerun with a fresh token to resume."
            ) from None
        self.errors.append(f"{what}: {exc}")

    def fetch(self, path: str, dest: Path, what: str) -> bool:
        """Download *path* into *dest* within the budget; False when it was
        left out (over budget, or the portal refused)."""
        dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            size = self.client.download(path, dest, self.remaining)
        except PortalError as exc:
            dest.unlink(missing_ok=True)
            if exc.kind == "too_large":
                self.partial = True
                self.errors.append(f"{what}: over the export size cap, not saved")
            else:
                self.note_error(what, exc)
            return False
        self.remaining -= size
        self.bytes += size
        return True


def _write_json(ctx: MigrationContext, path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    safe = redact_json(value, ctx.redact)
    _report.write_private(path, json.dumps(safe, indent=2, ensure_ascii=False) + "\n")


def _redacted_json_file(ctx: MigrationContext, path: Path) -> Any | None:
    """Parse the JSON in *path* if it is one, replace the file with its
    redacted form, and return the parsed (unredacted) value."""
    try:
        if path.stat().st_size > JSON_LIMIT:
            return None
        value = json.loads(path.read_bytes())
    except (OSError, ValueError, RecursionError):
        return None
    if isinstance(value, dict | list):
        _write_json(ctx, path, value)
        return value
    return None


def _save_data(ctx: MigrationContext, export: _Export, item: Mapping[str, Any]) -> Any:
    path = f"content/items/{item['id']}/data"
    raw = export.folder / "data.download"
    if not export.fetch(path, raw, "data"):
        return None
    name = FILENAMES.get(item["type"], "data.json")
    target = export.folder / name
    parsed = _redacted_json_file(ctx, raw)
    if parsed is not None and name == "data.json":
        raw.replace(target)
        return parsed
    if name == "data.json":
        name = "data.bin"
    raw.replace(export.folder / name)
    return None


def _resource_names(export: _Export, item_id: str) -> list[str]:
    names: list[str] = []
    start = 1
    for _page in range(1000):
        try:
            page = export.client.get_json(
                f"content/items/{item_id}/resources", {"num": 100, "start": start}
            )
        except PortalError as exc:
            export.note_error("resources", exc)
            break
        for entry in page.get("resources") or []:
            if isinstance(entry, Mapping) and isinstance(entry.get("resource"), str):
                names.append(entry["resource"])
        start = page.get("nextStart", -1)
        if not isinstance(start, int) or start < 1:
            break
    return names


def _safe_relative(name: str) -> PurePosixPath | None:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        return None
    return path


def _save_resources(ctx: MigrationContext, export: _Export, item_id: str) -> None:
    for name in _resource_names(export, item_id):
        relative = _safe_relative(name)
        if relative is None:
            export.errors.append(f"resource {name!r}: unsafe name, not saved")
            continue
        dest = export.folder / "resources" / relative
        url = f"content/items/{item_id}/resources/{quote(name)}"
        if not export.fetch(url, dest, f"resource {name}"):
            if export.partial:
                break
            continue
        if dest.suffix.lower() == ".json":
            _redacted_json_file(ctx, dest)


def _map_link(ctx: MigrationContext, item_id: str) -> str:
    migrated = ctx.items.get(item_id)
    if migrated is not None and migrated.map_id:
        return f"{ctx.web_origin}/maps/{migrated.map_id}"
    return f"{ctx.portal_root}/home/item.html?id={item_id}"


def _story(
    ctx: MigrationContext, item: Mapping[str, Any], data: Any, folder: Path
) -> bool:
    if not isinstance(data, dict):
        return False

    def link(item_id: str) -> str:
        return _map_link(ctx, item_id)

    text = None
    if item["type"] == "StoryMap" and "nodes" in data:
        text = render_storymap(data, title=item["title"], map_link=link)
    elif item["type"] == _STORY:
        text = render_classic(data, title=item["title"], map_link=link)
    if text is None:
        return False
    _report.write_private(folder / "story.md", ctx.redact(text))
    return True


def export_item(
    ctx: MigrationContext, item: Mapping[str, Any], entry: ItemState
) -> ItemResult:
    """Write the item's bundle; the item is done even when parts were left out,
    which its ``export`` record and notes say."""
    row = ctx.inventory.get(item["id"])
    client = ctx.portal.client if ctx.portal is not None else None
    if row is None or client is None or ctx.export_dir is None:
        raise ItemFailed("the run can't read this item from the portal")
    if not _ITEM_ID.fullmatch(item["id"]):
        raise ItemFailed("the item id is not an ArcGIS item id")
    folder = ctx.export_dir / _slug(item["type"]) / item["id"]
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    export = _Export(client, folder, ctx.export_cap)
    try:
        full = client.get_json(f"content/items/{item['id']}")
    except PortalError as exc:
        export.note_error("item", exc)
        raise ItemFailed(f"reading the item failed, {exc}") from None
    _write_json(ctx, folder / "item.json", {"inventory": row, "item": full})
    data = None
    if item["type"] not in ITEM_JSON_ONLY:
        data = _save_data(ctx, export, item)
    _save_resources(ctx, export, item["id"])
    story = _story(ctx, item, data, folder)
    relative = folder.relative_to(ctx.export_dir.parent)
    entry.export = {
        "path": relative.as_posix(),
        "bytes": export.bytes,
        "partial": export.partial,
        "errors": export.errors,
        "story": story,
    }
    notes = [f"exported to {relative.as_posix()}"]
    if export.partial:
        notes.append("partial: the item is over the export size cap")
    notes.extend(f"export: {e}" for e in export.errors)
    return ItemResult(notes=notes)


def write_index(
    ctx: MigrationContext, plan: Mapping[str, Any], state: MigrationState
) -> None:
    """``export/INDEX.md``: every exported item with its replacement note."""
    if ctx.export_dir is None:
        return
    lines = [
        "# Export index",
        "",
        "Items GeoLens can't host, saved so nothing is lost when the ArcGIS "
        "subscription ends.",
        "",
        "| Item | Type | Owner | Size | Status | Folder | Replacement |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    rows = 0
    for item in plan["items"]:
        entry = state.items.get(item["id"])
        if entry is None or entry.export is None:
            continue
        export = entry.export
        status = (
            "failed"
            if entry.status == FAILED
            else ("partial" if export["partial"] else "complete")
        )
        if export["errors"] and status == "complete":
            status = "complete, with errors"
        cells = [
            item["title"],
            item["type"],
            item["owner"],
            f"{export['bytes'] / (1024 * 1024):.1f} MB",
            status,
            f"`{export['path']}`",
            replacement_note(item["type"]),
        ]
        lines.append("| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |")
        rows += 1
    if rows:
        _report.write_private(
            ctx.export_dir / "INDEX.md", ctx.redact("\n".join(lines) + "\n")
        )
