# SPDX-License-Identifier: Apache-2.0
"""The checks `geolens arcgis migrate --cutover` runs before it marks the final run.

Hand-maintained. Each check names what would not carry over if the portal
were retired now; the run is marked only when every failing check is
accepted with its ``--accept-<check>`` flag.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

from . import arcgis_plan as _plan
from .arcgis_portal import PortalClient, PortalError
from .arcgis_migrate_state import FINISHED, ItemState, MigrationState

UNFINISHED = "unfinished-items"
INVENTORY = "incomplete-inventory"
ATTACHMENTS = "attachment-loss"
USERS = "unresolved-users"
CHECKS = (UNFINISHED, INVENTORY, ATTACHMENTS, USERS)
ADMIN_VIEW_ITEMS = "portal:admin:viewItems"


def _covers_org(inventory: Mapping[str, Any]) -> bool:
    return (
        "scope" in inventory and "auth" in inventory and _plan.shows_removals(inventory)
    )


def _unfinished(plan: Mapping[str, Any], state: MigrationState) -> list[dict[str, str]]:
    out = []
    for item in plan["items"]:
        if item.get("removed") or item["action"] == _plan.SKIP:
            continue
        entry = state.items.get(item["id"])
        status = state.status(item["id"])
        # A finished item the last merge didn't list isn't brought up to date.
        if item.get("unlisted"):
            out.append({"item": item["id"], "reason": "unlisted"})
        elif status not in FINISHED:
            out.append({"item": item["id"], "reason": status})
        for reason in [*entry.left_behind, *entry.stale] if entry else []:
            out.append({"item": item["id"], "reason": reason})
        export = (entry.export or {}) if entry else {}
        if export.get("partial") or export.get("errors"):
            missing = (
                "; ".join(export.get("errors") or []) or "some files were left out"
            )
            out.append(
                {
                    "item": item["id"],
                    "reason": f"its export bundle is missing files: {missing}",
                }
            )
    return out


def attachment_losses(
    item: Mapping[str, Any], entry: ItemState | None
) -> list[tuple[str, str, str]]:
    """``(layer, dataset, "has" | "may have")`` for each migrated layer of a
    service item whose attachments stay behind, or that the probe didn't say."""
    if item.get("removed") or item["action"] != _plan.IMPORT_LAYERS or not entry:
        return []
    flags = entry.attachments or {}
    return [
        (layer, dataset, "has" if flags.get(layer) else "may have")
        for layer, dataset in entry.layer_datasets.items()
        if flags.get(layer) is not False
    ]


def _attachments(
    plan: Mapping[str, Any], state: MigrationState
) -> list[dict[str, str]]:
    return [
        {"item": item["id"], "reason": f"layer {layer} ({dataset}) {has} attachments"}
        for item in plan["items"]
        for layer, dataset, has in attachment_losses(item, state.items.get(item["id"]))
    ]


def _users(
    plan: Mapping[str, Any],
    state: MigrationState,
    unresolved: Iterable[Mapping[str, str]],
) -> list[dict[str, str]]:
    out = []
    for item in plan["items"]:
        entry = state.items.get(item["id"])
        if entry is not None and entry.owner_pending and not item.get("removed"):
            out.append({"item": item["id"], "reason": entry.owner_pending})
    out += [{"item": u["item"], "reason": u["reason"]} for u in unresolved]
    return out


def inventory_changes(
    client: PortalClient | None, plan: Mapping[str, Any], now: datetime
) -> str | None:
    """Why the plan's inventory may be out of date, or None: the portal has an
    item of the organization changed after the inventory was read, or the
    portal couldn't be asked."""
    inventory = plan["inventory"]
    if not inventory.get("started_at"):
        return (
            "the plan's inventory records no start time by the portal's clock, so "
            "items changed while it ran can't be told apart; run inventory and "
            "plan again"
        )
    # The start, not the end: an item changed while the inventory ran may
    # have been read before the change.
    read_at = datetime.fromisoformat(inventory["started_at"])
    age = _age(now - read_at)
    org = (inventory.get("scope") or {}).get("org_id")
    unchecked = f"couldn't check the portal for items changed since the inventory was read {age} ago"
    if client is None or not client.token:
        return f"{unchecked}: the run has no ArcGIS credential"
    if not org:
        return f"{unchecked}: the plan records no ArcGIS organization"
    try:
        if not _org_admin(client.get_json("portals/self")):
            return (
                f"{unchecked}: the run's ArcGIS account isn't an organization "
                f"administrator ({_plan.ORG_ADMIN}), so its search can miss items "
                "not shared with it"
            )
        page = client.get_json(
            "search",
            {
                "q": f"orgid:{org}",
                "sortField": "modified",
                "sortOrder": "desc",
                "num": 1,
            },
        )
    except PortalError as exc:
        return f"{unchecked}: {exc}"
    results = page.get("results") if isinstance(page, dict) else None
    if not isinstance(results, list):
        return f"{unchecked}: the portal's search answered without results"
    if not results:
        return None
    newest = results[0].get("modified") if isinstance(results[0], dict) else None
    if not isinstance(newest, int) or isinstance(newest, bool):
        return f"{unchecked}: the portal's newest item has no usable modified time"
    if newest > read_at.timestamp() * 1000:
        return (
            f"portal items changed after the inventory was read {age} ago; run "
            "inventory and plan again"
        )
    return None


def _org_admin(info: Any) -> bool:
    """Whether ``portals/self`` describes an org admin, by role or by the
    privilege to view every item."""
    user = info.get("user") if isinstance(info, dict) else None
    if not isinstance(user, dict):
        return False
    privileges = user.get("privileges")
    return user.get("role") == _plan.ORG_ADMIN or (
        isinstance(privileges, list) and ADMIN_VIEW_ITEMS in privileges
    )


def _age(delta: timedelta) -> str:
    days = delta.days
    if days >= 1:
        return f"{days} day{'s' if days != 1 else ''}"
    hours = max(int(delta.total_seconds() // 3600), 0)
    return f"{hours} hour{'s' if hours != 1 else ''}"


def _inventory(plan: Mapping[str, Any], changed: str | None) -> list[dict[str, str]]:
    if not _covers_org(plan["inventory"]):
        changed = (
            "the plan was last merged from an inventory that isn't a complete "
            "--scope org one read by an organization administrator, so portal "
            "items may be missing from it"
        )
    return [{"item": "-", "reason": changed}] if changed else []


def failing_checks(
    plan: Mapping[str, Any],
    state: MigrationState,
    unresolved: Sequence[Mapping[str, str]] = (),
    inventory_changed: str | None = None,
) -> list[dict[str, Any]]:
    """Every check that fails as of *state*, with the items it names."""
    found = {
        UNFINISHED: _unfinished(plan, state),
        INVENTORY: _inventory(plan, inventory_changed),
        ATTACHMENTS: _attachments(plan, state),
        USERS: _users(plan, state, unresolved),
    }
    return [{"check": name, "items": found[name]} for name in CHECKS if found[name]]
