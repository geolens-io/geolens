# SPDX-License-Identifier: Apache-2.0
"""Plan items that import one ArcGIS service between them.

Hand-maintained. A hosted feature layer item and an item added by URL over
the same service (or over one of its layers) end up on one GeoLens dataset,
since GeoLens keeps one copy per source. One item owns that dataset: the
hosted item for the service when the plan has one, else the first in plan
order. Only the owner writes it; ownership is decided from the plan and
inventory before any item runs, so the outcome doesn't depend on order.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from .arcgis_migrate_state import DONE, EXISTS, ItemState, aware_time
from .arcgis_plan import IMPORT_LAYERS

_SERVICE_PATH = re.compile(r"^(.*?/(?:feature|map)server)(?:/(\d+))?/?$", re.IGNORECASE)
_REACH = {"private": 0, "restricted": 1, "internal": 2, "public": 3}
# Records a donor keeps per dataset, which stop applying once it no longer
# writes the dataset.
_PER_DATASET = (
    "metadata_baseline",
    "last_update",
    "visibility",
    "groups",
    "granted",
    "kept",
    "refreshing",
)


def service_of(url: Any) -> tuple[str, str | None] | None:
    """(the service a FeatureServer or MapServer URL belongs to, the layer id
    it names or None), or None for any other URL. ArcGIS service paths are
    case-insensitive, so the service is compared lowercased."""
    if not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url)
        port = f":{parts.port}" if parts.port else ""
    except ValueError:
        return None
    match = _SERVICE_PATH.match(parts.path)
    if not match or not parts.hostname:
        return None
    service = f"{parts.scheme}://{parts.hostname}{port}{match.group(1)}".lower()
    return service, match.group(2)


@dataclass(frozen=True)
class Reuse:
    """A plan item over the service *owner* imports and alone writes."""

    item: Mapping[str, Any]
    owner: Mapping[str, Any]


def service_owners(
    items: list[Mapping[str, Any]], rows: Mapping[str, Mapping[str, Any]]
) -> dict[str, Reuse]:
    """Plan item id -> its ``Reuse``, for every import_layers item that
    shares its service with an item that owns it.

    The owner is the item the inventory marks hosted whose URL is the service
    itself, not one of its layers; without one, the first in plan order.
    """
    services: dict[str, list[tuple[Mapping[str, Any], bool]]] = {}
    for item in items:
        if (
            item["action"] != IMPORT_LAYERS
            or item.get("removed")
            or item.get("unlisted")
        ):
            continue
        row = rows.get(item["id"]) or {}
        found = service_of(row.get("url"))
        if found is not None:
            hosted = row.get("hosted") is True and found[1] is None
            services.setdefault(found[0], []).append((item, hosted))
    owners: dict[str, Reuse] = {}
    for members in services.values():
        if len(members) < 2:
            continue
        owner = next((i for i, hosted in members if hosted), members[0][0])
        owners.update({i["id"]: Reuse(i, owner) for i, _ in members if i is not owner})
    return owners


def reuse_notes(
    item: Mapping[str, Any], owner: Mapping[str, Any] | None, datasets: list[str]
) -> list[str]:
    """The report lines of an item whose *datasets* belong to *owner*."""
    if owner is None:
        return [
            f"reuses dataset {d}, which another item over the same service "
            "imported; this item changed nothing on it"
            for d in datasets
        ]
    name = owner["target"]["title"] or owner["title"]
    notes = [
        f"reuses dataset {d} of item {owner['id']} ({name}), which sets its "
        "title, metadata and sharing; this item changed nothing on it"
        for d in datasets
    ]
    mine, theirs = item["target"]["visibility"], owner["target"]["visibility"]
    if _REACH.get(mine, 0) > _REACH.get(theirs, 0):
        notes.append(
            f"shared {mine} in ArcGIS, more widely than item {owner['id']} "
            f"({theirs}); ArcGIS applied the service's own sharing to the data, "
            "and the dataset keeps that item's"
        )
    elif mine == theirs == "restricted":
        extra = sorted(
            set(item["target"]["groups"] or []) - set(owner["target"]["groups"] or [])
        )
        if extra:
            notes.append(
                f"shared in ArcGIS with groups item {owner['id']} isn't shared with "
                f"({', '.join(extra)}); the dataset keeps that item's groups"
            )
    return notes


def _wrote_last(mine: ItemState, other: ItemState, dataset: str) -> bool:
    """Whether *mine* recorded a later write of *dataset* than *other*."""
    a, b = (
        aware_time((entry.last_update.get(dataset) or {}).get("updated_at"))
        for entry in (mine, other)
    )
    if a is not None and b is not None and a != b:
        return a > b
    if (a is None) != (b is None):
        return a is not None
    # The item that found the dataset already there ran second.
    return dataset in mine.reused and dataset not in other.reused


def take_over(
    owner: ItemState,
    donor: ItemState,
    dataset: str,
    notes: list[str],
    *,
    both_recorded: bool,
) -> None:
    """Make *owner* the item that writes *dataset*, which this command
    imported or reused for *donor* before the two were known to share it.

    The donor's metadata baseline joins the owner's, since what the donor
    wrote is this command's own and not an edit made in GeoLens. With
    *both_recorded* (both items finished with it), the record of whichever
    wrote last becomes the owner's, so a rerun compares with that write.
    The donor keeps the dataset only as shared, with *notes*.
    """
    mine = dict(owner.metadata_baseline.get(dataset) or {})
    theirs = dict(donor.metadata_baseline.get(dataset) or {})
    donor_last = not both_recorded or _wrote_last(donor, owner, dataset)
    if mine or theirs:
        merged = {**mine, **theirs} if donor_last else {**theirs, **mine}
        merged["keywords"] = list(
            dict.fromkeys([*mine.get("keywords", []), *theirs.get("keywords", [])])
        )
        owner.metadata_baseline[dataset] = merged
    if both_recorded and donor_last:
        for name in ("last_update", "visibility"):
            record = getattr(donor, name).get(dataset)
            if record is not None:
                getattr(owner, name)[dataset] = record
    if dataset not in donor.reused and dataset in owner.reused:
        owner.reused.remove(dataset)
    owner.notes = [
        n
        for n in owner.notes
        if not (
            n.startswith("kept the ")
            and n.endswith(f" edited in GeoLens on dataset {dataset}")
        )
    ]
    if owner.status == EXISTS and not owner.reused:
        owner.status = DONE
    _release(donor, dataset, notes)


def _release(donor: ItemState, dataset: str, notes: list[str]) -> None:
    moved = [key for key, d in donor.layer_datasets.items() if d == dataset]
    for key in moved:
        donor.shared[key] = donor.layer_datasets.pop(key)
    if len(donor.record_ids) == len(donor.dataset_ids):
        donor.record_ids = [
            r for d, r in zip(donor.dataset_ids, donor.record_ids) if d != dataset
        ]
    donor.dataset_ids = [d for d in donor.dataset_ids if d != dataset]
    for name in _PER_DATASET:
        getattr(donor, name).pop(dataset, None)
    if dataset in donor.reused:
        donor.reused.remove(dataset)
    for name in ("attachments", "relationships"):
        layers = getattr(donor, name)
        if layers:
            setattr(donor, name, {k: v for k, v in layers.items() if k not in moved})
    kept = [n for n in donor.notes if f"dataset {dataset}" not in n]
    donor.notes = [*kept, *(n for n in notes if n not in kept)]
    if donor.status == DONE and not donor.layer_datasets:
        donor.status = EXISTS


def reconcile(items: Mapping[str, ItemState], reuses: Mapping[str, Reuse]) -> bool:
    """Hand each dataset that both an item and its service's owner record as
    their own to the owner, as a state from before ownership was decided can
    hold; whether anything moved."""
    moved = False
    for donor_id, reuse in reuses.items():
        donor, owner = items.get(donor_id), items.get(reuse.owner["id"])
        if donor is None or owner is None:
            continue
        held = set(owner.layer_datasets.values())
        for dataset in dict.fromkeys(donor.layer_datasets.values()):
            if dataset in held:
                notes = reuse_notes(reuse.item, reuse.owner, [dataset])
                take_over(owner, donor, dataset, notes, both_recorded=True)
                moved = True
    return moved
