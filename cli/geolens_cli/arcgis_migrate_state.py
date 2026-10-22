# SPDX-License-Identifier: Apache-2.0
"""The state file `geolens arcgis migrate` resumes from.

Hand-maintained. One JSON file (mode 0600) records, per plan item, what the
migration did: its status, the GeoLens ids it created or found, the owner it
handed them to, and the last error. Errors pass through the run's redactor
before they are stored, so the file never holds a token or password.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import arcgis_report as _report
from .arcgis_portal import Redactor, redact_json

STATE_FILENAME = "arcgis-migration-state.json"
STATE_VERSION = "1"

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


def _now() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


@dataclass
class ItemState:
    status: str = PENDING
    dataset_ids: list[str] = field(default_factory=list)
    record_ids: list[str] = field(default_factory=list)
    map_id: str | None = None
    job_ids: list[str] = field(default_factory=list)
    # Service layer (its id, or its name) -> the dataset imported from it, so
    # a rerun never imports a layer twice, even after its dataset changed owner.
    layer_datasets: dict[str, str] = field(default_factory=dict)
    # Layer -> its committed ingest job, until the job yields the dataset.
    layer_jobs: dict[str, str] = field(default_factory=dict)
    # The coordinate columns a CSV's pending upload job is committed with.
    file_columns: dict[str, str] = field(default_factory=dict)
    # The service the pins above belong to; None in a file written before it
    # was recorded, which a rerun adopts rather than distrusts.
    service_url: str | None = None
    collection_ids: list[str] = field(default_factory=list)
    owner_id: str | None = None
    notes: list[str] = field(default_factory=list)
    error: str | None = None
    loss_report_path: str | None = None
    metadata_hash: str | None = None
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
            if data.get("schema_version") != STATE_VERSION:
                raise ValueError("unknown schema_version")
            items = {
                str(item_id): ItemState.from_dict(entry)
                for item_id, entry in data["items"].items()
            }
            collections = {
                str(k): str(v) for k, v in data.get("collections", {}).items()
            }
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
            "items": {k: vars(v) for k, v in self.items.items()},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Rewritten after every item, so compact: a plan can hold 10,000 items.
        _report.write_private(self.path, json.dumps(payload, separators=(",", ":")))
