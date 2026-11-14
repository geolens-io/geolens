# SPDX-License-Identifier: Apache-2.0
"""Plan items that import the same ArcGIS service layer.

Hand-maintained. A hosted feature layer item and an item added by URL over
the same service, or over one of its layers, would import one service layer
twice; GeoLens keeps one dataset per source. Each shared layer has one owner
item, which alone writes its dataset; the others borrow it and write nothing.

An item that recorded a layer's dataset in an earlier run stays its owner.
For a layer nobody has recorded, the plan decides: the hosted item whose URL
is the service itself, else the first item in plan order that covers the
layer. Ownership records never move between items.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from .arcgis_migrate_state import DONE, EXISTS, ItemState
from .arcgis_plan import IMPORT_LAYERS

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
    if not parts.hostname:
        return None
    path = parts.path.rstrip("/")
    if path.lower().endswith("/query"):
        path = path[: -len("/query")].rstrip("/")
    layer = None
    if match := _LAYER.search(path):
        layer = match.group(2)
        path = path[: match.start() + 1 + len(match.group(1))]
    if not _ROOT.search(path):
        return None
    return f"{parts.scheme}://{parts.hostname}{port}{path}".lower(), layer


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

    def dependencies(self) -> dict[str, list[str]]:
        """Item -> the items owning a layer it shares, which run before it.
        Items whose layers don't overlap get none."""
        out: dict[str, list[str]] = {}
        for item_id, mine in self._covers.items():
            if mine.layer is not None:
                layers = [mine.layer]
            else:
                named = {
                    c.layer
                    for c in self._covers.values()
                    if c.service == mine.service and c.layer is not None
                }
                layers = [*sorted(named), None]
            owners = {self.plan_owner(item_id, layer)["id"] for layer in layers}
            owners.discard(item_id)
            if owners:
                out[item_id] = sorted(owners)
        return out

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
    ) -> Iterator[tuple[str, str]]:
        """(item, dataset) for each item whose state records *layer* of
        *service* as its own import."""
        for item_id, entry in items.items():
            dataset = entry.layer_datasets.get(layer)
            if dataset and self.service_of(item_id, entry) == service:
                yield item_id, dataset

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


def borrowers(items: Mapping[str, ItemState], dataset: str) -> list[ItemState]:
    """The states that borrow *dataset* from its owner."""
    return [entry for entry in items.values() if dataset in entry.shared.values()]


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


def gone_note(owner_id: str, dataset: str) -> str:
    return (
        f"dataset {dataset} belongs to item {owner_id}, which the plan no longer "
        "migrates; this item doesn't import or refresh it"
    )


def settle_recorded(
    items: Mapping[str, ItemState], layers: SharedLayers, names: Mapping[str, str]
) -> bool:
    """Decide ownership of each dataset that two migrated items both record
    as their own, as a state from an earlier version can hold.

    The plan's preferred holder owns it. Each other holder keeps its records
    of the dataset as they are and only lists it as borrowed from then on;
    nothing moves to the owner. Groups such a holder granted are reported on
    the owner, since no item manages them any more. Whether anything changed.
    """
    holders: dict[str, list[str]] = {}
    for item_id, entry in items.items():
        if not migrated(layers.items.get(item_id)):
            continue
        for dataset in dict.fromkeys(entry.layer_datasets.values()):
            holders.setdefault(dataset, []).append(item_id)
    changed = False
    for dataset, ids in holders.items():
        if len(ids) < 2:
            continue
        owner_id = layers.preferred(ids)
        owner = items[owner_id]
        for other_id in ids:
            if other_id == owner_id:
                continue
            other = items[other_id]
            for key in [k for k, d in other.layer_datasets.items() if d == dataset]:
                other.shared[key] = other.layer_datasets.pop(key)
            other.dataset_ids = [d for d in other.dataset_ids if d != dataset]
            other.notes = _without_false_edits(other.notes, dataset)
            note = reuse_note(layers.items[owner_id], dataset)
            if note not in other.notes:
                other.notes.append(note)
            if other.status == DONE and not other.layer_datasets:
                other.status = EXISTS
            for group in sorted(
                set(other.granted.get(dataset) or [])
                - set(owner.groups.get(dataset) or [])
            ):
                note = (
                    f"group {names.get(group, group)} was granted on dataset "
                    f"{dataset} by item {other_id} in an earlier run and is no "
                    "longer managed; remove it in GeoLens if it shouldn't have access"
                )
                if note not in owner.notes:
                    owner.notes.append(note)
            changed = True
        owner.notes = _without_false_edits(owner.notes, dataset)
    return changed


def _without_false_edits(notes: list[str], dataset: str) -> list[str]:
    """*notes* without those that took the other holder's writes, this
    command's own, for edits made in GeoLens; a rerun notes a real edit again."""
    return [
        n
        for n in notes
        if not (
            n.startswith("kept the ")
            and n.endswith(f" edited in GeoLens on dataset {dataset}")
        )
    ]
