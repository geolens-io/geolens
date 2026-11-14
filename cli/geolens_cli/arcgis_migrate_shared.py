# SPDX-License-Identifier: Apache-2.0
"""Plan items that import the same ArcGIS service layer.

Hand-maintained. A hosted feature layer item and an item added by URL over
the same service, or over one of its layers, would import one service layer
twice; GeoLens keeps one dataset per source. Each shared layer has one owner
item, which alone writes its dataset; the others borrow it and write nothing.

An item that recorded a layer's dataset, or has its import job pending, owns
the layer. For a layer nobody holds, the plan decides: the hosted item whose
URL is the service itself, else the first item in plan order that covers the
layer. Ownership records never move between items; a dataset an earlier
version let several items record is written by none of them until the plan
skips all but one. Every write is checked with ``may_write`` when it is made.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from .arcgis_migrate_state import ItemState
from .arcgis_plan import IMPORT_FILE, IMPORT_LAYERS

_LAYER = re.compile(r"/(FeatureServer|MapServer)/(\d+)$", re.IGNORECASE)
_ROOT = re.compile(r"/(FeatureServer|MapServer)$", re.IGNORECASE)
_REACH = {"private": 0, "restricted": 1, "internal": 2, "public": 3}


def service_layer(url: Any) -> tuple[str, str | None] | None:
    """(the service, the layer id the URL names or None for every layer) of a
    FeatureServer or MapServer URL, read the way GeoLens's service import
    reads it: no query, no trailing slash or ``/query``. The service is
    lowercased, since ArcGIS service paths are case-insensitive. None for any
    other URL."""
    if not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url)
        port = f":{parts.port}" if parts.port else ""
    except ValueError:
        return None
    host = parts.hostname
    if not host:
        return None
    if ":" in host:
        # An IPv6 literal keeps its brackets, so its last group is never read
        # as a port.
        host = f"[{host}]"
    path = parts.path.rstrip("/")
    if path.lower().endswith("/query"):
        path = path[: -len("/query")].rstrip("/")
    layer = None
    if match := _LAYER.search(path):
        # As the service probe reads it: /01 is layer 1.
        layer = str(int(match.group(2)))
        path = path[: match.start() + 1 + len(match.group(1))]
    if not _ROOT.search(path):
        return None
    return f"{parts.scheme}://{host}{port}{path}".lower(), layer


@dataclass(frozen=True)
class _Covers:
    item: Mapping[str, Any]
    service: str
    # None: every layer of the service.
    layer: str | None
    hosted_root: bool


def migrated(item: Mapping[str, Any] | None) -> bool:
    """Whether the plan still imports the service *item* names."""
    return bool(
        item
        and item["action"] == IMPORT_LAYERS
        and not item.get("removed")
        and not item.get("unlisted")
    )


class SharedLayers:
    """Who owns each service layer the plan's items import."""

    def __init__(
        self, items: list[Mapping[str, Any]], rows: Mapping[str, Mapping[str, Any]]
    ) -> None:
        self.items = {item["id"]: item for item in items}
        self.rows = rows
        self._covers: dict[str, _Covers] = {}
        for item in items:
            row = rows.get(item["id"]) or {}
            found = service_layer(row.get("url"))
            if migrated(item) and found is not None:
                hosted = row.get("hosted") is True and found[1] is None
                self._covers[item["id"]] = _Covers(item, found[0], found[1], hosted)

    def _candidates(self, service: str, layer: str | None) -> list[_Covers]:
        return [
            c
            for c in self._covers.values()
            if c.service == service and (c.layer is None or c.layer in (layer, None))
        ]

    def plan_owner(self, item_id: str, layer: str | None) -> Mapping[str, Any]:
        """The item the plan picks to own *layer* of *item_id*'s service, or
        with None the service layers no layer URL names; *item_id*'s own item
        when it shares nothing."""
        mine = self._covers.get(item_id)
        if mine is None:
            return self.items[item_id]
        candidates = self._candidates(mine.service, layer)
        hosted = [c for c in candidates if c.hosted_root]
        return (hosted or candidates or [mine])[0].item

    def owner(
        self, items: Mapping[str, ItemState], item_id: str, layer: str | None
    ) -> str:
        """The item owning *layer* of *item_id*'s service: the item whose
        state holds it, else the one the plan picks. With None, the service
        layers no layer URL names and no state holds."""
        mine = self._covers.get(item_id)
        if mine is None:
            return item_id
        if layer is not None:
            held = [
                other
                for other, _ in self.holders(items, mine.service, layer)
                if migrated(self.items.get(other))
            ]
            if held:
                return self.preferred(held)
        return self.plan_owner(item_id, layer)["id"]

    def dependencies(
        self, items: Mapping[str, ItemState], *, blocking: bool = False
    ) -> dict[str, list[str]]:
        """Item -> the items that run before it: the owner the plan picks for
        a layer it shares that nobody holds, and an item whose import job for
        such a layer is pending. With *blocking*, only the former, which an
        item waits on; a pending holder only runs first, since its job settles
        whatever else it waits on. A finished holder's dataset is borrowed at
        once, so it adds none. Items whose layers don't overlap get none."""
        out: dict[str, set[str]] = {}
        for item_id, mine in self._covers.items():
            if mine.layer is not None:
                layers: list[str | None] = [mine.layer]
            else:
                named = {
                    c.layer
                    for c in self._covers.values()
                    if c.service == mine.service and c.layer is not None
                }
                for other, entry in items.items():
                    if self.service_of(other, entry) == mine.service:
                        named |= {*entry.layer_datasets, *entry.layer_jobs}
                layers = [*sorted(named), None]
            for layer in layers:
                owner = self.owner(items, item_id, layer)
                held = dict(self.holders(items, mine.service, layer)) if layer else {}
                pending = owner in held and held[owner] is None
                if owner != item_id and (owner not in held or pending):
                    if not (blocking and pending):
                        out.setdefault(item_id, set()).add(owner)
        kept = _acyclic(out, list(self.items))
        return {i: sorted(owners) for i, owners in kept.items() if owners}

    def service_of(self, item_id: str, entry: ItemState | None) -> str | None:
        """The service *item_id* imports, from the URL its state recorded or
        else its inventory row."""
        url = (entry.service_url if entry else None) or (
            self.rows.get(item_id) or {}
        ).get("url")
        found = service_layer(url)
        return found[0] if found else None

    def holders(
        self, items: Mapping[str, ItemState], service: str, layer: str
    ) -> Iterator[tuple[str, str | None]]:
        """(item, dataset) for each item whose state holds *layer* of
        *service* as its own import: its dataset, or None while its import
        job is pending."""
        for item_id, entry in items.items():
            held = entry.layer_datasets.get(layer)
            if (held or layer in entry.layer_jobs) and self.service_of(
                item_id, entry
            ) == service:
                yield item_id, held

    def preferred(self, item_ids: list[str]) -> str:
        """Of *item_ids*, the one the plan prefers as owner: a hosted item at
        the service root, else the first in plan order."""
        order = list(self.items)
        ranked = sorted(
            item_ids,
            key=lambda i: (
                not (self._covers.get(i) and self._covers[i].hosted_root),
                order.index(i) if i in order else len(order),
            ),
        )
        return ranked[0]


def reuse_note(owner: Mapping[str, Any] | None, dataset: str) -> str:
    if owner is None:
        return f"reuses dataset {dataset}; this item changed nothing on it"
    name = owner["target"]["title"] or owner["title"]
    return (
        f"reuses dataset {dataset} of item {owner['id']} ({name}), which sets its "
        "title, metadata and sharing; this item changed nothing on it"
    )


def wider_note(item: Mapping[str, Any], owner: Mapping[str, Any]) -> str | None:
    """Why a borrower shared more widely in ArcGIS than the owner reaches
    fewer people in GeoLens, or None."""
    mine, theirs = item["target"]["visibility"], owner["target"]["visibility"]
    if _REACH.get(mine, 0) > _REACH.get(theirs, 0):
        return (
            f"shared {mine} in ArcGIS, more widely than item {owner['id']} "
            f"({theirs}); ArcGIS applied the service's own sharing to the data, "
            "and the dataset keeps that item's"
        )
    if mine == theirs == "restricted":
        extra = sorted(
            set(item["target"]["groups"] or []) - set(owner["target"]["groups"] or [])
        )
        if extra:
            return (
                f"shared in ArcGIS with groups item {owner['id']} isn't shared "
                f"with ({', '.join(extra)}); the dataset keeps that item's groups"
            )
    return None


def gone_note(owner_id: str, what: str) -> str:
    return (
        f"{what} belongs to item {owner_id}, which the plan no longer migrates; "
        "this item doesn't import or refresh it"
    )


def _records(item: Mapping[str, Any] | None) -> bool:
    return bool(
        item
        and item["action"] in (IMPORT_LAYERS, IMPORT_FILE)
        and not item.get("removed")
        and not item.get("unlisted")
    )


def double_recorded(
    plan_items: list[Mapping[str, Any]], items: Mapping[str, ItemState]
) -> dict[str, list[str]]:
    """Dataset -> the plan items that each record it as their own import, for
    a dataset that two or more items the plan still migrates record, which
    an earlier version of this command could leave."""
    by_id = {item["id"]: item for item in plan_items}
    found: dict[str, list[str]] = {}
    for item_id, entry in items.items():
        if _records(by_id.get(item_id)):
            for dataset in dict.fromkeys(entry.layer_datasets.values()):
                found.setdefault(dataset, []).append(item_id)
    return {d: ids for d, ids in found.items() if len(ids) > 1}


def _acyclic(edges: dict[str, set[str]], order: list[str]) -> dict[str, set[str]]:
    """*edges* without each edge that closes a cycle, which only a state from
    an earlier version can hold. An edge to an earlier plan item is kept
    first, so such items run in plan order."""
    kept: dict[str, set[str]] = {}
    rank = {item_id: n for n, item_id in enumerate(order)}

    def reaches(start: str, goal: str) -> bool:
        seen, stack = set(), [start]
        while stack:
            node = stack.pop()
            if node == goal:
                return True
            if node not in seen:
                seen.add(node)
                stack.extend(kept.get(node, ()))
        return False

    pairs = sorted(
        ((item_id, owner) for item_id, owners in edges.items() for owner in owners),
        key=lambda p: (rank.get(p[1], 0) > rank.get(p[0], 0), rank.get(p[0], 0)),
    )
    for item_id, owner in pairs:
        if not reaches(owner, item_id):
            kept.setdefault(item_id, set()).add(owner)
    return kept


def may_write(ctx: Any, entry: ItemState, dataset: str) -> str | None:
    """Why the item whose state is *entry* must not write *dataset* now, or
    None. Decided from the state as it is at the write: another plan item
    records the same dataset, or another item owns its service layer."""
    layers = ctx.shared_layers
    if layers is None:
        return None
    item_id = next((i for i, e in ctx.items.items() if e is entry), None)
    others = [
        other
        for other, held in ctx.items.items()
        if held is not entry
        and dataset in held.layer_datasets.values()
        and _records(layers.items.get(other))
    ]
    if others:
        items = ", ".join(sorted([item_id or "this item", *others]))
        return (
            f"dataset {dataset} is recorded by items {items}, as an earlier "
            "version of this command left it; none of them writes it until all "
            "but one are set to skip in the plan"
        )
    key = next((k for k, d in entry.layer_datasets.items() if d == dataset), None)
    if item_id is None or key is None:
        return None
    owner = layers.owner(ctx.items, item_id, key)
    if owner != item_id:
        return (
            f"dataset {dataset} is this item's copy of layer {key}, which item "
            f"{owner} over the same service owns; it isn't written"
        )
    return None
