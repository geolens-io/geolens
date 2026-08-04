"""Inherited-keyword derivation for analysis-derived records (feat #1070).

``apply_analysis_provenance`` copies the source record's keyword rows onto a
materialized analysis output. Nothing marks those rows, by decision: marking
them would cost a migration and a backfill, while the inherited set is
recoverable at read time by resolving ``Record.derived_from`` to the source
record and intersecting keyword sets. That derivation lives here.

Two questions, two audiences:

* Which of this record's keywords are inherited? The intersection of its
  keyword triples with the source record's. Read-side callers gate this on the
  requester being able to access the source (the ``visible_derived_from``
  rule), so a requester who cannot see the source also cannot tell "not
  derived" from "derived from something you cannot see".
* Does this record's audience reach beyond the source's? Asked of the
  permission authority via ``record_audience`` (#1068), so an overlay's policy
  answers rather than a restatement of the community ladder. This is what
  makes an inherited keyword worth warning about: it is only consequential
  when someone who cannot open the source can read it here.

Accepted limitation (#1178 review): deleting a keyword on the SOURCE also
empties the intersection here, so the copied row on the derived record loses
its badge and stops triggering the publish-moment warning even though the
copy still exists. That is the read-time route working as decided: row
marking was rejected (it costs a migration and a backfill), and a source
that no longer carries the keyword no longer has its association disclosed
by it — the copy is just a word the owner can keep or delete. Revisit only
if the read-time derivation route is itself replaced.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
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

    ``visibility`` / ``record_status`` override the record's stored state so a
    caller can ask the counterfactual — "would publishing this widen past the
    source?" — which is the publish-moment question #1070 exists for.

    An authority without ``record_audience`` cannot answer, and an
    unanswerable question is not evidence the audiences nest — so it warns.
    Over-warning is the cheap error here: this gates prose in a dialog, not a
    row in a result set.

    The NULL handling (``IS NOT false`` / ``IS NOT true``) follows
    ``_stranded_viewer_exists`` in ``maps/service_public.py``: an overlay
    predicate that cannot classify an account must send it to the warning
    side, not silently out of the WHERE.
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
    session: AsyncSession, record: Record, dataset_id: uuid.UUID | None
) -> list[str]:
    """Inherited keywords readable, at the record's CURRENT state, by someone
    who cannot open the source. Empty when there is nothing to warn about.

    The single question the ``update_user_metadata`` chokepoint asks after a
    visibility or record_status change resolves — keyed off resolved state, so
    both widening axes (visibility, and record_status to published) route
    through one check.
    """
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
    session: AsyncSession, record: Record, dataset_id: uuid.UUID | None
) -> str | None:
    """The advisory warning every resolved-state audience writer emits, or None.

    fix(#1178 review): the check lived inline in ``update_user_metadata`` and
    the ordinary publish flow bypassed it — ``set_target_status`` writes
    ``record_status`` directly, so a draft public analysis output published
    with no warning. One shared helper, called AFTER each writer resolves the
    new state, is the boundary that keeps the next status writer from
    reopening the gap. Current callers: ``update_user_metadata``
    (metadata PATCH, both axes) and the two publication-status endpoints in
    ``datasets/api/router_data.py``.

    Creation-time writers are deliberately not callers: ingest finalize
    (``processing/ingest/tasks_common.py``) and the registration paths assign
    an initial status/visibility to a record that cannot yet be
    analysis-derived — ``derived_from`` and inherited keywords are written by
    ``apply_analysis_provenance`` on outputs registered private — and a
    worker has no owner on the wire to warn.
    """
    disclosed = await disclosed_inherited_keywords(session, record, dataset_id)
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
