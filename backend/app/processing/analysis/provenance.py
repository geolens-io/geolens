"""Provenance written onto a materialized analysis output (feat(#765)).

A materialized result used to land with empty lineage and no durable link to
its source: ``source_dataset_id`` lived only in ``ingest_jobs.user_metadata``,
which is purgeable. Everything needed is known at registration time, so it is
written there.

Two products, kept in one place so a new operation adds a phrase here rather
than editing the materialize path:

* ``build_lineage_sentence`` -- prose for ``records.lineage_summary``, which
  DCAT exports as ``dcterms:provenance`` and the record search vector indexes.
* ``build_derived_from`` -- the durable reference for ``records.derived_from``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.extensions import get_processing_port

logger = structlog.get_logger(__name__)

# Params carried into the sentence and the reference. Mirrors the analysis
# metadata the router records on the job, minus the bookkeeping keys.
#
# fix(#1097 review): the spatial-join pair was missing. _materialize passes
# join_dataset_id and join_fields to apply_analysis_provenance, and this filter
# silently dropped both — so a join's durable lineage recorded the source and
# the operation and neither the layer it joined against nor the columns it
# transferred, which is most of what makes a join reproducible.
#
# This list is the STORAGE contract, and that has a consequence worth stating
# where the keys are: anything added here becomes visible to every requester
# who can see the output, so a key naming a dataset must also appear in
# _DATASET_ID_PARAMS in catalog/authorization.py, which access-checks each one
# per requester. test_every_dataset_id_param_is_redactable enforces exactly
# that pairing, and it reads THIS tuple.
PARAM_KEYS = (
    "distance_meters",
    "by_field",
    "mask_source",
    "mask_dataset_id",
    "join_dataset_id",
    "join_fields",
)


def _format_metres(value: Any) -> str:
    """Metres as a person would write them: 500 m, 1609.34 m, 12345.678 m.

    fix(#765 review): this used ``f"{number:g}"``, whose DEFAULT PRECISION IS
    SIX SIGNIFICANT DIGITS — so it silently rounded, and the comment claiming
    it did not was simply wrong. Measured: 12345.678 became "12345.7",
    33.333333333 became "33.3333", and 99999.99 (a valid distance, just under
    MAX_BUFFER_METERS) became "100000". The sentence is the human-readable
    provenance shown to users and exported through DCAT, so it was recording a
    distance the geometry had not been built with.

    ``repr`` of a float is the SHORTEST string that round-trips to the same
    double, so it reproduces whatever the caller submitted exactly, by
    construction rather than by choosing a precision that looks big enough.
    Only the trailing ".0" on whole metres is trimmed, which is the one thing
    the old formatting was actually wanted for.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return f"{value} m"
    text = repr(number)
    return f"{text.removesuffix('.0')} m"


def _quoted(title: str | None) -> str:
    clean = (title or "").strip()
    return f'"{clean}"' if clean else "an unnamed dataset"


def _operation_phrase(
    operation: str,
    source: str,
    params: Mapping[str, Any],
    mask_title: str | None,
    join_title: str | None = None,
) -> str:
    """The clause naming the operation and its parameters.

    The extension point: a new operation adds one branch. The fallback matters
    — an operation with no branch still has to produce SOME lineage, because an
    empty ``lineage_summary`` is a hard VAL-01 validation failure.
    """
    if operation == "buffer":
        distance = params.get("distance_meters")
        if distance is None:
            return f"Buffered from {source}"
        return f"Buffered from {source} by {_format_metres(distance)}"
    if operation == "centroid":
        return f"Centroids computed from {source}"
    if operation == "clip":
        if params.get("mask_source") == "layer":
            # The mask layer's own title when it could be read, its absence
            # otherwise -- a bare UUID would not read as a sentence.
            target = _quoted(mask_title) if mask_title else "another layer"
            return f"Clipped from {source} to {target}"
        return f"Clipped from {source} to a drawn area"
    if operation == "dissolve":
        by_field = params.get("by_field")
        if by_field:
            return f"Dissolved from {source} by {by_field}"
        return f"Dissolved from {source} into a single feature"
    # fix(#1097 review): the four operations this branch adds had no branch, so
    # they fell through to the generic fallback and their sentences named only
    # the source. That sentence is a product surface — the dataset page shows
    # it, search indexes it, and DCAT exports it — so an overlay whose whole
    # point is the second layer was described without mentioning one.
    if operation == "spatial_join":
        target = _quoted(join_title) if join_title else "another layer"
        fields = params.get("join_fields")
        if fields:
            return (
                f"Joined from {source} against {target}, "
                f"transferring {', '.join(fields)}"
            )
        return f"Joined from {source} against {target}"
    if operation == "intersect":
        target = _quoted(mask_title) if mask_title else "another layer"
        return f"Intersected from {source} with {target}"
    if operation == "select_by_location":
        if params.get("mask_source") == "layer":
            target = _quoted(mask_title) if mask_title else "another layer"
            return f"Selected from {source} by {target}"
        return f"Selected from {source} by a drawn area"
    if operation == "measure":
        return f"Measurements computed from {source}"
    return f"{operation.replace('_', ' ').capitalize()} applied to {source}"


def build_lineage_sentence(
    *,
    operation: str,
    source_title: str | None,
    params: Mapping[str, Any] | None = None,
    actor: str,
    created_at: datetime,
    mask_title: str | None = None,
    join_title: str | None = None,
) -> str:
    """A human sentence describing how this dataset was produced.

    Reads as prose because it is exported as prose: DCAT serves it as
    ``dcterms:provenance`` and the dataset page shows it verbatim.
    """
    params = params or {}
    phrase = _operation_phrase(
        operation, _quoted(source_title), params, mask_title, join_title
    )
    return f"{phrase}, created by {actor} on {created_at.date().isoformat()}."


def build_derived_from(
    *,
    source_dataset_id: str,
    operation: str,
    params: Mapping[str, Any] | None = None,
    created_at: datetime,
) -> dict[str, Any]:
    """The durable reference stored on ``records.derived_from``.

    Only the parameters that shaped the output are kept; the drawn clip mask
    itself is deliberately excluded, as it is on the job metadata, because it
    can be kilobytes of geometry.
    """
    params = params or {}
    return {
        "dataset_id": source_dataset_id,
        "operation": operation,
        "params": {k: params[k] for k in PARAM_KEYS if params.get(k) is not None},
        "created_at": created_at.isoformat(),
    }


async def _actor_label(session: AsyncSession, user_id: str) -> str:
    """Username, else the email's local part, else a neutral label.

    The same precedence as ``resolve_actor``, resolved here in SQL because
    ``processing/`` cannot import from ``app.modules.catalog`` (PROCESS-02).
    """
    row = (
        await session.execute(
            text(
                "SELECT username, email FROM catalog.users WHERE id = :uid"
            ).bindparams(uid=uuid.UUID(user_id))
        )
    ).first()
    if row is None:
        return "a user"
    username = (row.username or "").strip()
    if username:
        return username
    local_part = (row.email or "").split("@")[0].strip()
    return local_part or "a user"


async def _record_title(session: AsyncSession, dataset_id: str | None) -> str | None:
    """Title of a dataset's catalog record, or None when it is gone."""
    if not dataset_id:
        return None
    port = get_processing_port()
    try:
        dataset = await port.get_dataset(session, uuid.UUID(dataset_id))
    except ValueError:
        return None
    if dataset is None:
        return None
    record = await port.get_record(session, dataset.record_id)
    return record.title if record is not None else None


async def apply_analysis_provenance(
    session: AsyncSession,
    *,
    new_record_id: uuid.UUID,
    source_dataset_id: str,
    user_id: str,
    operation: str,
    params: Mapping[str, Any] | None = None,
) -> None:
    """Write lineage, the derived_from reference, and inherited keywords.

    Called from the materialize path right after registration, inside the same
    session, so the provenance commits with the dataset rather than in a second
    transaction that could fail on its own.

    Two things here are copied VALUES rather than gated references, and that
    is deliberate (#765):

    * Inherited keywords. NOT because a keyword is harmless in itself: it can
      be a project codename or a client name, and no geometry embodies those
      (#1045 review). It rests on the same ground as the title below. The
      output is registered ``visibility="private"`` and owned by the caller
      who already held access to the source, so an inherited keyword reaches
      anyone else only when that owner publishes or shares the dataset. That
      is their deliberate act, on ordinary editable record metadata they can
      delete first. Warning an owner what they inherited before they publish
      is #1070.
    * The source (and mask) title inside the lineage sentence. The output is
      registered private and owned by that same caller, so the title only
      reaches anyone else if its owner publishes or shares the dataset —
      a deliberate act, on prose they can read and edit, exactly like typing
      the source's name into the summary field.

    Read paths gate the derived_from REFERENCE, where the disclosure would be
    a dataset id the requester could act on rather than words in a sentence:
    see visible_derived_from, which checks the source AND the mask id.
    """
    params = params or {}
    now = datetime.now(timezone.utc)
    port = get_processing_port()

    record = await port.get_record(session, new_record_id)
    if record is None:  # pragma: no cover - registration just created it
        logger.warning(
            "analysis.provenance_record_missing", record_id=str(new_record_id)
        )
        return

    source_title = await _record_title(session, source_dataset_id)
    # fix(#1097 review): keyed off the ID being present, not off the
    # mask_source discriminator. intersect takes a layer and has no
    # mask_source — the discriminator only distinguishes drawn from layer for
    # the operations that can be either — so gating on it meant an overlay's
    # title was never resolved and its sentence said "another layer" for a
    # layer whose title was one query away.
    mask_title = await _record_title(session, params.get("mask_dataset_id"))
    join_title = await _record_title(session, params.get("join_dataset_id"))

    record.lineage_summary = build_lineage_sentence(
        operation=operation,
        source_title=source_title,
        params=params,
        actor=await _actor_label(session, user_id),
        created_at=now,
        mask_title=mask_title,
        join_title=join_title,
    )
    record.derived_from = build_derived_from(
        source_dataset_id=source_dataset_id,
        operation=operation,
        params=params,
        created_at=now,
    )

    # Keywords are child rows (catalog.record_keywords) with a keyword_type
    # CHECK constraint, not an array column -- copy the rows and carry the type
    # across. INSERT..SELECT rather than an ORM round-trip: the new record has
    # none of its own, so there is nothing to merge with.
    await session.execute(
        text(
            "INSERT INTO catalog.record_keywords "
            "(record_id, keyword, vocabulary_uri, keyword_type) "
            "SELECT :new_id, keyword, vocabulary_uri, keyword_type "
            "FROM catalog.record_keywords WHERE record_id = ("
            "  SELECT record_id FROM catalog.datasets WHERE id = :source_id"
            ")"
        ).bindparams(new_id=new_record_id, source_id=uuid.UUID(source_dataset_id))
    )
