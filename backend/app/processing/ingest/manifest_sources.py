"""Helpers for manifest apply source handling and metadata projection."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlparse

import structlog
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.async_io import (
    run_in_thread_draining,
    run_in_thread_draining_capture_cancel,
)
from app.core.config import settings
from app.core.db.session import release_connection
from app.platform.jobs.models import (
    DATABASE_SOURCE_METADATA_KEY,
    MANIFEST_FINGERPRINT_METADATA_KEY,
    IngestJob,
)
from app.platform.jobs.sweep import JOB_TIMEOUT_SECONDS, may_be_stale
from app.processing.ingest.manifest_reservation import (
    claim_upload,
    plain_upload,
    unclaimed_upload,
)
from app.processing.ingest.manifest_schemas import (
    MANIFEST_SOURCE_EXTENSIONS,
    UPLOAD_URI_PREFIX,
    ManifestDataset,
    ManifestPublication,
    ManifestSource,
)

if TYPE_CHECKING:
    from app.core.identity import Identity
    from app.processing.ingest.manifest_dataset_fields import ManifestEntryFields

log = structlog.get_logger()

# A catalog record_status is an open set (an overlay may define
# its own, #1183); validate against the live extension, never re-freeze it.
ManifestPublicationIntent = str
ManifestSourceKind = Literal["local", "http", "storage", "upload"]

# One answer for every upload an entry can't claim, so a caller can't tell
# another account's job id from one that never existed.
UPLOAD_SOURCE_UNAVAILABLE = (
    "The upload this source names is unknown, has expired, or was already "
    "used. Upload the file again."
)

UPLOAD_READ_FAILED = (
    "The uploaded file could not be read to check its checksum. Try again later."
)

# Reading the upload back is bounded like staging a downloaded source.
UPLOAD_CHECKSUM_MAX_SECONDS = JOB_TIMEOUT_SECONDS // 2
_CHECKSUM_CHUNK_BYTES = 1024 * 1024


class ManifestSourceError(ValueError):
    """A manifest source cannot be routed through existing ingest paths."""


@dataclass(frozen=True)
class ManifestUpload:
    """The caller's own pending upload, with bytes that matched the entry's checksum."""

    job_id: uuid.UUID
    attempt_id: uuid.UUID | None
    file_path: str
    size_bytes: int


@dataclass(frozen=True)
class ManifestPreparedSource:
    """A source after URI validation and filename/path derivation.

    ``upload`` is set for an ``upload:`` source this entry may still claim.
    An ``upload:`` source without it names an upload this key already used.
    """

    kind: ManifestSourceKind
    source: ManifestSource
    source_uri: str
    source_filename: str
    extension: str
    file_path: str | None
    source_url: str | None
    source_layer: str | None
    file_type: str | None
    upload: ManifestUpload | None = None


# Visibility for the four community statuses only. An unlisted
# extension-defined status gets `_UNMAPPED_INTENT_VISIBILITY` — a status this
# backend can't interpret must never be the one that widens visibility.
_COMMUNITY_INTENT_VISIBILITY: dict[str, str] = {
    "draft": "private",
    "ready": "private",
    "internal": "internal",
    "published": "public",
}
_UNMAPPED_INTENT_VISIBILITY = "private"


def validate_publication_intent(
    intent: ManifestPublication | ManifestPublicationIntent,
) -> str:
    """Check a manifest publication intent against the live workflow extension.

    The allowed set is the registered WorkflowExtension's ``status_order()``,
    resolved per call and never cached, because an overlay registers after
    import.
    """
    from app.platform.extensions import get_workflow_extension

    raw_intent = intent.intent if isinstance(intent, ManifestPublication) else intent
    allowed = tuple(get_workflow_extension().status_order())
    if raw_intent not in allowed:
        raise ManifestSourceError(
            f"Unsupported manifest publication intent {raw_intent!r}; the "
            f"workflow extension allows: {', '.join(allowed)}"
        )
    return raw_intent


def publication_to_catalog_fields(
    intent: ManifestPublication | ManifestPublicationIntent,
) -> tuple[str, str]:
    """Map manifest publication intent to catalog visibility and record_status."""
    raw_intent = validate_publication_intent(intent)
    visibility = _COMMUNITY_INTENT_VISIBILITY.get(
        raw_intent, _UNMAPPED_INTENT_VISIBILITY
    )
    return visibility, raw_intent


def manifest_dataset_fingerprint(dataset: ManifestDataset) -> str:
    """Return a deterministic fingerprint for a manifest dataset entry.

    An ``upload:`` source counts by its checksum, not its job id, so the same
    file uploaded again matches the entry that published it.
    """
    payload = dataset.model_dump(mode="json", exclude_none=True)
    for source in payload["sources"]:
        if source["uri"].startswith(UPLOAD_URI_PREFIX):
            source["uri"] = source["checksum"]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _validate_existing_dataset_update(
    existing_dataset: object,
    prepared: ManifestPreparedSource,
) -> None:
    """Reject a manifest update whose source can't replace the dataset's data.

    A ``raster_cog`` source replaces only a raster dataset's COG, the way a
    raster re-upload does; a mosaic is defined by its members, not a file. A
    vector source replaces only a feature table.
    """
    record = getattr(existing_dataset, "record", None)
    record_type = getattr(record, "record_type", None)

    if prepared.source.type == "raster_cog":
        if record_type != "raster_dataset":
            raise ManifestSourceError(
                "Manifest raster updates can replace only a raster dataset, "
                f"not an existing {record_type or 'unknown'} dataset."
            )
        return
    if record_type not in {"vector_dataset", "table"}:
        raise ManifestSourceError(
            f"Manifest vector updates cannot replace an existing {record_type or 'unknown'} dataset."
        )


def parse_manifest_crs(crs: str | None) -> int | None:
    """Parse a manifest EPSG CRS string into an integer SRID override."""
    if crs is None:
        return None
    prefix, _, value = crs.partition(":")
    if prefix.upper() != "EPSG" or not value:
        raise ManifestSourceError(f"Unsupported CRS value: {crs}")
    return int(value)


def derive_source_filename(source: ManifestSource) -> str:
    """Derive a safe source filename from a manifest source URI."""
    parsed = urlparse(source.uri)
    path_value = parsed.path if parsed.scheme else source.uri
    filename = Path(path_value).name
    if not filename:
        raise ManifestSourceError("Manifest source URI must include a filename")
    return filename


def derive_source_extension(source: ManifestSource) -> str:
    """Return the lower-case file extension for a manifest source."""
    extension = Path(derive_source_filename(source)).suffix.lower()
    if not extension:
        raise ManifestSourceError("Manifest source URI must include a file extension")
    return extension


def _storage_uri_to_key(uri: str) -> str:
    parsed = urlparse(uri)
    if parsed.scheme != "s3":
        raise ManifestSourceError(
            f"Storage URI scheme '{parsed.scheme}' is not supported by this backend"
        )
    if settings.storage_provider != "s3":
        raise ManifestSourceError("s3:// manifest sources require S3 storage mode")
    if settings.s3_bucket and parsed.netloc != settings.s3_bucket:
        raise ManifestSourceError(
            f"s3:// manifest source bucket must match configured bucket "
            f"'{settings.s3_bucket}'"
        )
    key = parsed.path.lstrip("/")
    if not key:
        raise ManifestSourceError("s3:// manifest source must include an object key")
    # `staging/` keys are system-owned transient uploads, reaped at terminal
    # job status; an operator-declared source there would be deleted.
    if key.startswith("staging/"):
        raise ManifestSourceError(
            "s3:// manifest source keys must not use the 'staging/' prefix: "
            "staging/ is system-owned transient storage that is deleted when "
            "ingest jobs reach terminal status. Move the object to a "
            "different prefix."
        )
    return key


def _require_source_extension(source: ManifestSource, extension: str) -> None:
    allowed_extensions = MANIFEST_SOURCE_EXTENSIONS[source.type]
    if extension == ".vrt":
        raise ManifestSourceError(
            "Standalone VRT manifest sources are not supported; create a "
            "managed VRT from catalog-tracked raster datasets"
        )
    if extension not in allowed_extensions:
        expected = ", ".join(sorted(allowed_extensions))
        raise ManifestSourceError(
            f"Manifest source type {source.type!r} requires one of: {expected}"
        )


async def classify_manifest_source(
    source: ManifestSource,
) -> ManifestPreparedSource:
    """Validate and classify the first source for existing ingest task routing."""
    if source.type not in {"vector", "raster_cog"}:
        raise ManifestSourceError(f"Unsupported manifest source type: {source.type}")

    filename = derive_source_filename(source)
    extension = derive_source_extension(source)
    _require_source_extension(source, extension)
    parsed = urlparse(source.uri)
    file_type = "raster" if source.type == "raster_cog" else None

    if parsed.scheme in {"http", "https"}:
        from app.platform import security as source_security

        try:
            await source_security.validate_url_for_ssrf(source.uri)
        except source_security.SSRFError as exc:
            raise ManifestSourceError(str(exc)) from exc
        return ManifestPreparedSource(
            kind="http",
            source=source,
            source_uri=source.uri,
            source_filename=filename,
            extension=extension,
            file_path=None,
            source_url=source.uri,
            source_layer=source.layer,
            file_type=file_type,
        )

    if parsed.scheme in {"s3"}:
        return ManifestPreparedSource(
            kind="storage",
            source=source,
            source_uri=source.uri,
            source_filename=filename,
            extension=extension,
            file_path=_storage_uri_to_key(source.uri),
            source_url=None,
            source_layer=source.layer,
            file_type=file_type,
        )

    if parsed.scheme:
        raise ManifestSourceError(f"Unsupported manifest source URI: {source.uri}")

    # Defense-in-depth beyond the ManifestSourceUri regex's `..` rejection:
    # resolve against upload_staging_dir and refuse an escape, catching
    # symlink chases, encoding tricks, and future regex weakening.
    staging_root = Path(settings.upload_staging_dir).resolve()
    relative_source = Path(source.uri)
    # `staging/foo.geojson` spellings mean the leading component IS the
    # root, not `staging/staging`.
    if relative_source.parts and relative_source.parts[0] == staging_root.name:
        relative_source = Path(*relative_source.parts[1:])
    candidate = (staging_root / relative_source).resolve()
    try:
        candidate.relative_to(staging_root)
    except ValueError as exc:
        raise ManifestSourceError(
            f"Local manifest source URI {source.uri!r} resolves outside "
            f"the configured upload_staging_dir; path traversal is not "
            f"permitted."
        ) from exc

    return ManifestPreparedSource(
        kind="local",
        source=source,
        source_uri=source.uri,
        source_filename=filename,
        extension=extension,
        # Canonical path, not the caller's relative spelling, so workers
        # don't resolve it against their own cwd.
        file_path=str(candidate),
        source_url=None,
        source_layer=source.layer,
        file_type=file_type,
    )


def manifest_job_metadata(
    dataset: ManifestDataset,
    prepared: ManifestPreparedSource,
    *,
    fingerprint: str,
    fields: ManifestEntryFields | None = None,
) -> dict[str, object]:
    """Build the metadata ledger stored on manifest-created ingest jobs.

    A version 2 entry passes ``fields``: its visibility is the explicit one,
    never the intent's, and an omitted one is left out so a create is private
    and an update keeps what the dataset has.
    """
    visibility, record_status = publication_to_catalog_fields(dataset.publication)
    metadata = dataset.metadata
    srid_override = parse_manifest_crs(metadata.crs if metadata else None)
    from app.core.url_redaction import redact_url_credentials

    job_metadata: dict[str, object] = {
        "title": prepared.source.title or dataset.title,
        "summary": prepared.source.description or dataset.description,
        "visibility": visibility,
        "record_status": record_status,
        "manifest_key": dataset.key,
        MANIFEST_FINGERPRINT_METADATA_KEY: fingerprint,
        "manifest_source_type": prepared.source.type,
        "manifest_source_uri": redact_url_credentials(prepared.source_uri),
        "manifest_publication_intent": dataset.publication.intent,
        "manifest_tags": list(metadata.tags or []) if metadata else [],
    }
    if srid_override is not None:
        job_metadata["srid_override"] = srid_override
    if prepared.source_layer:
        job_metadata["layer_name"] = prepared.source_layer
    if prepared.file_type:
        job_metadata["file_type"] = prepared.file_type
    if metadata is not None:
        if metadata.organization is not None:
            job_metadata["manifest_organization"] = metadata.organization
        if metadata.license is not None:
            job_metadata["manifest_license"] = metadata.license
        if metadata.attribution is not None:
            job_metadata["manifest_attribution"] = metadata.attribution
        if metadata.bbox is not None:
            job_metadata["manifest_bbox"] = list(metadata.bbox)
    if fields is not None:
        from app.processing.ingest.manifest_dataset_fields import job_metadata_fields

        job_metadata.pop("visibility")
        job_metadata.update(job_metadata_fields(dataset, fields))
    return job_metadata


async def prepare_manifest_source(
    db: AsyncSession, dataset: ManifestDataset, user: Identity
) -> ManifestPreparedSource:
    """Validate and classify an entry's source.

    An ``upload:`` source must name the caller's own pending upload, unclaimed
    and unexpired, whose bytes match the entry's checksum, or one this key
    already used. Every other miss raises ``UPLOAD_SOURCE_UNAVAILABLE``.
    """
    source = dataset.sources[0]
    if not source.uri.startswith(UPLOAD_URI_PREFIX):
        return await classify_manifest_source(source)

    job_id = uuid.UUID(source.uri.removeprefix(UPLOAD_URI_PREFIX))
    row = (
        await db.execute(
            select(
                IngestJob,
                and_(
                    IngestJob.status == "pending",
                    func.coalesce(IngestJob.file_path, "") != "",
                    plain_upload(),
                    unclaimed_upload(),
                ).label("claimable"),
            ).where(
                IngestJob.id == job_id,
                IngestJob.created_by == user.id,
                IngestJob.source_url.is_(None),
                IngestJob.user_metadata[DATABASE_SOURCE_METADATA_KEY].astext.is_(None),
            )
        )
    ).one_or_none()
    if row is None:
        raise ManifestSourceError(UPLOAD_SOURCE_UNAVAILABLE)
    job, claimable = row
    metadata = job.user_metadata or {}
    claimable = claimable and not may_be_stale(job, datetime.now(timezone.utc))
    if not claimable and metadata.get("manifest_key") != dataset.key:
        raise ManifestSourceError(UPLOAD_SOURCE_UNAVAILABLE)

    filename = job.source_filename or ""
    extension = Path(filename).suffix.lower()
    _require_source_extension(source, extension)
    expected_file_type = "raster" if source.type == "raster_cog" else None
    if metadata.get("file_type") not in (None, expected_file_type):
        raise ManifestSourceError(
            f"The upload is a {metadata['file_type']} file, not a {source.type} source."
        )
    prepared = ManifestPreparedSource(
        kind="upload",
        source=source,
        source_uri=source.uri,
        source_filename=filename,
        extension=extension,
        file_path=job.file_path,
        source_url=None,
        source_layer=source.layer,
        file_type=expected_file_type,
    )
    if not claimable:
        return prepared

    file_path, attempt_id = job.file_path, job.attempt_id
    # The file may be a large object in S3; no pooled connection waits on it.
    await release_connection(db)
    size_bytes = await _verify_upload_checksum(file_path, source.checksum or "")
    return replace(
        prepared,
        upload=ManifestUpload(job_id, attempt_id, file_path, size_bytes),
    )


def refuse_used_upload(prepared: ManifestPreparedSource) -> None:
    """Refuse to queue an ``upload:`` source this key already used."""
    if prepared.kind == "upload" and prepared.upload is None:
        raise ManifestSourceError(UPLOAD_SOURCE_UNAVAILABLE)


async def claim_upload_source(
    db: AsyncSession,
    prepared: ManifestPreparedSource,
    user: Identity,
    metadata: dict[str, object],
    *,
    dataset_id: uuid.UUID | None,
) -> IngestJob:
    """Make the entry's checked upload its reservation, or refuse. Does not commit."""
    upload = prepared.upload
    job = None
    if upload is not None:
        job = await claim_upload(
            db,
            job_id=upload.job_id,
            attempt_id=upload.attempt_id,
            file_path=upload.file_path,
            owner=user.id,
            metadata=metadata,
            dataset_id=dataset_id,
            source_layer=prepared.source_layer,
        )
    if job is None:
        raise ManifestSourceError(UPLOAD_SOURCE_UNAVAILABLE)
    return job


async def _verify_upload_checksum(file_path: str, checksum: str) -> int:
    """Hash the staged upload and compare it to ``checksum``. Returns its size."""
    try:
        async with asyncio.timeout(UPLOAD_CHECKSUM_MAX_SECONDS):
            digest, size_bytes = await _staged_upload_sha256(file_path)
    except TimeoutError as exc:
        raise ManifestSourceError(
            "The upload could not be checked against its checksum within "
            f"{UPLOAD_CHECKSUM_MAX_SECONDS} seconds"
        ) from exc
    except (OSError, RuntimeError) as exc:
        raise ManifestSourceError(UPLOAD_SOURCE_UNAVAILABLE) from exc
    except Exception as exc:  # broad: a storage SDK error can name the endpoint and key
        log.warning("manifest_upload_checksum_read_failed", exc_info=exc)
        raise ManifestSourceError(UPLOAD_READ_FAILED) from exc
    if not hmac.compare_digest(f"sha256:{digest}", checksum):
        raise ManifestSourceError(
            "The uploaded file does not match the source's checksum. Send the "
            "SHA-256 of the file you uploaded, or upload the file again."
        )
    return size_bytes


async def _staged_upload_sha256(file_path: str) -> tuple[str, int]:
    """SHA-256 and size of an upload's staged bytes, read in chunks.

    A ``staging/`` key is a logical storage key, resolved for the caller's
    tenant like every other reader of one; anything else is the local file the
    upload door wrote under the staging directory.
    """
    digest = hashlib.sha256()
    size_bytes = 0
    if file_path.startswith("staging/"):
        from app.platform.storage import get_storage
        from app.platform.storage.titiler_url import resolve_current_storage_key

        chunks = get_storage().get_stream(resolve_current_storage_key(file_path))
        try:
            async for chunk in chunks:
                await run_in_thread_draining(digest.update, chunk)
                size_bytes += len(chunk)
        finally:
            aclose = getattr(chunks, "aclose", None)
            if aclose is not None:
                await aclose()
        return digest.hexdigest(), size_bytes

    staging_root = Path(settings.upload_staging_dir).resolve()
    path = Path(file_path).resolve()
    if not path.is_relative_to(staging_root):
        raise RuntimeError("upload file is outside the staging directory")
    handle, cancelled = await run_in_thread_draining_capture_cancel(path.open, "rb")
    try:
        if cancelled is not None:
            raise cancelled
        while read := await run_in_thread_draining(_hash_next_chunk, handle, digest):
            size_bytes += read
    finally:
        await run_in_thread_draining(handle.close)
    return digest.hexdigest(), size_bytes


def skip_complete_message(prepared: ManifestPreparedSource) -> str:
    """Explain a skip_complete result.

    Matching the last completed entry means only that, not that the source
    bytes were read: a stable URI whose file changed underneath it lands
    here too, so the message says the source wasn't inspected and that a
    bumped `checksum` forces the update. A fresh upload's bytes were checked,
    so its message says the file is the same and the upload is spare; an
    entry replayed with the upload it already used says only that.
    """
    if prepared.kind == "upload" and prepared.upload is None:
        return "Manifest dataset entry is unchanged: this upload was already applied."
    if prepared.kind == "upload":
        return (
            "Manifest dataset entry is unchanged: the uploaded file matches "
            "the last apply. Cancel the unused upload."
        )
    return (
        "Manifest dataset entry is unchanged; the source was not "
        "inspected. Set checksum on the source to force a re-import "
        "when the file changes under a stable URI."
    )


def _hash_next_chunk(handle, digest) -> int:
    """Read and hash one chunk on a worker thread. Returns its length, 0 at the end."""
    chunk = handle.read(_CHECKSUM_CHUNK_BYTES)
    digest.update(chunk)
    return len(chunk)
