"""Backend-local Pydantic models for manifest apply requests."""

import uuid
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    ValidationInfo,
    field_validator,
)

NonEmptyString100 = Annotated[str, Field(min_length=1, max_length=100)]
NonEmptyString320 = Annotated[str, Field(min_length=1, max_length=320)]
NonEmptyString500 = Annotated[str, Field(min_length=1, max_length=500)]
NonEmptyString2000 = Annotated[str, Field(min_length=1, max_length=2000)]
NonEmptyString5000 = Annotated[str, Field(min_length=1, max_length=5000)]

ManifestDatasetKey = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$",
        description="Stable dataset identity key used for idempotent apply operations.",
    ),
]
ManifestSourceUri = Annotated[
    str,
    Field(
        min_length=1,
        max_length=2000,
        # Phase 268 H-29: the local-path alternation now allows only `./`
        # prefix (NOT `../`); this reverses the prior `(?:\.{1,2}/)?`.
        # The `..` mid-path / trailing exclusion is enforced separately by
        # `_reject_dotdot_segments` below — pydantic_core's regex engine
        # (Rust) does not support look-ahead, so a single regex can't
        # express both the prefix-shape and the `..`-anywhere rule.
        # HTTP/storage URIs in the alternation remain unrestricted because
        # they're not resolved as local filesystem paths.
        pattern=(
            r"^(?:(?:\./)?[^\s:/][^\s:]*|"
            r"https?://[^\s]+|"
            r"s3://[^\s]+|gs://[^\s]+|az://[^\s]+|abfs://[^\s]+)$"
        ),
        description=("Relative path (no `..` traversal), HTTP(S) URL, or storage URI."),
    ),
]
ManifestUrl = Annotated[
    str,
    Field(max_length=2000, pattern=r"^https?://[^\s]+$"),
]
ManifestCrs = Annotated[str, Field(pattern=r"^EPSG:[0-9]{1,6}$")]
ManifestBboxCoordinate = Annotated[float, Field(ge=-180, le=180)]
ManifestBbox = Annotated[
    list[ManifestBboxCoordinate],
    Field(min_length=4, max_length=4, description="WGS84 bbox hint."),
]

MANIFEST_SOURCE_EXTENSIONS: dict[str, frozenset[str]] = {
    "vector": frozenset(
        {".zip", ".gpkg", ".geojson", ".json", ".csv", ".xlsx", ".xls"}
    ),
    "raster_cog": frozenset({".tif", ".tiff"}),
}


class _ManifestBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ManifestContact(_ManifestBaseModel):
    name: NonEmptyString500 | None = None
    email: EmailStr | None = Field(default=None, max_length=320)
    url: ManifestUrl | None = None


class ManifestCatalog(_ManifestBaseModel):
    title: NonEmptyString500
    description: NonEmptyString5000 | None = None
    organization: NonEmptyString500 | None = None
    contact: ManifestContact | None = None


class ManifestSource(_ManifestBaseModel):
    # Manifest v1 can only route sources through the ordinary vector/COG
    # ingestion lifecycle. Standalone VRT files are deliberately excluded:
    # their referenced files are not owned or preserved by a manifest apply.
    type: Literal["vector", "raster_cog"] = Field(
        description=(
            "Source modality. Vector sources require zip, gpkg, geojson, json, "
            "csv, xlsx, or xls; raster_cog sources require tif or tiff."
        )
    )
    uri: ManifestSourceUri
    title: NonEmptyString500 | None = None
    description: NonEmptyString5000 | None = None
    format: NonEmptyString100 | None = None
    layer: NonEmptyString500 | None = None

    @field_validator("uri")
    @classmethod
    def _reject_dotdot_segments(cls, uri: str) -> str:
        """Phase 268 H-29: reject `..` path traversal in manifest source URIs.

        Looks at every path segment (split on `/`). If any equals `..`, the
        URI is rejected — this catches `../etc/passwd`, `foo/../bar`, and
        trailing `./..` regardless of whether the local-path or storage-URI
        alternation matched the structural regex. The check is also applied
        to remote schemes for defense-in-depth (no legitimate HTTP/S3 URI
        contains `..` segments either).
        """
        # Strip scheme so the segment check sees only the path portion;
        # otherwise `https://...` would be split on `/` and pass trivially.
        # urlparse handles this without re-implementing scheme parsing.
        from urllib.parse import urlparse

        parsed = urlparse(uri)
        path = parsed.path if parsed.scheme else uri
        segments = path.split("/")
        if ".." in segments:
            raise ValueError(
                "Manifest source URI must not contain `..` path segments "
                "(traversal is rejected)."
            )
        return uri

    @field_validator("uri")
    @classmethod
    def _require_source_type_extension(cls, uri: str, info: ValidationInfo) -> str:
        """Keep the declared source modality aligned with its file path."""
        source_type = info.data.get("type")
        allowed = MANIFEST_SOURCE_EXTENSIONS.get(str(source_type))
        if allowed is None:
            # The ``type`` field reports its own enum error.
            return uri

        parsed = urlparse(uri)
        path = parsed.path if parsed.scheme else uri
        extension = Path(path).suffix.lower()
        if extension == ".vrt":
            raise ValueError(
                "Standalone VRT manifest sources are not supported; create "
                "a managed VRT from catalog-tracked raster datasets"
            )
        if extension not in allowed:
            expected = ", ".join(sorted(allowed))
            raise ValueError(
                f"Manifest source type {source_type!r} requires one of: {expected}"
            )
        return uri


class ManifestMetadata(_ManifestBaseModel):
    tags: list[NonEmptyString100] | None = None
    organization: NonEmptyString500 | None = None
    crs: ManifestCrs | None = None
    license: NonEmptyString500 | None = None
    attribution: NonEmptyString5000 | None = None
    bbox: ManifestBbox | None = None

    @field_validator("tags")
    @classmethod
    def tags_must_be_unique(
        cls, tags: list[NonEmptyString100] | None
    ) -> list[NonEmptyString100] | None:
        if tags is not None and len(tags) != len(set(tags)):
            raise ValueError("metadata tags must be unique")
        return tags


class ManifestPublication(_ManifestBaseModel):
    intent: Literal["draft", "ready", "internal", "published"]


class ManifestDataset(_ManifestBaseModel):
    key: ManifestDatasetKey
    title: NonEmptyString500
    description: NonEmptyString5000 | None = None
    # Manifest v1 currently routes exactly one source through one ingest job.
    # Accepting additional entries would include them in the idempotency
    # fingerprint while silently ignoring every source after the first.
    sources: list[ManifestSource] = Field(min_length=1, max_length=1)
    metadata: ManifestMetadata | None = None
    publication: ManifestPublication


class ManifestApplyRequest(_ManifestBaseModel):
    manifest_version: Literal["1"]
    catalog: ManifestCatalog
    # Keep one request from causing an unbounded number of remote downloads,
    # quota queries, transactions, and queued jobs. Callers can submit another
    # batch after this one completes.
    datasets: list[ManifestDataset] = Field(min_length=1, max_length=100)
    dry_run: bool = False

    @field_validator("datasets")
    @classmethod
    def dataset_keys_must_be_unique(
        cls, datasets: list[ManifestDataset]
    ) -> list[ManifestDataset]:
        seen: set[str] = set()
        duplicate_keys: list[str] = []
        for dataset in datasets:
            if dataset.key in seen and dataset.key not in duplicate_keys:
                duplicate_keys.append(dataset.key)
            seen.add(dataset.key)
        if duplicate_keys:
            keys = ", ".join(duplicate_keys)
            raise ValueError(f"duplicate dataset key(s): {keys}")
        return datasets


class ManifestApplyEntryResult(BaseModel):
    dataset_key: str
    action: Literal["create", "update", "skip", "error"]
    job_id: uuid.UUID | None = None
    dataset_id: uuid.UUID | None = None
    message: str
    errors: list[str] = Field(default_factory=list)


class ManifestApplyResponse(BaseModel):
    accepted: bool
    dry_run: bool
    results: list[ManifestApplyEntryResult]
