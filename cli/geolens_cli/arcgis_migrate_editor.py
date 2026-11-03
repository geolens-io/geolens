# SPDX-License-Identifier: Apache-2.0
"""A migration of one user's own content, run by a GeoLens editor.

Hand-maintained. When every owner in the plan is the operator, the run needs
neither the admin user list nor an ownership transfer: the items are imported
as the operator and stay theirs. What the editor's role can't do degrades and
is reported instead of refused. A public item under
``restrict_public_visibility`` becomes internal, collections are skipped
without ``manage_collections``, and an item shared only with ArcGIS groups
goes to the matching groups the editor belongs to, or becomes private. It never
becomes internal or public, which would show it to more people than the portal
did. A plan that names another owner still needs an admin.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .arcgis_migrate_groups import (
    GROUP_PAGE,
    GroupPlan,
    _find,
    _title,
    wanted_groups,
)
from .arcgis_migrate_session import GeoLens, GeoLensError
from .arcgis_migrate_state import MigrationState


def is_admin(me: Any) -> bool:
    return "admin" in (me.roles or [])


def own_content_refusal(
    me: Any, plan: Mapping[str, Any], unmapped_owner: str | None
) -> str | None:
    """Why the plan needs an admin, or None when every item it imports is
    mapped to the operator *me*."""
    from .arcgis_migrate import IMPORTING, _target_name

    names = {n.lower() for n in (me.username, me.email) if n}
    others = sorted(
        {
            name or f"(none; ArcGIS user {item['owner']})"
            for item in plan["items"]
            if item["action"] in IMPORTING
            and not item.get("removed")
            and not item.get("unlisted")
            for name in [_target_name(item, plan)]
            if name.lower() not in names
        }
    )
    if unmapped_owner and unmapped_owner.lower() not in names:
        others.append(f"--unmapped-owner {unmapped_owner}")
    if not others:
        return None
    return (
        "migrate needs a GeoLens admin session when the plan maps items to "
        f"someone other than {me.username}: it reads the user list and "
        f"transfers ownership. Owners other than {me.username}: "
        f"{', '.join(others)}. Run `geolens login` as an admin, or map every "
        f"owner to {me.username} in owner_map."
    )


def cannot_import(geolens: GeoLens) -> str | None:
    """Why the operator's role can't import, or None. An unreadable role
    matrix passes, since the server decides on every write."""
    from geolens.api.auth import me_permissions_auth_me_permissions_get as get

    try:
        granted = geolens.call(get.sync_detailed).permissions.to_dict()
    except GeoLensError:
        return None
    if granted.get("upload") is False:
        return (
            "migrate needs a GeoLens editor or admin session: this account's "
            "role can't upload. Run `geolens login` as an editor or admin."
        )
    return None


def _my_groups(geolens: GeoLens) -> list[Any]:
    from geolens.api.groups import list_my_groups_groups_mine_get as list_mine

    groups: list[Any] = []
    while True:
        page = geolens.call(list_mine.sync_detailed, skip=len(groups), limit=GROUP_PAGE)
        groups.extend(page.groups)
        if not page.groups or len(groups) >= page.total:
            return groups


def my_groups_plan(
    geolens: GeoLens,
    plan: Mapping[str, Any],
    inventory_groups: Mapping[str, Mapping[str, Any]],
    state: MigrationState,
    items: Iterable[Mapping[str, Any]],
    *,
    dry_run: bool,
) -> GroupPlan:
    """Resolve each ArcGIS group *items* are shared with to a GeoLens group
    the editor already belongs to, by ``group_map``'s ``geolens_group`` or
    else the group's title. Nothing is created or filled: an editor can do
    neither. A group with no match maps to none, which makes its items
    private."""
    out = GroupPlan()
    wanted = wanted_groups(plan, items)
    if not wanted:
        return out
    mine = _my_groups(geolens)
    for arcgis_id in wanted:
        entry = plan["group_map"].get(arcgis_id) or {}
        named = entry.get("geolens_group")
        record: dict[str, Any] = {"id": None, "name": None, "created": False}
        if named == "":
            record["unmapped"] = True
        else:
            found = _find(mine, named or _title(arcgis_id, entry, inventory_groups))
            if found is None:
                out.warnings.append(
                    f"ArcGIS group {arcgis_id} matches no GeoLens group you belong "
                    "to, so the items shared only with it become private"
                )
            else:
                record |= {
                    "id": str(found.id),
                    "name": found.name,
                    "members": {},
                    "unsynced": [],
                }
        out.groups[arcgis_id] = record
        if not dry_run:
            # A record an admin run made keeps the history that run needs to
            # recognise the group it created; this run only resolves a target.
            kept = state.groups.get(arcgis_id)
            if named == "":
                state.groups[arcgis_id] = {**(kept or record), "unmapped": True}
            elif kept:
                state.groups[arcgis_id] = {
                    k: v for k, v in kept.items() if k != "unmapped"
                }
            else:
                state.groups[arcgis_id] = dict(record)
            state.save()
    return out
