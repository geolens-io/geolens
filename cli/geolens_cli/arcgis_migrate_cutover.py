# SPDX-License-Identifier: Apache-2.0
"""The checks `geolens arcgis migrate --cutover` runs before it marks the final run.

Hand-maintained. Each check names what would not carry over if the portal
were retired now; the run is marked only when every failing check is
accepted with its ``--accept-<check>`` flag.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from . import arcgis_plan as _plan
from .arcgis_migrate_state import FINISHED, ItemState, MigrationState

UNFINISHED = "unfinished-items"
INVENTORY = "incomplete-inventory"
ATTACHMENTS = "attachment-loss"
USERS = "unresolved-users"
CHECKS = (UNFINISHED, INVENTORY, ATTACHMENTS, USERS)


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


def failing_checks(
    plan: Mapping[str, Any],
    state: MigrationState,
    unresolved: Sequence[Mapping[str, str]] = (),
) -> list[dict[str, Any]]:
    """Every check that fails as of *state*, with the items it names."""
    found = {
        UNFINISHED: _unfinished(plan, state),
        INVENTORY: []
        if _covers_org(plan["inventory"])
        else [
            {
                "item": "-",
                "reason": "the plan was last merged from an inventory that isn't a "
                "complete --scope org one read by an organization administrator, "
                "so portal items may be missing from it",
            }
        ],
        ATTACHMENTS: _attachments(plan, state),
        USERS: _users(plan, state, unresolved),
    }
    return [{"check": name, "items": found[name]} for name in CHECKS if found[name]]
