"""Version 2 dataset fields of a manifest entry: visibility, collection and the
coded messages an apply reports, plus what the ingest tail applies later.

Catalog access goes through ``ProcessingPort``; this module imports no catalog
code.
"""

from __future__ import annotations

import contextlib
import uuid
from dataclasses import dataclass, field
from typing import Any

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity, IdentityRole, IdentitySnapshot
from app.core.permissions import EDIT_METADATA
from app.platform.extensions import get_permission_extension, get_processing_port
from app.platform.jobs.models import (
    ADMITTED_CAPABILITY_METADATA_KEY,
    ADMITTED_PUBLISH_KEY_METADATA_KEY,
    MANIFEST_VERSION_METADATA_KEY,
    IngestJob,
)
from app.platform.request_credential import (
    ApiKeyCredential,
    acting_with,
)
from app.platform.record_audience import (
    audience_phrase,
    readable_level,
    widens_audience,
)
from app.processing.ingest.manifest_schemas import (
    MAX_MANIFEST_ATTRIBUTES,
    MAX_MANIFEST_GROUPS,
    ManifestApplyEntryResult,
    ManifestApplyRequest,
    ManifestAttribute,
    ManifestDataset,
    ManifestMessage,
)
from app.processing.ingest.manifest_sources import (
    ManifestSourceError,
    publication_to_catalog_fields,
)

import structlog
from sqlalchemy import text

log = structlog.get_logger()

PUBLIC_RESTRICTED = "A020"
COLLECTION_REFUSED = "A033"
# What the port answers when the collection row stayed locked.
COLLECTION_BUSY_CODE = "collection_busy"
EDITED_SINCE_PUBLISH = "A053"
RASTER_NOT_REPLACED = "A054"
SHARING_KEPT = "A056"
MORE_VISIBLE = "A057"
GROUP_LEFT_OFF = "A058"
ATTRIBUTE_UNMATCHED = "A092"

TILE_CACHE_VERSION_METADATA_KEY = "manifest_tile_cache_version"
COLLECTION_METADATA_KEY = "manifest_collection_id"
ATTRIBUTES_METADATA_KEY = "manifest_attributes"
REQUESTED_VISIBILITY_METADATA_KEY = "manifest_requested_visibility"
PUBLIC_FALLBACK_METADATA_KEY = "manifest_public_fallback"
GROUPS_METADATA_KEY = "manifest_groups"
# The groups the entry named, whatever share its plan permitted: a publish
# never leaves its data with a group outside them.
REQUESTED_GROUPS_METADATA_KEY = "manifest_groups_requested"
# The dataset's visibility when the apply planned its groups.
GROUPS_PLANNED_FROM_METADATA_KEY = "manifest_groups_planned_from"
# And its groups then.
GROUPS_GRANTED_METADATA_KEY = "manifest_groups_granted"
WIDENING_KEPT_KIND = "manifest_widening_kept"

# Job warning kinds, which a client reads as the codes beside them.
COLLECTION_REFUSED_KIND = "manifest_collection_refused"
ATTRIBUTE_UNMATCHED_KIND = "manifest_attribute_unmatched"
GROUPS_LEFT_OFF_KIND = "manifest_groups_left_off"


def public_refused_message(
    dataset: ManifestDataset, severity: str, *, publish_key: bool
) -> ManifestMessage:
    reason, fix = (
        ("A publish key can't make anything public", "Use Organization, or sign in.")
        if publish_key
        else (
            "Public visibility is restricted on this server",
            "Use Organization, or ask the admin.",
        )
    )
    outcome = (
        "was not published"
        if severity == "error"
        else "is shared with the organization instead"
    )
    return ManifestMessage(
        code=PUBLIC_RESTRICTED,
        severity=severity,
        message=f"{reason}, so {dataset.title!r} {outcome}.",
        fix=fix,
    )


def raster_not_replaced_message(dataset: ManifestDataset) -> ManifestMessage:
    """Error A054: a publish key may not replace a raster's data."""
    return ManifestMessage(
        code=RASTER_NOT_REPLACED,
        severity="error",
        message=(
            f"A publish key can't replace raster data, so {dataset.title!r} "
            "was not updated: a replaced raster can't be restored."
        ),
        fix="Publish as new, or use a full key or sign in.",
    )


def widening_kept_message(dataset: ManifestDataset, level: str) -> ManifestMessage:
    """A056 for an entry whose wider ``level`` a publish key may not set."""
    return ManifestMessage(
        code=SHARING_KEPT,
        severity="warning",
        message=(
            f"A publish key can't share {dataset.title!r} with more people, so "
            f"it keeps its current Sharing level: {audience_phrase(level)} "
            "won't see it unless they already can."
        ),
        fix="Share the dataset in GeoLens, or lower the Sharing level.",
    )


class ManifestEntryRefused(ManifestSourceError):
    """An entry refused with coded messages; nothing is queued for it."""

    def __init__(self, messages: list[ManifestMessage]) -> None:
        super().__init__(messages[0].message)
        self.messages = messages


@dataclass
class ManifestEntryFields:
    """What a version 2 entry decides before its job is reserved."""

    visibility: str | None
    public_fallback: str | None = None
    collection_id: uuid.UUID | None = None
    # The groups the entry shares its dataset with, None to keep its groups.
    groups: list[uuid.UUID] | None = None
    group_names: list[str] | None = None
    groups_added: bool = False
    # Whether a role grant keeps the dataset restricted without groups.
    role_granted: bool = False
    # The dataset's visibility and groups when the groups were planned, None
    # for a create.
    groups_planned_from: str | None = None
    groups_granted: list[uuid.UUID] = field(default_factory=list)
    messages: list[ManifestMessage] = field(default_factory=list)
    # Whether the gate let the caller name public, for an entry that writes;
    # a skip writes nothing, so it applies no fallback.
    may_set_public: bool = True

    @classmethod
    def of(
        cls, request: ManifestApplyRequest, dataset: ManifestDataset
    ) -> ManifestEntryFields | None:
        """None for a version 1 request, whose entries take none of this."""
        if request.manifest_version != "2":
            return None
        return cls(
            visibility=dataset.visibility, public_fallback=request.public_fallback
        )

    def note_edits_since_publish(
        self, dataset: ManifestDataset, completed_job: Any, existing: Any
    ) -> None:
        """Warn when the dataset's tile cache version moved since that publish.

        A replaced raster keeps no previous version, so its warning says the
        data it replaces can't be restored.
        """
        recorded = (completed_job.user_metadata or {}).get(
            TILE_CACHE_VERSION_METADATA_KEY
        )
        current = getattr(existing, "tile_cache_version", None)
        if not (
            isinstance(recorded, int)
            and isinstance(current, int)
            and current > recorded
        ):
            return
        record = getattr(existing, "record", None)
        if getattr(record, "record_type", None) == "raster_dataset":
            message = (
                f"The data in {dataset.title!r} was changed in GeoLens since "
                "the last publish. Replacing discards it, and a replaced "
                "raster can't be restored."
            )
        else:
            message = (
                f"Features in {dataset.title!r} were edited in GeoLens "
                "since the last publish. Replacing discards those "
                "edits; the previous version stays restorable once."
            )
        self.messages.append(
            ManifestMessage(
                code=EDITED_SINCE_PUBLISH,
                severity="warning",
                message=message,
                fix="Publish as new, or Continue.",
            )
        )


def required_capabilities(metadata: dict, recorded: str | None) -> list[str]:
    """What a job's submitter must still hold: the capability its door
    recorded, and ``edit_metadata`` for a manifest job that writes attribute
    text or groups onto the dataset it replaces, as the attribute edit and
    the sharing route need."""
    needed = [recorded] if recorded is not None else []
    edits_metadata = (
        metadata.get("manifest_key")
        and metadata.get("reupload")
        and (
            metadata.get(ATTRIBUTES_METADATA_KEY)
            or metadata.get(GROUPS_METADATA_KEY) is not None
        )
    )
    if edits_metadata and EDIT_METADATA not in needed:
        needed.append(EDIT_METADATA)
    return needed


async def _require(db: AsyncSession, user: Identity, capability: str) -> None:
    """Refuse an entry the caller's roles, as committed now, don't cover."""
    submitter = await load_submitter(db, user.id)
    if submitter is None or not await get_permission_extension().check_permission(
        db, submitter, capability, user_roles={r.name for r in submitter.roles}
    ):
        raise ManifestSourceError(f"Missing permission: {capability}")


async def check_job_capabilities(
    db: AsyncSession, user: Identity, metadata: dict
) -> None:
    """Refuse an entry whose job the caller's roles don't cover, judged as
    the publish judges it, on the account as committed now."""
    for capability in required_capabilities(
        metadata, metadata.get(ADMITTED_CAPABILITY_METADATA_KEY)
    ):
        await _require(db, user, capability)


def report_entry(
    fields: ManifestEntryFields | None, result: ManifestApplyEntryResult
) -> ManifestApplyEntryResult:
    """Give a version 2 entry's result its messages and planned groups,
    whatever it did: a held run still carries what the entry decided."""
    if fields is not None and result.action != "error":
        result.messages = [*(result.messages or []), *fields.messages]
        result.decide(fields.visibility, fields.group_names, fields.role_granted)
    return result


def _left_off_message(dataset: ManifestDataset, group_ids: list[uuid.UUID]):
    listed = ", ".join(str(group_id) for group_id in group_ids)
    return ManifestMessage(
        code=GROUP_LEFT_OFF,
        severity="warning",
        message=(
            f"{dataset.title!r} isn't shared with {listed}: no such group "
            "exists, or you aren't a member."
        ),
        fix="Choose another group from the capabilities list.",
    )


async def resolve_entry_groups(
    db: AsyncSession,
    dataset: ManifestDataset,
    user: Identity,
    fields: ManifestEntryFields | None,
    existing: Any,
) -> None:
    """Decide the groups a version 2 entry shares its dataset with, once its
    publication is decided.

    Naming groups needs ``edit_metadata``, as the sharing route does, or the
    entry is refused. A group that doesn't exist or that the caller may not
    add is left off with warning A058, and what a publish key may not share
    is held back with A056; the entry goes ahead with the rest. A held-back
    share keeps the dataset's groups, so one that would keep a group the
    entry leaves out refuses the entry with error A056: its data would reach
    readers it removes. Writes nothing: the publish shares the dataset.
    """
    if fields is None or dataset.groups is None:
        return
    await _require(db, user, EDIT_METADATA)
    plan = await get_processing_port().plan_manifest_groups(
        db,
        existing.id if existing is not None else None,
        dataset.groups,
        user,
        level=fields.visibility,
    )
    fields.role_granted = plan.role_granted
    fields.groups_planned_from = existing.record.visibility if existing else None
    fields.groups_granted = list(plan.granted)
    if not plan.unchanged:
        fields.groups, fields.group_names = plan.group_ids, plan.names
        fields.groups_added = plan.added
    if plan.left_off:
        fields.messages.append(_left_off_message(dataset, plan.left_off))
    if plan.unchanged and set(plan.granted) - set(dataset.groups):
        raise ManifestEntryRefused(
            [
                ManifestMessage(
                    code=SHARING_KEPT,
                    severity="error",
                    message=(
                        f"A publish key can't share {dataset.title!r} with "
                        "more people, so its groups would stay as they are. "
                        "This publish also removes groups, which would then "
                        f"read the new data, so {dataset.title!r} was not "
                        "updated."
                    ),
                    fix=(
                        "Change the dataset's groups in GeoLens, or publish "
                        "with the groups it has now."
                    ),
                )
            ]
        )
    if plan.held_back:
        fields.messages.append(
            ManifestMessage(
                code=SHARING_KEPT,
                severity="warning",
                message=(
                    f"A publish key can't share {dataset.title!r} with more "
                    f"people, so {audience_phrase('restricted', plan.held_back)} "
                    "won't see it unless they already can, and its groups stay "
                    "as they are."
                ),
                fix="Share the dataset in GeoLens, or lower the Sharing level.",
            )
        )


def note_more_visible(
    dataset: ManifestDataset, fields: ManifestEntryFields | None, existing: Any
) -> None:
    """Warn, with A057, that an entry's dataset will reach more readers
    than it does now: through a level or groups the request changed, since an
    omitted one keeps the dataset's, or because the entry publishes a dataset
    that only its owner and admins read until then. A dataset that stays
    unpublished reaches nobody more, whatever its level and groups."""
    if fields is None or existing is None:
        return
    record = existing.record
    before = record.visibility
    after = fields.visibility or before
    if fields.groups is not None and after in ("private", "restricted"):
        kept_by_role = after == "restricted" and fields.role_granted
        after = "restricted" if fields.groups or kept_by_role else "private"
    _, record_status = publication_to_catalog_fields(dataset.publication)
    if not widens_audience(
        readable_level(before, record.record_status),
        readable_level(after, record_status),
        added_groups=fields.groups_added,
    ):
        return
    if widens_audience(before, after):
        cause = "its Sharing level changed in this publish"
        fix = "Continue, or keep the current level."
    elif record.record_status != "published":
        cause = "this publish marks it published"
        fix = "Continue, or keep its current status."
    else:
        cause = "this publish adds groups to it"
        fix = "Continue, or keep its current groups."
    audience = audience_phrase(after, fields.group_names or [])
    if after == "restricted" and not fields.group_names:
        audience = "the groups and roles it is shared with"
    fields.messages.append(
        ManifestMessage(
            code=MORE_VISIBLE,
            severity="warning",
            message=(
                f"{dataset.title!r} will be visible to {audience}, more "
                f"people than now, because {cause}."
            ),
            fix=fix,
        )
    )


def _collection_message(code: str) -> ManifestMessage:
    if code == COLLECTION_BUSY_CODE:
        message = (
            "Another change held the collection too long, so the dataset was "
            "not added to it. Publishing again may add it."
        )
    else:
        message = (
            "The collection doesn't exist and you can't create it, or you "
            "can't add datasets to it, so the dataset is published without one."
        )
    return ManifestMessage(
        code=COLLECTION_REFUSED,
        severity="warning",
        message=message,
        fix="Choose another collection.",
    )


async def resolve_entry_collection(
    db: AsyncSession,
    dataset: ManifestDataset,
    user: Identity,
    fields: ManifestEntryFields | None,
    *,
    dry_run: bool,
) -> None:
    """Resolve a version 2 entry's collection before anything is queued.

    A refusal is warning A033 and the entry carries on without a collection.
    A dry run creates nothing and reports what an apply would.
    """
    if fields is None or dataset.collection is None:
        return
    ref = dataset.collection.model_dump(mode="json", exclude_none=True)
    collection_id, code = await get_processing_port().resolve_manifest_collection(
        db, ref, user, may_create=not dry_run
    )
    if code is not None:
        fields.messages.append(_collection_message(code))
        return
    fields.collection_id = collection_id


async def attach_unchanged_entry(
    db: AsyncSession,
    dataset: ManifestDataset,
    user: Identity,
    fields: ManifestEntryFields | None,
    dataset_id: uuid.UUID,
    *,
    dry_run: bool,
) -> None:
    """Add an unchanged version 2 entry's dataset to its collection, which the
    publish that made it may have had to leave out. Nothing happens when it is
    a member already; a refusal is warning A033, and a dry run only resolves.
    """
    if fields is None:
        return
    await resolve_entry_collection(db, dataset, user, fields, dry_run=dry_run)
    if dry_run or fields.collection_id is None:
        return
    code = await get_processing_port().add_dataset_to_manifest_collection(
        db, fields.collection_id, dataset_id, user
    )
    if code is not None:
        fields.messages.append(_collection_message(code))


def job_metadata_fields(
    dataset: ManifestDataset, fields: ManifestEntryFields
) -> dict[str, object]:
    """The v2 keys of a manifest job's metadata: what the ingest tail applies,
    and the request's version, visibility and fallback, from which later doors
    judge the entry again."""
    metadata: dict[str, object] = {MANIFEST_VERSION_METADATA_KEY: "2"}
    if dataset.visibility is not None:
        metadata[REQUESTED_VISIBILITY_METADATA_KEY] = dataset.visibility
    if fields.public_fallback is not None:
        metadata[PUBLIC_FALLBACK_METADATA_KEY] = fields.public_fallback
    if fields.visibility is not None:
        metadata["visibility"] = fields.visibility
    if fields.collection_id is not None:
        metadata[COLLECTION_METADATA_KEY] = str(fields.collection_id)
    if dataset.groups is not None:
        metadata[REQUESTED_GROUPS_METADATA_KEY] = [
            str(group_id) for group_id in dataset.groups
        ]
    if fields.groups is not None:
        metadata[GROUPS_METADATA_KEY] = [str(group_id) for group_id in fields.groups]
        if fields.groups_planned_from is not None:
            metadata[GROUPS_PLANNED_FROM_METADATA_KEY] = fields.groups_planned_from
            metadata[GROUPS_GRANTED_METADATA_KEY] = [
                str(group_id) for group_id in fields.groups_granted
            ]
    if dataset.attributes:
        # A null keeps the stored text, so it is dropped here.
        metadata[ATTRIBUTES_METADATA_KEY] = [
            attribute.model_dump(exclude_none=True) for attribute in dataset.attributes
        ]
    return metadata


_SUBMITTER = text(
    "SELECT u.id, u.username, u.email, u.is_active, u.created_at, "
    "ARRAY(SELECT r.name FROM catalog.user_roles ur "
    "JOIN catalog.roles r ON r.id = ur.role_id WHERE ur.user_id = u.id) AS roles "
    "FROM catalog.users u WHERE u.id = :uid"
)


async def load_submitter(
    session: AsyncSession, user_id: uuid.UUID | None
) -> IdentitySnapshot | None:
    """The submitting account as committed now, or None when it is gone or inactive.

    In SQL, since processing may not import the auth models.
    """
    if user_id is None:
        return None
    row = (await session.execute(_SUBMITTER, {"uid": user_id})).first()
    if row is None or not row.is_active:
        return None
    return IdentitySnapshot(
        id=row.id,
        username=row.username,
        email=row.email,
        is_active=row.is_active,
        roles=tuple(IdentityRole(name) for name in row.roles),
        created_at=row.created_at,
    )


_ATTRIBUTES = TypeAdapter(list[ManifestAttribute])


def _stored_attributes(user_metadata: dict) -> list[dict[str, Any]]:
    """The attributes the job carries, checked again by the request's own model.

    The apply validated them, but a job's metadata is data the worker reads
    later, so it is not trusted: anything that no longer validates is dropped.
    """
    raw = user_metadata.get(ATTRIBUTES_METADATA_KEY)
    if not raw:
        return []
    try:
        if not isinstance(raw, list) or len(raw) > MAX_MANIFEST_ATTRIBUTES:
            raise ValueError("attributes are not a bounded list")
        checked = _ATTRIBUTES.validate_python(raw)
    except (ValidationError, ValueError):
        log.warning("Dropping malformed manifest attributes")
        return []
    return [entry.model_dump(exclude_none=True) for entry in checked]


def append_job_warning(job: Any, warning: dict[str, Any]) -> None:
    warnings = list((job.user_metadata or {}).get("warnings", []))
    warnings.append(warning)
    job.user_metadata = {**(job.user_metadata or {}), "warnings": warnings}


async def apply_dataset_fields(
    session: AsyncSession,
    job: Any,
    dataset: Any,
    user_metadata: dict | None,
    *,
    audience_before: str | None = None,
    share_groups: bool = True,
) -> GroupShare:
    """Add the dataset to its collection, share it with its groups unless
    ``share_groups`` is False because that was done already, save its
    attribute text and note the tile cache version the dataset has now.
    Returns how the share ended, for a replacement to judge the groups that
    are left (``hold_to_entry_groups``).

    The ingest tail calls this inside the transaction that publishes the
    dataset, after the submitter's write access to it was checked, and after
    any storage writes, since the collection row it takes is held to the
    commit. A job no manifest created changes nothing. Refusals, a collection
    that stays busy and unmatched names become job warnings; none fails the
    job here.
    """
    share = GroupShare()
    if not user_metadata or "manifest_key" not in user_metadata:
        return share
    port = get_processing_port()
    submitter = await load_submitter(session, job.created_by)

    collection = user_metadata.get(COLLECTION_METADATA_KEY)
    if collection is not None:
        code: str | None = COLLECTION_REFUSED
        collection_id: uuid.UUID | None
        try:
            collection_id = uuid.UUID(str(collection))
        except ValueError:
            collection_id = None
        if collection_id is not None and submitter is not None:
            with as_publish_key(session, user_metadata):
                code = await port.add_dataset_to_manifest_collection(
                    session, collection_id, dataset.id, submitter
                )
        if code is not None:
            details = {"collection_id": str(collection)}
            if code == COLLECTION_BUSY_CODE:
                details["reason"] = "busy"
            append_job_warning(
                job, {"kind": COLLECTION_REFUSED_KIND, "details": details}
            )

    if share_groups:
        share = await _apply_groups(
            session, job, dataset, user_metadata, submitter, audience_before
        )

    attributes = _stored_attributes(user_metadata)
    if attributes and submitter is not None:
        unmatched = await port.apply_manifest_attributes(
            session, dataset.id, attributes, actor_id=submitter.id
        )
        if unmatched:
            append_job_warning(
                job,
                {
                    "kind": ATTRIBUTE_UNMATCHED_KIND,
                    "details": {"source_names": list(unmatched)},
                },
            )
    record_manifest_tile_cache_version(job, dataset)
    return share


_MALFORMED = object()


def _stored_ids(
    user_metadata: dict, key: str, *, limit: int | None = MAX_MANIFEST_GROUPS
) -> list[uuid.UUID] | None | object:
    """The group ids the job stores under ``key``, None when it stores
    none, or ``_MALFORMED`` for a value that no longer parses, which keeps the
    dataset's groups: an empty list would remove every grant.

    Checked again like the attributes, since a job's metadata is data the
    worker reads later. ``limit`` is the request's own, for the groups an
    entry named; None for the grants the dataset had, which map shares add
    to without one.
    """
    raw = user_metadata.get(key)
    if raw is None:
        return None
    try:
        if not isinstance(raw, list) or (limit is not None and len(raw) > limit):
            raise ValueError("groups are not a bounded list")
        return [uuid.UUID(str(group_id)) for group_id in raw]
    except ValueError:
        log.warning("Keeping the groups of a malformed manifest groups entry")
        return _MALFORMED


def shares_groups(user_metadata: dict) -> bool:
    """Whether the job shares its dataset with at least one group."""
    wanted = _stored_ids(user_metadata, GROUPS_METADATA_KEY)
    return isinstance(wanted, list) and bool(wanted)


def _groups_warning(job: Any, group_ids: list[uuid.UUID], reason: str) -> None:
    append_job_warning(
        job,
        {
            "kind": GROUPS_LEFT_OFF_KIND,
            "details": {
                "group_ids": sorted(str(group_id) for group_id in group_ids),
                "reason": reason,
            },
        },
    )


@dataclass(frozen=True)
class GroupShare:
    """How a job's share of its dataset ended. ``shared`` says the dataset
    now has the groups it was shared with, at least one. ``kept_because`` is
    why the job left the dataset's groups as they were, as a sentence, and
    None when it wrote the share or had none to write."""

    shared: bool = False
    kept_because: str | None = None


_KEPT_FOR_KEY = (
    "The group change was held back because a publish key can't share a "
    "dataset with more people."
)
_KEPT_NARROWED = (
    "The group change was held back because the dataset was made visible to "
    "fewer people after this publish was submitted."
)
_KEPT_NO_PERMISSION = (
    "The account that started this job may no longer change the dataset's groups."
)
_KEPT_UNREADABLE = "The groups this job stored could not be read."


async def _apply_groups(
    session: AsyncSession,
    job: Any,
    dataset: Any,
    user_metadata: dict,
    submitter: IdentitySnapshot | None,
    audience_before: str | None,
) -> GroupShare:
    """Share the published dataset with the job's groups, judged against
    ``audience_before``, the replaced dataset's visibility before this
    publish, and the visibility and groups the apply planned the share from.

    What it can't share becomes a job warning (A058), as does a submitter who
    no longer holds ``edit_metadata`` or a groups entry that no longer
    parses, which keep the dataset's groups; none fails the job here. The
    result says why the groups were kept, which ``hold_to_entry_groups``
    reports when they include one the entry left out."""
    wanted = _stored_ids(user_metadata, GROUPS_METADATA_KEY)
    granted = _stored_ids(user_metadata, GROUPS_GRANTED_METADATA_KEY, limit=None)
    by_key = bool(user_metadata.get(ADMITTED_PUBLISH_KEY_METADATA_KEY))
    if wanted is None:
        # A publish key's entry that named groups and stores no share had it
        # held back whole at the apply.
        named = user_metadata.get(REQUESTED_GROUPS_METADATA_KEY) is not None
        return GroupShare(kept_because=_KEPT_FOR_KEY if named and by_key else None)
    if wanted is _MALFORMED or granted is _MALFORMED:
        _groups_warning(job, [], "refused")
        return GroupShare(kept_because=_KEPT_UNREADABLE)
    before = None
    if user_metadata.get("reupload"):
        before = audience_before or dataset.record.visibility
    if submitter is None or not await get_permission_extension().check_permission(
        session, submitter, EDIT_METADATA, user_roles={r.name for r in submitter.roles}
    ):
        _groups_warning(job, wanted, "refused")
        return GroupShare(kept_because=_KEPT_NO_PERMISSION)
    with as_publish_key(session, user_metadata):
        plan, refusal = await get_processing_port().apply_manifest_groups(
            session,
            dataset.id,
            wanted,
            submitter,
            audience_before=before,
            planned_from=user_metadata.get(GROUPS_PLANNED_FROM_METADATA_KEY),
            granted_at_plan=granted,
        )
    if refusal:
        _groups_warning(job, wanted, "refused")
        return GroupShare(
            kept_because=f"The group change was refused: {refusal.rstrip('.')}."
        )
    if plan.left_off:
        _groups_warning(job, plan.left_off, "left_off")
    if plan.held_back_ids:
        _groups_warning(job, plan.held_back_ids, "held_back")
    if plan.unchanged:
        return GroupShare(kept_because=_KEPT_FOR_KEY if by_key else _KEPT_NARROWED)
    return GroupShare(shared=bool(plan.group_ids))


_GRANTED_GROUPS = text(
    "SELECT group_id FROM catalog.dataset_group_grants WHERE dataset_id = :dataset_id"
)


class GroupsOutsideEntry(ValueError):
    """A replacement's dataset is shared with a group its entry leaves out,
    which would read the data the replacement publishes."""

    def __init__(self, because: str | None) -> None:
        super().__init__(
            " ".join(
                part
                for part in (
                    "The dataset's data was not replaced: it is shared with "
                    "groups this publish leaves out, which would have read the "
                    "new data.",
                    because,
                    "Change the dataset's groups in GeoLens, or publish again "
                    "with the groups it has now.",
                )
                if part
            )
        )


async def hold_to_entry_groups(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    user_metadata: dict,
    *,
    because: str | None,
) -> None:
    """Raise ``GroupsOutsideEntry`` when a replacement whose entry named
    groups, an empty list included, would commit while its dataset holds a
    grant for a group outside them, whatever left it there; ``because`` is
    why the job's own share kept the groups, when it did.

    Call once the share was attempted, in the publish transaction, holding
    the catalog rows, which every writer of the dataset's grants takes. The
    grants are read as they are then, in SQL, since processing may not
    import the catalog models. An entry that named no groups is not held to
    any, and a job that stores a share without the entry's own list is held
    to the share's. A list that no longer parses allows no group.
    """
    named = _stored_ids(user_metadata, REQUESTED_GROUPS_METADATA_KEY)
    if named is None:
        named = _stored_ids(user_metadata, GROUPS_METADATA_KEY)
    if named is None:
        return
    granted = set(
        (await session.execute(_GRANTED_GROUPS, {"dataset_id": dataset_id})).scalars()
    )
    if named is _MALFORMED:
        named, because = [], _KEPT_UNREADABLE
    if granted - set(named):
        raise GroupsOutsideEntry(because)


def as_publish_key(
    session: AsyncSession, metadata: dict
) -> contextlib.AbstractContextManager[None]:
    """The scope of the publish key a job was queued or accepted with, so a
    check made for the job reaches only the key owner's own datasets and
    collections, as the key's request did."""
    marker = metadata.get(ADMITTED_PUBLISH_KEY_METADATA_KEY)
    if not marker:
        return contextlib.nullcontext()
    try:
        key_id = uuid.UUID(str(marker))
    except ValueError:
        key_id = uuid.UUID(int=0)
    return acting_with(
        session, ApiKeyCredential(id=key_id, scope="publish", dataset_id=None)
    )


async def apply_fields_for_job(
    session: AsyncSession,
    job_id: uuid.UUID,
    dataset: Any,
    user_metadata: dict | None,
    *,
    audience_before: str | None = None,
    share_groups: bool = True,
) -> GroupShare:
    """:func:`apply_dataset_fields` for a task that holds the job's id.

    The row is the one the publication already loaded, which carries its
    pending warnings.
    """
    job = await session.get(IngestJob, job_id)
    if job is None:
        return GroupShare()
    return await apply_dataset_fields(
        session,
        job,
        dataset,
        user_metadata,
        audience_before=audience_before,
        share_groups=share_groups,
    )


async def share_groups_for_job(
    session: AsyncSession,
    job_id: uuid.UUID,
    dataset: Any,
    user_metadata: dict,
    *,
    audience_before: str | None,
) -> GroupShare:
    """The job's share alone, for a replacement that shares before it writes
    the visibility; see ``_apply_groups``."""
    job = await session.get(IngestJob, job_id)
    if job is None:
        return GroupShare()
    submitter = await load_submitter(session, job.created_by)
    return await _apply_groups(
        session, job, dataset, user_metadata, submitter, audience_before
    )


def record_manifest_tile_cache_version(job: Any, dataset: Any) -> None:
    """Remember the tile cache version this publish left, for the next dry run."""
    metadata = job.user_metadata or {}
    if "manifest_key" not in metadata:
        return
    job.user_metadata = {
        **metadata,
        TILE_CACHE_VERSION_METADATA_KEY: dataset.tile_cache_version,
    }
