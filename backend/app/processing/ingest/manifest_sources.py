"""Helpers for manifest apply source handling and metadata projection."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from app.core.config import settings
from app.processing.ingest.manifest_schemas import (
    ManifestDataset,
    ManifestPublication,
    ManifestSource,
)

ManifestPublicationIntent = Literal["draft", "ready", "internal", "published"]
ManifestSourceKind = Literal["local", "http", "storage"]


class ManifestSourceError(ValueError):
    """A manifest source cannot be routed through existing ingest paths."""


@dataclass(frozen=True)
class ManifestPreparedSource:
    """A source after URI validation and filename/path derivation."""

    kind: ManifestSourceKind
    source: ManifestSource
    source_uri: str
    source_filename: str
    extension: str
    file_path: str | None
    source_url: str | None
    source_layer: str | None
    file_type: str | None


_PUBLICATION_TO_CATALOG: dict[ManifestPublicationIntent, tuple[str, str]] = {
    "draft": ("private", "draft"),
    "ready": ("private", "ready"),
    "internal": ("internal", "internal"),
    "published": ("public", "published"),
}


def publication_to_catalog_fields(
    intent: ManifestPublication | ManifestPublicationIntent,
) -> tuple[str, str]:
    """Map manifest publication intent to catalog visibility and record_status."""
    raw_intent = intent.intent if isinstance(intent, ManifestPublication) else intent
    return _PUBLICATION_TO_CATALOG[raw_intent]


def manifest_dataset_fingerprint(dataset: ManifestDataset) -> str:
    """Return a deterministic fingerprint for a manifest dataset entry."""
    payload = dataset.model_dump(mode="json", exclude_none=True)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


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
    return key


async def classify_manifest_source(
    source: ManifestSource,
) -> ManifestPreparedSource:
    """Validate and classify the first source for existing ingest task routing."""
    if source.type not in {"vector", "raster_cog", "vrt"}:
        raise ManifestSourceError(f"Unsupported manifest source type: {source.type}")

    filename = derive_source_filename(source)
    extension = derive_source_extension(source)
    parsed = urlparse(source.uri)
    file_type = "raster" if source.type in {"raster_cog", "vrt"} else None

    if parsed.scheme in {"http", "https"}:
        from app.modules.catalog.sources import security as source_security

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

    if parsed.scheme in {"s3", "gs", "az", "abfs"}:
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

    return ManifestPreparedSource(
        kind="local",
        source=source,
        source_uri=source.uri,
        source_filename=filename,
        extension=extension,
        file_path=source.uri,
        source_url=None,
        source_layer=source.layer,
        file_type=file_type,
    )


def manifest_job_metadata(
    dataset: ManifestDataset,
    prepared: ManifestPreparedSource,
    *,
    fingerprint: str,
) -> dict[str, object]:
    """Build the metadata ledger stored on manifest-created ingest jobs."""
    visibility, record_status = publication_to_catalog_fields(dataset.publication)
    metadata = dataset.metadata
    srid_override = parse_manifest_crs(metadata.crs if metadata else None)
    job_metadata: dict[str, object] = {
        "title": prepared.source.title or dataset.title,
        "summary": prepared.source.description or dataset.description,
        "visibility": visibility,
        "record_status": record_status,
        "manifest_key": dataset.key,
        "manifest_fingerprint": fingerprint,
        "manifest_source_type": prepared.source.type,
        "manifest_source_uri": prepared.source_uri,
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
    return job_metadata
