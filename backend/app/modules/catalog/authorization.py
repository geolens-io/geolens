"""Dataset visibility enforcement.

SEC-04: all dataset access paths use these shared functions —
DatasetVisibility, apply_visibility_filter(), get_user_roles(),
check_dataset_access() — relocated from the deleted auth visibility
module (Phase 213).
"""

import enum
import uuid
from collections.abc import Iterable, Sequence
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.identity import Identity
from app.modules.auth.permissions import get_user_roles as _get_user_roles
from app.platform.extensions import get_permission_extension


class DatasetVisibility(str, enum.Enum):
    """Controls who can see a dataset."""

    PUBLIC = "public"
    # fix(#930): internal mirrors MapVisibility — any signed-in user, on a
    # published record. It was already accepted by the API Literal and written
    # by `geolens apply`, but had no branch in the permission layer.
    INTERNAL = "internal"
    RESTRICTED = "restricted"
    PRIVATE = "private"


def apply_visibility_filter(
    stmt: Select[Any],
    user: Identity | None,
    user_roles: set[str],
    record_cls: Any,
    grant_cls: Any | None = None,
) -> Select[Any]:
    """Filter a query based on visibility and user permissions.

    Visibility and created_by live on Record (not Dataset); grant_cls still
    references datasets via dataset_id. Delegates to the registered
    permission extension's filter_visible.
    """
    return get_permission_extension().filter_visible(
        stmt, user, user_roles, record_cls, grant_cls
    )


async def get_user_roles(db: AsyncSession, user: Identity) -> set[str]:
    """Role names for a user. The query itself lives in ``auth.permissions``.

    Auth owns the query (selects auth-only tables); this delegates rather
    than re-exports because ``test_permission_chokepoints_use_extension``
    reads this file's ``async def get_user_roles`` as a block boundary, and
    callers that patch ``catalog.authorization.get_user_roles`` need a real def.
    """
    return await _get_user_roles(db, user)


async def check_dataset_access_or_anonymous(
    db: AsyncSession, dataset: Any, dataset_id: uuid.UUID, user: Identity | None
) -> set[str]:
    """Enforce visibility for both authenticated and anonymous users.

    Returns the resolved user_roles set (empty for anonymous).
    Anonymous users may only access public + published datasets.
    Authenticated users follow the full RBAC rules via check_dataset_access().
    """
    if user is None:
        allowed = await get_permission_extension().can_access_dataset(
            db,
            dataset,
            dataset_id,
            None,
            user_roles=set(),
        )
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
            )
        return set()
    return await check_dataset_access(db, dataset, dataset_id, user)


async def check_dataset_access(
    db: AsyncSession,
    dataset: Any,
    dataset_id: uuid.UUID,
    user: Identity,
    *,
    user_roles: set[str] | None = None,
) -> set[str]:
    """Enforce RBAC visibility on a single dataset. Raises 404 if access denied.

    Returns the resolved user_roles set so callers can reuse it downstream.
    Visibility and created_by live on ``dataset.record``. Admins and public
    datasets always pass; private is owner-only; restricted needs a grant.
    """
    if user_roles is None:
        user_roles = await get_user_roles(db, user)

    allowed = await get_permission_extension().can_access_dataset(
        db,
        dataset,
        dataset_id,
        user,
        user_roles=user_roles,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )

    return user_roles


async def check_datasets_access_bulk(
    db: AsyncSession,
    dataset_ids: Sequence[uuid.UUID],
    user: Identity,
    user_roles: set[str],
) -> dict[uuid.UUID, Any]:
    """Load and authorize multiple datasets in a small, constant number of queries.

    fix(#1298): batch sibling of ``check_dataset_access`` — one SELECT
    plus one ``apply_visibility_filter`` pass, replacing a per-id loop
    that cost ~1000 queries for a 500-id VRT request. Same visibility
    seam as ``_accessible_dataset_ids``, same 404 as the scalar path.

    Returns every requested dataset keyed by id, reachable only once
    every id has passed.
    """
    if not dataset_ids:
        return {}

    from app.modules.catalog.datasets.domain.models import Dataset

    result = await db.execute(
        select(Dataset)
        .options(joinedload(Dataset.record))
        .where(Dataset.id.in_(set(dataset_ids)))
    )
    datasets_by_id = {
        dataset.id: dataset for dataset in result.scalars().unique().all()
    }

    accessible = await _accessible_dataset_ids(db, dataset_ids, user, user_roles)
    for dataset_id in dataset_ids:
        if dataset_id not in accessible:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
            )

    return datasets_by_id


async def _can_access_dataset_id(
    db: AsyncSession,
    dataset_id: Any,
    user: Identity | None,
    user_roles: set[str],
) -> bool:
    """Boolean form of the visibility check, for a raw id that may be junk.

    False for an unparseable id and for one whose dataset no longer exists:
    access cannot be established either way, so the caller withholds.
    """
    from app.modules.catalog.datasets.domain.service import get_dataset

    try:
        parsed = uuid.UUID(str(dataset_id))
    except (TypeError, ValueError):
        return False
    dataset = await get_dataset(db, parsed)
    if dataset is None:
        return False
    return await get_permission_extension().can_access_dataset(
        db,
        dataset,
        parsed,
        user,
        user_roles=user_roles,
    )


# fix(#1097): every provenance param naming a dataset, mapped to
# what describes it and must drop with it. A new dataset-id param must
# add a row here — test_every_dataset_id_param_is_redactable enforces it.
_DATASET_ID_PARAMS: dict[str, tuple[str, ...]] = {
    "mask_dataset_id": (),
    "join_dataset_id": ("join_fields",),
}


async def visible_derived_from(
    db: AsyncSession,
    derived_from: dict | None,
    user: Identity | None,
    user_roles: set[str],
) -> dict | None:
    """The provenance reference, with every dataset id in it access-checked.

    feat(#765): omitted, not stubbed — a requester must not be able to tell
    "not derived from anything" from "derived from something you cannot see".
    Every id in ``_DATASET_ID_PARAMS`` (not just the source) is checked and
    dropped on its own if denied, since a public output can be derived from
    a public source through a private mask/join layer. Always returns a copy.

    A deleted source also yields None: access can no longer be established,
    while the prose lineage on the record still reads.
    """
    if not derived_from:
        return None
    if not await _can_access_dataset_id(
        db, derived_from.get("dataset_id"), user, user_roles
    ):
        return None

    params = dict(derived_from.get("params") or {})
    for id_param, dependent_params in _DATASET_ID_PARAMS.items():
        dataset_id = params.get(id_param)
        if dataset_id is None:
            continue
        if await _can_access_dataset_id(db, dataset_id, user, user_roles):
            continue
        params.pop(id_param)
        # Dropping join_dataset_id alone would still publish join_fields —
        # the private layer's column names.
        for dependent in dependent_params:
            params.pop(dependent, None)
    return {**derived_from, "params": params}


# fix(#1103): never the dataset's id — _DATASET_ID_PARAMS already redacts
# that; putting it in the prose would route around it.
#
# fix(#1108): never edit the prose span-by-span — three rounds
# each forged a span-boundary attack. Binary rule: full prose if every
# referenced dataset is accessible, else this constant, never a byte of it.
_REDACTED_SUMMARY = "Derived from another dataset."


def _provenance_dataset_ids(derived_from: dict) -> list[uuid.UUID | None]:
    """The datasets a lineage sentence can name, in the order it names them.

    The source first, then the second layer, mirroring how build_lineage_sentence
    assembles the phrase. ``None`` marks an id that cannot be parsed, which the
    caller treats as inaccessible.
    """
    params = derived_from.get("params") or {}
    raw_ids = [derived_from.get("dataset_id")]
    raw_ids += [
        params[key] for key in _DATASET_ID_PARAMS if params.get(key) is not None
    ]

    parsed: list[uuid.UUID | None] = []
    for raw in raw_ids:
        try:
            parsed.append(uuid.UUID(str(raw)))
        except (TypeError, ValueError):
            parsed.append(None)
    return parsed


async def _accessible_dataset_ids(
    db: AsyncSession,
    dataset_ids: Iterable[uuid.UUID],
    user: Identity | None,
    user_roles: set[str],
) -> set[uuid.UUID]:
    """The subset of ``dataset_ids`` this requester may read, in one query.

    List-shaped form of ``check_dataset_access``: both delegate to
    PermissionExtension (#929/#930). Batching is what makes redaction
    affordable on a page of results — one statement, not one per dataset.
    An id that no longer resolves is simply absent: access can't be established.
    """
    wanted = set(dataset_ids)
    if not wanted:
        return set()

    from app.modules.catalog.datasets.domain.models import (
        Dataset,
        DatasetGrant,
        Record,
    )

    stmt = (
        select(Dataset.id)
        .join(Record, Record.id == Dataset.record_id)
        .where(Dataset.id.in_(wanted))
    )
    stmt = apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)
    rows = await db.execute(stmt)
    return {row for row in rows.scalars() if row in wanted}


async def visible_lineage_summaries(
    db: AsyncSession,
    records: Sequence[Any],
    user: Identity | None,
    user_roles: set[str],
) -> dict[uuid.UUID, str | None]:
    """Lineage prose per record, with unreachable datasets' titles redacted.

    fix(#1103): ``lineage_summary`` was served raw to every viewer, even
    though the sentence can name a PRIVATE mask/join layer's title —
    the disclosure ``visible_derived_from`` prevents, reaching here
    through an unredacted channel.

    All-or-nothing per requester (see _REDACTED_SUMMARY): a viewer who
    can open every referenced dataset gets the sentence verbatim, else
    the neutral constant. This also covers owner-edited prose safely,
    since unverifiable free text is withheld whole, not edited by guess.

    Records with no ``derived_from`` are untouched, which keeps this
    cheap: the query only runs for analysis outputs on the page.
    """
    referenced: dict[uuid.UUID, list[uuid.UUID | None]] = {}
    for record in records:
        if record.lineage_summary and record.derived_from:
            referenced[record.id] = _provenance_dataset_ids(record.derived_from)

    accessible = await _accessible_dataset_ids(
        db,
        {
            dataset_id
            for ids in referenced.values()
            for dataset_id in ids
            if dataset_id is not None
        },
        user,
        user_roles,
    )

    summaries: dict[uuid.UUID, str | None] = {}
    for record in records:
        summary = record.lineage_summary
        dataset_ids = referenced.get(record.id)
        if summary is None or not dataset_ids:
            summaries[record.id] = summary
            continue
        any_hidden = any(
            dataset_id is None or dataset_id not in accessible
            for dataset_id in dataset_ids
        )
        summaries[record.id] = _REDACTED_SUMMARY if any_hidden else summary
    return summaries


async def visible_lineage_summary(
    db: AsyncSession,
    record: Any,
    user: Identity | None,
    user_roles: set[str],
) -> str | None:
    """One record's access-checked lineage prose. See visible_lineage_summaries."""
    return (await visible_lineage_summaries(db, [record], user, user_roles))[record.id]


def can_view_dataset_provenance(
    record: Any, user: Identity | None, user_roles: set[str]
) -> bool:
    """Owner-or-admin predicate for the provenance projection (#1316).

    ADR-002 amendment: the single provenance projection for every surface
    that carries it. Owner/admin see raw fields (``origin_uri``,
    ``origin_ref``, ``uploaded_by``, ``file_hash``); everyone else gets
    those nulled and keeps only the capability summary (origin kind,
    ``source_freshness``, ``source_health``, ``last_refreshed_at``,
    ``last_checked_at``).
    """
    return bool(user and (record.created_by == user.id or "admin" in user_roles))


async def check_dataset_write_access(
    db: AsyncSession,
    dataset: Any,
    dataset_id: uuid.UUID,
    user: Identity,
    *,
    user_roles: set[str] | None = None,
) -> set[str]:
    """Enforce owner-or-admin for dataset MUTATIONS. Raises 404/403.

    ``check_dataset_access`` is a VISIBILITY check — it lets any authenticated
    user through on a public+published dataset, so it must not gate writes.
    Applies visibility first (404, so we don't leak unreadable datasets),
    then ownership (403). Datasets with no recorded owner
    (``record.created_by`` is NULL) are admin-only.

    Returns the resolved ``user_roles`` set so callers can reuse it downstream.
    """
    user_roles = await check_dataset_access(
        db, dataset, dataset_id, user, user_roles=user_roles
    )
    created_by = dataset.record.created_by
    if created_by is not None and created_by == user.id:
        return user_roles
    if "admin" in user_roles:
        return user_roles
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Only the dataset owner or an admin may modify this dataset.",
    )


async def require_dataset_editing_enabled(db: AsyncSession) -> None:
    """Enforce the `enable_dataset_editing` admin flag. Raises 403 when off.

    fix(#458): the flag gated only the UI (StructureTab), so an owner/admin
    could still edit features and run column DDL through the API with editing
    switched off. Enforce it on those write paths server-side. Metadata edits are
    deliberately *not* gated — the UI keeps only structure/feature editing behind
    this toggle, and the backend mirrors that boundary.
    """
    # Local import mirrors the other persistent_config call sites (e.g.
    # service_metadata's REQUIRE_METADATA_FOR_PUBLISH) and avoids any import cycle.
    from app.core.persistent_config import ENABLE_DATASET_EDITING

    if not await ENABLE_DATASET_EDITING.get(db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dataset editing is disabled by the administrator.",
        )


async def check_public_visibility_allowed(
    db: AsyncSession,
    user: Identity,
    visibility: str | None,
    *,
    user_roles: set[str] | None = None,
) -> set[str] | None:
    """Enforce the `restrict_public_visibility` instance setting (#1691).

    The ONE shared gate for every mutation that accepts a `visibility` value
    (dataset metadata PATCH, ingest paths, STAC import, manifest apply, map
    update). When ON, a non-admin requesting `public` gets a 403; every
    other value passes through, and existing public content is unaffected —
    the gate fires only when a mutation REQUESTS public.

    Pass ``user_roles`` when already resolved to skip a lookup. Returns the
    resolved (or caller-provided) roles, or ``None`` when no lookup happened.
    """
    if visibility != "public":
        return user_roles

    # Local import mirrors the other persistent_config call sites in this
    # module (require_dataset_editing_enabled) and avoids any import cycle.
    from app.core.persistent_config import RESTRICT_PUBLIC_VISIBILITY

    if not await RESTRICT_PUBLIC_VISIBILITY.get(db):
        return user_roles

    if user_roles is None:
        user_roles = await get_user_roles(db, user)
    if "admin" in user_roles:
        return user_roles

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            "Public visibility is restricted to administrators on this "
            "instance. Choose a narrower visibility or ask an admin to "
            "make this content public."
        ),
    )
