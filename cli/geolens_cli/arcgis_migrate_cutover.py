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
from .arcgis_migrate_groups import wanted_groups
from .arcgis_portal import PortalClient, PortalError
from .arcgis_migrate_state import (
    FINISHED,
    ItemState,
    MigrationState,
    aware_time,
    whole_number,
)

UNFINISHED = "unfinished-items"
INVENTORY = "incomplete-inventory"
ATTACHMENTS = "attachment-loss"
USERS = "unresolved-users"
SHARING = "under-sharing"
CHECKS = (UNFINISHED, INVENTORY, ATTACHMENTS, USERS, SHARING)
ADMIN_VIEW_ITEMS = "portal:admin:viewItems"
SEARCH_PAGE = 100
SEARCH_PAGES = 10


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
        reasons = [*entry.left_behind, *entry.stale] if entry else []
        extras = (
            (
                entry.owed_reason(),
                entry.unsettled_reason(),
                entry.pending_metadata_reason(),
            )
            if entry
            else ()
        )
        for extra in extras:
            if extra and extra not in reasons:
                reasons.append(extra)
        for reason in reasons:
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


def current(made: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    """The record to read for a state group: what an editor run resolved over
    an admin run's record, else the record itself. The admin record keeps the
    history that run needs; this is the audience items are shared with now."""
    if made and not made.get("unmapped") and "effective" in made:
        return made["effective"]
    return made


def in_use(made: Mapping[str, Any] | None) -> bool:
    """Whether a state group record names a GeoLens group items are shared
    with now: not unmapped in the plan and not deleted in GeoLens."""
    return bool(
        made and made.get("id") and not made.get("deleted") and not made.get("unmapped")
    )


def groups_in_use(plan: Mapping[str, Any], state: MigrationState) -> set[str]:
    """The ArcGIS groups a restricted item still shares with: one still to
    import, or one migrated and not removed, unlisted ones included, whose
    GeoLens objects keep the group's grant. A group outside these waits on
    nobody."""
    needed = set(wanted_groups(plan, plan["items"]))
    for item in plan["items"]:
        entry = state.items.get(item["id"])
        if (
            not item.get("removed")
            and item["target"]["visibility"] == "restricted"
            and entry is not None
            and (entry.dataset_ids or entry.map_id)
        ):
            needed.update(item["target"]["groups"] or [])
    return needed


def sharing_losses(
    plan: Mapping[str, Any],
    state: MigrationState,
    item: Mapping[str, Any],
    prepared: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[str]:
    """Why a migrated item shared only with ArcGIS groups may reach fewer
    people in GeoLens than in the portal. *prepared* holds what this run
    resolved for its groups, which a dry run doesn't record in the state."""
    entry = state.items.get(item["id"])
    if (
        item.get("removed")
        or item["target"]["visibility"] != "restricted"
        or entry is None
        or not (entry.dataset_ids or entry.map_id)
    ):
        return []
    plan_reason = _plan.possibly_under_shared(plan, item)
    out = [plan_reason] if plan_reason else []
    for group in item["target"]["groups"] or []:
        if prepared is not None and group in prepared:
            made = prepared[group]
            usable = bool(made.get("name"))
        else:
            made = current(state.groups.get(group))
            usable = in_use(made)
        if not usable:
            out.append(f"ArcGIS group {group} maps to no GeoLens group")
        elif made.get("members_unread"):
            out.append(
                f"the members of ArcGIS group {group} weren't read, so its GeoLens "
                f"group {made['name']} lacks them: {made['members_unread']}"
            )
        elif made.get("unsynced"):
            out.append(
                f"{len(made['unsynced'])} ArcGIS member(s) of group {group} aren't "
                f"in the existing GeoLens group {made['name']}, whose members this "
                "command leaves as they are"
            )
    return out


def _sharing(
    plan: Mapping[str, Any],
    state: MigrationState,
    prepared: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, str]]:
    return [
        {"item": item["id"], "reason": reason}
        for item in plan["items"]
        for reason in sharing_losses(plan, state, item, prepared)
    ]


def _users(
    plan: Mapping[str, Any],
    state: MigrationState,
    unresolved: Iterable[Mapping[str, str]],
    prepared: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, str]]:
    out = []
    for item in plan["items"]:
        entry = state.items.get(item["id"])
        if entry is not None and entry.owner_pending and not item.get("removed"):
            out.append({"item": item["id"], "reason": entry.owner_pending})
    out += [{"item": u["item"], "reason": u["reason"]} for u in unresolved]
    needed = groups_in_use(plan, state)
    for group_id in sorted(needed):
        recorded = current(state.groups.get(group_id))
        if not in_use(recorded):
            recorded = None
        planned = (prepared or {}).get(group_id)
        if planned is None and recorded is None:
            continue
        made = planned or recorded
        # A dry run records no group, so what this run resolved joins the
        # members an earlier run left pending.
        pending = {
            p["member"]: p
            for source in (recorded, planned)
            for p in (source or {}).get("pending") or []
        }
        for member, pending_member in pending.items():
            out.append(
                {
                    "item": f"group {group_id}",
                    "reason": f"member {member} isn't in GeoLens group "
                    f"{made['name']}: {pending_member['reason']}",
                }
            )
    return out


def inventory_changes(
    client: PortalClient | None, plan: Mapping[str, Any], now: datetime
) -> str | None:
    """Why the plan's inventory may be out of date, or None: the portal has an
    item of the organization changed after the inventory was read, other than
    one the plan skips, or the portal couldn't be asked. An item the plan
    doesn't hold counts: it is new since the inventory."""
    inventory = plan["inventory"]
    # The start, not the end: an item changed while the inventory ran may
    # have been read before the change.
    read_at = aware_time(inventory.get("started_at"))
    if read_at is None:
        return (
            "the plan's inventory records no start time by the portal's clock, so "
            "items changed while it ran can't be told apart; run inventory and "
            "plan again"
        )
    age = _age(now - read_at)
    org = (inventory.get("scope") or {}).get("org_id")
    unchecked = f"couldn't check the portal for items changed since the inventory was read {age} ago"
    if client is None or not client.token:
        return f"{unchecked}: the run has no ArcGIS credential"
    if not org:
        return f"{unchecked}: the plan records no ArcGIS organization"
    try:
        info = client.get_json("portals/self")
        own = info.get("id") if isinstance(info, dict) else None
        if own != org:
            return (
                f"{unchecked}: the run's ArcGIS account belongs to organization "
                f"{own or 'unknown'}, not the plan's organization {org}"
            )
        if not _org_admin(info):
            return (
                f"{unchecked}: the run's ArcGIS account isn't an organization "
                f"administrator ({_plan.ORG_ADMIN}), so its search can miss items "
                "not shared with it"
            )
        changed = _changed_since(client, org, read_at.timestamp() * 1000)
    except PortalError as exc:
        return f"{unchecked}: {exc}"
    if isinstance(changed, str):
        return f"{unchecked}: {changed}"
    items = plan.get("items", [])
    planned = {i["id"] for i in items if i["action"] != _plan.SKIP}
    held = {i["id"] for i in items}
    mine = [i for i in changed if i in planned]
    new = [i for i in changed if i not in held]
    found = []
    if mine:
        found.append(
            f"portal items changed after the inventory was read {age} ago "
            f"({_plan._id_list(mine)})"
        )
    if new:
        found.append(
            "portal items the plan doesn't hold were created or changed after "
            f"the inventory was read {age} ago ({_plan._id_list(new)})"
        )
    if not found:
        return None
    return "; ".join(found) + "; run inventory and plan again to include them"


def _changed_since(client: PortalClient, org: str, since: float) -> list[str] | str:
    """The ids of the organization's items modified after *since* (epoch
    milliseconds), newest first, or why the search can't tell."""
    changed: list[str] = []
    start = 1
    for _ in range(SEARCH_PAGES):
        page = client.get_json(
            "search",
            {
                "q": f"orgid:{org}",
                "sortField": "modified",
                "sortOrder": "desc",
                "num": SEARCH_PAGE,
                "start": start,
            },
        )
        results = page.get("results") if isinstance(page, dict) else None
        if not isinstance(results, list):
            return "the portal's search answered without results"
        if not results and start == 1:
            # A plan with items to migrate came from this organization, so an
            # empty search means the search didn't reach them.
            return "the portal's search found no items of the organization"
        for found in results:
            modified = found.get("modified") if isinstance(found, dict) else None
            if whole_number(modified) is None:
                return "a portal item has no usable modified time"
            if modified <= since:
                return changed
            if not isinstance(found.get("id"), str):
                return "a portal item changed since has no id"
            changed.append(found["id"])
        next_start = whole_number(page.get("nextStart"))
        if not results or next_start is None or next_start <= start:
            return changed
        start = next_start
    return f"over {SEARCH_PAGES * SEARCH_PAGE} items changed since, more than it reads"


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


def refused_before_run(
    plan: Mapping[str, Any],
    unresolved: Sequence[Mapping[str, str]],
    inventory_changed: str | None,
    accept: Iterable[str],
) -> dict[str, Any] | None:
    """The cutover's refusal for what no run can change, checked before the
    run starts: the portal changed since the inventory, or a plan owner who
    can't be resolved. None unless one of those fails unaccepted."""
    found = {
        INVENTORY: _inventory(plan, inventory_changed),
        USERS: [{"item": u["item"], "reason": u["reason"]} for u in unresolved],
    }
    checks = [{"check": name, "items": found[name]} for name in found if found[name]]
    accepted = [c["check"] for c in checks if c["check"] in accept]
    refused = [c["check"] for c in checks if c["check"] not in accept]
    if not refused:
        return None
    return {"marked": False, "refused": refused, "accepted": accepted, "checks": checks}


def failing_checks(
    plan: Mapping[str, Any],
    state: MigrationState,
    unresolved: Sequence[Mapping[str, str]] = (),
    inventory_changed: str | None = None,
    prepared_groups: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Every check that fails as of *state*, with the items it names."""
    found = {
        UNFINISHED: _unfinished(plan, state),
        INVENTORY: _inventory(plan, inventory_changed),
        ATTACHMENTS: _attachments(plan, state),
        USERS: _users(plan, state, unresolved, prepared_groups),
        SHARING: _sharing(plan, state, prepared_groups),
    }
    return [{"check": name, "items": found[name]} for name in CHECKS if found[name]]
