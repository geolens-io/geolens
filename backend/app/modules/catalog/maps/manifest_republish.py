"""Whether a manifest republish replaces a map's styling, and its notes block.

A publish that applies styling sets the baseline. Builder edits to styling
after it make ``replace_if_unedited`` keep the map's styling; edits that
aren't styling don't.
"""

from __future__ import annotations

import unicodedata
import uuid
from collections.abc import Sequence
from datetime import date

import structlog
from fastapi import HTTPException
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.dialects.postgresql import array
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.modules.catalog.maps.models import MapEditHistoryEvent

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
# A settings change is a styling edit only when it moves the view or the
# basemap; notes, description and the other settings are not styling.
_VIEW_FIELDS = ("center_lng", "center_lat", "zoom", "bearing", "pitch", "basemap_style")

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
    styling_edit = or_(
        event.action.in_(sorted(STYLING_EDIT_ACTIONS - {"map.config_update"})),
        and_(
            event.action == "map.config_update",
            event.details["changed_fields"].has_any(array(_VIEW_FIELDS)),
        ),
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


def managed_notes(
    existing: str | None,
    lines: Sequence[str],
    limit: int = NOTES_LIMIT,
) -> str:
    """``existing`` notes with the managed block replaced by ``lines``.

    The managed block is everything before the first line that is exactly
    ``---``; what follows it is the user's and is kept whole. Notes with no
    such line are all the user's. Lines are cut at the last whole one that
    keeps the notes within ``limit``, with a count of the ones left out.
    """
    user = existing or ""
    rows = user.splitlines(keepends=True)
    for index, row in enumerate(rows):
        if row.rstrip("\r\n") == NOTES_SEPARATOR:
            user = "".join(rows[index + 1 :])
            break
    tail = f"\n{NOTES_SEPARATOR}\n{user}"
    return "\n".join(_fitting(lines, limit - len(tail))) + tail


def _fitting(lines: Sequence[str], room: int) -> list[str]:
    """The longest run of ``lines`` from the start that fits in ``room``
    characters joined, with a last line counting the ones left out."""
    sizes = [0]
    for line in lines:
        sizes.append(sizes[-1] + len(line))
    for shown in range(len(lines), -1, -1):
        size = sizes[shown] + max(shown - 1, 0)
        if shown < len(lines):
            note = f"... {len(lines) - shown} more entries"
            size += len(note) + (1 if shown else 0)
        if size <= room:
            if shown < len(lines):
                return [*lines[:shown], note]
            return list(lines)
    return []


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
