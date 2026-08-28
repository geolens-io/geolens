"""Dataset visibility enforcement.

Provides:
- DatasetVisibility enum for public/internal/restricted/private
- apply_visibility_filter() for query-level dataset filtering
- get_user_roles() for role lookup (replaces per-router duplicates)
- check_dataset_access() for per-endpoint visibility checks

SEC-04: All dataset access paths use these shared functions.
Relocated from the deleted auth visibility module (Phase 213).
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

    After the records+datasets refactor, visibility and created_by
    live on the Record model. The grant_cls still references datasets
    via dataset_id.

    Args:
        stmt: An existing SQLAlchemy Select statement.
        user: The currently authenticated User, or None for anonymous access.
        user_roles: Set of role name strings for the user.
        record_cls: The model class with visibility/created_by fields (Record).
        grant_cls: The DatasetGrant model class (optional).

    Returns:
        The filtered Select statement.
    """
    return get_permission_extension().filter_visible(
        stmt, user, user_roles, record_cls, grant_cls
    )


async def get_user_roles(db: AsyncSession, user: Identity) -> set[str]:
    """Role names for a user. The query itself lives in ``auth.permissions``.

    It selects the auth-owned ``Role``/``UserRole`` tables and reads nothing
    catalog, so auth owns it; keeping it callable from here leaves the ~40
    catalog call sites and the ``catalog.authorization`` import path unchanged
    while ``auth.dependencies`` stops importing catalog to get it.

    A delegating def rather than a bare re-export on purpose:
    ``test_permission_chokepoints_use_extension`` reads this file's
    ``async def get_user_roles`` as the end of the ``apply_visibility_filter``
    block it inspects, and tests that patch
    ``catalog.authorization.get_user_roles`` keep working through it.
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

    After refactor, visibility and created_by are on dataset.record.

    Logic:
    - Admins: always allowed
    - Private datasets: only the owner can access
    - Restricted datasets: user must have a grant via their roles
    - Public datasets: always allowed
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

    fix(#1298): ``create_vrt_job`` and the collection-linking route each
    authorized their linked datasets one id at a time — ``get_dataset()`` then
    ``check_dataset_access()`` per id — so a 500-source VRT request cost
    roughly 500 SELECTs plus 500 access checks before the job was even
    queued. This is the batch sibling of ``check_dataset_access``: same
    fail-closed 404, same "first requested id wins" ordering, but the load
    and the visibility computation each run once for the whole set instead
    of once per id.

    Loads every requested dataset (with ``Record`` eager-loaded, mirroring
    ``_load_source_datasets`` in ``router_vrt.py``) in one SELECT, then
    resolves the accessible subset through the same
    ``apply_visibility_filter``/``filter_visible`` seam ``_accessible_dataset_ids``
    uses — so a permission-extension overlay sees the batch path exactly as
    it sees the scalar one, never bypassed for the sake of a query count.
    Raises the same 404 as ``check_dataset_access`` for the first id in
    ``dataset_ids`` (request order) that is missing or denied — a batch that
    fails partway raises without returning anything, matching what the
    scalar loop it replaces would have done.

    Returns every requested dataset keyed by id (only reachable once every
    id has passed).
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


# fix(#1097 review): every provenance param naming a dataset, mapped to the
# params that DESCRIBE that dataset and must be dropped with it.
#
# The keys are what an unauthorized requester must not learn the value of; the
# values are what would still describe the layer once its id was gone. An
# operation that adds a dataset-id param adds a row here, and
# test_every_dataset_id_param_is_redactable fails until it does — the check is
# structural because the failure mode is silence: the leak looks like ordinary
# provenance, and nothing errors.
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

    feat(#765): an analysis output can be shared while the dataset it was
    derived from stays private, so the reference is gated on access to that
    source. It is omitted rather than stubbed: a requester cannot tell
    "not derived from anything" from "derived from something you cannot see",
    which is what keeps the id (and the fact of its existence) from leaking.

    fix(#765 review): the source is not the only dataset in here. A clip
    carries ``params.mask_dataset_id``, and a public output can be derived
    from a public source through a PRIVATE mask layer — so that id is checked
    on its own and dropped when it fails, rather than riding along on the
    source's verdict. A returned dict is always a copy; the caller must not be
    able to mutate the record's JSONB through it.

    fix(#1097 review): driven by ``_DATASET_ID_PARAMS`` rather than by a check
    per id. Spatial join added ``join_dataset_id`` and this function kept
    redacting only the mask, so a public join output derived through a PRIVATE
    join layer published that layer's id — and ``join_fields`` with it, which
    is the layer's column names. That is the same gap #765's review closed for
    the mask, reopened by the next operation to carry a dataset id, which is
    the argument for a table over another branch: an operation that adds one is
    now a row here, and the structural test enforcing that lives in
    ``test_analysis_provenance.py``.

    A source that has since been deleted also yields None: access to it can no
    longer be established, and the prose lineage on the record still reads.
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
        # The id is not the only thing that describes the layer. Dropping
        # join_dataset_id while keeping join_fields would still publish the
        # private layer's column names, which is most of what its schema is.
        for dependent in dependent_params:
            params.pop(dependent, None)
    return {**derived_from, "params": params}


# fix(#1103): the sentence a restricted requester gets instead of the stored
# prose. Deliberately not the dataset's id — _DATASET_ID_PARAMS above exists
# because an id the requester cannot resolve is still a disclosure worth
# withholding, and putting it in the prose would route around the redaction
# that drops it from the reference.
#
# fix(#1108 review): the replacement is ALWAYS the whole sentence — the prose
# is never edited span-by-span. Three review rounds each produced a working
# forgery against in-place editing: an unnamed source shifts every quoted span
# onto the wrong dataset; a title with embedded quotes (odd or even) corrupts
# the span boundaries so fragments of the hidden title survive between them;
# and quote characters in NON-title free text (an actor name) can compensate
# for a missing title so even a quote-character count reads as aligned. The
# sentence interleaves attacker-influenced free text with the secrets, so no
# delimiter arithmetic over it is trustworthy. The unforgeable rule is binary:
# a requester who can read every referenced dataset gets the prose verbatim,
# and one who cannot gets this constant — never any byte of the stored text.
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

    The list-shaped form of the same rule ``check_dataset_access`` applies per
    dataset: both delegate to PermissionExtension, whose ``filter_visible`` and
    ``can_access_dataset`` are written and changed as a pair (see #929/#930).
    A batch is what makes the redaction affordable on a page of results — one
    statement for the whole page rather than one per referenced dataset.

    An id that no longer resolves to a dataset is simply absent from the result:
    access to it cannot be established, so the caller withholds.
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

    fix(#1103): ``records.lineage_summary`` is written once at materialize time
    and was served raw to everyone who could see the OUTPUT — the dataset
    response, the OGC record properties, and the three DCAT exports all read the
    column. For an analysis output the sentence names its source and, since
    #765's clip and #1097's three overlay operations, the second layer's title
    too. So a public clip of a public layer against a PRIVATE mask published
    that mask's title, and the fact that it exists, to every viewer — the
    disclosure ``visible_derived_from`` deliberately prevents for the mask's id,
    arriving through a channel that had no redaction.

    Prose has no per-requester form on its own, so this is the per-requester
    form, and it is deliberately all-or-nothing (see _REDACTED_SUMMARY for the
    three forgeries that killed span editing): a requester who can open every
    dataset the provenance references gets the sentence exactly as stored, and
    one who cannot gets the neutral constant. The entry itself survives either
    way — that a derived dataset HAS provenance is not the secret.

    Records with no ``derived_from`` are returned untouched. Their lineage is
    hand-written or inherited from ingest rather than assembled from other
    datasets' titles, which is also what keeps this cheap: the query below runs
    only for the analysis outputs on the page.

    The all-or-nothing rule is also what makes owner-edited prose safe to
    serve: ``lineage_summary`` is editable metadata, and edited free text can
    embed anything, so it is never partially rewritten — a full-access viewer
    reads it verbatim (an owner who types a private layer's name into it has
    published that name themselves, see apply_analysis_provenance), and a
    restricted viewer gets the constant, because prose that CANNOT be verified
    clean is withheld whole rather than edited by guesswork.
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

    Decided 2026-08-09 (ADR-002 amendment): the refresh-runs redaction model
    (Decision 4e) is the single provenance projection for every surface that
    carries it — dataset reads (single, list, collection), ``/versions/``,
    and refresh-runs itself. The dataset's owner and any admin see raw
    provenance in full (``origin_uri``, ``origin_ref``, ``uploaded_by``,
    ``file_hash``); every other reader of an accessible dataset, named or
    anonymous, gets those fields nulled and keeps only the capability summary
    (origin kind, ``source_freshness``, ``source_health``,
    ``last_refreshed_at``, ``last_checked_at``).

    Extracted from the inline check refresh-runs used before this decision so
    every surface applies the same rule rather than a hand-copied one.
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

    ``check_dataset_access`` is a VISIBILITY check: it lets any authenticated
    user through on a public+published dataset, so it must not gate writes.
    Mutating a dataset (edit metadata, publish/unpublish, change visibility,
    reupload, delete, attributes, relationships, VRT regenerate) requires the
    caller to be the dataset's creator (``record.created_by``) or a global admin.

    Applies the visibility check first (404, so we don't leak datasets the user
    cannot even see), then the ownership check (403). Datasets with no recorded
    owner (``record.created_by`` is NULL — e.g. seeded/imported data, or rows
    whose owner was deleted) are admin-only.

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

    fix(#458 E-11): the flag gated only the UI (StructureTab), so an owner/admin
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

    The ONE shared gate for every mutation that accepts a `visibility` value:
    dataset metadata PATCH, ingest commit/fan-out/register/bulk-register/VRT
    create, STAC import, manifest apply, and map update. When the setting is
    ON, a non-admin requesting `public` gets a 403; every other visibility
    value passes through untouched. Existing public content is unaffected —
    the gate fires only on a mutation that REQUESTS public.

    Pass ``user_roles`` when the caller already resolved them (e.g. after
    ``check_dataset_write_access``) to avoid a second lookup. Returns the
    resolved roles when a lookup happened (or the caller-provided set), so
    callers can reuse them downstream; returns ``None`` untouched when the
    fast paths made a role lookup unnecessary.
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
