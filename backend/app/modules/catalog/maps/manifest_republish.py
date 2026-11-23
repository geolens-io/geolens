"""Whether a manifest republish replaces a map's styling, and its notes block.

A builder edit to styling a publish would write, made after the last publish
that wrote it, makes ``replace_if_unedited`` keep the map's styling; other
edits don't.
"""

from __future__ import annotations

import hashlib
import unicodedata
import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date, datetime

import structlog
from fastapi import HTTPException
from sqlalchemy import and_, exists, func, literal_column, or_, select
from sqlalchemy.dialects.postgresql import array
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.core.text import normalize_nfc
from app.modules.catalog.maps.models import MapEditHistoryEvent, MapLayer
from app.modules.catalog.maps.service_update import CAMERA_FIELDS

log = structlog.get_logger()

PUBLISH_ACTION = "manifest.publish"
# The builder's history actions that edit styling a publish writes: the
# layers' paint, layout, style, labels, popup, filter, opacity, visible flag
# and name, and the map's view and basemap choice (``basemap_style``), which
# ``map.config_update`` records in ``view_changed``. One aimed at a single
# layer counts only while that layer is one the manifest publishes.
STYLING_EDIT_ACTIONS = frozenset(
    {
        "layer.replace",
        "layer.style_update",
        "layer.label_update",
        "layer.popup_update",
        "layer.symbol_update",
        "layer.filter_update",
        "layer.opacity_update",
        "layer.visibility_update",
        "layer.rename",
        "map.import_style",
        "map.config_update",
    }
)
# Every other history action. A publish never writes what these change, such
# as the basemap's appearance (``basemap_config``) or terrain, or writes it on
# every publish whatever the styling decision.
OTHER_HISTORY_ACTIONS = frozenset(
    {
        "layer.add",
        "layer.remove",
        "layer.bulk_remove",
        "layer.reorder",
        "map.create",
        "map.rename",
        "map.visibility_update",
        "map.basemap_update",
        "map.terrain_update",
        "map.import_arcgis_webmap",
        PUBLISH_ACTION,
    }
)

NOTES_SEPARATOR = "---"
NOTES_LIMIT = 50_000


async def styling_edited_since_publish(
    session: AsyncSession,
    map_id: uuid.UUID,
    *,
    view: bool,
    basemap: bool,
    bookmarks: bool = False,
) -> bool:
    """Whether the map's styling that a publish would write was edited after
    the last publish that wrote it, or ever when none did.

    Layer styling counts after the last publish that applied styling, and
    an edit aimed at one layer only while that layer is still on the map
    with a manifest key: a publish never touches a layer added in GeoLens,
    and adds a removed keyed layer back as new. A settings save counts for the camera only with ``view``, when the publish
    sends a view, and after the last publish that wrote the camera; for
    ``basemap_style`` only with ``basemap``, after the last publish that
    wrote it. A save that sent bookmarks counts only with ``bookmarks``, after
    the last publish that wrote them. A publish that didn't write a view, basemap or bookmarks leaves the
    ones it didn't write as edited as they were.
    """
    event = MapEditHistoryEvent

    def last_publish(flag: str):
        """When the map's last publish with ``flag`` true was recorded.
        A publish recorded without the flag isn't one."""
        return func.coalesce(
            select(func.max(event.created_at))
            .where(
                event.map_id == map_id,
                event.action == PUBLISH_ACTION,
                event.details[flag].as_boolean(),
            )
            .scalar_subquery(),
            literal_column("'-infinity'::timestamptz"),
        )

    def moved(fields: Sequence[str]):
        # An event from before ``view_changed`` was recorded lists only the
        # fields sent, and counts when it sent any of them.
        return and_(
            event.action == "map.config_update",
            or_(
                and_(
                    event.details.has_key("view_changed"),
                    event.details["view_changed"].has_any(array(list(fields))),
                ),
                and_(
                    ~event.details.has_key("view_changed"),
                    event.details["changed_fields"].has_any(array(list(fields))),
                ),
            ),
        )

    published_layer = exists().where(
        MapLayer.map_id == map_id,
        MapLayer.id == event.target_id,
        MapLayer.manifest_key.is_not(None),
    )
    styled = last_publish("styling_applied")
    edits = [
        and_(
            event.action.in_(sorted(STYLING_EDIT_ACTIONS - {"map.config_update"})),
            or_(event.target_type != "layer", published_layer),
            event.created_at > styled,
        )
    ]
    baselines = [styled]
    for wanted, flag, fields in (
        (view, "view_written", CAMERA_FIELDS),
        (basemap, "basemap_written", ("basemap_style",)),
    ):
        if wanted:
            baselines.append(last_publish(flag))
            edits.append(and_(moved(fields), event.created_at > baselines[-1]))
    if bookmarks:
        # The builder sends bookmarks only when they were edited.
        baselines.append(last_publish("bookmarks_written"))
        edits.append(
            and_(
                event.action == "map.config_update",
                event.details["changed_fields"].has_key("bookmarks"),
                event.created_at > baselines[-1],
            )
        )
    return bool(
        await session.scalar(
            select(
                exists().where(
                    event.map_id == map_id,
                    # Implied by each edit's own test; on its own it lets the
                    # (map_id, created_at) index skip the older history.
                    event.created_at > func.least(*baselines),
                    or_(*edits),
                )
            )
        )
    )


def styling_applies(mode: str, *, edited: bool) -> bool:
    """Whether a republish in ``mode`` replaces the map's styling."""
    return mode == "replace" or (mode == "replace_if_unedited" and not edited)


def _one_line(text: str) -> str:
    return "".join(
        " " if unicodedata.category(char) in {"Cc", "Zl", "Zp"} else char
        for char in text
    )


def publish_line(client, on: date) -> str:
    """The provenance line: the app, then the client and its version."""
    made_by = f"{client.id} {client.version}"
    source = f"{client.app} ({made_by})" if client.app else made_by
    return _one_line(f"Published from {source} on {on.isoformat()}")


def loss_lines(loss_report) -> list[str]:
    """One line per loss item; the schema holds each item to one line."""
    if loss_report is None:
        return []
    return [
        f"{item.path}: {item.kind}" + (f" ({item.detail})" if item.detail else "")
        for item in loss_report.items
    ]


@dataclass(frozen=True)
class ManagedNotes:
    """The notes a publish writes, the digest of its block, None when no
    block fit, and whether an earlier publish's block was taken out."""

    text: str
    digest: str | None
    replaced: bool = False


def _digest(block: str) -> str:
    return hashlib.sha256(block.encode()).hexdigest()


async def written_notes_digests(
    session: AsyncSession, map_id: uuid.UUID
) -> frozenset[str]:
    """The digests of every notes block a publish of the map wrote.

    A set, not the last one: the notes can hold an older publish's block,
    such as one the user put back, so the newest publish need not be the
    one whose block the notes hold.
    """
    event = MapEditHistoryEvent
    digest = event.details["notes_digest"].astext
    rows = await session.scalars(
        select(digest).where(
            event.map_id == map_id,
            event.action == PUBLISH_ACTION,
            digest.is_not(None),
        )
    )
    return frozenset(rows)


def _users_notes(existing: str, written: Collection[str]) -> str:
    """``existing`` without its leading block when that block, unchanged, is
    one a publish of the map wrote, followed by its divider. Anything else is
    all the user's."""
    rows = existing.splitlines(keepends=True)
    for index, row in enumerate(rows):
        if row.rstrip("\r\n") == NOTES_SEPARATOR:
            block = "".join(rows[:index]).replace("\r\n", "\n").removesuffix("\n")
            if _digest(block) in written:
                return "".join(rows[index + 1 :])
            break
    return existing


def managed_notes(
    existing: str | None,
    lines: Sequence[str],
    written: Collection[str],
    limit: int = NOTES_LIMIT,
) -> ManagedNotes:
    """The notes with a new block of ``lines`` above the user's.

    The user's notes are ``existing`` less a leading block whose digest is in
    ``written``, the blocks the map's publishes wrote, and are never cut. The block takes the room the
    limit leaves them: the first line and as many after it as fit, with a
    count of the ones left out. No block is written when not even the first
    line and the divider fit.

    Fitted and hashed as the notes field stores them, NFC-normalized, so the
    digest matches the stored block on the next publish.
    """
    kept = _users_notes(existing or "", written)
    replaced = kept != (existing or "")
    user = normalize_nfc(kept)
    lines = [normalize_nfc(line) for line in lines]
    tail = f"\n{NOTES_SEPARATOR}\n{user}"
    shown = _fitting(lines, limit - len(tail))
    if not shown:
        return ManagedNotes(user, None, replaced)
    block = "\n".join(shown)
    return ManagedNotes(block + tail, _digest(block), replaced)


def _fitting(lines: Sequence[str], room: int) -> list[str]:
    """The longest run of ``lines`` from the start, at least the first, that
    fits in ``room`` characters joined, with a last line counting the ones
    left out when it fits too. Empty when the first line doesn't fit."""
    if not lines or len(lines[0]) > room:
        return []
    sizes = [0]
    for line in lines:
        sizes.append(sizes[-1] + len(line))
    for shown in range(len(lines), 0, -1):
        size = sizes[shown] + shown - 1
        if shown == len(lines):
            if size <= room:
                return list(lines)
            continue
        note = f"... {len(lines) - shown} more entries"
        if size + 1 + len(note) <= room:
            return [*lines[:shown], note]
    return [lines[0]]


async def store_manifest_thumbnail(
    session: AsyncSession,
    map_id: uuid.UUID,
    data_uri: str,
    user: Identity,
    published_at: datetime,
) -> str | None:
    """Store ``data_uri`` as the map's thumbnail with the thumbnail upload's
    own checks, storage and commit; the reason when it isn't stored.

    Runs after the map's own commit: the map is published either way.
    ``published_at`` is the map's ``updated_at`` as this publish committed
    it; a map written since keeps the thumbnail it has.
    """
    from app.modules.catalog.maps.router import store_map_image

    try:
        await store_map_image(
            session,
            map_id,
            data_uri,
            "thumbnail",
            user,
            expected_updated_at=published_at,
        )
    except HTTPException as exc:
        await session.rollback()
        detail = exc.detail
        if isinstance(detail, dict):
            if detail.get("code") == "stale_write":
                return (
                    "The thumbnail wasn't stored: the map was changed after "
                    "this publish, and the newer change stands."
                )
            detail = detail.get("message", "")
        return f"The thumbnail wasn't stored: {detail}"
    except Exception:  # broad: a thumbnail failure is only a warning
        await session.rollback()
        log.exception("manifest_map_thumbnail_failed", map_id=str(map_id))
        return "The thumbnail wasn't stored. Try again."
    return None
