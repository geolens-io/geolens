"""Inherited-keyword derivation for analysis-derived records (feat #1070).

``apply_analysis_provenance`` copies the source's keyword rows without
marking them; recovered at read time by intersecting keyword sets via
``Record.derived_from``. Access gates on ``visible_derived_from``;
audience-widening checks route through ``record_audience`` (#1068).

Accepted limitation (#1178): deleting a source keyword leaves the copied row
in place but drops it from the inherited set, losing its badge and the
publish-moment warning.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.modules.auth.models import User
from app.modules.catalog.authorization import get_user_roles, visible_derived_from
from app.modules.catalog.datasets.domain.models import (
    Dataset,
    DatasetGrant,
    Record,
    RecordKeyword,
)
from app.platform.extensions import get_permission_extension
from app.platform.extensions.protocols import RecordAudienceQuery

logger = structlog.stdlib.get_logger(__name__)

KeywordKey = tuple[str, str | None, str]
"""(keyword, vocabulary_uri, keyword_type) — the copied columns, so identity
matches what ``apply_analysis_provenance``'s INSERT..SELECT carried across."""


@dataclass(frozen=True)
class InheritedSource:
    """The dataset a record was derived from, resolved to its catalog record."""

    dataset_id: uuid.UUID
    record: Record


async def resolve_inherited_source(
    session: AsyncSession, record: Record
) -> InheritedSource | None:
    """The source record ``record`` inherited keywords from, or None.

    None for a record that is not analysis-derived, for an unparseable
    ``derived_from.dataset_id``, and for a source dataset that has since been
    deleted — in every case there is nothing left to attribute inheritance to,
    matching how ``visible_derived_from`` treats a gone source.
    """
    derived_from = record.derived_from
    raw = derived_from.get("dataset_id") if isinstance(derived_from, dict) else None
    try:
        source_dataset_id = uuid.UUID(str(raw))
    except (TypeError, ValueError):
        return None
    source_record = (
        await session.execute(
            select(Record)
            .join(Dataset, Dataset.record_id == Record.id)
            .where(Dataset.id == source_dataset_id)
        )
    ).scalar_one_or_none()
    if source_record is None:
        return None
    return InheritedSource(dataset_id=source_dataset_id, record=source_record)


async def inherited_keyword_keys(
    session: AsyncSession, record: Record, source: InheritedSource
) -> set[KeywordKey]:
    """Keyword triples present on BOTH the record and its source.

    The intersection, not the source set: a copied keyword the owner has since
    deleted is no longer theirs to disclose, and a keyword they typed that
    happens to match one on the source is indistinguishable from the copy —
    treating it as inherited errs toward warning, which is the cheap error.
    """
    own = select(
        RecordKeyword.keyword,
        RecordKeyword.vocabulary_uri,
        RecordKeyword.keyword_type,
    ).where(RecordKeyword.record_id == record.id)
    theirs = select(
        RecordKeyword.keyword,
        RecordKeyword.vocabulary_uri,
        RecordKeyword.keyword_type,
    ).where(RecordKeyword.record_id == source.record.id)
    rows = await session.execute(own.intersect(theirs))
    return {(row[0], row[1], row[2]) for row in rows.all()}


async def audience_exceeds_source(
    session: AsyncSession,
    *,
    record: Record,
    dataset_id: uuid.UUID | None,
    source: InheritedSource,
    visibility: str | None = None,
    record_status: str | None = None,
) -> bool:
    """Can anyone read ``record`` who cannot read its source?

    ``visibility``/``record_status`` let a caller ask the counterfactual —
    "would publishing this widen past the source?" (#1070). An authority
    without ``record_audience`` can't answer, so it warns (over-warning is
    cheap here — this gates dialog prose, not a result-set row). NULL
    handling follows ``_stranded_viewer_exists`` in
    ``maps/service_public.py``: an unclassifiable account warns too.
    """
    permission = get_permission_extension()
    if getattr(type(permission), "record_audience", None) is None:
        return True
    derived_audience = await permission.record_audience(
        RecordAudienceQuery(
            dataset_id=dataset_id,
            record_id=record.id,
            owner_id=record.created_by,
            visibility=visibility or record.visibility,
            record_status=record_status or record.record_status,
        ),
        User,
        grant_cls=DatasetGrant,
    )
    source_audience = await permission.record_audience(
        RecordAudienceQuery(
            dataset_id=source.dataset_id,
            record_id=source.record.id,
            owner_id=source.record.created_by,
            visibility=source.record.visibility,
            record_status=source.record.record_status,
        ),
        User,
        grant_cls=DatasetGrant,
    )
    if derived_audience.includes_anonymous and not source_audience.includes_anonymous:
        return True
    stmt = (
        select(User.id)
        .where(User.is_active.is_(True))
        .where(User.status == "active")
        .where(derived_audience.users.is_not(False))
        .where(source_audience.users.is_not(True))
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def disclosed_inherited_keywords(
    session: AsyncSession,
    record: Record,
    dataset_id: uuid.UUID | None,
    *,
    actor: "Identity | None",
) -> list[str]:
    """Inherited keywords readable, at the record's CURRENT state, by someone
    who cannot open the source. Empty when there is nothing to warn about.

    fix(#1178): gated on ``actor``'s access to the SOURCE — otherwise an
    output owner who lost source access could add a guessed keyword, PATCH
    their record, and read the warning as confirmation the guess exists
    there. No source access means no warning either, or that would disclose
    the very association being redacted.
    """
    # Settle "not derived at all" before any query — role resolution and the
    # gate itself only make sense once there is a source to gate.
    if not record.derived_from:
        return []
    actor_roles = set() if actor is None else await get_user_roles(session, actor)
    source_ref = await visible_derived_from(
        session, record.derived_from, actor, actor_roles
    )
    if source_ref is None:
        return []
    source = await resolve_inherited_source(session, record)
    if source is None:
        return []
    keys = await inherited_keyword_keys(session, record, source)
    if not keys:
        return []
    if not await audience_exceeds_source(
        session, record=record, dataset_id=dataset_id, source=source
    ):
        return []
    return sorted({key[0] for key in keys})


async def inherited_keyword_disclosure_warning(
    session: AsyncSession,
    record: Record,
    dataset_id: uuid.UUID | None,
    *,
    actor: "Identity | None",
) -> str | None:
    """The advisory warning every resolved-state audience writer emits, or None.

    fix(#1178): one shared helper, called AFTER state resolves — an inline
    check in ``update_user_metadata`` alone missed ``set_target_status``,
    letting a draft public output publish with no warning. Creation-time
    writers are not callers (nothing can be analysis-derived yet); ``actor``
    gates on source access, same as ``disclosed_inherited_keywords``.
    """
    disclosed = await disclosed_inherited_keywords(
        session, record, dataset_id, actor=actor
    )
    if not disclosed:
        return None
    logger.warning(
        "dataset.inherited_keywords_reach_beyond_source",
        dataset_id=str(dataset_id),
        keywords=disclosed,
    )
    return (
        "Keywords inherited from the source dataset are now visible to "
        "people who cannot open that source: " + ", ".join(disclosed)
    )
