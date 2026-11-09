"""Delete the map thumbnail and social-card objects no map row names.

An upload stores its object before the row that names it commits, and the
object a newer upload or a map deletion replaces is deleted best effort after
the commit, so either can leave an object behind. The pass declines while the
catalog holds no maps at all, so a database that lost its rows can't empty the
prefixes.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.maps.models import Map
from app.platform.jobs.orphan_scan import current_entry, reconcile_orphan_objects
from app.platform.storage.provider import StoredObject

log = structlog.get_logger()

ORPHAN_OBJECT_MIN_AGE = timedelta(days=1)

MAP_IMAGE_PREFIXES = ("maps/thumbnails/", "maps/og-images/")

# Both shapes the upload handlers have written: ``{map_id}-{hex}.{ext}`` and the
# older ``{map_id}.{ext}`` that rows may still name.
_OBJECT_NAME = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"(?:-[0-9a-f]{32})?\.(?:jpg|png)"
)

_MAX_DELETES_PER_PASS = 200
_MAX_OBJECTS_SCANNED_PER_PASS = 20_000
# A provider that filters the resume cursor client-side still fetches the pages
# before it, and those count here.
_MAX_PAGES_PER_PASS = 100


@dataclass
class MapImageSweepOutcome:
    """What one pass over both prefixes saw and did."""

    # False when neither prefix was walked: declined, or locked elsewhere.
    ran: bool = False
    objects_listed: int = 0
    objects_deleted: int = 0
    delete_failures: int = 0
    skipped_recent: int = 0
    skipped_live: int = 0
    # Gone, rewritten or named by a row between the listing and its delete.
    skipped_changed: int = 0
    # A key that is not exactly a map image's shape.
    skipped_unattributable: int = 0

    def budget_spent(self) -> bool:
        return self.objects_deleted + self.delete_failures >= _MAX_DELETES_PER_PASS


def _logical_key(key: str, prefix: str, physical_prefix: str) -> str | None:
    """The key a row records for the object ``key``, or None unless it is a
    map image's."""
    if not key.startswith(physical_prefix):
        return None
    name = key[len(physical_prefix) :]
    if _OBJECT_NAME.fullmatch(name) is None:
        return None
    return f"{prefix}{name}"


async def _catalog_has_maps(db: AsyncSession) -> bool:
    return bool(await db.scalar(select(exists(select(Map.id)))))


async def _referenced(db: AsyncSession, logical_keys: set[str]) -> set[str]:
    """The ``logical_keys`` either image column names, in one fresh statement.

    Both columns for every key: a key found under the other column is still
    live, and keeping it costs nothing.
    """
    if not logical_keys:
        return set()
    rows = await db.execute(
        select(Map.thumbnail_uri, Map.og_image_uri).where(
            or_(
                Map.thumbnail_uri.in_(logical_keys),
                Map.og_image_uri.in_(logical_keys),
            )
        )
    )
    return {key for row in rows for key in row if key} & logical_keys


async def _delete_if_unchanged(
    db: AsyncSession,
    storage,
    logical_key: str,
    entry: StoredObject,
    *,
    cutoff: datetime,
    now: datetime,
    outcome: MapImageSweepOutcome,
) -> None:
    """Delete one object if it is still old and no row has named it since."""
    try:
        current = await current_entry(storage, entry.key)
    except Exception as exc:  # broad: best-effort per object, the pass continues
        outcome.delete_failures += 1
        log.warning(
            "Failed to re-read a map image no row names",
            error_type=type(exc).__name__,
        )
        return
    if current is None or current.last_modified >= cutoff:
        outcome.skipped_changed += 1
        return
    # Outside any try: a database error ends the pass instead of deleting an
    # object whose row could not be checked.
    if await _referenced(db, {logical_key}):
        outcome.skipped_changed += 1
        return
    try:
        await storage.delete(current.key)
    except Exception as exc:  # broad: best-effort per object, the pass continues
        outcome.delete_failures += 1
        log.warning(
            "Failed to delete a map image no row names",
            error_type=type(exc).__name__,
        )
        return
    outcome.objects_deleted += 1
    log.warning(
        "Deleted a map image no row names",
        age_seconds=int((now - current.last_modified).total_seconds()),
    )


async def _sweep_page(
    db: AsyncSession,
    storage,
    page: list[StoredObject],
    prefix: str,
    physical_prefix: str,
    *,
    previous_end: str | None,
    cutoff: datetime,
    now: datetime,
    outcome: MapImageSweepOutcome,
) -> tuple[bool, str | None]:
    """Sweep the unnamed map images one page lists.

    Returns whether the page was finished and the key the next pass resumes
    after: the page's end, or where the delete budget stopped it.
    """
    old: dict[str, StoredObject] = {}
    for entry in page:
        logical = _logical_key(entry.key, prefix, physical_prefix)
        if logical is None:
            outcome.skipped_unattributable += 1
        elif entry.last_modified >= cutoff:
            outcome.skipped_recent += 1
        else:
            old[logical] = entry
    live = await _referenced(db, set(old))

    resume_after = previous_end
    for logical, entry in sorted(old.items(), key=lambda item: item[1].key):
        if logical in live:
            outcome.skipped_live += 1
            continue
        if outcome.budget_spent():
            return False, resume_after
        await _delete_if_unchanged(
            db, storage, logical, entry, cutoff=cutoff, now=now, outcome=outcome
        )
        resume_after = entry.key
    return True, page[-1].key


async def _sweep_prefix(
    db: AsyncSession,
    prefix: str,
    *,
    cutoff: datetime,
    now: datetime,
    outcome: MapImageSweepOutcome,
) -> bool:
    """Walk one prefix; False when the pass declined it."""

    async def handle_page(storage, physical_prefix, page, previous_end):
        return await _sweep_page(
            db,
            storage,
            page,
            prefix,
            physical_prefix,
            previous_end=previous_end,
            cutoff=cutoff,
            now=now,
            outcome=outcome,
        )

    progress = await reconcile_orphan_objects(
        prefix=prefix,
        lock_name="map-image-sweep",
        handle_page=handle_page,
        max_objects=_MAX_OBJECTS_SCANNED_PER_PASS,
        max_pages=_MAX_PAGES_PER_PASS,
        db=db,
        guard=lambda: _catalog_has_maps(db),
    )
    if progress is None:
        return False
    outcome.objects_listed += progress.objects_listed
    return True


async def _sweep(db: AsyncSession, *, now: datetime) -> MapImageSweepOutcome:
    outcome = MapImageSweepOutcome()
    cutoff = now - ORPHAN_OBJECT_MIN_AGE
    for prefix in MAP_IMAGE_PREFIXES:
        if outcome.budget_spent():
            break
        if await _sweep_prefix(db, prefix, cutoff=cutoff, now=now, outcome=outcome):
            outcome.ran = True
    return outcome


async def sweep_unnamed_map_image_objects(
    db: AsyncSession, *, now: datetime | None = None
) -> MapImageSweepOutcome:
    """Delete the objects under ``maps/thumbnails/`` and ``maps/og-images/``
    that no map row names.

    Only reads through ``db``, inside a savepoint, so a database error rolls
    back just this pass. Never raises: a failure leaves the rest for the next
    pass.
    """
    try:
        outcome = await _sweep(db, now=now or datetime.now(timezone.utc))
    except Exception:  # broad: best-effort pass, never fails its caller
        log.warning("Map image sweep failed", exc_info=True)
        return MapImageSweepOutcome()
    if outcome.objects_deleted or outcome.delete_failures:
        log.info("Swept map images no row names", **asdict(outcome))
    return outcome
