# SPDX-License-Identifier: Apache-2.0
"""File migrated datasets into collections: ``defaults.collection_from``.

Hand-maintained. ``folder`` puts an item's datasets into a collection named
after its ArcGIS folder; ``none`` files nothing. ``group`` files nothing
either: ArcGIS groups become GeoLens groups, so the step says so in the
item's notes instead of imitating a group with a collection.

Collections are created and filled as the operator, who needs
``manage_collections``. Names are unique across the instance, so a folder
whose name a collection this run did not create already holds is filed
under the portal's name as a prefix. When that name is held too, the run
stops before any item imports.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from .arcgis_migrate_session import (
    GeoLensError,
    ItemFailed,
    MigrationContext,
)
from .arcgis_migrate_state import ItemState

FOLDER = "folder"
GROUP = "group"
MAX_NAME = 255
# The most datasets one add-datasets request accepts.
ADD_BATCH = 100
COLLECTION_PAGE = 200
FALLBACK_PREFIX = "ArcGIS"
DENIED = "not filed into collections: the operator can't manage collections"
# The plan actions whose datasets are filed into collections.
_FILED_ACTIONS = ("import_layers", "import_file")


def _prefix(portal_info: Mapping[str, Any] | None) -> str:
    return str((portal_info or {}).get("name") or "") or FALLBACK_PREFIX


def _names(geolens: Any) -> set[str]:
    from geolens.api.datasets import (
        list_collections_endpoint_catalog_collections_get as list_collections,
    )

    names: list[str] = []
    while True:
        page = geolens.call(
            list_collections.sync_detailed, skip=len(names), limit=COLLECTION_PAGE
        )
        names.extend(c.name for c in page.collections)
        if not page.collections or len(names) >= page.total:
            return set(names)


def taken_collections(
    geolens: Any,
    plan: Mapping[str, Any],
    items: list[Mapping[str, Any]],
    known: Mapping[str, str],
    portal_info: Mapping[str, Any] | None,
) -> str | None:
    """Why *items* can't be filed, read before any of them imports: a
    collection they need whose name and prefixed name are both held by
    collections this command didn't create; None when nothing collides.
    *known* holds the collections the state records as made for the plan's
    names."""
    if plan["defaults"]["collection_from"] != FOLDER:
        return None
    wanted = [
        name
        for item in items
        if item["action"] in _FILED_ACTIONS and not item.get("unlisted")
        for name in item["target"]["collections"]
        if name and name not in known
    ]
    if not wanted:
        return None
    existing = _names(geolens)
    prefix = _prefix(portal_info)
    taken = [
        name
        for name in dict.fromkeys(wanted)
        if name[:MAX_NAME] in existing and f"{prefix} - {name}"[:MAX_NAME] in existing
    ]
    if not taken:
        return None
    return (
        "GeoLens already has collections named "
        + "; ".join(f"{name} and {prefix} - {name}" for name in taken)
        + ", so the items filed there would fail after their import; rename "
        "them in the plan items' target collections, or set "
        "defaults.collection_from to none"
    )


def _create(ctx: MigrationContext, name: str) -> str:
    from geolens.api.datasets import (
        create_collection_endpoint_catalog_collections_post as create,
    )
    from geolens.models.collection_create import CollectionCreate

    created = ctx.geolens.call(
        create.sync_detailed, body=CollectionCreate(name=name), expected=201
    )
    return str(created.id)


def _collection_id(ctx: MigrationContext, name: str) -> str | None:
    """The id of the collection for the plan's *name*, creating it on first use;
    None when the operator may not manage collections."""
    known = ctx.collections.get(name)
    if known:
        return known
    prefix = _prefix(ctx.portal_info)
    try:
        try:
            created = _create(ctx, name[:MAX_NAME])
        except GeoLensError as exc:
            if exc.status != 409:
                raise
            created = _create(ctx, f"{prefix} - {name}"[:MAX_NAME])
    except GeoLensError as exc:
        if exc.status == 403:
            return None
        raise
    ctx.collections[name] = created
    ctx.save()
    return created


def _add(ctx: MigrationContext, collection_id: str, dataset_ids: list[str]) -> None:
    from geolens.api.datasets import (
        add_datasets_endpoint_catalog_collections_collection_id_datasets_post as add,
    )
    from geolens.models.collection_add_datasets_request import (
        CollectionAddDatasetsRequest,
    )

    for start in range(0, len(dataset_ids), ADD_BATCH):
        batch = dataset_ids[start : start + ADD_BATCH]
        try:
            ctx.geolens.call(
                add.sync_detailed,
                collection_id=UUID(collection_id),
                body=CollectionAddDatasetsRequest(dataset_ids=[UUID(d) for d in batch]),
            )
        except GeoLensError as exc:
            if exc.status == 403 and start:
                raise ItemFailed(
                    f"filing into a collection stopped partway, {exc}; "
                    "rerun to finish it"
                ) from None
            raise


def file_into_collections(
    ctx: MigrationContext, item: Mapping[str, Any], entry: ItemState
) -> list[str]:
    """Add the item's datasets to the collections its plan target names.

    Returns notes for the report. Adding is idempotent, so a rerun files
    nothing twice. A refusal for lack of ``manage_collections`` skips the
    step with a note instead of failing the item.
    """
    target = item["target"]
    if ctx.collection_from == GROUP:
        if target.get("groups"):
            return [
                "not filed into collections: collection_from is group, and ArcGIS "
                "groups map to GeoLens groups, not collections"
            ]
        return []
    names = list(dict.fromkeys(n for n in target["collections"] if n))
    if ctx.collection_from != FOLDER or not names or not entry.dataset_ids:
        return []
    if ctx.collections_denied:
        return [DENIED]
    try:
        for name in names:
            collection_id = _collection_id(ctx, name)
            if collection_id is None:
                ctx.collections_denied = True
                return [DENIED]
            _add(ctx, collection_id, entry.dataset_ids)
            if collection_id not in entry.collection_ids:
                entry.collection_ids.append(collection_id)
    except GeoLensError as exc:
        if exc.status == 403:
            ctx.collections_denied = True
            return [DENIED]
        hint = (
            "; if the collection was deleted, remove it from `collections` in "
            "the state file and rerun"
            if exc.status == 404
            else ""
        )
        raise ItemFailed(f"filing into a collection failed, {exc}{hint}") from None
    ctx.save()
    return []
