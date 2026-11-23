"""Where a version 2 manifest entry's publication is decided and judged again.

``effective_publication`` (``platform/record_audience.py``) holds every rule.
This module gathers its inputs at each door that writes or reuses a manifest
job: the apply, a held or in-flight job the apply would reuse, and the worker
that publishes the job. Version 1 jobs, which store no ``manifest_version``,
and jobs no manifest created take none of this: their worker only refuses a
public visibility the restriction no longer lets their submitter set
(``refuse_restricted_public``).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity

from app.core.permissions import UPLOAD
from app.platform.jobs.models import (
    ADMITTED_CAPABILITY_METADATA_KEY,
    ADMITTED_RAW_SOURCE_METADATA_KEY,
    ADMITTED_PUBLIC_VISIBILITY_METADATA_KEY,
    ADMITTED_PUBLISH_KEY_METADATA_KEY,
    IngestJob,
    publication_owner,
)
from app.platform.record_audience import (
    Publication,
    PublicationRefused,
    effective_publication,
    may_set_public,
    settled_visibility,
)
from app.platform.request_credential import is_publish_key, stamp_publish_key
from app.processing.ingest.manifest_dataset_fields import (
    COLLECTION_METADATA_KEY,
    MANIFEST_VERSION_METADATA_KEY,
    PUBLIC_FALLBACK_METADATA_KEY,
    REQUESTED_VISIBILITY_METADATA_KEY,
    ManifestEntryFields,
    ManifestEntryRefused,
    append_job_warning,
    check_job_capabilities,
    load_submitter,
    public_refused_message,
)
from app.processing.ingest.manifest_schemas import ManifestDataset
from app.processing.ingest.manifest_sources import (
    ManifestSourceError,
    manifest_job_metadata,
    publication_to_catalog_fields,
)

PUBLIC_FALLBACK_KIND = "manifest_public_fallback"

# What a job publishes besides its source, which depends on who applies and
# when, and so can differ for an unchanged entry: the decision and the policy
# a later door judges it by again.
_POLICY_KEYS = ("visibility", "record_status", PUBLIC_FALLBACK_METADATA_KEY)
# And what a held job, which the apply reserved in full, records besides.
_HELD_KEYS = (COLLECTION_METADATA_KEY, ADMITTED_PUBLIC_VISIBILITY_METADATA_KEY)


def _same_policy(stored: dict, effective: dict, keys: tuple[str, ...] = ()) -> bool:
    """Whether a stored job publishes as ``effective`` would, by the same
    policy: the same fallback, and a publish key's limits when, and only
    when, a key applies."""
    return all(
        stored.get(key) == effective.get(key) for key in (*_POLICY_KEYS, *keys)
    ) and bool(stored.get(ADMITTED_PUBLISH_KEY_METADATA_KEY)) == bool(
        effective.get(ADMITTED_PUBLISH_KEY_METADATA_KEY)
    )


def is_version_2(metadata: dict) -> bool:
    return metadata.get(MANIFEST_VERSION_METADATA_KEY) == "2"


def entry_job_metadata(
    db: AsyncSession,
    dataset: ManifestDataset,
    prepared: Any,
    fingerprint: str,
    fields: ManifestEntryFields | None,
    dataset_id: uuid.UUID | None,
    *,
    admitted_public: bool,
) -> dict[str, object]:
    """What an entry's job records: the manifest ledger and what its doors
    admitted, which the publish checks again. ``admitted_public`` is whether
    the restricted-public gate admitted the caller as an admin."""
    metadata = {
        **manifest_job_metadata(
            dataset, prepared, fingerprint=fingerprint, fields=fields
        )
    }
    stamp_publish_key(db, metadata)
    if dataset_id is not None:
        metadata["reupload"] = True
        metadata["dataset_id"] = str(dataset_id)
        if is_publish_key(db) and fields is None:
            # Version 1's comes from the intent, applied later over whatever
            # the visibility is by then, so the update keeps it.
            metadata.pop("visibility", None)
        metadata[ADMITTED_CAPABILITY_METADATA_KEY] = UPLOAD
        if admitted_public:
            metadata[ADMITTED_PUBLIC_VISIBILITY_METADATA_KEY] = True
        if prepared.kind not in ("http", "upload"):
            metadata[ADMITTED_RAW_SOURCE_METADATA_KEY] = True
    return metadata


def _record_now(record: Any) -> tuple[str, str]:
    return record.visibility, record.record_status


async def _entry_publication(
    db: AsyncSession, fields: ManifestEntryFields, dataset: ManifestDataset, record
) -> Publication:
    _, record_status = publication_to_catalog_fields(dataset.publication)
    now = None
    if record is not None:
        await db.refresh(record, attribute_names=["visibility", "record_status"])
        now = _record_now(record)
    return effective_publication(
        dataset.visibility,
        record_status,
        fields.public_fallback,
        may_set_public=fields.may_set_public,
        is_key=is_publish_key(db),
        now=now,
    )


async def decide_publication(
    db: AsyncSession,
    fields: ManifestEntryFields | None,
    dataset: ManifestDataset,
    existing: Any,
) -> None:
    """Decide what a version 2 entry that writes will publish: the visibility
    its job stores, and warning A020 when public fell back to internal. A
    refusal fails the entry."""
    if fields is None:
        return
    record = existing.record if existing is not None else None
    try:
        result = await _entry_publication(db, fields, dataset, record)
    except PublicationRefused as refused:
        if refused.reason == "widening":
            raise ManifestSourceError(refused.message) from refused
        raise ManifestEntryRefused(
            [
                public_refused_message(
                    dataset, "error", publish_key=refused.reason == "key"
                )
            ]
        ) from refused
    fields.visibility = result.visibility
    if result.fell_back_for is not None:
        fields.messages.append(
            public_refused_message(
                dataset, "warning", publish_key=result.fell_back_for == "key"
            )
        )


async def judge_update(
    db: AsyncSession,
    user: Identity,
    fields: ManifestEntryFields | None,
    dataset: ManifestDataset,
    completed_job: Any,
    existing: Any,
    *,
    metadata: dict,
    dry_run: bool,
) -> None:
    """A version 2 update's capabilities, judged on the job ``metadata`` it
    would queue, and a dry run's A053."""
    if fields is None:
        return
    await check_job_capabilities(db, user, metadata)
    if dry_run:
        fields.note_edits_since_publish(dataset, completed_job, existing)


async def in_flight_job_matches(
    db: AsyncSession,
    fields: ManifestEntryFields | None,
    dataset: ManifestDataset,
    job: IngestJob,
) -> bool:
    """Whether an in-flight job of an unchanged entry publishes what this
    apply would, by the same policy. A version 1 apply reuses only a
    version 1 job."""
    metadata = job.user_metadata or {}
    if fields is None:
        return not is_version_2(metadata)
    if not is_version_2(metadata):
        return False
    existing = None
    if job.dataset_id is not None:
        from app.platform.extensions import get_processing_port

        existing = await get_processing_port().get_dataset(db, job.dataset_id)
    try:
        await decide_publication(db, fields, dataset, existing)
    except ManifestSourceError:
        fields.messages.clear()
        return False
    _, record_status = publication_to_catalog_fields(dataset.publication)
    effective = {
        "visibility": fields.visibility,
        "record_status": record_status,
        PUBLIC_FALLBACK_METADATA_KEY: fields.public_fallback,
        ADMITTED_PUBLISH_KEY_METADATA_KEY: is_publish_key(db),
    }
    return _same_policy(metadata, effective)


async def held_job_matches(
    db: AsyncSession,
    held: Any,
    fields: ManifestEntryFields | None,
    effective: dict,
) -> bool:
    """Whether the held entry ``held`` answers for this apply: its job is of
    the same version and stores the publication this apply decided,
    ``effective``. Otherwise the entry is queued past the hold, as a changed
    entry is."""
    if held is None:
        return False
    job = await db.get(IngestJob, held.job_id)
    if job is None:
        return False
    stored = job.user_metadata or {}
    if is_version_2(stored) != (fields is not None):
        return False
    return fields is None or _same_policy(stored, effective, _HELD_KEYS)


async def settle_stored_publication(
    session: AsyncSession, job: IngestJob | uuid.UUID, record: Any, user_metadata: dict
) -> dict:
    """Judge a version 2 job's publication again against ``record`` as
    committed now, holding its rows (None for a create), with its submitter's
    standing and the restriction as they are now. Any other job goes through
    ``refuse_restricted_public`` and publishes its metadata as stored.

    The publish writes the narrower of the stored and the recomputed
    visibility (``settled_visibility``). A recompute whose refused public
    fell back to internal by the stored fallback adds an A020 job warning; a
    public refused by the restriction raises ``PublicVisibilityRefused`` and
    any other refusal ``WideningRefused``. Returns the metadata to publish
    from.
    """
    from app.core.persistent_config import RESTRICT_PUBLIC_VISIBILITY
    from app.processing.ingest.publication import (
        PublicVisibilityRefused,
        WideningRefused,
    )

    if not is_version_2(user_metadata):
        await refuse_restricted_public(session, job, record, user_metadata)
        return user_metadata
    if isinstance(job, uuid.UUID):
        job = await session.get(IngestJob, job)
    submitter = await load_submitter(session, job.created_by if job else None)
    if job is None or submitter is None:
        raise WideningRefused
    is_key = bool(user_metadata.get(ADMITTED_PUBLISH_KEY_METADATA_KEY))
    now = None
    if record is not None:
        await session.refresh(record, attribute_names=["visibility", "record_status"])
        now = _record_now(record)
    try:
        result = effective_publication(
            user_metadata.get(REQUESTED_VISIBILITY_METADATA_KEY),
            user_metadata["record_status"],
            user_metadata.get(PUBLIC_FALLBACK_METADATA_KEY),
            may_set_public=may_set_public(
                is_key=is_key,
                is_admin=any(role.name == "admin" for role in submitter.roles),
                restricted=bool(await RESTRICT_PUBLIC_VISIBILITY.get_uncached(session)),
            ),
            is_key=is_key,
            now=now,
        )
    except PublicationRefused as refused:
        if refused.reason == "restriction":
            raise PublicVisibilityRefused from None
        raise WideningRefused from None
    stored = user_metadata.get("visibility")
    if result.fell_back_for is not None and result.visibility != stored:
        append_job_warning(
            job,
            {"kind": PUBLIC_FALLBACK_KIND, "details": {"reason": result.fell_back_for}},
        )
    settled = {
        key: value for key, value in user_metadata.items() if key != "visibility"
    }
    visibility = settled_visibility(stored, result.visibility, now and now[0])
    if visibility is not None:
        settled["visibility"] = visibility
    return settled


async def refuse_restricted_public(
    session: AsyncSession, job: IngestJob | uuid.UUID, record: Any, user_metadata: dict
) -> None:
    """Raise ``PublicVisibilityRefused`` when a job that is not a version 2
    manifest job would make its dataset public while public visibility is
    restricted to admins now and the account it publishes for
    (``publication_owner``, the one admission judged) is not one now,
    whatever its admission recorded.

    ``record`` is the dataset's record, held, or None for a create. An update
    applies a visibility only from a manifest job, and one whose record is
    already public widens nothing, so neither is refused.
    """
    from app.core.persistent_config import RESTRICT_PUBLIC_VISIBILITY
    from app.processing.ingest.publication import PublicVisibilityRefused

    if user_metadata.get("visibility") != "public":
        return
    if record is not None:
        if "manifest_key" not in user_metadata:
            return
        await session.refresh(record, attribute_names=["visibility"])
        if record.visibility == "public":
            return
    if not await RESTRICT_PUBLIC_VISIBILITY.get_uncached(session):
        return
    if isinstance(job, uuid.UUID):
        job = await session.get(IngestJob, job)
    owner = await load_submitter(session, publication_owner(job) if job else None)
    if owner is None or not any(role.name == "admin" for role in owner.roles):
        raise PublicVisibilityRefused


async def settle_created_publication(
    session: AsyncSession, job: IngestJob, record: Any, user_metadata: dict
) -> None:
    """Judge a create's publication once more as the last step before it
    commits, after the waits, scans and storage writes since
    ``settle_stored_publication`` first decided it, and narrow the new
    ``record`` to the result. Raises as that does."""
    settled = await settle_stored_publication(session, job, None, user_metadata)
    record.visibility = settled.get("visibility", "private")
