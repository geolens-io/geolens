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
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import click
import typer

from . import arcgis_plan as _plan
from . import output as _output
from ._sdk_helpers import EXIT_AUTH, EXIT_GENERIC, EXIT_OK, EXIT_SERVER, EXIT_USAGE
from .arcgis_migrate_layers import import_layers
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
    release_locks,
)
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
EXIT_INTERRUPTED = 130


class UsageError(Exception):
    """The plan, state or owner mapping can't be run; nothing was imported."""


Handler = Callable[[MigrationContext, Mapping[str, Any], ItemState], ItemResult]
# Action -> handler. An action without one is reported as not available in
# this version and left pending, so a later version can run it.
HANDLERS: dict[str, Handler] = {_plan.IMPORT_LAYERS: import_layers}


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


def order_items(items: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """*items* with every item after the plan items it ``depends_on``.

    Ties keep plan order. A dependency missing from the plan doesn't hold an
    item back; a cycle is a ``UsageError``.
    """
    index = {item["id"]: n for n, item in enumerate(items)}
    waiting_on = {
        item["id"]: {d for d in item["depends_on"] if d in index and d != item["id"]}
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
    wanted: set[str] = set()
    stack = list(only)
    while stack:
        item_id = stack.pop()
        if item_id in wanted:
            continue
        wanted.add(item_id)
        for dep in by_id[item_id]["depends_on"]:
            if dep in by_id and state.status(dep) not in FINISHED:
                stack.append(dep)
    return wanted


def _needs_run(item: Mapping[str, Any], status: str, no_retry: bool) -> bool:
    if status in FINISHED:
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


def resolve_owners(
    geolens: GeoLens,
    plan: Mapping[str, Any],
    to_run: list[Mapping[str, Any]],
    state: MigrationState,
    unmapped_owner: str | None,
) -> Owners:
    """The GeoLens owner of every importing item, or a ``UsageError``.

    An empty mapping or an inactive owner falls back to *unmapped_owner* when
    it is given. A name that matches no GeoLens user is always refused, since
    it is most likely a typo. An owner whose roles don't grant the permission
    the transfer needs is kept with a warning: the server has the last word,
    and a refused transfer fails only that item.
    """
    directory = _Directory(_list_users(geolens), _role_permissions(geolens))
    fallback = directory.find(unmapped_owner) if unmapped_owner else None
    problems: set[str] = set()
    if unmapped_owner and fallback is None:
        problems.add(f"--unmapped-owner {unmapped_owner} is not a GeoLens user")

    by_item: dict[str, Owner] = {}
    reassigned: list[str] = []
    warnings: list[str] = []
    for item in to_run:
        permission = TRANSFER_PERMISSION.get(item["action"])
        if permission is None:
            continue
        name = _target_name(item, plan)
        user = directory.find(name) if name else None
        if name and user is None:
            problems.add(f"{name} (owner of {item['id']}) is not a GeoLens user")
            continue
        if user is None:
            reason = f"ArcGIS user {item['owner']} has no GeoLens owner in owner_map"
        else:
            reason = directory.inactive(user)
        if reason is not None:
            if fallback is None:
                problems.add(reason)
                continue
            fallback_reason = directory.inactive(fallback)
            if fallback_reason:
                problems.add(f"--unmapped-owner: {fallback_reason}")
                continue
            reassigned.append(f"{item['id']}: {reason}")
            user = fallback
        by_item[item["id"]] = Owner(str(user.id), user.username)
        grant = directory.missing_grant(user, permission)
        if grant:
            warnings.append(f"{item['id']}: {grant}")
    if problems:
        hint = "" if unmapped_owner else " Fix owner_map, or pass --unmapped-owner."
        raise UsageError(
            "can't assign owners: " + "; ".join(sorted(problems)) + "." + hint
        )
    changed = _changed_owners(directory, plan, to_run, state)
    return Owners(by_item, reassigned, changed, directory.roles is not None, warnings)


def _changed_owners(
    directory: _Directory,
    plan: Mapping[str, Any],
    to_run: list[Mapping[str, Any]],
    state: MigrationState,
) -> list[dict[str, str]]:
    """Migrated items whose plan now names a different owner."""
    running = {item["id"] for item in to_run}
    changed = []
    for item in plan["items"]:
        entry = state.items.get(item["id"])
        if item["id"] in running or entry is None or entry.status not in FINISHED:
            continue
        try:
            user = directory.find(_target_name(item, plan))
        except UsageError:
            continue
        if user is not None and entry.owner_id and str(user.id) != entry.owner_id:
            changed.append({"item": item["id"], "owner": user.username})
    return changed


def _require_admin(geolens: GeoLens) -> None:
    from geolens.api.auth import me_auth_me_get

    me = geolens.call(me_auth_me_get.sync_detailed)
    if "admin" not in (me.roles or []):
        raise UsageError(
            "migrate needs a GeoLens admin session: it reads the user list and "
            "transfers ownership. Run `geolens login` as an admin."
        )


def transfer(geolens: GeoLens, entry: ItemState, owner: Owner) -> None:
    """Hand every dataset and the map recorded for an item to *owner*."""
    from uuid import UUID

    from geolens.api.datasets import (
        update_dataset_metadata_datasets_dataset_id_patch as patch_dataset,
    )
    from geolens.api.maps import patch_map_endpoint_maps_map_id_patch as patch_map
    from geolens.models.dataset_meta import DatasetMeta
    from geolens.models.map_patch import MapPatch

    owner_id = UUID(owner.id)
    for dataset_id in entry.dataset_ids:
        geolens.call(
            patch_dataset.sync_detailed,
            dataset_id=UUID(dataset_id),
            body=DatasetMeta(owner_id=owner_id),
        )
    if entry.map_id:
        geolens.call(
            patch_map.sync_detailed,
            map_id=UUID(entry.map_id),
            body=MapPatch(owner_id=owner_id),
        )


@dataclass
class RunSummary:
    unavailable: list[str] = field(default_factory=list)
    waiting: list[dict[str, Any]] = field(default_factory=list)
    stopped: str | None = None


def _unmet(
    item: Mapping[str, Any], by_id: Mapping[str, Any], state: MigrationState
) -> list[str]:
    return [
        dep
        for dep in item["depends_on"]
        if dep in by_id
        and dep != item["id"]
        and state.status(dep) not in (*FINISHED, SKIPPED)
    ]


def _migrate_one(
    ctx: MigrationContext,
    state: MigrationState,
    item: Mapping[str, Any],
    handler: Handler,
    owner: Owner,
) -> None:
    entry = state.start(item["id"])
    try:
        result = handler(ctx, item, entry)
        entry.notes = result.notes
        state.save()
        # Even to the operator: a run that failed part way may have handed
        # some of the item's objects to another owner already.
        transfer(ctx.geolens, entry, owner)
        entry.owner_id = owner.id
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


def run_items(
    ctx: MigrationContext,
    plan: Mapping[str, Any],
    state: MigrationState,
    to_run: list[Mapping[str, Any]],
    owners: Mapping[str, Owner],
) -> RunSummary:
    by_id = {item["id"]: item for item in plan["items"]}
    summary = RunSummary()
    for item in to_run:
        if item["action"] == _plan.SKIP:
            state.finish(item["id"], SKIPPED, save=False)
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
            _migrate_one(ctx, state, item, handler, owners[item["id"]])
        except StopRun:
            summary.stopped = state.item(item["id"]).error
            break
    state.save()
    return summary


def _report(
    fmt: _output.Formatter,
    opts: MigrateOptions,
    state: MigrationState,
    to_run: list[Mapping[str, Any]],
    owners: Owners,
    summary: RunSummary,
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
        }
        for item in to_run
    ]
    counts = Counter(entry.status for entry in state.items.values())
    failed = [r["id"] for r in rows if r["status"] == FAILED]
    payload = {
        "plan": str(opts.plan_path),
        "state": None if opts.dry_run else str(state.path),
        "dry_run": opts.dry_run,
        "items": rows,
        "counts": dict(sorted(counts.items())),
        "owner_reassigned": owners.reassigned,
        "owner_changed": owners.changed,
        "owner_roles_checked": owners.roles_checked,
        "owner_warnings": owners.warnings,
        "not_available": summary.unavailable,
        "waiting": summary.waiting,
        "stopped": summary.stopped,
    }
    if fmt.json_mode:
        fmt.json(payload)
    else:
        verb = "Would run" if opts.dry_run else "Ran"
        fmt.info(f"{verb} {len(rows)} item(s).")
        for row in rows:
            owner = f" as {row['owner']}" if row["owner"] else ""
            fmt.info(f"  {row['id']} {row['action']}{owner}: {row['status']}")
        for line in owners.reassigned:
            fmt.warn(f"owner fell back to --unmapped-owner for {line}")
        for line in owners.warnings:
            fmt.warn(f"{line}; GeoLens may refuse the transfer")
        for change in owners.changed:
            fmt.warn(
                f"{change['item']} was migrated before its owner changed to "
                f"{change['owner']}; it was not imported again. Transfer it by hand."
            )
        if not owners.roles_checked:
            fmt.warn(
                "the instance's role permissions couldn't be read, so owners were "
                "checked for an active account only"
            )
        if summary.unavailable:
            fmt.warn(
                f"{len(summary.unavailable)} item(s) use an action this version "
                "can't run yet and were left pending."
            )
        for wait in summary.waiting:
            fmt.warn(f"{wait['item']} waits on {', '.join(wait['waiting_on'])}")
        if summary.stopped:
            fmt.error(f"stopped: {summary.stopped}")
        if not opts.dry_run:
            fmt.info(f"State: {state.path}")
    left = summary.unavailable or summary.waiting or summary.stopped
    return EXIT_GENERIC if failed or left else EXIT_OK


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

    Refuses an inventory from another portal than the plan's: the plan's
    portal receives the password, and the inventory's decides where the
    token may go.
    """
    if not any(item["action"] == _plan.IMPORT_LAYERS for item in to_run):
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
    return {row["id"]: row for row in inventory["items"]}, inventory["portal"]


def _portal_client(
    opts: MigrateOptions,
    plan: Mapping[str, Any],
    to_run: list[Mapping[str, Any]],
    rows: Mapping[str, Mapping[str, Any]],
    redact: Redactor,
) -> tuple[PortalClient, str | None] | None:
    """A client for the plan's portal holding the run's token or password.

    None when no item to import needs one; a ``UsageError`` when one does and
    no credential was given.
    """
    private = sum(
        1
        for item in to_run
        if item["action"] == _plan.IMPORT_LAYERS
        and item["id"] in rows
        and (rows[item["id"]].get("sharing") or {}).get("access") != "public"
    )
    if not private:
        return None
    try:
        token, password = read_credentials(
            opts.token, opts.token_stdin, opts.username, opts.password_stdin
        )
        if token is None and password is None:
            raise UsageError(
                f"{private} item(s) to import are not public: pass --token, "
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


def _run(
    fmt: _output.Formatter,
    opts: MigrateOptions,
    redact: Redactor,
    sdk_factory: Callable[[], Any],
    instance: str,
) -> int:
    try:
        _check_hosts(opts.trusted_hosts)
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
        rows, portal_info = _inventory_rows(plan, opts.plan_path, to_run)
        portal = (
            None if opts.dry_run else _portal_client(opts, plan, to_run, rows, redact)
        )
    except (_plan.PlanError, StateError, UsageError) as exc:
        fmt.error(str(exc))
        return EXIT_USAGE

    sdk = sdk_factory()
    geolens = GeoLens(sdk, instance, redact)
    try:
        _require_admin(geolens)
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
        unavailable = [
            item["id"]
            for item in to_run
            if item["action"] != _plan.SKIP and item["action"] not in HANDLERS
        ]
        return _report(
            fmt, opts, state, to_run, owners, RunSummary(unavailable=unavailable)
        )
    auth = None
    if portal is not None:
        client, password = portal
        try:
            if password is not None and opts.username:
                client.generate_token(opts.username, password)
        except PortalError as exc:
            fmt.error(str(exc))
            return EXIT_AUTH if exc.kind == "auth" else EXIT_GENERIC
        auth = PortalAuth(client, renewable=password is not None)
    ctx = MigrationContext(
        geolens=geolens,
        inventory=rows,
        portal=auth,
        save=state.save,
        portal_info=portal_info,
        trusted_hosts=frozenset(h.strip().lower() for h in opts.trusted_hosts),
        allow_insecure_http=opts.allow_insecure_http,
    )
    try:
        summary = run_items(ctx, plan, state, to_run, owners.by_item)
    except KeyboardInterrupt:
        fmt.error(
            f"interrupted; rerun with the same state file ({state.path}) to resume"
        )
        return EXIT_INTERRUPTED
    return _report(fmt, opts, state, to_run, owners, summary)
