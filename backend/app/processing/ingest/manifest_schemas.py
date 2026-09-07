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

from app.core.text import reject_html_markup

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
        # Local-path alternation allows only a `./` prefix (not `../`); `..`
        # mid-path/trailing is enforced separately by `_reject_dotdot_segments`
        # below, since pydantic_core's regex (Rust) has no look-ahead to
        # express both rules at once. HTTP/storage URIs are unrestricted —
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
# gh#1736: caller-declared digest, used only for change-detection — apply
# never fetches the source to verify it (see manifest_service._run_entry's
# skip-complete message for the implication on a stable URI whose content
# changes underneath it).
#
# gh#1773: min_length/max_length(71) is a security bound, not padding.
# Python's `re` (used by the CLI's separate JSON Schema mirror of this
# pattern) treats `$` as matching just before a trailing newline; pydantic-
# core's regex anchors to the true string end. Without the length bound
# here AND in the emitted OpenAPI schema, a trailing-newline checksum could
# pass one validator and not the other. test_manifest_apply_api.py pins both.
#
# Checksum bumps do not force reclassification for a raster_cog source —
# _validate_existing_dataset_update rejects the update instead of skipping
# it (see the Field description below and _skip_complete_message).
ManifestChecksum = Annotated[
    str,
    Field(
        min_length=71,
        max_length=71,
        pattern=r"^sha256:[0-9a-f]{64}$",
        description=(
            "Declared SHA-256 digest of the source bytes, as "
            "'sha256:<64 lowercase hex characters>'. Apply uses this only as "
            "a change-detection input alongside the rest of the entry; it is "
            "not verified against the fetched bytes. For a vector source, "
            "bump it when the file under a stable URI changes, to force "
            "apply to reclassify the entry as an update instead of "
            "skipping it. Manifest raster updates are not supported: do not "
            "set or change checksum on a raster_cog source, because a "
            "changed value there makes apply report that entry as an error "
            "('Manifest raster updates are not supported; create a new "
            "raster dataset instead.'), not a skip. An unchanged raster "
            "entry, checksum included, still skips normally."
        ),
    ),
]
ManifestBboxCoordinate = Annotated[float, Field(ge=-180, le=180)]
ManifestBbox = Annotated[
    list[ManifestBboxCoordinate],
    Field(min_length=4, max_length=4, description="WGS84 bbox hint."),
]

# fix(#1683): mirrors the upload door's tier-1 vector formats (FlatGeobuf,
# KML, KMZ, zipped File Geodatabase). `.zip` already covers a zipped FGDB —
# the shapefile-vs-fgdb split happens downstream in `source_format.py`,
# keyed off content, not this schema.
MANIFEST_SOURCE_EXTENSIONS: dict[str, frozenset[str]] = {
    "vector": frozenset(
        {
            ".zip",
            ".gpkg",
            ".geojson",
            ".json",
            ".csv",
            ".xlsx",
            ".xls",
            ".fgb",
            ".kml",
            ".kmz",
        }
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
    # Standalone VRT files are deliberately excluded: their referenced files
    # are not owned or preserved by a manifest apply.
    type: Literal["vector", "raster_cog"] = Field(
        description=(
            "Source modality. Vector sources require zip, gpkg, geojson, json, "
            "csv, xlsx, xls, fgb, kml, or kmz; raster_cog sources require tif "
            "or tiff."
        )
    )
    uri: ManifestSourceUri
    title: NonEmptyString500 | None = None
    description: NonEmptyString5000 | None = None
    format: NonEmptyString100 | None = None
    layer: NonEmptyString500 | None = None
    checksum: ManifestChecksum | None = None

    @field_validator("uri")
    @classmethod
    def _reject_dotdot_segments(cls, uri: str) -> str:
        """Reject `..` path traversal in manifest source URIs.

        Checks every `/`-split path segment, catching `../etc/passwd`,
        `foo/../bar`, and trailing `./..` regardless of which alternation
        matched the structural regex. Also applied to remote schemes for
        defense-in-depth.
        """
        # Strip scheme first, or `https://...` splits on `/` and passes trivially.
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

    # fix(#1472): the manifest is another write path to records.attribution,
    # so it carries the dataset PATCH's same guard — enforced here so markup
    # fails apply with a 422 instead of being silently dropped at commit.
    @field_validator("attribution")
    @classmethod
    def attribution_is_not_markup(cls, v: str | None) -> str | None:
        return reject_html_markup(v)

    @field_validator("tags")
    @classmethod
    def tags_must_be_unique(
        cls, tags: list[NonEmptyString100] | None
    ) -> list[NonEmptyString100] | None:
        if tags is not None and len(tags) != len(set(tags)):
            raise ValueError("metadata tags must be unique")
        return tags


class ManifestPublication(_ManifestBaseModel):
    # fix(#1201): deliberately NOT a Literal — record_status is an open set
    # (an overlay may define its own, #1183), and a frozen enum here 422'd
    # statuses the API itself accepted. Checked live by
    # `validate_publication_intent` in manifest_sources.py. 20-char bound
    # matches the record_status column (String(20)).
    intent: str = Field(
        min_length=1,
        max_length=20,
        description=(
            "Publication intent. Deliberately not pinned to an enum: the "
            "values come from the workflow extension's status_order(), so an "
            "overlay may define its own, and apply validates against the live "
            "extension. Community default order: draft, ready, internal, "
            "published."
        ),
    )


class ManifestDataset(_ManifestBaseModel):
    key: ManifestDatasetKey
    title: NonEmptyString500
    description: NonEmptyString5000 | None = None
    # Exactly one source per ingest job — extra entries would join the
    # idempotency fingerprint while silently being ignored.
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
