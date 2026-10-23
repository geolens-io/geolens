# SPDX-License-Identifier: Apache-2.0
"""Execute an ArcGIS migration plan: ``geolens arcgis migrate``.

Hand-maintained. Reads a plan written by ``geolens arcgis plan``, runs its
items one at a time in ``depends_on`` order, and records progress in a state
file so a rerun resumes where the last one stopped. Items are imported as
the operator, who must be a GeoLens admin, then handed to the owner the plan
maps them to through the admin ownership transfer on ``PATCH /datasets/{id}``
and ``PATCH /maps/{id}``. No credential is minted for the owners.

GeoLens is reached only through the SDK client for the configured instance;
see ``arcgis_portal`` for the portal side of the egress contract.
"""

from __future__ import annotations

import heapq
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import click
import typer

from . import arcgis_plan as _plan
from . import output as _output
from ._sdk_helpers import (
    EXIT_AUTH,
    EXIT_GENERIC,
    EXIT_NETWORK,
    EXIT_OK,
    EXIT_SERVER,
    EXIT_USAGE,
)
from .arcgis_item_metadata import apply_item_metadata
from .arcgis_migrate_collections import file_into_collections
from .arcgis_migrate_export import (
    DEFAULT_CAP_MB,
    EXPORT_DIRNAME,
    export_item,
    refresh_export,
    write_index,
)
from .arcgis_migrate_cutover import failing_checks, inventory_changes
from .arcgis_migrate_report import build_run_report, write_run_report
from .arcgis_migrate_files import FILE_TYPES, import_file
from .arcgis_migrate_layers import import_layers
from .arcgis_migrate_refresh import (
    Refresher,
    changed_in_geolens,
    get_dataset,
    record,
    record_last_update,
    refresh_file,
    refresh_layers,
)
from .arcgis_migrate_session import (
    GeoLens,
    GeoLensError,
    ItemFailed,
    ItemResult,
    MigrationContext,
    PortalAuth,
    StopRun,
)
from .arcgis_migrate_state import (
    FAILED,
    FINISHED,
    SKIPPED,
    STATE_FILENAME,
    ItemState,
    MigrationState,
    StateError,
    _now,
    release_locks,
)
from .publish import _web_origin
from .arcgis_portal import (
    PortalClient,
    PortalError,
    Redactor,
    build_opener,
    portal_root,
    read_credentials,
)

# The permission the server checks before it transfers what each action
# creates: datasets need upload, a map needs edit_metadata.
TRANSFER_PERMISSION = {
    _plan.IMPORT_LAYERS: "upload",
    _plan.IMPORT_FILE: "upload",
    _plan.IMPORT_MAP: "edit_metadata",
}
# The server's built-in grants of the two permissions; the role_permissions
# setting stores only the overrides, which the server applies on top.
DEFAULT_TRANSFER_GRANTS = {
    "viewer": {"upload": False, "edit_metadata": False},
    "editor": {"upload": True, "edit_metadata": True},
    "admin": {"upload": True, "edit_metadata": True},
}
USER_PAGE_SIZE = 200
_PORTAL_EXIT = {
    "auth": EXIT_AUTH,
    "network": EXIT_NETWORK,
    "server": EXIT_SERVER,
    "redirect": EXIT_USAGE,
}
EXIT_INTERRUPTED = 130
CUTOVER_LINES = 10
# Actions that read the inventory and, for a non-public item, the portal.
_PORTAL_ACTIONS = (_plan.IMPORT_LAYERS, _plan.IMPORT_FILE, _plan.EXPORT_ONLY)


class UsageError(Exception):
    """The plan, state or owner mapping can't be run; nothing was imported."""


Handler = Callable[[MigrationContext, Mapping[str, Any], ItemState], ItemResult]
# Action -> handler. An action without one is reported as not available in
# this version and left pending, so a later version can run it.
HANDLERS: dict[str, Handler] = {
    _plan.IMPORT_LAYERS: import_layers,
    _plan.IMPORT_FILE: import_file,
    _plan.EXPORT_ONLY: export_item,
}
# Action -> how a rerun brings a finished item of it up to date.
REFRESHERS: dict[str, Refresher] = {
    _plan.IMPORT_LAYERS: refresh_layers,
    _plan.IMPORT_FILE: refresh_file,
    _plan.EXPORT_ONLY: refresh_export,
}


@dataclass(frozen=True)
class Owner:
    id: str
    username: str


@dataclass
class MigrateOptions:
    plan_path: Path
    state_path: Path | None
    only: list[str]
    dry_run: bool
    no_retry: bool
    unmapped_owner: str | None
    token: str | None = None
    token_stdin: bool = False
    username: str | None = None
    password_stdin: bool = False
    allow_insecure_http: bool = False
    trusted_hosts: list[str] = field(default_factory=list)
    export_cap_mb: int = DEFAULT_CAP_MB
    cutover: bool = False
    # The cutover checks whose loss the operator accepts (CHECKS names).
    accept: frozenset[str] = frozenset()


def order_items(items: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """*items* with every item after the plan items it ``depends_on``.

    Ties keep plan order. A dependency missing from the plan, or marked
    removed and so never run, doesn't hold an item back. An unlisted item is
    left pending, so its own stale dependencies order nothing, while items
    that depend on it still wait for it. A cycle is a ``UsageError``.
    """
    index = {item["id"]: n for n, item in enumerate(items)}
    removed = {item["id"] for item in items if item.get("removed")}
    waiting_on = {
        item["id"]: set()
        if item.get("unlisted")
        else {
            d
            for d in item["depends_on"]
            if d in index and d != item["id"] and d not in removed
        }
        for item in items
    }
    dependents: dict[str, list[str]] = {}
    for item_id, deps in waiting_on.items():
        for dep in deps:
            dependents.setdefault(dep, []).append(item_id)
    ready = [index[i] for i, deps in waiting_on.items() if not deps]
    heapq.heapify(ready)
    ordered: list[Mapping[str, Any]] = []
    while ready:
        item = items[heapq.heappop(ready)]
        ordered.append(item)
        for dependent in dependents.get(item["id"], []):
            waiting_on[dependent].discard(item["id"])
            if not waiting_on[dependent]:
                heapq.heappush(ready, index[dependent])
    if len(ordered) < len(items):
        stuck = sorted(i for i, deps in waiting_on.items() if deps)
        raise UsageError(
            f"depends_on forms a cycle among these items: {', '.join(stuck[:10])}"
        )
    return ordered


def _wanted(
    by_id: Mapping[str, Mapping[str, Any]], only: list[str], state: MigrationState
) -> set[str]:
    """The --only items plus every unfinished plan item they depend on."""
    unknown = sorted(set(only) - set(by_id))
    if unknown:
        raise UsageError(f"--only names items not in the plan: {', '.join(unknown)}")
    removed = sorted(i for i in only if by_id[i].get("removed"))
    if removed:
        raise UsageError(
            "--only names items marked removed in the plan, which never run: "
            + ", ".join(removed)
        )
    wanted: set[str] = set()
    stack = list(only)
    while stack:
        item_id = stack.pop()
        if item_id in wanted:
            continue
        wanted.add(item_id)
        if by_id[item_id].get("removed") or by_id[item_id].get("unlisted"):
            continue
        for dep in by_id[item_id]["depends_on"]:
            if dep in by_id and state.status(dep) not in FINISHED:
                stack.append(dep)
    return wanted


def _needs_run(item: Mapping[str, Any], status: str, no_retry: bool) -> bool:
    if status in FINISHED or item.get("removed"):
        return False
    if status == FAILED and no_retry:
        return False
    return not (status == SKIPPED and item["action"] == _plan.SKIP)


def select_items(
    plan: Mapping[str, Any], state: MigrationState, only: list[str], no_retry: bool
) -> list[Mapping[str, Any]]:
    """The plan items this run executes, in order."""
    ordered = order_items(plan["items"])
    by_id = {item["id"]: item for item in ordered}
    wanted = _wanted(by_id, only, state) if only else set(by_id)
    return [
        item
        for item in ordered
        if item["id"] in wanted and _needs_run(item, state.status(item["id"]), no_retry)
    ]


def select_refresh(
    plan: Mapping[str, Any], state: MigrationState, only: list[str]
) -> list[Mapping[str, Any]]:
    """The finished plan items this run brings up to date, in plan order."""
    return [
        item
        for item in plan["items"]
        if item["action"] in REFRESHERS
        and not item.get("removed")
        and not item.get("unlisted")
        and state.status(item["id"]) in FINISHED
        and (not only or item["id"] in only)
    ]


def _target_name(item: Mapping[str, Any], plan: Mapping[str, Any]) -> str:
    """The item's owner name: ``target.owner`` unless it is null (an empty
    override stays empty), else ``owner_map``."""
    override = item["target"]["owner"]
    if override is not None:
        return override
    return plan["owner_map"].get(item["owner"], "")


def _list_users(geolens: GeoLens) -> list[Any]:
    from geolens.api.admin import list_users_admin_users_get as list_users

    users: list[Any] = []
    while True:
        page = geolens.call(
            list_users.sync_detailed, skip=len(users), limit=USER_PAGE_SIZE
        )
        users.extend(page.users)
        if not page.users or len(users) >= page.total:
            return users


def _effective(
    stored: Mapping[str, Mapping[str, bool]],
) -> dict[str, dict[str, bool]]:
    """The stored role overrides applied over the built-in grants."""
    effective = {role: dict(grants) for role, grants in DEFAULT_TRANSFER_GRANTS.items()}
    for role, grants in stored.items():
        if isinstance(grants, Mapping):
            effective.setdefault(role, {}).update(grants)
    return effective


def _role_permissions(geolens: GeoLens) -> Mapping[str, Mapping[str, bool]] | None:
    """The instance's role permissions, or None when the setting can't be read."""
    from geolens.api.admin import get_all_settings_settings_all_get as get_settings

    try:
        settings = geolens.call(get_settings.sync_detailed)
    except GeoLensError:
        return None
    for items in settings.tabs.additional_properties.values():
        for setting in items:
            if setting.key == "role_permissions" and isinstance(setting.value, dict):
                return setting.value
    return None


class _Directory:
    """GeoLens users by lower-cased username and email."""

    def __init__(
        self, users: Iterable[Any], roles: Mapping[str, Mapping[str, bool]] | None
    ) -> None:
        self._by_name: dict[str, dict[str, Any]] = {}
        for user in users:
            for name in (user.username, user.email):
                if isinstance(name, str) and name:
                    self._by_name.setdefault(name.lower(), {})[str(user.id)] = user
        self.roles = _effective(roles) if roles is not None else None

    def find(self, name: str) -> Any | None:
        """The one user *name* names, or None; ``UsageError`` when one user's
        email is another's username, since either could be meant."""
        matches = self._by_name.get(name.strip().lower(), {})
        if len(matches) > 1:
            raise UsageError(
                f"{name} matches more than one GeoLens user (one's username and "
                "another's email); name the owner by a value only one user has"
            )
        return next(iter(matches.values()), None)

    @staticmethod
    def inactive(user: Any) -> str | None:
        """Why *user* can't own anything, or None."""
        if not user.is_active or str(user.status) != "active":
            return f"{user.username} is not an active GeoLens user"
        return None

    def missing_grant(self, user: Any, permission: str) -> str | None:
        """Why the role matrix says *user* lacks *permission*, or None.

        Advisory only: a permission extension can grant it out of band, and
        the server decides on every transfer.
        """
        if self.roles is None or any(
            (self.roles.get(r) or {}).get(permission) for r in user.roles
        ):
            return None
        roles = ", ".join(user.roles) or "none"
        return f"{user.username}'s roles ({roles}) don't grant {permission}"


@dataclass
class Owners:
    by_item: dict[str, Owner]
    reassigned: list[str]
    changed: list[dict[str, str]]
    roles_checked: bool
    warnings: list[str]
    # Item -> why it goes to, or stays with, --unmapped-owner for now.
    pending: dict[str, str] = field(default_factory=dict)
    # Finished items whose plan owner doesn't name one GeoLens user.
    unresolved: list[dict[str, str]] = field(default_factory=list)
    # Finished items that wait for their owner, and who to hand some to now.
    waiting: list[str] = field(default_factory=list)
    handovers: dict[str, Owner] = field(default_factory=dict)


def _pending_reason(
    directory: _Directory, item: Mapping[str, Any], name: str, user: Any | None
) -> str | None:
    """Why *item* can't go to *user*, the GeoLens user its plan owner *name*
    names, or None."""
    if name and user is None:
        return f"{name} is not a GeoLens user yet"
    if user is None:
        return f"ArcGIS user {item['owner']} has no GeoLens owner in owner_map"
    return directory.inactive(user)


def _promotion(directory: _Directory, user: Any, permission: str) -> str | None:
    grant = directory.missing_grant(user, permission)
    if grant is None:
        return None
    return f"{grant}; promote {user.username} to editor in GeoLens to hand it over"


def resolve_owners(
    geolens: GeoLens,
    plan: Mapping[str, Any],
    to_run: list[Mapping[str, Any]],
    state: MigrationState,
    unmapped_owner: str | None,
) -> Owners:
    """The GeoLens owner of every importing item, or a ``UsageError``.

    An item whose plan owner is empty, not a GeoLens user yet, inactive or,
    when the role matrix is known, without the permission the transfer needs
    goes to *unmapped_owner* for now and is recorded as pending, so a later
    run hands it over. Without *unmapped_owner* those are refused, except a
    missing permission, which is a warning: the server has the last word, and
    a refused transfer fails only that item.
    """
    directory = _Directory(_list_users(geolens), _role_permissions(geolens))
    fallback = directory.find(unmapped_owner) if unmapped_owner else None
    problems: set[str] = set()
    if unmapped_owner and fallback is None:
        problems.add(f"--unmapped-owner {unmapped_owner} is not a GeoLens user")
    owners = Owners({}, [], [], directory.roles is not None, [])
    for item in to_run:
        permission = TRANSFER_PERMISSION.get(item["action"])
        # An unlisted item is left pending without an import, so it needs no owner.
        if permission is None or item.get("unlisted"):
            continue
        name = _target_name(item, plan)
        user = directory.find(name) if name else None
        if name and user is None and fallback is None:
            problems.add(f"{name} (owner of {item['id']}) is not a GeoLens user")
            continue
        reason = _pending_reason(directory, item, name, user)
        if reason is None and fallback is not None:
            reason = _promotion(directory, user, permission)
        if reason is not None:
            if fallback is None:
                problems.add(reason)
                continue
            fallback_reason = directory.inactive(fallback)
            if fallback_reason:
                problems.add(f"--unmapped-owner: {fallback_reason}")
                continue
            owners.reassigned.append(f"{item['id']}: {reason}")
            owners.pending[item["id"]] = reason
            user = fallback
        owners.by_item[item["id"]] = Owner(str(user.id), user.username)
        grant = directory.missing_grant(user, permission)
        if grant:
            owners.warnings.append(f"{item['id']}: {grant}")
    if problems:
        hint = "" if unmapped_owner else " Fix owner_map, or pass --unmapped-owner."
        raise UsageError(
            "can't assign owners: " + "; ".join(sorted(problems)) + "." + hint
        )
    _finished_owners(directory, plan, to_run, state, fallback, owners)
    return owners


def _finished_owners(
    directory: _Directory,
    plan: Mapping[str, Any],
    to_run: list[Mapping[str, Any]],
    state: MigrationState,
    fallback: Any | None,
    owners: Owners,
) -> None:
    """Sort the migrated items this run doesn't import by how their owner
    stands: a pending one to hand over, one whose plan now names another or
    no single GeoLens user."""
    running = {item["id"] for item in to_run}
    for item in plan["items"]:
        entry = state.items.get(item["id"])
        permission = TRANSFER_PERMISSION.get(item["action"])
        if (
            item["id"] in running
            or item.get("removed")
            or permission is None
            or entry is None
            or entry.status not in FINISHED
            or not entry.owner_id
        ):
            continue
        name = _target_name(item, plan)
        try:
            user = directory.find(name) if name else None
        except UsageError as exc:
            owners.unresolved.append({"item": item["id"], "reason": str(exc)})
            continue
        if entry.owner_pending:
            owners.waiting.append(item["id"])
            reason = _pending_reason(directory, item, name, user) or _promotion(
                directory, user, permission
            )
            target = user if reason is None else fallback
            if reason is not None:
                owners.pending[item["id"]] = reason
            if (
                target is not None
                and directory.inactive(target) is None
                and str(target.id) != entry.owner_id
            ):
                owners.handovers[item["id"]] = Owner(str(target.id), target.username)
        elif user is None:
            owners.unresolved.append(
                {
                    "item": item["id"],
                    "reason": f"its plan owner {name} is not a GeoLens user"
                    if name
                    else "its plan owner is empty",
                }
            )
        elif str(user.id) != entry.owner_id:
            owners.changed.append({"item": item["id"], "owner": user.username})


def _require_admin(geolens: GeoLens) -> str:
    """The admin operator's user id; ``UsageError`` for anyone else."""
    from geolens.api.auth import me_auth_me_get

    me = geolens.call(me_auth_me_get.sync_detailed)
    if "admin" not in (me.roles or []):
        raise UsageError(
            "migrate needs a GeoLens admin session: it reads the user list and "
            "transfers ownership. Run `geolens login` as an admin."
        )
    return str(me.id)


def _check_cutover(opts: MigrateOptions) -> None:
    if opts.accept and not opts.cutover:
        raise UsageError("the --accept-* options go with --cutover")
    if opts.cutover and opts.only:
        raise UsageError("--cutover is the final run of the whole plan; drop --only")


def mark_cutover(
    opts: MigrateOptions,
    plan: Mapping[str, Any],
    state: MigrationState,
    owners: Owners,
    summary: RunSummary,
    portal: PortalClient | None = None,
) -> dict[str, Any] | None:
    """With --cutover, the checks that fail and whether the run is marked as
    the final one: only when it finished and every failing check is accepted.
    Outside a dry run the portal is asked whether anything changed since the
    plan's inventory was read."""
    if not opts.cutover:
        return None
    changed = (
        None if opts.dry_run else inventory_changes(portal, plan, datetime.now(tz=UTC))
    )
    failing = failing_checks(plan, state, owners.unresolved, changed)
    accepted = [c["check"] for c in failing if c["check"] in opts.accept]
    refused = [c["check"] for c in failing if c["check"] not in opts.accept]
    marked = not refused and summary.stopped is None and not opts.dry_run
    if marked:
        state.cutover = {"at": _now(), "accepted": accepted}
        state.save()
    return {
        "marked": marked,
        "refused": refused,
        "accepted": accepted,
        "checks": failing,
    }


def transfer_dataset(geolens: GeoLens, dataset_id: str, owner: Owner) -> Any:
    """Hand one dataset to *owner*; the dataset as the transfer left it."""
    from geolens.api.datasets import (
        update_dataset_metadata_datasets_dataset_id_patch as patch_dataset,
    )
    from geolens.models.dataset_meta import DatasetMeta

    return geolens.call(
        patch_dataset.sync_detailed,
        dataset_id=UUID(dataset_id),
        body=DatasetMeta(owner_id=UUID(owner.id)),
    )


def _transfer_map(geolens: GeoLens, map_id: str, owner: Owner) -> None:
    from geolens.api.maps import patch_map_endpoint_maps_map_id_patch as patch_map
    from geolens.models.map_patch import MapPatch

    geolens.call(
        patch_map.sync_detailed,
        map_id=UUID(map_id),
        body=MapPatch(owner_id=UUID(owner.id)),
    )


def transfer(geolens: GeoLens, entry: ItemState, owner: Owner) -> None:
    """Hand every dataset and the map recorded for an item to *owner*."""
    for dataset_id in entry.dataset_ids:
        transfer_dataset(geolens, dataset_id, owner)
    if entry.map_id:
        _transfer_map(geolens, entry.map_id, owner)


@dataclass
class RunSummary:
    unavailable: list[str] = field(default_factory=list)
    unlisted: list[str] = field(default_factory=list)
    waiting: list[dict[str, Any]] = field(default_factory=list)
    stopped: str | None = None
    # Finished items this run brought up to date, or meant to.
    refreshed: list[str] = field(default_factory=list)
    handed_over: list[dict[str, str]] = field(default_factory=list)
    handover_failed: list[str] = field(default_factory=list)


def _unmet(
    item: Mapping[str, Any], by_id: Mapping[str, Any], state: MigrationState
) -> list[str]:
    # A removed dependency never runs, so like a missing one it holds nothing back.
    return [
        dep
        for dep in item["depends_on"]
        if dep in by_id
        and dep != item["id"]
        and not by_id[dep].get("removed")
        and state.status(dep) not in (*FINISHED, SKIPPED)
    ]


def _migrate_one(
    ctx: MigrationContext,
    state: MigrationState,
    item: Mapping[str, Any],
    handler: Handler,
    owner: Owner | None,
    pending: str | None = None,
) -> None:
    entry = state.start(item["id"])
    try:
        result = handler(ctx, item, entry)
        entry.notes = [state.clean(note) for note in result.notes]
        state.save()
        if owner is not None:
            entry.visibility = dict.fromkeys(
                entry.dataset_ids, item["target"]["visibility"]
            )
            apply_item_metadata(ctx, item, entry)
            entry.notes.extend(
                state.clean(n) for n in file_into_collections(ctx, item, entry)
            )
            # Even to the operator: a run that failed part way may have handed
            # some of the item's objects to another owner already.
            transfer(ctx.geolens, entry, owner)
            entry.owner_id = owner.id
            entry.owner_pending = pending
            record_last_update(ctx, entry, entry.dataset_ids)
    except (ItemFailed, GeoLensError) as exc:
        state.finish(item["id"], FAILED, str(exc))
        return
    except StopRun as exc:
        state.finish(item["id"], FAILED, str(exc))
        raise
    except KeyboardInterrupt:
        state.finish(item["id"], FAILED, "interrupted")
        raise
    except typer.Exit:
        state.finish(item["id"], FAILED, "stopped by a failed request")
        raise
    state.finish(item["id"], result.status)


def _hand_over_one(ctx: MigrationContext, entry: ItemState, owner: Owner) -> None:
    """Transfer the item to *owner* one dataset at a time.

    A dataset *owner* already has, given by an earlier run that stopped part
    way or by someone in GeoLens, is left as it is. Each transfer is recorded
    as this command's own write, so a rerun resumes with the rest.
    """
    for dataset_id in entry.dataset_ids:
        dataset = get_dataset(ctx, dataset_id)
        if str(dataset.created_by) == owner.id:
            continue
        reason = changed_in_geolens(ctx, entry, dataset_id, dataset)
        if reason:
            raise ItemFailed(f"dataset {dataset_id} was {reason}")
        record(entry, dataset_id, transfer_dataset(ctx.geolens, dataset_id, owner))
        ctx.save()
    if entry.map_id:
        _transfer_map(ctx.geolens, entry.map_id, owner)
    entry.owner_id = owner.id


def hand_over(
    ctx: MigrationContext, state: MigrationState, owners: Owners, summary: RunSummary
) -> None:
    """Hand each migrated item that waits for its owner to the owner it can go
    to now, unless GeoLens changed one of its datasets since the last run."""
    for item_id in owners.waiting:
        entry = state.items[item_id]
        owner = owners.handovers.get(item_id)
        if owner is not None:
            try:
                _hand_over_one(ctx, entry, owner)
            except (ItemFailed, GeoLensError) as exc:
                summary.handover_failed.append(
                    state.clean(f"{item_id}: not handed to {owner.username}, {exc}")
                )
                continue
            summary.handed_over.append({"item": item_id, "owner": owner.username})
        elif entry.owner_pending == owners.pending.get(item_id):
            continue
        entry.owner_pending = owners.pending.get(item_id)
        state.save()


def refresh_finished(
    ctx: MigrationContext,
    state: MigrationState,
    items: Sequence[Mapping[str, Any]],
    summary: RunSummary,
) -> None:
    """Bring each finished item up to date and record why any isn't."""
    for item in items:
        entry = state.items[item["id"]]
        summary.refreshed.append(item["id"])
        try:
            reasons = REFRESHERS[item["action"]](ctx, item, entry)
        except StopRun as exc:
            entry.stale = [state.clean(str(exc))]
            summary.stopped = entry.stale[0]
            break
        entry.stale = [state.clean(reason) for reason in reasons]
        state.save()


def run_items(
    ctx: MigrationContext,
    plan: Mapping[str, Any],
    state: MigrationState,
    to_run: list[Mapping[str, Any]],
    owners: Mapping[str, Owner],
    refresh: Sequence[Mapping[str, Any]] = (),
    pending: Mapping[str, str] | None = None,
    summary: RunSummary | None = None,
) -> RunSummary:
    """Run the items to import, then bring the finished *refresh* items up to
    date unless the run stopped."""
    by_id = {item["id"]: item for item in plan["items"]}
    summary = summary or RunSummary()
    for item in to_run:
        if item["action"] == _plan.SKIP:
            state.finish(item["id"], SKIPPED, save=False)
            continue
        if item.get("unlisted"):
            summary.unlisted.append(item["id"])
            continue
        handler = HANDLERS.get(item["action"])
        if handler is None:
            summary.unavailable.append(item["id"])
            continue
        unmet = _unmet(item, by_id, state)
        if unmet:
            summary.waiting.append({"item": item["id"], "waiting_on": unmet})
            continue
        try:
            _migrate_one(
                ctx,
                state,
                item,
                handler,
                owners.get(item["id"]),
                (pending or {}).get(item["id"]),
            )
        except StopRun:
            summary.stopped = state.item(item["id"]).error
            break
    if summary.stopped is None:
        refresh_finished(ctx, state, refresh, summary)
    state.save()
    write_index(ctx, plan, state)
    return summary


def _report_files(
    state: MigrationState,
    plan: Mapping[str, Any],
    owners: Owners,
    redact: Redactor,
    stopped: str | None,
    cutover: Mapping[str, Any] | None = None,
) -> tuple[Path, Path]:
    return write_run_report(
        state.path.parent,
        build_run_report(
            plan,
            state,
            runnable=HANDLERS,
            owner_changes=owners.changed,
            owner_unresolved=owners.unresolved,
            stopped=stopped,
            cutover=cutover,
        ),
        redact,
    )


def _report(
    fmt: _output.Formatter,
    opts: MigrateOptions,
    plan: Mapping[str, Any],
    state: MigrationState,
    to_run: list[Mapping[str, Any]],
    owners: Owners,
    summary: RunSummary,
    redact: Redactor,
    cutover: Mapping[str, Any] | None = None,
) -> int:
    rows = [
        {
            "id": item["id"],
            "title": item["title"],
            "action": item["action"],
            "status": state.status(item["id"]),
            "owner": owners.by_item[item["id"]].username
            if item["id"] in owners.by_item
            else None,
            "notes": list(state.items[item["id"]].notes)
            if item["id"] in state.items
            else [],
            "error": state.items[item["id"]].error
            if item["id"] in state.items
            else None,
        }
        for item in to_run
    ]
    counts = Counter(entry.status for entry in state.items.values())
    # Every failed item of the plan counts, also one this run left out
    # (--no-retry, --only), so the exit code agrees with the report.
    failed = [
        item["id"] for item in plan["items"] if state.status(item["id"]) == FAILED
    ]
    stale = {
        item_id: list(state.items[item_id].stale)
        for item_id in summary.refreshed
        if state.items[item_id].stale
    }
    ran = {item["id"] for item in to_run}
    report_files: tuple[Path, Path] | None = None
    report_failed = False
    if not opts.dry_run:
        try:
            report_files = _report_files(
                state, plan, owners, redact, summary.stopped, cutover
            )
        except OSError as exc:
            report_failed = True
            fmt.error(f"couldn't write the report: {exc.strerror or exc}")
    payload = {
        "plan": str(opts.plan_path),
        "state": None if opts.dry_run else str(state.path),
        "dry_run": opts.dry_run,
        "items": rows,
        "counts": dict(sorted(counts.items())),
        "owner_reassigned": owners.reassigned,
        "owner_changed": owners.changed,
        "owner_pending": owners.pending,
        "owner_unresolved": owners.unresolved,
        "owner_roles_checked": owners.roles_checked,
        "owner_warnings": owners.warnings,
        "handed_over": summary.handed_over,
        "handover_failed": summary.handover_failed,
        "not_available": summary.unavailable,
        "unlisted": summary.unlisted,
        "waiting": summary.waiting,
        "refreshed": summary.refreshed,
        "not_up_to_date": stale,
        "stopped": summary.stopped,
        "cutover": cutover,
        "report": [str(p) for p in report_files] if report_files else None,
        "failed": failed,
    }
    if fmt.json_mode:
        fmt.json(payload)
    else:
        verb = "Would run" if opts.dry_run else "Ran"
        fmt.info(f"{verb} {len(rows)} item(s).")
        for row in rows:
            owner = f" as {row['owner']}" if row["owner"] else ""
            fmt.info(f"  {row['id']} {row['action']}{owner}: {row['status']}")
            for note in row["notes"]:
                fmt.info(f"    {note}")
            if row["error"]:
                # An error, not a warning: --quiet must not hide a failed item.
                fmt.error(f"{row['id']}: {row['error']}")
        for item_id in failed:
            if item_id not in ran:
                # Failed before, left out of this run: the exit code counts it.
                fmt.error(f"{item_id}: {state.item(item_id).error or 'failed'}")
        _print_owners(fmt, owners, summary)
        verb = "Would bring" if opts.dry_run else "Brought"
        fmt.info(f"{verb} {len(summary.refreshed)} migrated item(s) up to date.")
        for item_id, reasons in stale.items():
            for reason in reasons:
                fmt.error(f"{item_id} is not up to date: {reason}")
        if summary.unavailable:
            fmt.warn(
                f"{len(summary.unavailable)} item(s) use an action this version "
                "can't run yet and were left pending."
            )
        if summary.unlisted:
            fmt.warn(
                f"{len(summary.unlisted)} item(s) are missing from the inventory the "
                "plan was last merged from and were left pending; merge a complete "
                "inventory to run them: " + ", ".join(summary.unlisted[:5])
            )
        for wait in summary.waiting:
            fmt.warn(f"{wait['item']} waits on {', '.join(wait['waiting_on'])}")
        if summary.stopped:
            fmt.error(f"stopped: {summary.stopped}")
        _print_cutover(fmt, cutover, opts.dry_run)
        if state.cutover and not opts.cutover:
            fmt.warn(f"this migration was cut over at {state.cutover['at']}")
        if not opts.dry_run:
            fmt.info(f"State: {state.path}")
            if report_files:
                fmt.info(f"Report: {report_files[1]}")
            if failed:
                fmt.error(
                    f"{len(failed)} item(s) failed; see {report_files[1] if report_files else state.path}"
                )
    left = (
        summary.unavailable
        or summary.unlisted
        or summary.waiting
        or summary.stopped
        or stale
        or summary.handover_failed
        or (cutover is not None and cutover["refused"])
    )
    return EXIT_GENERIC if failed or left or report_failed else EXIT_OK


def _print_owners(fmt: _output.Formatter, owners: Owners, summary: RunSummary) -> None:
    for line in owners.reassigned:
        fmt.warn(f"owner fell back to --unmapped-owner for {line}")
    for line in owners.warnings:
        fmt.warn(f"{line}; GeoLens may refuse the transfer")
    for change in owners.changed:
        fmt.warn(
            f"{change['item']} was migrated before its owner changed to "
            f"{change['owner']}; it was not imported again. Transfer it by hand."
        )
    for unresolved in owners.unresolved:
        fmt.warn(f"{unresolved['item']}: {unresolved['reason']}")
    for handed in summary.handed_over:
        fmt.info(f"{handed['item']} handed to {handed['owner']}")
    for line in summary.handover_failed:
        fmt.error(line)
    for item_id, reason in owners.pending.items():
        if item_id not in owners.by_item:
            fmt.warn(f"{item_id} still waits for its owner: {reason}")
    if not owners.roles_checked:
        fmt.warn(
            "the instance's role permissions couldn't be read, so owners were "
            "checked for an active account only"
        )


def _print_cutover(
    fmt: _output.Formatter, cutover: Mapping[str, Any] | None, dry_run: bool
) -> None:
    if cutover is None:
        return
    for check in cutover["checks"]:
        accepted = check["check"] in cutover["accepted"]
        say = fmt.warn if accepted else fmt.error
        for found in check["items"][:CUTOVER_LINES]:
            say(f"{check['check']}: {found['item']}: {found['reason']}")
        more = len(check["items"]) - CUTOVER_LINES
        if more > 0:
            say(f"{check['check']}: {more} more; see the report")
    if cutover["refused"]:
        flags = " ".join(f"--accept-{name}" for name in cutover["refused"])
        fmt.error(
            "cutover refused: fix what is listed and run again, or accept the "
            f"loss with {flags}"
        )
    elif cutover["marked"]:
        fmt.success("cutover marked: this run is the migration's final one")
    elif dry_run:
        fmt.info("cutover checks pass as the state stands")


def run_cli(
    fmt: _output.Formatter,
    opts: MigrateOptions,
    *,
    sdk_factory: Callable[[], Any],
    instance: str,
) -> int:
    """Run ``geolens arcgis migrate`` and return its exit code."""
    redact = Redactor()
    try:
        return _run(fmt, opts, redact, sdk_factory, instance)
    except (typer.Exit, click.ClickException):
        raise
    except (
        Exception
    ) as exc:  # broad: last guard so a traceback can't print a credential
        fmt.error(redact(f"unexpected error: {type(exc).__name__}: {exc}"))
        return EXIT_GENERIC
    finally:
        release_locks()


def _inventory_rows(
    plan: Mapping[str, Any], plan_path: Path, to_run: list[Mapping[str, Any]]
) -> tuple[dict[str, Mapping[str, Any]], Mapping[str, Any] | None]:
    """Inventory rows by item id and the inventory's portal record, read only
    when an item imports a service.

    Refuses an inventory from another portal or ArcGIS organization than the
    plan's (the plan's portal receives the password, and the inventory's
    decides where the token may go), and an inventory rewritten since the plan
    was built, whose URLs and sharing the operator hasn't reviewed.
    """
    if not any(item["action"] in _PORTAL_ACTIONS for item in to_run):
        return {}, None
    inventory = _plan.load_inventory(plan_path.parent / plan["inventory"]["path"])
    try:
        same = portal_root(inventory["portal"]["url"], True) == portal_root(
            plan["portal"]["url"], True
        )
    except ValueError:
        same = False
    if not same:
        raise UsageError(
            "the plan's portal.url doesn't match the portal of the inventory it "
            f"names ({inventory['portal']['url']}); rebuild the plan from that inventory"
        )
    other = _plan.other_organization(plan, inventory)
    if other is not None:
        raise UsageError(
            f"the inventory the plan names is of ArcGIS organization {other}, "
            "not the plan's; rebuild the plan from that inventory"
        )
    if inventory["generated_at"] != plan["inventory"]["generated_at"]:
        raise UsageError(
            "the inventory the plan names was written at "
            f"{inventory['generated_at']}, not {plan['inventory']['generated_at']} "
            "when the plan was built; rebuild the plan and review it again"
        )
    return {row["id"]: row for row in inventory["items"]}, inventory["portal"]


def _resumes_without_download(entry: ItemState | None) -> bool:
    """Whether an unfinished data file's state already holds what its import
    continues from (a pending upload, a committed job, a fan-out or a dataset),
    so the rerun does not download it from the portal. A finished one is
    downloaded again to bring it up to date."""
    return (
        entry is not None
        and entry.status not in FINISHED
        and bool(
            entry.layer_datasets
            or entry.layer_jobs
            or entry.fan_out
            or entry.pending_upload
        )
    )


def _portal_client(
    opts: MigrateOptions,
    plan: Mapping[str, Any],
    to_run: list[Mapping[str, Any]],
    rows: Mapping[str, Mapping[str, Any]],
    state: MigrationState,
    redact: Redactor,
) -> tuple[PortalClient, str | None] | None:
    """A client for the plan's portal holding the run's token or password.

    None when no item to import or bring up to date needs one; a
    ``UsageError`` when one does and no credential was given.
    """
    wanted = [
        i
        for i in to_run
        if i["action"] in _PORTAL_ACTIONS
        and i["id"] in rows
        and (i["action"] != _plan.IMPORT_FILE or i["type"] in FILE_TYPES)
    ]
    # A private file that resumes without a download needs no credential; if
    # its job turns out to be gone, the item says to rerun with one.
    private = sum(
        1
        for item in wanted
        if (rows[item["id"]].get("sharing") or {}).get("access") != "public"
        and not (
            item["action"] == _plan.IMPORT_FILE
            and _resumes_without_download(state.items.get(item["id"]))
        )
    )
    files = any(i["action"] != _plan.IMPORT_LAYERS for i in wanted)
    supplied = bool(opts.token or opts.token_stdin or opts.username)
    # The cutover searches the organization, which takes a credential.
    if not private and not ((files or opts.cutover) and supplied):
        # A public data file is still downloaded from the portal, anonymously
        # unless the operator gave a credential (a portal can require one for
        # public sharing).
        if files:
            try:
                root = portal_root(
                    plan["portal"]["url"],
                    opts.allow_insecure_http,
                    label="the plan's portal.url",
                )
            except ValueError as exc:
                raise UsageError(str(exc)) from None
            return PortalClient(root, opener=build_opener(), redact=redact), None
        return None
    try:
        token, password = read_credentials(
            opts.token, opts.token_stdin, opts.username, opts.password_stdin
        )
        if token is None and password is None:
            raise UsageError(
                f"{private} item(s) to import or bring up to date are not public: pass --token, "
                "ARCGIS_TOKEN, --token-stdin or --username"
            )
        root = portal_root(
            plan["portal"]["url"],
            opts.allow_insecure_http,
            label="the plan's portal.url",
        )
    except ValueError as exc:
        raise UsageError(str(exc)) from None
    redact.add(token)
    redact.add(password)
    return PortalClient(
        root, opener=build_opener(), redact=redact, token=token
    ), password


def _check_hosts(hosts: list[str]) -> None:
    for host in hosts:
        if not host.strip() or any(c in host for c in "/:@"):
            raise UsageError(
                f"--trust-service-host takes a bare host name, not {host!r}"
            )


def _portal_base(url: str) -> str:
    """The portal root story links start from, without a ``/home`` or
    ``/sharing/rest`` tail."""
    try:
        return portal_root(url, True)
    except ValueError:
        return url.rstrip("/")


def _run(
    fmt: _output.Formatter,
    opts: MigrateOptions,
    redact: Redactor,
    sdk_factory: Callable[[], Any],
    instance: str,
) -> int:
    try:
        _check_hosts(opts.trusted_hosts)
        _check_cutover(opts)
        plan = _plan.load_plan(opts.plan_path)
        state_path = opts.state_path or opts.plan_path.parent / STATE_FILENAME
        state = MigrationState.load(
            state_path,
            plan["portal"]["url"],
            instance,
            redact,
            persist=not opts.dry_run,
        )
        to_run = select_items(plan, state, opts.only, opts.no_retry)
        refresh = select_refresh(plan, state, opts.only)
        touched = [*to_run, *refresh]
        rows, portal_info = _inventory_rows(plan, opts.plan_path, touched)
        portal = (
            None
            if opts.dry_run
            else _portal_client(opts, plan, touched, rows, state, redact)
        )
    except (_plan.PlanError, StateError, UsageError) as exc:
        fmt.error(str(exc))
        return EXIT_USAGE

    sdk = sdk_factory()
    geolens = GeoLens(sdk, instance, redact)
    try:
        operator_id = _require_admin(geolens)
        owners = resolve_owners(geolens, plan, to_run, state, opts.unmapped_owner)
    except UsageError as exc:
        fmt.error(str(exc))
        return EXIT_USAGE
    except GeoLensError as exc:
        fmt.error(redact(f"can't check the GeoLens session and users: {exc}"))
        if exc.status in (401, 403):
            return EXIT_AUTH
        return EXIT_SERVER if exc.status >= 500 else EXIT_GENERIC

    if opts.dry_run:
        summary = RunSummary(
            unavailable=[
                item["id"]
                for item in to_run
                if item["action"] != _plan.SKIP
                and not item.get("unlisted")
                and item["action"] not in HANDLERS
            ],
            unlisted=[
                item["id"]
                for item in to_run
                if item["action"] != _plan.SKIP and item.get("unlisted")
            ],
            refreshed=[item["id"] for item in refresh],
        )
        return _report(
            fmt,
            opts,
            plan,
            state,
            to_run,
            owners,
            summary,
            redact,
            mark_cutover(opts, plan, state, owners, summary),
        )
    auth = None
    if portal is not None:
        client, password = portal
        try:
            if password is not None and opts.username:
                client.generate_token(opts.username, password)
        except PortalError as exc:
            fmt.error(str(exc))
            return _PORTAL_EXIT.get(exc.kind, EXIT_GENERIC)
        auth = PortalAuth(client, renewable=password is not None)
    ctx = MigrationContext(
        geolens=geolens,
        inventory=rows,
        portal=auth,
        save=state.save,
        portal_info=portal_info,
        trusted_hosts=frozenset(h.strip().lower() for h in opts.trusted_hosts),
        collection_from=plan["defaults"]["collection_from"],
        collections=state.collections,
        items=state.items,
        export_dir=state.path.parent / EXPORT_DIRNAME,
        export_cap=opts.export_cap_mb * 1024 * 1024,
        web_origin=_web_origin(instance),
        portal_root=_portal_base(plan["portal"]["url"]),
        redact=redact,
        operator_id=operator_id,
    )
    # Any way out of the loop but a normal return leaves the report to the
    # finally block, so it is never stale.
    stopped: str | None = "stopped by an unexpected error"
    try:
        summary = RunSummary()
        hand_over(ctx, state, owners, summary)
        run_items(
            ctx, plan, state, to_run, owners.by_item, refresh, owners.pending, summary
        )
        stopped = None
    except KeyboardInterrupt:
        stopped = "interrupted"
        fmt.error(
            f"interrupted; rerun with the same state file ({state.path}) to resume"
        )
        return EXIT_INTERRUPTED
    except typer.Exit:
        stopped = "stopped by a failed request"
        raise
    finally:
        if stopped is not None:
            try:
                state.save()
                _json_path, md_path = _report_files(
                    state, plan, owners, redact, stopped
                )
                fmt.info(f"Report: {md_path}")
            except OSError as exc:
                # Not allowed to replace the exit outcome this run is leaving by.
                fmt.warn(f"couldn't write the report: {exc.strerror or exc}")
    return _report(
        fmt,
        opts,
        plan,
        state,
        to_run,
        owners,
        summary,
        redact,
        mark_cutover(opts, plan, state, owners, summary, auth.client if auth else None),
    )
