# SPDX-License-Identifier: Apache-2.0
"""File migrated datasets into collections: ``defaults.collection_from``.

Hand-maintained. ``folder`` puts an item's datasets into a collection named
after its ArcGIS folder; ``none`` files nothing. ``group`` files nothing
either: ArcGIS groups become GeoLens groups, so the step says so in the
item's notes instead of imitating a group with a collection.

Collections are created and filled as the operator, who needs
``manage_collections``. Names are unique across the instance, so a folder
whose name a collection this run did not create already holds is filed
under the portal's name as a prefix.
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
FALLBACK_PREFIX = "ArcGIS"


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
    prefix = str((ctx.portal_info or {}).get("name") or "") or FALLBACK_PREFIX
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

    ctx.geolens.call(
        add.sync_detailed,
        collection_id=UUID(collection_id),
        body=CollectionAddDatasetsRequest(dataset_ids=[UUID(d) for d in dataset_ids]),
    )


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
        return ["not filed into collections: the operator can't manage collections"]
    try:
        for name in names:
            collection_id = _collection_id(ctx, name)
            if collection_id is None:
                ctx.collections_denied = True
                return [
                    "not filed into collections: the operator can't manage collections"
                ]
            _add(ctx, collection_id, entry.dataset_ids)
            if collection_id not in entry.collection_ids:
                entry.collection_ids.append(collection_id)
    except GeoLensError as exc:
        raise ItemFailed(f"filing into a collection failed, {exc}") from None
    ctx.save()
    return []
