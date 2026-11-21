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
from app.platform.jobs.models import ADMITTED_PUBLISH_KEY_METADATA_KEY, IngestJob
from app.platform.record_audience import opens_to_anonymous, publish_key_widening
from app.platform.request_credential import (
    ApiKeyCredential,
    acting_with,
    is_publish_key,
)
from app.processing.ingest.manifest_schemas import (
    MAX_MANIFEST_ATTRIBUTES,
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
ATTRIBUTE_UNMATCHED = "A092"

TILE_CACHE_VERSION_METADATA_KEY = "manifest_tile_cache_version"
COLLECTION_METADATA_KEY = "manifest_collection_id"
ATTRIBUTES_METADATA_KEY = "manifest_attributes"

# Job warning kinds, which a client reads as the codes beside them.
COLLECTION_REFUSED_KIND = "manifest_collection_refused"
ATTRIBUTE_UNMATCHED_KIND = "manifest_attribute_unmatched"


def _public_refused(
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
    messages: list[ManifestMessage] = field(default_factory=list)
    # Who was refused a named public, decided once the entry is known to
    # change something: a skip writes nothing, so it applies no fallback.
    public_refused_for_key: bool | None = None
    edits_attributes: bool = False

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

    def downgrade_or_refuse(
        self, dataset: ManifestDataset, *, publish_key: bool
    ) -> None:
        """Handle a refused ``public``: write ``internal`` only when asked to."""
        if self.public_fallback == "internal":
            self.visibility = "internal"
            self.messages.append(
                _public_refused(dataset, "warning", publish_key=publish_key)
            )
            return
        raise ManifestEntryRefused(
            [_public_refused(dataset, "error", publish_key=publish_key)]
        )

    async def judge_update(
        self,
        db: AsyncSession,
        user: Identity,
        dataset: ManifestDataset,
        existing: Any,
    ) -> None:
        """Hold an update to what the metadata edit lets the caller change.

        Attribute text on an existing dataset needs ``edit_metadata``, as the
        attribute edit does; the job then records that capability, which the
        publish checks again. An omitted visibility keeps the dataset's, so
        publishing a public draft opens it to anonymous readers without the
        entry naming ``public``. A publish key may not do that: it is a
        refused public, with the fallback to internal when asked. The publish
        judges it again, holding the dataset's rows.
        """
        if dataset.attributes:
            submitter = await load_submitter(db, user.id)
            if (
                submitter is None
                or not await get_permission_extension().check_permission(
                    db,
                    submitter,
                    EDIT_METADATA,
                    user_roles={r.name for r in submitter.roles},
                )
            ):
                raise ManifestSourceError(f"Missing permission: {EDIT_METADATA}")
            self.edits_attributes = True
        if not is_publish_key(db):
            return
        record = existing.record
        await db.refresh(record, attribute_names=["visibility", "record_status"])
        _, record_status = publication_to_catalog_fields(dataset.publication)
        now = (record.visibility, record.record_status)
        change = {"visibility": self.visibility, "record_status": record_status}
        if self.visibility is None and opens_to_anonymous(*now, **change):
            self.downgrade_or_refuse(dataset, publish_key=True)
            change["visibility"] = self.visibility
        if refusal := publish_key_widening(*now, **change):
            raise ManifestSourceError(refusal)

    def note_edits_since_publish(
        self, dataset: ManifestDataset, completed_job: Any, existing: Any
    ) -> None:
        """Warn when the dataset's tile cache version moved since that publish."""
        recorded = (completed_job.user_metadata or {}).get(
            TILE_CACHE_VERSION_METADATA_KEY
        )
        current = getattr(existing, "tile_cache_version", None)
        if (
            isinstance(recorded, int)
            and isinstance(current, int)
            and current > recorded
        ):
            self.messages.append(
                ManifestMessage(
                    code=EDITED_SINCE_PUBLISH,
                    severity="warning",
                    message=(
                        f"Features in {dataset.title!r} were edited in GeoLens "
                        "since the last publish. Replacing discards those "
                        "edits; the previous version stays restorable once."
                    ),
                    fix="Publish as new, or Continue.",
                )
            )


def settle_refused_public(
    fields: ManifestEntryFields | None, dataset: ManifestDataset
) -> None:
    """Act on a named public the gate refused, once the entry is known to
    write something."""
    if fields is not None and fields.public_refused_for_key is not None:
        fields.downgrade_or_refuse(dataset, publish_key=fields.public_refused_for_key)


def report_entry(
    fields: ManifestEntryFields | None, result: ManifestApplyEntryResult
) -> ManifestApplyEntryResult:
    """Give a version 2 entry's result its messages, whatever it did: a held
    run still carries what the entry decided."""
    if fields is not None and result.action != "error":
        result.messages = [*(result.messages or []), *fields.messages]
    return result


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
    fields: ManifestEntryFields,
    *,
    dry_run: bool,
) -> None:
    """Resolve the entry's collection before anything is queued.

    A refusal is warning A033 and the entry carries on without a collection.
    A dry run creates nothing and reports what an apply would.
    """
    if dataset.collection is None:
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
    """The v2 keys of a manifest job's metadata, for the ingest tail to apply."""
    metadata: dict[str, object] = {}
    if fields.visibility is not None:
        metadata["visibility"] = fields.visibility
    if fields.collection_id is not None:
        metadata[COLLECTION_METADATA_KEY] = str(fields.collection_id)
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


def _append_warning(job: Any, warning: dict[str, Any]) -> None:
    warnings = list((job.user_metadata or {}).get("warnings", []))
    warnings.append(warning)
    job.user_metadata = {**(job.user_metadata or {}), "warnings": warnings}


async def apply_dataset_fields(
    session: AsyncSession,
    job: Any,
    dataset: Any,
    user_metadata: dict | None,
) -> None:
    """Add the dataset to its collection, save its attribute text and note the
    tile cache version the dataset has now.

    The ingest tail calls this inside the transaction that publishes the
    dataset, after the submitter's write access to it was checked, and after
    any storage writes, since the collection row it takes is held to the
    commit. A job no manifest created changes nothing. Refusals, a collection
    that stays busy and unmatched names become job warnings; none fails the
    job.
    """
    if not user_metadata or "manifest_key" not in user_metadata:
        return
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
            with _as_publish_key(session, user_metadata):
                code = await port.add_dataset_to_manifest_collection(
                    session, collection_id, dataset.id, submitter
                )
        if code is not None:
            details = {"collection_id": str(collection)}
            if code == COLLECTION_BUSY_CODE:
                details["reason"] = "busy"
            _append_warning(job, {"kind": COLLECTION_REFUSED_KIND, "details": details})

    attributes = _stored_attributes(user_metadata)
    if attributes and submitter is not None:
        unmatched = await port.apply_manifest_attributes(
            session, dataset.id, attributes, actor_id=submitter.id
        )
        if unmatched:
            _append_warning(
                job,
                {
                    "kind": ATTRIBUTE_UNMATCHED_KIND,
                    "details": {"source_names": list(unmatched)},
                },
            )
    record_manifest_tile_cache_version(job, dataset)


def _as_publish_key(
    session: AsyncSession, metadata: dict
) -> contextlib.AbstractContextManager[None]:
    """The scope of the publish key a job was queued or accepted with, so
    the collection checks reach only the key owner's own collections."""
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
) -> None:
    """:func:`apply_dataset_fields` for a task that holds the job's id.

    The row is the one the publication already loaded, which carries its
    pending warnings.
    """
    job = await session.get(IngestJob, job_id)
    if job is not None:
        await apply_dataset_fields(session, job, dataset, user_metadata)


def record_manifest_tile_cache_version(job: Any, dataset: Any) -> None:
    """Remember the tile cache version this publish left, for the next dry run."""
    metadata = job.user_metadata or {}
    if "manifest_key" not in metadata:
        return
    job.user_metadata = {
        **metadata,
        TILE_CACHE_VERSION_METADATA_KEY: dataset.tile_cache_version,
    }
