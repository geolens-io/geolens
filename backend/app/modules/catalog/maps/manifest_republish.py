"""Whether a manifest republish replaces a map's styling, and its notes block.

A publish that applies styling sets the baseline. Builder edits to styling
after it make ``replace_if_unedited`` keep the map's styling; edits that
aren't styling don't.
"""

from __future__ import annotations

import hashlib
import unicodedata
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import structlog
from fastapi import HTTPException
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.dialects.postgresql import array
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.core.text import normalize_nfc
from app.modules.catalog.maps.models import MapEditHistoryEvent
from app.modules.catalog.maps.service_update import VIEW_FIELDS

log = structlog.get_logger()

PUBLISH_ACTION = "manifest.publish"
# The builder's history actions that edit styling a publish writes: the
# layers' paint, layout, style, labels, popup, filter, opacity, visible flag
# and name, and the map's basemap and view.
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
        "map.basemap_update",
        "map.config_update",
    }
)
# Every other history action. A publish never writes what these change, or
# writes it on every publish whatever the styling decision.
OTHER_HISTORY_ACTIONS = frozenset(
    {
        "layer.add",
        "layer.remove",
        "layer.bulk_remove",
        "layer.reorder",
        "map.create",
        "map.rename",
        "map.visibility_update",
        "map.terrain_update",
        "map.import_arcgis_webmap",
        PUBLISH_ACTION,
    }
)

NOTES_SEPARATOR = "---"
NOTES_LIMIT = 50_000


async def styling_edited_since_publish(
    session: AsyncSession, map_id: uuid.UUID
) -> bool:
    """Whether the map's styling was edited after the last publish that
    applied styling, or ever when no publish applied it."""
    event = MapEditHistoryEvent
    baseline = (
        select(func.max(event.created_at))
        .where(
            event.map_id == map_id,
            event.action == PUBLISH_ACTION,
            event.details["styling_applied"].as_boolean(),
        )
        .scalar_subquery()
    )
    # A settings change is a styling edit only when it moved the view or the
    # basemap. An event from before ``view_changed`` was recorded lists only
    # the fields sent, and counts when it sent any of them.
    view_moved = or_(
        and_(
            event.details.has_key("view_changed"),
            func.jsonb_array_length(event.details["view_changed"]) > 0,
        ),
        and_(
            ~event.details.has_key("view_changed"),
            event.details["changed_fields"].has_any(array(VIEW_FIELDS)),
        ),
    )
    styling_edit = or_(
        event.action.in_(sorted(STYLING_EDIT_ACTIONS - {"map.config_update"})),
        and_(event.action == "map.config_update", view_moved),
    )
    return bool(
        await session.scalar(
            select(
                exists().where(
                    event.map_id == map_id,
                    styling_edit,
                    or_(baseline.is_(None), event.created_at > baseline),
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
    """The notes a publish writes, and the digest of its block, None when no
    block fit."""

    text: str
    digest: str | None


def _digest(block: str) -> str:
    return hashlib.sha256(block.encode()).hexdigest()


async def last_notes_digest(session: AsyncSession, map_id: uuid.UUID) -> str | None:
    """The digest of the notes block the map's last publish wrote."""
    event = MapEditHistoryEvent
    return await session.scalar(
        select(event.details["notes_digest"].astext)
        .where(event.map_id == map_id, event.action == PUBLISH_ACTION)
        .order_by(event.created_at.desc())
        .limit(1)
    )


def _users_notes(existing: str, written_digest: str | None) -> str:
    """``existing`` without the block the last publish wrote, when the notes
    still start with that block, unchanged, and its divider. Anything else is
    all the user's."""
    rows = existing.splitlines(keepends=True)
    for index, row in enumerate(rows):
        if row.rstrip("\r\n") == NOTES_SEPARATOR:
            block = "".join(rows[:index]).replace("\r\n", "\n").removesuffix("\n")
            if written_digest is not None and _digest(block) == written_digest:
                return "".join(rows[index + 1 :])
            break
    return existing


def managed_notes(
    existing: str | None,
    lines: Sequence[str],
    written_digest: str | None,
    limit: int = NOTES_LIMIT,
) -> ManagedNotes:
    """The notes with a new block of ``lines`` above the user's.

    The user's notes are ``existing`` less the block the last publish wrote
    (``written_digest``), and are never cut. The block takes the room the
    limit leaves them: the first line and as many after it as fit, with a
    count of the ones left out. No block is written when not even the first
    line and the divider fit.

    Fitted and hashed as the notes field stores them, NFC-normalized, so the
    digest matches the stored block on the next publish.
    """
    user = normalize_nfc(_users_notes(existing or "", written_digest))
    lines = [normalize_nfc(line) for line in lines]
    tail = f"\n{NOTES_SEPARATOR}\n{user}"
    shown = _fitting(lines, limit - len(tail))
    if not shown:
        return ManagedNotes(user, None)
    block = "\n".join(shown)
    return ManagedNotes(block + tail, _digest(block))


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
    session: AsyncSession, map_id: uuid.UUID, data_uri: str, user: Identity
) -> str | None:
    """Store ``data_uri`` as the map's thumbnail with the thumbnail upload's
    own checks, storage and commit; the reason when it isn't stored.

    Runs after the map's own commit: the map is published either way.
    """
    from app.modules.catalog.maps.router import store_map_image

    try:
        await store_map_image(session, map_id, data_uri, "thumbnail", user)
    except HTTPException as exc:
        await session.rollback()
        detail = exc.detail
        if isinstance(detail, dict):
            detail = detail.get("message", "")
        return f"The thumbnail wasn't stored: {detail}"
    except (
        Exception
    ):  # broad: the map is published; a thumbnail failure is only a warning
        await session.rollback()
        log.exception("manifest_map_thumbnail_failed", map_id=str(map_id))
        return "The thumbnail wasn't stored. Try again."
    return None
