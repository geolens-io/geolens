"""Delete the story image objects no ``story_assets`` row names.

An object can outlive every row that names it: an upload stores it before its
row commits, a story deletion or prune deletes objects best effort after the
rows are gone, and a server version that predates an image's other sizes
deletes the rows without them. The pass declines while the catalog holds no
stories at all, so a database that lost its rows can't empty the prefix.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import exists, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.stories.assets import (
    STORY_ASSET_KEY_PREFIX,
    STORY_ASSET_VARIANTS,
)
from app.modules.catalog.stories.models import Story, StoryAsset
from app.platform.jobs.staging_reconcile import (
    _current_entry,
    _iter_leg,
    _resume_point,
    _scan_cursors,
)
from app.platform.storage.provider import StoredObject
from app.platform.storage.titiler_url import resolve_current_storage_key

log = structlog.get_logger()

ORPHAN_OBJECT_MIN_AGE = timedelta(days=1)

_PREFIX = f"{STORY_ASSET_KEY_PREFIX}/"
_OBJECT_NAME = re.compile(
    r"(?P<image>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"-[0-9a-f]{32})(?:"
    + "|".join(re.escape(suffix) for suffix, _ in STORY_ASSET_VARIANTS.values())
    + ")"
)

_MAX_DELETES_PER_PASS = 200
_MAX_OBJECTS_SCANNED_PER_PASS = 20_000
# A provider that filters the resume cursor client-side still fetches the pages
# before it, and those count here.
_MAX_PAGES_PER_PASS = 100


@dataclass
class StoryAssetSweepOutcome:
    """What one pass saw and did."""

    # False when the pass declined, or another process held the pass's lock.
    ran: bool = False
    objects_listed: int = 0
    objects_deleted: int = 0
    delete_failures: int = 0
    skipped_recent: int = 0
    skipped_live: int = 0
    # Gone, rewritten or named by a row between the listing and its delete.
    skipped_changed: int = 0
    # A key that is not exactly a story image's shape.
    skipped_unattributable: int = 0

    def budget_spent(self) -> bool:
        return self.objects_deleted + self.delete_failures >= _MAX_DELETES_PER_PASS


def _logical_key(key: str, physical_prefix: str) -> str | None:
    """The key a row records for the image ``key`` holds, or a size of, or
    None unless it is a story image's."""
    if not key.startswith(physical_prefix):
        return None
    name = _OBJECT_NAME.fullmatch(key[len(physical_prefix) :])
    if name is None:
        return None
    return f"{_PREFIX}{name['image']}.webp"


async def _catalog_has_stories(db: AsyncSession) -> bool:
    return bool(await db.scalar(select(exists(select(Story.id)))))


async def _referenced(db: AsyncSession, logical_keys: set[str]) -> set[str]:
    """The ``logical_keys`` some row names, in one fresh statement."""
    if not logical_keys:
        return set()
    rows = await db.scalars(
        select(StoryAsset.storage_key).where(StoryAsset.storage_key.in_(logical_keys))
    )
    return set(rows)


async def _still_old(
    storage,
    entries: list[StoredObject],
    *,
    cutoff: datetime,
    outcome: StoryAssetSweepOutcome,
) -> list[StoredObject]:
    """The ``entries`` still there and still older than ``cutoff``, read again."""
    kept: list[StoredObject] = []
    for entry in entries:
        try:
            current = await _current_entry(storage, entry.key)
        except Exception as exc:  # broad: best-effort per object, the pass continues
            outcome.delete_failures += 1
            log.warning(
                "Failed to re-read a story image no row names",
                error_type=type(exc).__name__,
            )
            continue
        if current is None or current.last_modified >= cutoff:
            outcome.skipped_changed += 1
        else:
            kept.append(current)
    return kept


async def _delete_image_if_unchanged(
    db: AsyncSession,
    storage,
    logical_key: str,
    entries: list[StoredObject],
    *,
    cutoff: datetime,
    now: datetime,
    outcome: StoryAssetSweepOutcome,
) -> None:
    """Delete the objects of one image's sizes if no row has named it since."""
    entries = await _still_old(storage, entries, cutoff=cutoff, outcome=outcome)
    # Outside any try: a database error ends the pass instead of deleting an
    # object whose row could not be checked.
    if not entries or await _referenced(db, {logical_key}):
        outcome.skipped_changed += len(entries)
        return
    for entry in entries:
        try:
            await storage.delete(entry.key)
        except Exception as exc:  # broad: best-effort per object, the pass continues
            outcome.delete_failures += 1
            log.warning(
                "Failed to delete a story image no row names",
                error_type=type(exc).__name__,
            )
            continue
        outcome.objects_deleted += 1
        log.warning(
            "Deleted a story image no row names",
            age_seconds=int((now - entry.last_modified).total_seconds()),
        )


async def _sweep_page(
    db: AsyncSession,
    storage,
    page: list[StoredObject],
    physical_prefix: str,
    *,
    previous_end: str | None,
    cutoff: datetime,
    now: datetime,
    outcome: StoryAssetSweepOutcome,
) -> tuple[bool, str | None]:
    """Sweep the unnamed story images one page lists.

    Returns whether the page was finished and the key the next pass resumes
    after: the page's end, or where the delete budget stopped it.
    """
    old: defaultdict[str, list[StoredObject]] = defaultdict(list)
    for entry in page:
        logical = _logical_key(entry.key, physical_prefix)
        if logical is None:
            outcome.skipped_unattributable += 1
        elif entry.last_modified >= cutoff:
            outcome.skipped_recent += 1
        else:
            old[logical].append(entry)
    live = await _referenced(db, set(old))

    resume_after = previous_end
    for logical, entries in sorted(old.items(), key=lambda item: item[1][0].key):
        if logical in live:
            outcome.skipped_live += len(entries)
            continue
        if outcome.budget_spent():
            return False, resume_after
        await _delete_image_if_unchanged(
            db, storage, logical, entries, cutoff=cutoff, now=now, outcome=outcome
        )
        resume_after = max(entry.key for entry in entries)
    return True, page[-1].key


async def _scan(
    db: AsyncSession, storage, physical_prefix: str, *, now: datetime
) -> StoryAssetSweepOutcome:
    """The pass body, entered only with the advisory lock held.

    Scans circularly from the resume point, so every key is reached across passes.
    """
    outcome = StoryAssetSweepOutcome(ran=True)
    cutoff = now - ORPHAN_OBJECT_MIN_AGE
    resume_point = _resume_point(physical_prefix)
    legs: list[tuple[str | None, str | None]] = [(resume_point, None)]
    if resume_point is not None:
        legs.append((None, resume_point))

    last_examined: str | None = None
    pages = 0
    stopped_early = False
    for start_after, stop_at in legs:
        async for page in _iter_leg(
            storage, physical_prefix, start_after=start_after, stop_at=stop_at
        ):
            pages += 1
            outcome.objects_listed += len(page)
            finished = True
            if page:
                finished, last_examined = await _sweep_page(
                    db,
                    storage,
                    page,
                    physical_prefix,
                    previous_end=last_examined,
                    cutoff=cutoff,
                    now=now,
                    outcome=outcome,
                )
            if (
                not finished
                or pages >= _MAX_PAGES_PER_PASS
                or outcome.objects_listed >= _MAX_OBJECTS_SCANNED_PER_PASS
            ):
                stopped_early = True
                break
        if stopped_early:
            break

    # A stop before any key was examined leaves no cursor worth resuming from.
    _scan_cursors[physical_prefix] = last_examined if stopped_early else None
    return outcome


async def _sweep(db: AsyncSession, *, now: datetime) -> StoryAssetSweepOutcome:
    from app.core.db import async_session  # late-bound so a test engine applies
    from app.core.db.tenant_session import current_tenant_var
    from app.core.tenancy import is_multi_tenant
    from app.platform.storage import get_storage

    if is_multi_tenant() and current_tenant_var.get() is None:
        return StoryAssetSweepOutcome()
    physical_prefix = resolve_current_storage_key(_PREFIX)

    # A session that only holds the lock, so ending it releases the lock
    # without touching ``db``'s transaction.
    async with async_session() as lock_session:
        locked = await lock_session.execute(
            text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"story-asset-sweep:{physical_prefix}"},
        )
        if not locked.scalar():
            return StoryAssetSweepOutcome()
        async with db.begin_nested():
            if not await _catalog_has_stories(db):
                return StoryAssetSweepOutcome()
            return await _scan(db, get_storage(), physical_prefix, now=now)


async def sweep_unnamed_story_asset_objects(
    db: AsyncSession, *, now: datetime | None = None
) -> StoryAssetSweepOutcome:
    """Delete the objects under ``stories/assets/`` that no row names.

    Only reads through ``db``, inside a savepoint, so a database error rolls
    back just this pass. Never raises: a failure leaves the rest for the next
    pass.
    """
    try:
        outcome = await _sweep(db, now=now or datetime.now(timezone.utc))
    except Exception:  # broad: best-effort pass, never fails its caller
        log.warning("Story image sweep failed", exc_info=True)
        return StoryAssetSweepOutcome()
    if outcome.objects_deleted or outcome.delete_failures:
        log.info("Swept story images no row names", **asdict(outcome))
    return outcome
