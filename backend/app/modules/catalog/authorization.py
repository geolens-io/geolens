"""Dataset visibility enforcement.

All dataset access paths use these shared functions:
DatasetVisibility, apply_visibility_filter(), get_user_roles(),
check_dataset_access().
"""

import enum
import uuid
from dataclasses import replace
from collections.abc import Awaitable, Callable, Iterable, Sequence
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import (
    ColumnElement,
    Select,
    Uuid,
    and_,
    any_,
    bindparam,
    case,
    cast,
    column,
    exists,
    func,
    literal,
    or_,
    select,
    table,
    union_all,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, joinedload

from app.core.geo import VrtExtents, rollup_envelope
from app.core.identity import Identity
from app.core.permissions import EXPORT
from app.modules.auth.permissions import get_effective_permissions
from app.modules.auth.permissions import get_user_roles as _get_user_roles
from app.modules.catalog.write_recheck import (
    PUBLIC_VISIBILITY_DENIED,
    admit_public_visibility,
    admit_writer,
    admitted_public_visibility as admitted_public_visibility,
    forget_public_visibility,
    recheck_dataset_write_access,
)
from app.platform.catalog_locks import lock_catalog_rows
from app.platform.request_credential import (
    DATASET_KEY_SCOPES,
    api_key_credential,
    is_publish_key,
    refuse_publish_key,
)
from app.platform.extensions import (
    DefaultPermissionExtension,
    RecordAudienceQuery,
    get_permission_extension,
)


# catalog.vrt_source_links, whose ORM class belongs to processing.
_VRT_SOURCE_LINKS = table(
    "vrt_source_links",
    column("vrt_dataset_id", Uuid),
    column("source_dataset_id", Uuid),
    schema="catalog",
)


class DatasetVisibility(str, enum.Enum):
    """Controls who can see a dataset."""

    PUBLIC = "public"
    # Internal mirrors MapVisibility: any signed-in user, on a published
    # record.
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

    A publish key acts only on its owner's own objects, so a request it
    authenticates is judged without the owner's admin role.
    """
    roles = await _get_user_roles(db, user)
    if is_publish_key(db):
        roles.discard("admin")
    return roles


async def check_dataset_access_or_anonymous(
    db: AsyncSession, dataset: Any, dataset_id: uuid.UUID, user: Identity | None
) -> set[str]:
    """Enforce visibility for both authenticated and anonymous users.

    Returns the resolved user_roles set (empty for anonymous).
    Anonymous users may only access public + published datasets.
    Authenticated users follow the full RBAC rules via check_dataset_access().
    """
    if user is None:
        if not await _anonymous_may_read(db, dataset, dataset_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
            )
        return set()
    return await check_dataset_access(db, dataset, dataset_id, user)


async def _anonymous_may_read(
    db: AsyncSession, dataset: Any, dataset_id: uuid.UUID
) -> bool:
    """Whether a caller with no identity may read *dataset*."""
    return await get_permission_extension().can_access_dataset(
        db,
        dataset,
        dataset_id,
        None,
        user_roles=set(),
    )


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

    Batch sibling of ``check_dataset_access``: one SELECT plus one
    ``apply_visibility_filter`` pass, where a per-id loop costs ~1000
    queries for a 500-id VRT request. Same visibility seam as
    ``_accessible_dataset_ids``, same 404 as the scalar path.

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


# Every provenance param naming a dataset, mapped to what describes it and
# must drop with it. test_every_dataset_id_param_is_redactable enforces that
# each dataset-id param has a row.
_DATASET_ID_PARAMS: dict[str, tuple[str, ...]] = {
    "mask_dataset_id": ("mask_filter",),
    "join_dataset_id": ("join_fields", "join_filter"),
}


async def visible_derived_from(
    db: AsyncSession,
    derived_from: dict | None,
    user: Identity | None,
    user_roles: set[str],
) -> dict | None:
    """The provenance reference, with every dataset id in it access-checked.

    Omitted, not stubbed: a requester must not be able to tell "not derived
    from anything" from "derived from something you cannot see".
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
        # Dropping join_dataset_id alone would still publish join_fields and
        # the layer filters: the private layer's column names and values.
        for dependent in dependent_params:
            params.pop(dependent, None)
    return {**derived_from, "params": params}


# Never the dataset's id: _DATASET_ID_PARAMS already redacts that, and
# putting it in the prose would route around it.
#
# Never edit the prose span-by-span, because span boundaries can be forged.
# Binary rule: full prose if every referenced dataset is accessible, else
# this constant, never a byte of it.
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
    PermissionExtension. Batching is what makes redaction affordable on a
    page of results: one statement, not one per dataset. An id that no
    longer resolves is absent, since access can't be established.
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


async def datasets_account_can_read(
    db: AsyncSession, dataset_ids: Iterable[uuid.UUID], user_id: uuid.UUID | None
) -> set[uuid.UUID]:
    """The subset of ``dataset_ids`` the account ``user_id`` may read now.

    Empty for an account that is missing or that sign-in would refuse.
    """
    wanted = set(dataset_ids)
    if user_id is None or not wanted:
        return set()

    from app.modules.auth.models import User

    account = await db.get(User, user_id)
    if account is None or not account.is_active or account.status != "active":
        return set()
    # User.roles loads with the account, so the role set costs no extra query.
    user_roles = {role.name for role in account.roles}
    return await _accessible_dataset_ids(db, wanted, account, user_roles)


async def visible_lineage_summaries(
    db: AsyncSession,
    records: Sequence[Any],
    user: Identity | None,
    user_roles: set[str],
) -> dict[uuid.UUID, str | None]:
    """Lineage prose per record, with unreachable datasets' titles redacted.

    Served raw, ``lineage_summary`` would hand any viewer the title of a
    PRIVATE mask/join layer the sentence names: the disclosure
    ``visible_derived_from`` prevents, through an unredacted channel.

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


async def visible_vrt_source_counts(
    db: AsyncSession,
    vrt_dataset_ids: Iterable[uuid.UUID],
    user: Identity | None,
    user_roles: set[str],
) -> dict[uuid.UUID, int]:
    """How many of each VRT's member datasets this requester may read.

    Member lists omit the members a requester cannot read, so a count of every
    link would tell them how many are hidden. Each requested VRT gets an entry.
    The count stays in SQL: one page can link more members than a statement
    has bind parameters.
    """
    wanted = set(vrt_dataset_ids)
    if not wanted:
        return {}

    from app.modules.catalog.datasets.domain.models import (
        Dataset,
        DatasetGrant,
        Record,
    )

    links = _VRT_SOURCE_LINKS
    stmt = (
        select(links.c.vrt_dataset_id, func.count(links.c.source_dataset_id.distinct()))
        .join(Dataset, Dataset.id == links.c.source_dataset_id)
        .join(Record, Record.id == Dataset.record_id)
        .where(
            links.c.vrt_dataset_id
            == any_(bindparam("vrt_ids", list(wanted), type_=ARRAY(Uuid)))
        )
        .group_by(links.c.vrt_dataset_id)
    )
    stmt = apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)
    counts = dict.fromkeys(wanted, 0)
    for vrt_id, count in (await db.execute(stmt)).all():
        counts[vrt_id] = count
    return counts


async def visible_vrt_extents(
    db: AsyncSession,
    vrt_dataset_ids: Iterable[uuid.UUID],
    user: Identity | None,
    user_roles: set[str],
) -> VrtExtents:
    """Each VRT's extent as this requester sees it; see :func:`visible_extent_column`.

    Every existing VRT among ``vrt_dataset_ids`` gets an entry, None when the
    requester can read no member's extent. ``narrowed`` names the VRTs with a
    member the requester cannot read, whose full-mosaic size is withheld too.
    """
    wanted = set(vrt_dataset_ids)
    if not wanted:
        return VrtExtents({}, ())

    from app.modules.catalog.datasets.domain.models import Dataset, Record

    hides_member, shown = _vrt_view(user, user_roles)
    rows = await db.execute(
        select(Dataset.id, shown, hides_member)
        .join(Record, Record.id == Dataset.record_id)
        .where(
            Dataset.id == any_(bindparam("vrt_ids", list(wanted), type_=ARRAY(Uuid))),
            Record.record_type == "vrt_dataset",
        )
    )
    rows = rows.tuples().all()
    return VrtExtents(
        {dataset_id: extent for dataset_id, extent, _ in rows},
        (dataset_id for dataset_id, _, narrowed in rows if narrowed),
    )


def visible_extent_column(
    user: Identity | None, user_roles: set[str], record: Any = None
) -> ColumnElement:
    """``record.spatial_extent`` as this requester sees it.

    ``record`` defaults to ``Record`` in a statement that joins ``Dataset``; an
    aliased ``Record`` finds its dataset itself. A VRT's stored extent covers
    every member, so one with a member the requester cannot read shows the
    envelope of the members they can read (:func:`rollup_envelope`), or NULL
    when none has an extent. Every other row shows its own. Members are
    checked one by one, so the cost stays with VRT rows.
    """
    return _vrt_view(user, user_roles, record)[1]


def _vrt_view(
    user: Identity | None, user_roles: set[str], record: Any = None
) -> tuple[ColumnElement, ColumnElement]:
    """``(narrowed, shown extent)`` for ``record``; see :func:`visible_extent_column`."""
    from app.modules.catalog.datasets.domain.models import (
        Dataset,
        DatasetGrant,
        Record,
    )

    if record is None:
        record, dataset_id = Record, Dataset.id
    else:
        dataset_id = (
            select(Dataset.id)
            .where(Dataset.record_id == record.id)
            .correlate(record)
            .scalar_subquery()
        )
    links = _VRT_SOURCE_LINKS
    member = aliased(Dataset)
    member_record = aliased(Record)

    def readable(stmt: Select[Any]) -> Select[Any]:
        return apply_visibility_filter(
            stmt.join(member_record, member_record.id == member.record_id),
            user,
            user_roles,
            member_record,
            DatasetGrant,
        )

    of_row = links.c.vrt_dataset_id == dataset_id
    readable_envelope = readable(
        select(rollup_envelope(member_record.spatial_extent))
        .select_from(links.join(member, member.id == links.c.source_dataset_id))
        .where(of_row)
    ).scalar_subquery()
    member_is_readable = readable(
        select(member.id).where(member.id == links.c.source_dataset_id)
    ).exists()
    narrowed = and_(
        record.record_type == "vrt_dataset",
        exists().where(of_row, ~member_is_readable),
    )
    return narrowed, case((narrowed, readable_envelope), else_=record.spatial_extent)


def visible_extent_match(
    user: Identity | None,
    user_roles: set[str],
    match: Callable[[ColumnElement], ColumnElement],
    *,
    record: Any = None,
    missing_as_empty: bool = True,
) -> ColumnElement:
    """Rows whose extent, as this requester sees it, satisfies ``match``.

    Each arm tests one row's own extent, so the result composes under NOT and
    OR like ``match`` itself. The VRT arm never reads a stored VRT extent; the
    VRTs' record ids, not their extents, give it an index path. A VRT that
    shows no extent is tested as an empty geometry, so a predicate and its
    negation both answer for it; ``missing_as_empty=False`` keeps the NULL for
    an IS NULL test.
    """
    from app.modules.catalog.datasets.domain.models import Dataset, Record

    shown = visible_extent_column(user, user_roles, record)
    if missing_as_empty:
        shown = func.coalesce(
            shown, func.ST_GeomFromText("GEOMETRYCOLLECTION EMPTY", 4326)
        )
    record = Record if record is None else record
    vrt = aliased(Dataset)
    vrt_record_ids = (
        select(
            func.coalesce(
                func.array_agg(vrt.record_id), cast(literal("{}"), ARRAY(Uuid))
            )
        )
        .where(vrt.id.in_(select(_VRT_SOURCE_LINKS.c.vrt_dataset_id)))
        .correlate(None)
        .scalar_subquery()
    )
    own_view = and_(
        record.record_type == "vrt_dataset",
        record.id == any_(cast(vrt_record_ids, ARRAY(Uuid))),
    )
    return or_(
        and_(~own_view, match(record.spatial_extent)), and_(own_view, match(shown))
    )


def can_view_dataset_provenance(
    record: Any, user: Identity | None, user_roles: set[str]
) -> bool:
    """Owner-or-admin predicate for the provenance projection.

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

    ``check_dataset_access`` is a VISIBILITY check: it lets any authenticated
    user through on a public+published dataset, so it must not gate writes.
    Applies visibility first (404, so we don't leak unreadable datasets),
    then ownership (403). Datasets with no recorded owner
    (``record.created_by`` is NULL) are admin-only.

    Returns the resolved ``user_roles`` set so callers can reuse it downstream.
    The caller is checked again once the write holds the catalog row lock; see
    :func:`~app.modules.catalog.write_recheck.recheck_dataset_write_access`.
    """
    user_roles = await check_dataset_access(
        db, dataset, dataset_id, user, user_roles=user_roles
    )
    created_by = dataset.record.created_by
    if (created_by is not None and created_by == user.id) or "admin" in user_roles:
        admit_writer(db, ("dataset", dataset_id), user)
        return user_roles
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail=DATASET_WRITE_DENIED
    )


DATASET_WRITE_DENIED = "Only the dataset owner or an admin may modify this dataset."


async def lock_dataset_rows_for_write(
    db: AsyncSession, dataset: Any, *, raster_asset_cls: Any = None, also: Any = None
) -> None:
    """Take the dataset's catalog rows in the house order, then re-check the
    writer :func:`check_dataset_write_access` admitted, with its 404 or 403.

    ``also`` is a second dataset whose rows the write references. Both pairs
    are taken in dataset id order, so two writes between the same datasets
    in opposite directions queue instead of deadlocking.

    The terms of :func:`~app.platform.catalog_locks.lock_catalog_rows`: call it
    before the transaction's first write to either row, after any network I/O.
    """
    from app.modules.catalog.datasets.domain.models import Dataset, Record

    held = {dataset.id: dataset} | ({also.id: also} if also is not None else {})
    for dataset_id in sorted(held):
        await lock_catalog_rows(
            db,
            dataset_cls=Dataset,
            record_cls=Record,
            dataset_id=dataset_id,
            record_id=held[dataset_id].record_id,
            raster_asset_cls=raster_asset_cls if dataset_id == dataset.id else None,
        )
    await recheck_dataset_write_access(db, dataset)


async def require_dataset_editing_enabled(
    db: AsyncSession, dataset_id: uuid.UUID | None = None
) -> None:
    """Enforce the `enable_dataset_editing` admin flag. Raises 403 when off.

    The flag gates feature edits and column DDL through the API as well as the
    UI; metadata edits stay ungated, matching the UI.

    A request authenticated by a dataset key bound to ``dataset_id`` skips the
    flag for that dataset's feature writes: minting the key is how an editor
    opts a webhook in while the instance keeps editing off.
    """
    credential = api_key_credential(db)
    if (
        dataset_id is not None
        and credential is not None
        and credential.scope in DATASET_KEY_SCOPES
        and credential.dataset_id == dataset_id
    ):
        return

    # Local import, as at the other persistent_config call sites, to avoid an
    # import cycle.
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
    """Enforce the `restrict_public_visibility` instance setting.

    The ONE shared gate for every mutation that accepts a `visibility` value
    (dataset metadata PATCH, ingest paths, STAC import, manifest apply, map
    update). When ON, a non-admin requesting `public` gets a 403; every
    other value passes through, and existing public content is unaffected:
    the gate fires only when a mutation REQUESTS public. A publish key is
    refused every request for public, whatever the setting and even for
    content already public: that takes a signed-in user or a full key.

    Pass ``user_roles`` when already resolved to skip a lookup. Returns the
    resolved (or caller-provided) roles, or ``None`` when no lookup happened.
    An admin it lets through is recorded, and the write's lock checks again
    that they are still one. The record follows the caller's latest check.
    """
    forget_public_visibility(db, user.id)
    if visibility != "public":
        return user_roles
    refuse_publish_key(db, "A publish key can't make anything public")

    # Local import to avoid an import cycle, as above.
    from app.core.persistent_config import RESTRICT_PUBLIC_VISIBILITY

    if not await RESTRICT_PUBLIC_VISIBILITY.get(db):
        return user_roles

    if user_roles is None:
        user_roles = await get_user_roles(db, user)
    if "admin" in user_roles:
        admit_public_visibility(db, user.id)
        return user_roles

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail=PUBLIC_VISIBILITY_DENIED
    )


async def can_download_raster_cog(
    db: AsyncSession,
    dataset: Any,
    user: Identity | None,
    user_roles: set[str] | None = None,
    *,
    may_export: bool | None = None,
) -> bool:
    """Whether the COG download route would serve *dataset* to a caller who
    can already see it: :func:`can_export_dataset` for a raster.
    """
    if dataset.record.record_type != "raster_dataset":
        return False
    return await can_export_dataset(
        db, dataset, dataset.id, user, user_roles, may_export=may_export
    )


async def can_export_dataset(
    db: AsyncSession,
    dataset: Any,
    dataset_id: uuid.UUID,
    user: Identity | None,
    user_roles: set[str] | None = None,
    *,
    may_export: bool | None = None,
) -> bool:
    """Whether a caller who can already see *dataset* may download its data.

    The export capability covers file downloads and durable copies: the
    ``/export`` route, ``/download/cog`` and the STAC ``data`` href of a stored raster
    file, and analysis materialize. Paged reads through the API, map tiles,
    the attribute table, COPC and 3D Tiles files, and hrefs that point at a
    remote origin follow read access instead.

    Every caller may download a public dataset an anonymous caller can read,
    so signing in never takes away what signing out gives; anything beyond
    that needs the export capability. ``may_export`` is that capability when
    the caller already resolved it with :func:`can_export`.
    """
    if user is not None:
        if may_export is None:
            may_export = await can_export(db, user, user_roles)
        if may_export:
            return True
    return dataset.record.visibility == DatasetVisibility.PUBLIC.value and (
        await _anonymous_may_read(db, dataset, dataset_id)
    )


async def can_export(
    db: AsyncSession, user: Identity | None, user_roles: set[str] | None = None
) -> bool:
    """Whether *user* holds the export capability. It depends on the caller
    alone, so a page of items resolves it once."""
    if user is None:
        return False
    if user_roles is None:
        user_roles = await get_user_roles(db, user)
    return await get_permission_extension().check_permission(
        db,
        user,
        EXPORT,
        user_roles=user_roles,
        permission_matrix=await get_effective_permissions(db),
    )


def answers_audience_questions(permission: object) -> bool:
    """Whether this permission authority's ``record_audience`` can be trusted.

    False when it has none, or when it inherits the community answer while
    overriding a method that decides reads: the reported audience and what
    viewers get could then disagree. ``check_permission`` is not in the set,
    since capabilities don't decide which records a viewer can read.
    """
    default = DefaultPermissionExtension
    own = getattr(type(permission), "record_audience", None)
    if own is None:
        return False
    if own is not default.record_audience:
        return True
    return all(
        getattr(type(permission), name, None) is getattr(default, name)
        for name in ("filter_visible", "can_access_dataset")
    )


VRT_AUDIENCE_EXCEEDS_SOURCES = (
    "This VRT would reach people who cannot see all of its source datasets. "
    "Narrow the VRT's visibility or use sources its audience can see."
)


# Each pair binds its own audience arms; this keeps one statement well under
# the 32767 parameters Postgres accepts.
_AUDIENCE_PAIRS_PER_STATEMENT = 500


async def _audiences_exceeded(
    db: AsyncSession, pairs: Sequence[tuple[Any, Any]]
) -> list[bool]:
    """For each ``(vrt, member)`` RecordAudienceQuery pair: may somebody who
    can read the VRT be unable to read the member?

    A member the VRT's owner also owns and can read never counts: publishing
    a mosaic of one's own data is the owner's choice, as exporting it would
    be. An account the authority leaves unclassified (NULL) counts as unable,
    as in the shared-map guard. An authority that can't answer
    (:func:`answers_audience_questions`) gets every pair counted.
    """
    if len(pairs) > _AUDIENCE_PAIRS_PER_STATEMENT:
        step = _AUDIENCE_PAIRS_PER_STATEMENT
        return [
            flag
            for start in range(0, len(pairs), step)
            for flag in await _audiences_exceeded(db, pairs[start : start + step])
        ]

    from app.modules.auth.models import User
    from app.modules.catalog.datasets.domain.models import DatasetGrant

    permission = get_permission_extension()
    if not answers_audience_questions(permission):
        return [True] * len(pairs)
    audiences = [
        (
            await permission.record_audience(vrt, User, grant_cls=DatasetGrant),
            await permission.record_audience(member, User, grant_cls=DatasetGrant),
        )
        for vrt, member in pairs
    ]
    if not audiences:
        return []
    # One statement whatever the member count. An "x" row names a pair where a
    # reader of the VRT may be outside the member; an "o" row, a shared owner
    # who can read the member.
    arms = [
        select(literal(index), literal("x")).where(
            select(User.id)
            .where(User.is_active.is_(True))
            .where(User.status == "active")
            .where(outer.users.is_not(False))
            .where(inner.users.is_not(True))
            .exists()
        )
        for index, (outer, inner) in enumerate(audiences)
    ]
    shared = [
        index for index, (vrt, member) in enumerate(pairs) if _shares_owner(vrt, member)
    ]
    arms += [
        select(literal(index), literal("o")).where(
            audience_admits(audiences[index][1], pairs[index][0].owner_id)
        )
        for index in shared
    ]
    statement = arms[0] if len(arms) == 1 else union_all(*arms)
    rows = {(index, kind) for index, kind in (await db.execute(statement)).all()}
    return [
        (index, "o") not in rows
        and (
            (index, "x") in rows
            or (outer.includes_anonymous and not inner.includes_anonymous)
        )
        for index, (outer, inner) in enumerate(audiences)
    ]


async def _record_audience_queries(
    db: AsyncSession, dataset_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, tuple[RecordAudienceQuery, str]]:
    """Each dataset's current audience question and title, keyed by dataset id."""
    wanted = set(dataset_ids)
    if not wanted:
        return {}

    from app.modules.catalog.datasets.domain.models import Dataset, Record

    rows = await db.execute(
        select(
            Dataset.id,
            Record.id.label("record_id"),
            Record.created_by,
            Record.visibility,
            Record.record_status,
            Record.title,
        )
        .join(Record, Record.id == Dataset.record_id)
        .where(Dataset.id == any_(bindparam("wanted", list(wanted), type_=ARRAY(Uuid))))
    )
    return {
        row.id: (
            RecordAudienceQuery(
                dataset_id=row.id,
                record_id=row.record_id,
                owner_id=row.created_by,
                visibility=row.visibility,
                record_status=row.record_status,
            ),
            row.title,
        )
        for row in rows.all()
    }


async def vrt_member_ids(
    db: AsyncSession, vrt_dataset_id: uuid.UUID
) -> list[uuid.UUID]:
    """The source datasets currently linked into a VRT."""
    links = _VRT_SOURCE_LINKS
    rows = await db.execute(
        select(links.c.source_dataset_id).where(
            links.c.vrt_dataset_id == vrt_dataset_id
        )
    )
    return list(rows.scalars())


def dataset_audience_query(dataset: Any) -> RecordAudienceQuery:
    """The audience question for a loaded dataset as it stands."""
    record = dataset.record
    return RecordAudienceQuery(
        dataset_id=dataset.id,
        record_id=record.id,
        owner_id=record.created_by,
        visibility=record.visibility,
        record_status=record.record_status,
    )


def audience_admits(audience: Any, user_id: uuid.UUID | None) -> Any:
    """EXISTS clause: the account ``user_id`` is in ``audience``.

    An account the authority leaves unclassified (NULL) is not in it.
    """
    from app.modules.auth.models import User

    return (
        select(User.id)
        .where(User.id == user_id)
        .where(audience.users.is_(True))
        .exists()
    )


def _shares_owner(vrt: RecordAudienceQuery, member: RecordAudienceQuery) -> bool:
    return vrt.owner_id is not None and vrt.owner_id == member.owner_id


async def vrt_members_beyond_audience(
    db: AsyncSession, member_ids: Iterable[uuid.UUID], vrt: RecordAudienceQuery
) -> list[uuid.UUID]:
    """Members that somebody in ``vrt``'s audience cannot read.

    A mosaic serves its members' pixels to everyone who can read the mosaic,
    so each member's audience has to contain the mosaic's, unless the
    mosaic's owner (``vrt.owner_id``) also owns and can read the member.
    """
    members = await _record_audience_queries(db, member_ids)
    ids = list(members)
    flags = await _audiences_exceeded(db, [(vrt, members[i][0]) for i in ids])
    return [dataset_id for dataset_id, flag in zip(ids, flags, strict=True) if flag]


async def vrts_beyond_member_audience(
    db: AsyncSession,
    vrts: Sequence[tuple[RecordAudienceQuery, Iterable[uuid.UUID]]],
) -> list[bool]:
    """For each ``(vrt, member_ids)``: does a member lie beyond the VRT's
    audience? :func:`vrt_members_beyond_audience` for many VRTs in two
    statements."""
    listed = [(vrt, list(member_ids)) for vrt, member_ids in vrts]
    members = await _record_audience_queries(
        db, {member for _, ids in listed for member in ids}
    )
    pairs = [
        (index, vrt, members[member][0])
        for index, (vrt, ids) in enumerate(listed)
        for member in ids
        if member in members
    ]
    flags = await _audiences_exceeded(db, [(vrt, member) for _, vrt, member in pairs])
    beyond = [False] * len(listed)
    for (index, _, _), flag in zip(pairs, flags, strict=True):
        beyond[index] = beyond[index] or flag
    return beyond


async def vrt_links_beyond_audience(
    db: AsyncSession, dataset_ids: Iterable[uuid.UUID]
) -> dict[tuple[uuid.UUID, uuid.UUID], str]:
    """Each ``(vrt, member)`` link with either end in ``dataset_ids`` whose VRT
    reaches past the member as the catalog stands now, mapped to the VRT's
    title."""
    wanted = bindparam("wanted", list(set(dataset_ids)), type_=ARRAY(Uuid))
    links = _VRT_SOURCE_LINKS
    rows = await db.execute(
        select(links.c.vrt_dataset_id, links.c.source_dataset_id).where(
            or_(
                links.c.vrt_dataset_id == any_(wanted),
                links.c.source_dataset_id == any_(wanted),
            )
        )
    )
    pairs = [tuple(row) for row in rows.all()]
    queries = await _record_audience_queries(db, {i for pair in pairs for i in pair})
    pairs = [pair for pair in pairs if pair[0] in queries and pair[1] in queries]
    flags = await _audiences_exceeded(
        db, [(queries[vrt][0], queries[member][0]) for vrt, member in pairs]
    )
    return {
        pair: queries[pair[0]][1]
        for pair, flag in zip(pairs, flags, strict=True)
        if flag
    }


async def check_vrt_within_member_audience(
    db: AsyncSession, member_ids: Iterable[uuid.UUID], vrt: RecordAudienceQuery
) -> None:
    """Raise 422 when the VRT described by ``vrt`` would reach past a member."""
    if await vrt_members_beyond_audience(db, member_ids, vrt):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=VRT_AUDIENCE_EXCEEDS_SOURCES,
        )


async def check_vrt_serves(db: AsyncSession, dataset: Any) -> None:
    """Raise 409 for a VRT that reaches past one of its members, the answer its
    tiles give; any other dataset passes."""
    if dataset.record.record_type != "vrt_dataset":
        return
    member_ids = await vrt_member_ids(db, dataset.id)
    if await vrt_members_beyond_audience(
        db, member_ids, dataset_audience_query(dataset)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A source of this mosaic is not visible to everyone who can see it",
        )


async def check_vrt_members(
    db: AsyncSession, vrt_dataset: Any, *, adding: uuid.UUID | None = None
) -> None:
    """Raise 422 when a VRT, with ``adding`` linked too, reaches past a member."""
    member_ids = await vrt_member_ids(db, vrt_dataset.id)
    if adding is not None:
        member_ids.append(adding)
    await check_vrt_within_member_audience(
        db, member_ids, dataset_audience_query(vrt_dataset)
    )


async def check_vrt_audiences_after_change(
    db: AsyncSession,
    dataset: Any,
    *,
    visibility: str | None = None,
    record_status: str | None = None,
    owner_id: uuid.UUID | None = None,
    regrant: Callable[[], Awaitable[object]] | None = None,
) -> None:
    """Raise 422 when a new visibility, status or owner (None keeps the current
    one) would make a VRT reach past a member it doesn't reach past now.

    A VRT is compared with its members. A source is compared only on a
    transfer, with the VRTs its previous and incoming owners own, whose
    shared-owner exemption the transfer moves; other users' VRTs stop serving
    tiles instead of refusing a change.
    Only a newly exceeded member is refused, so a VRT can always narrow.
    ``regrant``, when given, changes the dataset's grants; it runs once,
    between the two measurements, and does not commit.
    """
    record = dataset.record
    before = dataset_audience_query(dataset)
    after = replace(
        before,
        visibility=visibility or before.visibility,
        record_status=record_status or before.record_status,
        owner_id=owner_id or before.owner_id,
    )
    if after == before and regrant is None:
        return
    is_vrt = record.record_type == "vrt_dataset"
    if is_vrt:
        linked = await _record_audience_queries(
            db, await vrt_member_ids(db, dataset.id)
        )
        pairs = [((before, q), (after, q), t) for q, t in linked.values()]
    else:
        vrt_ids = (
            []
            if after.owner_id == before.owner_id
            else await _owner_vrt_ids(db, dataset, {before.owner_id, after.owner_id})
        )
        linked = await _record_audience_queries(db, vrt_ids)
        pairs = [((q, before), (q, after), t) for q, t in linked.values()]
    then = await _audiences_exceeded(db, [pair[0] for pair in pairs])
    if regrant is not None:
        await regrant()
    now = await _audiences_exceeded(db, [pair[1] for pair in pairs])
    newly = sorted(
        pair[2]
        for pair, was, is_ in zip(pairs, then, now, strict=True)
        if is_ and not was
    )
    if newly:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=VRT_AUDIENCE_EXCEEDS_SOURCES
            if is_vrt
            else "This dataset is a source of VRTs that would reach people who "
            f"cannot see it: {', '.join(newly)}",
        )


async def _owner_vrt_ids(
    db: AsyncSession, dataset: Any, owner_ids: set[uuid.UUID | None]
) -> list[uuid.UUID]:
    """VRTs linking ``dataset`` that one of ``owner_ids`` owns."""
    owners = owner_ids - {None}
    if not owners:
        return []

    from app.modules.catalog.datasets.domain.models import Dataset, Record

    links = _VRT_SOURCE_LINKS
    rows = await db.execute(
        select(links.c.vrt_dataset_id)
        .join(Dataset, Dataset.id == links.c.vrt_dataset_id)
        .join(Record, Record.id == Dataset.record_id)
        .where(links.c.source_dataset_id == dataset.id)
        .where(Record.created_by.in_(owners))
    )
    return list(rows.scalars())
