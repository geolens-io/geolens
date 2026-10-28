# SPDX-License-Identifier: Apache-2.0
"""The state file `geolens arcgis migrate` resumes from.

Hand-maintained. One JSON file (mode 0600) records, per plan item, what the
migration did: its status, the GeoLens ids it created or found, the owner it
handed them to, and the last error. Errors pass through the run's redactor
before they are stored, so the file never holds a token or password.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from . import arcgis_report as _report
from .arcgis_portal import Redactor, redact_json

STATE_FILENAME = "arcgis-migration-state.json"
# v2 adds what a rerun compares and waits on, v3 the GeoLens groups made for
# ArcGIS groups, and v4 what this command's own writes added, which a rerun may
# take away again: a made group's members (``joined``) and each object's
# groups (``granted``). An older CLI refuses the file rather than rewriting it
# without them. A v3 file records neither, so a rerun removes nothing it
# added before.
STATE_VERSION = "4"
_READABLE_VERSIONS = ("1", "2", "3", STATE_VERSION)

PENDING = "pending"
RUNNING = "running"
DONE = "done"
EXISTS = "exists"
FAILED = "failed"
SKIPPED = "skipped"
STATUSES = (PENDING, RUNNING, DONE, EXISTS, FAILED, SKIPPED)
FINISHED = frozenset({DONE, EXISTS})
MAX_ERROR_CHARS = 2000


_HELD_LOCKS: list[Any] = []


def _lock_exclusive(handle: Any) -> None:
    """Take a non-blocking exclusive lock on an open file; ``OSError`` if
    another process holds it."""
    try:
        import fcntl
    except ImportError:
        import msvcrt  # Windows

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return
    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)


def release_locks() -> None:
    """Release every state file lock this process took."""
    while _HELD_LOCKS:
        _HELD_LOCKS.pop().close()


class StateError(Exception):
    """The state file can't be read, or belongs to another portal."""


def whole_number(value: Any) -> int | None:
    """*value* when it is an int, and not a bool, else None."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def aware_time(value: Any) -> datetime | None:
    """*value* as a timezone-aware datetime when it is an ISO time with an
    offset, else None."""
    try:
        when = datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None
    return when if when is not None and when.tzinfo is not None else None


def _uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def _joined(record: Mapping[str, Any]) -> bool:
    """Whether a group record's ``joined`` maps user ids it also lists as
    added to the ArcGIS names they were added for."""
    joined = record.get("joined", {})
    return (
        isinstance(joined, dict)
        and all(
            _uuid(user_id)
            and isinstance(names, list)
            and all(isinstance(n, str) for n in names)
            for user_id, names in joined.items()
        )
        and set(joined) <= set(record.get("added") or [])
    )


def _group_record(record: Any) -> bool:
    """Whether *record* has the shape of a state file group record."""
    return (
        isinstance(record, dict)
        and isinstance(record.get("id"), str | None)
        and isinstance(record.get("name"), str | None)
        and isinstance(record.get("created", False), bool)
        and all(
            isinstance(record.get(key, []), list)
            for key in ("added", "pending", "unsynced")
        )
        and all(
            isinstance(p, dict) and isinstance(p.get("member"), str)
            for key in ("pending", "unsynced")
            for p in record.get(key, [])
        )
        and _joined(record)
    )


def _now() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


@dataclass
class ItemState:
    status: str = PENDING
    dataset_ids: list[str] = field(default_factory=list)
    record_ids: list[str] = field(default_factory=list)
    map_id: str | None = None
    # ArcGIS operational layer id -> the map layer made for it, which a story
    # map's conversion and a later re-translation locate layers by.
    layer_ids: dict[str, str] = field(default_factory=dict)
    job_ids: list[str] = field(default_factory=list)
    # Service layer (its id, or its name) -> the dataset imported from it, so
    # a rerun never imports a layer twice, even after its dataset changed owner.
    layer_datasets: dict[str, str] = field(default_factory=dict)
    # Datasets GeoLens already held that the import reused, whose owner's
    # edits from before the migration are taken as they are.
    reused: list[str] = field(default_factory=list)
    # Layer -> its committed ingest job, until the job yields the dataset.
    layer_jobs: dict[str, str] = field(default_factory=dict)
    # The coordinate columns a CSV's pending upload job is committed with.
    file_columns: dict[str, str] = field(default_factory=dict)
    # A multi-layer file's fan-out, recorded before it is sent: the parent
    # upload job and the layers asked for.
    fan_out: dict[str, Any] | None = None
    # A file's upload job from the upload until its preview has chosen how it
    # is committed, so a rerun after a failed preview does not upload again.
    pending_upload: str | None = None
    # The service the pins above belong to; None in a file written before it
    # was recorded, which a rerun adopts rather than distrusts.
    service_url: str | None = None
    collection_ids: list[str] = field(default_factory=list)
    # The export bundle of an export_only item: folder, bytes, partial, errors.
    export: dict[str, Any] | None = None
    owner_id: str | None = None
    notes: list[str] = field(default_factory=list)
    error: str | None = None
    loss_report_path: str | None = None
    # A web map's loss payload from the import until its report file is written.
    pending_loss: dict[str, Any] | None = None
    # The portal item's modified time when a web map was read for its import,
    # which a rerun compares to report a map changed since.
    portal_modified: int | None = None
    # Hash of the summary a file written before the baseline wrote; read only
    # when a dataset has no baseline.
    metadata_hash: str | None = None
    # Dataset -> the item metadata this command last wrote there (summary,
    # attribution, license, source_organization, keywords), so a rerun can tell
    # a field it wrote from one someone edited in GeoLens.
    metadata_baseline: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Dataset -> its GeoLens updated_at, feature count and data revision when
    # this command last left it, so a rerun can tell a change made since.
    last_update: dict[str, dict[str, Any]] = field(default_factory=dict)
    # The migrated map's owner and updated_at as this command last left it,
    # so a deferred handover leaves a map somebody changed since.
    map_snapshot: dict[str, str] | None = None
    # Dataset -> the refresh run ({"run": id}), replacement upload job
    # ({"job": id}), refresh request not yet answered ({"pending": run total})
    # or run held for review ({"blocked": id}), with the data revision it was
    # sent with, until its outcome is settled.
    refreshing: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Imported service layer -> whether the probe reported attachments (None:
    # it didn't say); None until the service is probed by this version.
    attachments: dict[str, bool | None] | None = None
    # Imported service layer -> the relationship classes it declares, as
    # {"id", "name", "related", "cardinality", "role"}; None until probed by this
    # version.
    relationships: dict[str, list[dict[str, Any]]] | None = None
    # Why the item sits with --unmapped-owner instead of its plan owner.
    owner_pending: str | None = None
    # What of the item GeoLens doesn't import, such as a service's raster
    # layers; cutover counts each as a loss.
    left_behind: list[str] = field(default_factory=list)
    # Set when the item's import stage finished: the service's left-out layer
    # notes and, per imported layer, its label and layer id, from which a rerun
    # gives the recorded datasets the plan's current title and visibility
    # without probing the service again.
    import_pass: dict[str, Any] | None = None
    # Dataset -> the visibility this command last gave it, so a rerun can
    # tell a portal sharing change from an edit made in GeoLens.
    visibility: dict[str, str] = field(default_factory=dict)
    # Dataset or map id -> the GeoLens groups this command shared it with,
    # which a rerun doesn't add again after someone removed one in GeoLens.
    groups: dict[str, list[str]] = field(default_factory=dict)
    # Dataset or map id -> the groups among those that this command's own
    # writes added, the only ones a rerun removes when the plan drops them.
    granted: dict[str, list[str]] = field(default_factory=dict)
    # Why the last rerun couldn't bring the item up to date.
    stale: list[str] = field(default_factory=list)
    started_at: str | None = None
    finished_at: str | None = None

    @classmethod
    def from_dict(cls, data: Any) -> ItemState:
        if not isinstance(data, dict) or data.get("status") not in STATUSES:
            raise ValueError("item entry without a known status")
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


class MigrationState:
    """Per-item progress for one plan, saved after every change."""

    def __init__(
        self,
        path: Path,
        portal_url: str,
        instance: str,
        redact: Redactor,
        *,
        persist: bool = True,
    ) -> None:
        self.path = path
        self.portal_url = portal_url
        self.instance = instance
        self.items: dict[str, ItemState] = {}
        # Collection name the plan asked for -> the collection this run made
        # for it, which may carry the portal's name as a prefix.
        self.collections: dict[str, str] = {}
        # When `migrate --cutover` passed its checks, and the losses accepted.
        self.cutover: dict[str, Any] | None = None
        # ArcGIS group id -> the GeoLens group this command created for it:
        # its id and name, the members it added or found there (``added``),
        # those it added itself with the ArcGIS names they were added for
        # (``joined``), and those still pending.
        self.groups: dict[str, dict[str, Any]] = {}
        self._redact = redact
        self._persist = persist

    @classmethod
    def load(
        cls,
        path: Path,
        portal_url: str,
        instance: str,
        redact: Redactor,
        *,
        persist: bool = True,
    ) -> MigrationState:
        """The state at *path*, or an empty one when the file doesn't exist.

        Refuses a file written for another portal or another GeoLens
        instance: its item ids would be matched against the wrong
        organization, or its GeoLens ids against the wrong catalog. With
        *persist*, holds an exclusive lock on ``<path>.lock`` until
        ``release_locks``, so two runs can't import the same items at once.
        """
        state = cls(path, portal_url, instance, redact, persist=persist)
        if persist:
            state._lock()
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return state
        except OSError as exc:
            raise StateError(
                f"can't read the state file {path}: {exc.strerror}"
            ) from None
        except UnicodeDecodeError:
            raise StateError(
                f"the state file {path} is not a migration state v{STATE_VERSION} "
                "file (not UTF-8 text)"
            ) from None
        try:
            data = json.loads(raw)
            if data.get("schema_version") not in _READABLE_VERSIONS:
                raise ValueError("unknown schema_version")
            items = {
                str(item_id): ItemState.from_dict(entry)
                for item_id, entry in data["items"].items()
            }
            collections = {
                str(k): str(v) for k, v in data.get("collections", {}).items()
            }
            cutover = data.get("cutover")
            if cutover is not None and not isinstance(cutover, dict):
                raise ValueError("cutover is not an object")
            groups = data.get("groups", {})
            if not isinstance(groups, dict) or not all(
                _group_record(g) for g in groups.values()
            ):
                raise ValueError("groups holds a malformed group record")
            recorded_portal = data["portal_url"]
            recorded_instance = data["geolens_instance"]
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise StateError(
                f"the state file {path} is not a migration state v{STATE_VERSION} "
                f"file ({exc})"
            ) from None
        if recorded_portal != portal_url:
            raise StateError(
                f"the state file {path} records a migration from {recorded_portal}, "
                f"not {portal_url}; pass --state with another path"
            )
        if recorded_instance != instance:
            raise StateError(
                f"the state file {path} records a migration into {recorded_instance}, "
                f"not {instance}; pass --state with another path"
            )
        state.items = items
        state.collections = collections
        state.cutover = cutover
        state.groups = groups
        return state

    def _lock(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(f"{self.path}.lock", "a+")
        try:
            _lock_exclusive(handle)
        except OSError:
            handle.close()
            raise StateError(
                f"another `geolens arcgis migrate` run is using {self.path}; "
                "wait for it to finish"
            ) from None
        _HELD_LOCKS.append(handle)

    def status(self, item_id: str) -> str:
        entry = self.items.get(item_id)
        return entry.status if entry else PENDING

    def item(self, item_id: str) -> ItemState:
        return self.items.setdefault(item_id, ItemState())

    def start(self, item_id: str) -> ItemState:
        entry = self.item(item_id)
        entry.status = RUNNING
        entry.error = None
        entry.started_at = _now()
        entry.finished_at = None
        return entry

    def finish(
        self, item_id: str, status: str, error: str | None = None, *, save: bool = True
    ) -> None:
        entry = self.item(item_id)
        entry.status = status
        entry.error = self.clean(error) if error else None
        entry.finished_at = _now()
        if save:
            self.save()

    def clean(self, text: str) -> str:
        """*text* redacted and shortened, safe to store in the file."""
        return redact_json(text, self._redact)[:MAX_ERROR_CHARS]

    def save(self) -> None:
        if not self._persist:
            return
        payload = {
            "schema_version": STATE_VERSION,
            "portal_url": self.portal_url,
            "geolens_instance": self.instance,
            "collections": self.collections,
            "cutover": self.cutover,
            "groups": self.groups,
            "items": {k: vars(v) for k, v in self.items.items()},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Rewritten after every item, so compact: a plan can hold 10,000 items.
        _report.write_private(self.path, json.dumps(payload, separators=(",", ":")))
