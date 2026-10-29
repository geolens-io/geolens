# SPDX-License-Identifier: Apache-2.0
"""The ``export_only`` action of `geolens arcgis migrate`: the export bundle.

Hand-maintained. GeoLens can't host these items, so nothing is lost when the
ArcGIS subscription ends: for each one the CLI writes
``export/<type>/<item id>/`` next to the state file with ``item.json``, the
item's data (``data.json`` or the raw file), its ``resources/`` and, for a
story, a readable ``story.md``. ``export/INDEX.md`` lists every item with its
replacement note. Files are written at mode 0600 and every JSON
passes through the redactor. The only host contacted is the plan's portal.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

import typer

from . import arcgis_report as _report
from ._sdk_helpers import EXIT_NETWORK
from .arcgis_migrate_session import (
    GeoLensError,
    ItemFailed,
    ItemResult,
    MigrationContext,
    StopRun,
)
from .arcgis_migrate_state import (
    DONE,
    EXISTS,
    FAILED,
    ItemState,
    MigrationState,
    whole_number,
)
from .arcgis_portal import PortalClient, PortalError, redact_json
from .arcgis_story_markdown import render_classic, render_storymap

EXPORT_DIRNAME = "export"
DEFAULT_CAP_MB = 200
# A JSON document up to this size is parsed, redacted and pretty-printed.
JSON_LIMIT = 32 * 1024 * 1024
_ITEM_ID = re.compile(r"[0-9a-fA-F]{32}")
_TOKEN_STATUSES = (498, 499)
_NOT_JSON = object()
# A portal answers these for an item that has no data of its own.
_NO_DATA = (400, 404)
FILENAMES = {"Form": "form.zip", "Notebook": "notebook.ipynb"}
# The extension of an uploaded file whose portal item names none; types that
# can hold several formats (Image, the Office types) are left to .bin.
_TYPE_EXTENSIONS = {
    "CSV": ".csv",
    "PDF": ".pdf",
    "KML": ".kml",
    "Shapefile": ".zip",
    "File Geodatabase": ".zip",
    "Code Sample": ".zip",
}
_EXTENSION = re.compile(r"\.[A-Za-z0-9]{1,8}")
_STORY = "Web Mapping Application"
_NO_EQUIVALENT = "No equivalent in GeoLens."
_APP_REBUILD = (
    "Rebuild as a GeoLens map with a share link or embed; widgets with no "
    "equivalent are listed in data.json."
)
NOTES: dict[str, str] = {
    "StoryMap": (
        "Maps carry over. GeoLens stories are API-only for now (chapters with "
        "map scenes and Markdown blocks, draft and publish, no web editor yet); "
        "the story text and images are in story.md to recreate through the API "
        "or reuse in a site or docs."
    ),
    _STORY: _APP_REBUILD,
    "Web Experience": _APP_REBUILD,
    "Dashboard": (
        "Maps carry over. A GeoLens map can hold a dashboard_config with "
        "indicator and bar chart widgets (API-only for now, no viewer panel "
        "yet); lists, filters and other widgets have no equivalent. The data "
        "they summarize is in the imported datasets and queryable through the "
        "API, OGC Features and the MCP server."
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


def item_replacement(
    item: Mapping[str, Any], plan: Mapping[str, Any], state: MigrationState
) -> str:
    """The note for *item*; a source file superseded by a hosted layer says so,
    and says when that layer hasn't migrated, as the follow-ups do. An item
    whose action was changed from its recorded default is no longer the
    layer's source file, so it gets its type's note; a plan with no recorded
    defaults counts as unchanged."""
    layer = item.get("superseded_by")
    default_action = (item.get("defaults") or {}).get("action", item["action"])
    if not layer or item["action"] != default_action:
        return replacement_note(item["type"])
    title = next((i["title"] for i in plan["items"] if i["id"] == layer), layer)
    entry = state.items.get(layer)
    if entry and entry.dataset_ids and entry.status in (DONE, EXISTS):
        return f"Published as {title}; migrated with it."
    return f"Source file of {title}, which has not migrated."


def _private_dirs(path: Path) -> None:
    """Create *path* and any missing parent at mode 0700."""
    for directory in reversed([path, *path.parents]):
        if not directory.exists():
            directory.mkdir(mode=0o700)


def _stop_if_token_refused(exc: PortalError) -> None:
    if exc.http_status in _TOKEN_STATUSES:
        raise StopRun(
            f"the portal refused the ArcGIS token ({exc}); it may have "
            "expired. Rerun with a fresh token to resume."
        ) from None


def _slug(item_type: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", item_type.lower()).strip("-") or "item"


class _Export:
    """One item's bundle: its folder, byte budget and what went wrong.

    Downloads land in *stage*, a private temporary directory outside the
    bundle, and reach the bundle only through ``place``, which redacts JSON and
    writes atomically at mode 0600. Nothing unredacted is ever at a final path.
    """

    def __init__(
        self, client: PortalClient, folder: Path, cap: int, stage: Path
    ) -> None:
        self.client = client
        self.folder = folder
        self.stage = stage
        self.remaining = cap
        self.partial = False
        self.errors: list[str] = []
        # The errors a rerun may fix; they fail the item.
        self.failures: list[str] = []
        self.bytes = 0
        self._staged = 0

    def note_error(self, what: str, exc: PortalError) -> None:
        _stop_if_token_refused(exc)
        # The status or kind, not the error text, which repeats the request
        # path and with it a resource name.
        message = (
            f"{what}: {'HTTP ' + str(exc.http_status) if exc.http_status else exc.kind}"
        )
        self.errors.append(message)
        if exc.retryable or exc.kind in ("network", "server", "local"):
            # Worth another try: the item is left failed, not done.
            self.failures.append(message)

    def download(self, path: str, what: str) -> Path | None:
        """Download *path* into the stage within the budget; None when it was
        left out (over budget, or the portal refused)."""
        self._staged += 1
        staged = self.stage / str(self._staged)
        try:
            self.client.download(path, staged, self.remaining)
        except PortalError as exc:
            staged.unlink(missing_ok=True)
            if exc.kind == "too_large":
                self.partial = True
                self.errors.append(f"{what}: over the export size cap, not saved")
            elif what == "data" and exc.http_status in _NO_DATA:
                pass  # the item has no data of its own
            else:
                self.note_error(what, exc)
            return None
        return staged

    def charge(self, size: int) -> bool:
        """Count *size* bytes about to be written against the cap; False,
        counting nothing, when they don't fit."""
        if size > self.remaining:
            return False
        self.bytes += size
        self.remaining -= size
        return True

    def place(
        self,
        ctx: MigrationContext,
        staged: Path,
        what: str,
        *,
        json_dest: Path,
        raw_dest: Path,
        required: bool,
    ) -> Any | None:
        """Move a staged download into the bundle and return its parsed JSON.

        JSON goes to *json_dest* redacted. Anything that starts like JSON, or
        is *required* to be JSON, but can't be redacted (over ``JSON_LIMIT``
        or malformed) is dropped and the item marked partial. Other files are
        copied to *raw_dest*.
        """
        try:
            size = staged.stat().st_size
            value: Any = _NOT_JSON
            if size <= JSON_LIMIT:
                try:
                    value = json.loads(staged.read_bytes())
                except (ValueError, RecursionError):
                    value = _NOT_JSON
            if value is not _NOT_JSON:
                text = _redacted_text(ctx, value)
                if not self.charge(len(text)):
                    self.partial = True
                    self.errors.append(f"{what}: over the export size cap, not saved")
                    return None
                _private_dirs(json_dest.parent)
                _report.write_private(json_dest, text)
                return value
            if required or _looks_like_json(staged):
                self.partial = True
                self.errors.append(
                    f"{what}: JSON that can't be redacted (over 32 MiB or malformed), "
                    "not saved"
                )
                return None
            if not self.charge(size):
                self.partial = True
                self.errors.append(f"{what}: over the export size cap, not saved")
                return None
            _private_dirs(raw_dest.parent)
            _report.copy_private(raw_dest, staged)
            return None
        finally:
            staged.unlink(missing_ok=True)


def _redacted_text(ctx: MigrationContext, value: Any) -> bytes:
    safe = redact_json(value, ctx.redact)
    return (json.dumps(safe, indent=2, ensure_ascii=False) + "\n").encode()


_JSON_SNIFF_BYTES = 4096
_SNIFF_ENCODINGS = ("utf-8-sig", "utf-16", "utf-32", "utf-16-le", "utf-16-be")


def _looks_like_json(path: Path) -> bool:
    """Whether the file starts like a JSON object or array, under any encoding
    JSON may use and after any BOM and whitespace. A file that is nothing but
    whitespace in its first bytes counts, since it can't be ruled out."""
    with path.open("rb") as handle:
        head = handle.read(_JSON_SNIFF_BYTES)
    for encoding in _SNIFF_ENCODINGS:
        text = head.decode(encoding, errors="ignore").lstrip("\ufeff \t\r\n")
        if text[:1] in ("{", "["):
            return True
    return not head.strip(b"\x00 \t\r\n\xef\xbb\xbf\xff\xfe") and bool(head)


def _raw_name(item: Mapping[str, Any], full: Mapping[str, Any]) -> str:
    """``data`` plus the extension of the portal's file name, else of the item
    type, else ``.bin``. Only the extension is taken from the portal's name, so
    it can't steer the path; ``.json`` is left out since that name is for
    parsed data."""
    name = full.get("name")
    candidates = (
        [PurePosixPath(name.replace("\\", "/")).suffix] if isinstance(name, str) else []
    )
    candidates.append(_TYPE_EXTENSIONS.get(item["type"], ""))
    for suffix in candidates:
        if _EXTENSION.fullmatch(suffix) and suffix.lower() != ".json":
            return f"data{suffix.lower()}"
    return "data.bin"


def _save_data(
    ctx: MigrationContext,
    export: _Export,
    item: Mapping[str, Any],
    full: Mapping[str, Any],
) -> Any:
    staged = export.download(f"content/items/{item['id']}/data", "data")
    if staged is None:
        return None
    name = FILENAMES.get(item["type"])
    folder = export.folder
    return export.place(
        ctx,
        staged,
        "data",
        json_dest=folder / (name or "data.json"),
        raw_dest=folder / (name or _raw_name(item, full)),
        required=bool(name and name.endswith(".ipynb")),
    )


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


_WINDOWS_RESERVED = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{n}" for n in range(1, 10)}
    | {f"lpt{n}" for n in range(1, 10)}
)
_WINDOWS_BAD_CHARS = frozenset('<>:"|?*\\')


def _safe_relative(name: str) -> PurePosixPath | None:
    """*name* as a path below ``resources/``, or None when it could leave it or
    can't be a file name on some platform: backslashes, drive letters, absolute
    or UNC forms, ``.``/``..``/empty segments, control characters, the
    characters ``<>:"|?*``, a trailing dot or space, and Windows device names
    (``CON``, ``NUL``, ``COM1`` ... with or without an extension)."""
    parts = name.split("/")
    if (
        not name
        or any(ord(c) < 32 or c in _WINDOWS_BAD_CHARS for c in name)
        or any(part in ("", ".", "..") for part in parts)
        or any(part[-1] in (".", " ") for part in parts)
        or any(
            part.split(".")[0].strip().lower() in _WINDOWS_RESERVED for part in parts
        )
    ):
        return None
    return PurePosixPath(name)


def _save_resources(ctx: MigrationContext, export: _Export, item_id: str) -> set[str]:
    """Save the item's resources and return the names that reached the bundle."""
    saved: set[str] = set()
    base = (export.folder / "resources").resolve()
    for name in _resource_names(export, item_id):
        shown = redact_json(name, ctx.redact)
        relative = _safe_relative(name)
        # A name that carries a credential would become a file name, an index
        # entry and a note, so it is refused like an unsafe one.
        dest = export.folder / "resources" / relative if relative else None
        if shown != name or dest is None or not dest.resolve().is_relative_to(base):
            export.errors.append(f"resource {shown!r}: unsafe name, not saved")
            continue
        what = f"resource {name}"
        staged = export.download(
            f"content/items/{item_id}/resources/{quote(name)}", what
        )
        if staged is None:
            if export.remaining <= 0:
                break
            continue
        export.place(
            ctx,
            staged,
            what,
            json_dest=dest,
            raw_dest=dest,
            required=dest.suffix.lower() in (".json", ".ipynb"),
        )
        if dest.exists():
            saved.add(name)
    return saved


def _web_app(ctx: MigrationContext) -> str:
    """The configured PUBLIC_APP_URL, which a split-origin install serves the
    web app from, else the instance URL without /api."""
    if ctx.web_app is None:
        from geolens.api.admin import get_tile_config_settings_tile_config_get as tiles

        try:
            configured = ctx.geolens.call(tiles.sync_detailed).public_app_url
        except GeoLensError:
            configured = None
        except typer.Exit as exc:
            # How the SDK call reports a timeout or network failure; not
            # cached, so the next story asks again.
            if exc.exit_code != EXIT_NETWORK:
                raise
            return ctx.web_origin
        if isinstance(configured, str) and configured.startswith(
            ("https://", "http://")
        ):
            ctx.web_app = configured.rstrip("/")
        else:
            ctx.web_app = ctx.web_origin
    return ctx.web_app


def _map_link(
    ctx: MigrationContext, item_id: str, web_app: Callable[[], str] | None = None
) -> str:
    migrated = ctx.items.get(item_id)
    if migrated is not None and migrated.map_id:
        return f"{(web_app or (lambda: _web_app(ctx)))()}/maps/{migrated.map_id}"
    return f"{ctx.portal_root}/home/item.html?id={item_id}"


def _story_links(ctx: MigrationContext) -> Callable[[str], str]:
    """Map links for one story, which asks for the app URL at most once."""
    web_app = functools.cache(lambda: _web_app(ctx))
    return lambda item_id: _map_link(ctx, item_id, web_app)


def _story(
    ctx: MigrationContext,
    export: _Export,
    item: Mapping[str, Any],
    data: Any,
    saved: set[str],
) -> bool:
    if not isinstance(data, dict):
        return False

    link = _story_links(ctx)

    text = None
    if item["type"] == "StoryMap" and "nodes" in data:
        text = render_storymap(
            data, title=item["title"], map_link=link, available=saved
        )
    elif item["type"] == _STORY:
        text = render_classic(data, title=item["title"], map_link=link)
    if text is None:
        return False
    text = redact_json(text, ctx.redact)
    if not export.charge(len(text.encode())):
        export.partial = True
        export.errors.append("story.md: over the export size cap, not saved")
        return False
    _report.write_private(export.folder / "story.md", text)
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
    build: Path | None = None
    try:
        _private_dirs(folder.parent)
        _recover_leftovers(folder)
        # Each attempt is built beside the item's folder and swapped in only
        # when it ends, so a failed retry leaves the earlier bundle as it was
        # and a file an earlier attempt saved and this one doesn't is not kept.
        build = Path(tempfile.mkdtemp(dir=folder.parent, prefix=f".{folder.name}.new-"))
        return _export_into(ctx, item, entry, row, client, folder, build)
    except OSError as exc:
        # Setup, the build and the swap alike: a local error fails this item
        # only.
        raise ItemFailed(
            f"writing the export failed: {exc.strerror or type(exc).__name__}"
        ) from None
    finally:
        if build is not None:
            shutil.rmtree(build, ignore_errors=True)


def _modified(item: Any) -> int | None:
    return whole_number(item.get("modified") if isinstance(item, dict) else None)


def refresh_export(
    ctx: MigrationContext, item: Mapping[str, Any], entry: ItemState
) -> list[str]:
    """Export a finished item again when the portal changed it since its bundle
    was written; why the bundle may be out of date.

    A bundle without a recorded change time, from before it was recorded,
    counts as changed, and so does one missing from its path. A failed export
    keeps the earlier bundle.
    """
    client = ctx.portal.client if ctx.portal is not None else None
    if client is None:
        return ["the run can't read this item from the portal to check it for changes"]
    try:
        modified = _modified(client.get_json(f"content/items/{item['id']}"))
    except PortalError as exc:
        _stop_if_token_refused(exc)
        return [f"reading the item to check it for changes failed, {exc}"]
    if modified is None:
        return [
            "the portal doesn't say when the item last changed, so its bundle "
            "may be out of date"
        ]
    present = _bundle_in_place(ctx, item, entry)
    recorded = whole_number((entry.export or {}).get("modified"))
    if present and recorded is not None and modified <= recorded:
        return []
    why = (
        "changed in the portal since it was exported"
        if present
        else "its bundle is missing"
    )
    try:
        result = export_item(ctx, item, entry)
    except ItemFailed as exc:
        return [f"{why}, and exporting it again failed: {exc}"]
    entry.notes = list(result.notes)
    return []


def _bundle_in_place(
    ctx: MigrationContext, item: Mapping[str, Any], entry: ItemState
) -> bool:
    """Whether the item's bundle is at its path with every file the export
    recorded, at its recorded size and SHA-256, once what a run killed mid-swap
    left beside it is put back. A record without its file list or digests,
    from before they were kept, counts as not in place."""
    files = (entry.export or {}).get("files")
    if (
        ctx.export_dir is None
        or not _ITEM_ID.fullmatch(item["id"])
        or not isinstance(files, dict)
        or not files
    ):
        return False
    folder = ctx.export_dir / _slug(item["type"]) / item["id"]
    try:
        _recover_leftovers(folder)
        return _bundle_files(folder) == files
    except OSError:
        return False


def _bundle_files(folder: Path) -> dict[str, dict[str, Any]]:
    """Every file in *folder*, by its path inside it, with its size and
    SHA-256."""
    return {
        path.relative_to(folder).as_posix(): {
            "size": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in folder.rglob("*")
        if path.is_file()
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _recover_leftovers(folder: Path) -> None:
    """Undo what a run that was killed mid-swap left beside *folder*.

    A ``.old-*`` folder may be the only copy of a bundle, so it is put back when
    *folder* is missing and otherwise left alone; only ``.new-*`` builds and
    ``.trash-*`` folders (a bundle already replaced) are deleted.
    """
    parent = folder.parent
    for stale in [
        *parent.glob(f".{folder.name}.new-*"),
        *parent.glob(f".{folder.name}.trash-*"),
    ]:
        shutil.rmtree(stale, ignore_errors=True)
    if not folder.exists():
        for old in parent.glob(f".{folder.name}.old-*"):
            try:
                old.rename(folder)
            except OSError:
                continue
            break


def _swap_in(build: Path, folder: Path) -> None:
    old = None
    if folder.exists():
        old = folder.with_name(f".{folder.name}.old-{os.getpid()}")
        folder.rename(old)
    try:
        build.rename(folder)
    except OSError as swap_error:
        if old is None:
            raise
        # Put the kept bundle back before the error leaves.
        try:
            old.rename(folder)
        except OSError as restore_error:
            raise OSError(
                swap_error.errno,
                f"{swap_error.strerror or swap_error}; the earlier bundle is "
                f"kept at {old} and could not be moved back "
                f"({restore_error.strerror or restore_error}); move it to "
                f"{folder} by hand",
            ) from swap_error
        raise
    if old is not None:
        trash = old.with_name(old.name.replace(".old-", ".trash-", 1))
        old.rename(trash)
        shutil.rmtree(trash, ignore_errors=True)


def _export_into(
    ctx: MigrationContext,
    item: Mapping[str, Any],
    entry: ItemState,
    row: Mapping[str, Any],
    client: PortalClient,
    folder: Path,
    build: Path,
) -> ItemResult:
    with tempfile.TemporaryDirectory(prefix="geolens-arcgis-export-") as stage:
        export = _Export(client, build, ctx.export_cap, Path(stage))
        try:
            full = client.get_json(f"content/items/{item['id']}")
        except PortalError as exc:
            export.note_error("item", exc)
            raise ItemFailed(f"reading the item failed, {exc}") from None
        meta = _redacted_text(ctx, {"inventory": row, "item": full})
        if export.charge(len(meta)):
            _report.write_private(build / "item.json", meta)
        else:
            export.partial = True
            export.errors.append("item.json: over the export size cap, not saved")
        data = _save_data(ctx, export, item, full)
        saved = _save_resources(ctx, export, item["id"])
        story = _story(ctx, export, item, data, saved)
    swapped = not (export.failures and folder.exists())
    if swapped:
        _swap_in(build, folder)
    relative = folder.relative_to(ctx.export_dir.parent)
    record = {
        "path": relative.as_posix(),
        "bytes": export.bytes,
        "partial": export.partial,
        "errors": [redact_json(e, ctx.redact) for e in export.errors],
        "story": story,
        # The portal's last change to the item, which a rerun compares.
        "modified": _modified(full),
        # What the bundle holds, which a rerun checks before trusting it.
        "files": _bundle_files(folder) if swapped else {},
    }
    if swapped:
        # Otherwise the earlier bundle stays as it was, and so does its record.
        entry.export = record
    notes = [f"exported to {relative.as_posix()}"]
    if export.partial:
        notes.append("partial: some files were left out; see the export notes")
    notes.extend(f"export: {e}" for e in record["errors"])
    if export.failures:
        # Left failed, so a rerun fetches what a transient error cost.
        raise ItemFailed(
            "export incomplete, rerun to retry: "
            + "; ".join(redact_json(f, ctx.redact) for f in export.failures)
        )
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
        "Items saved so nothing is lost when the ArcGIS subscription ends: items "
        "GeoLens can't host, and source files of hosted layers.",
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
            item_replacement(item, plan, state),
        ]
        lines.append("| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |")
        rows += 1
    if rows:
        # The folder may be gone while the state still records its bundles.
        _private_dirs(ctx.export_dir)
        _report.write_private(
            ctx.export_dir / "INDEX.md",
            redact_json("\n".join(lines) + "\n", ctx.redact),
        )
