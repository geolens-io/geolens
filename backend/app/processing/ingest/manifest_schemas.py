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
    SerializerFunctionWrapHandler,
    ValidationInfo,
    field_validator,
    model_serializer,
    model_validator,
)

from app.core.text import reject_html_markup
from app.platform.value_labels import is_storable_text

NonEmptyString100 = Annotated[str, Field(min_length=1, max_length=100)]
NonEmptyString500 = Annotated[str, Field(min_length=1, max_length=500)]
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
        # A local path may start with `./` but not `../`. pydantic_core's
        # regex has no look-ahead, so `_reject_dotdot_segments` rejects `..`
        # elsewhere. HTTP and storage URIs are never resolved as local paths.
        pattern=(
            r"^(?:(?:\./)?[^\s:/][^\s:]*|"
            r"https?://[^\s]+|"
            r"s3://[^\s]+|"
            r"upload:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$"
        ),
        description=(
            "Relative path (no `..` traversal), HTTP(S) URL, s3:// storage URI, "
            "or, in manifest_version 2, `upload:<job_id>` naming a pending "
            "upload the caller made."
        ),
    ),
]
UPLOAD_URI_PREFIX = "upload:"
ManifestUrl = Annotated[
    str,
    Field(max_length=2000, pattern=r"^https?://[^\s]+$"),
]
ManifestCrs = Annotated[str, Field(pattern=r"^EPSG:[0-9]{1,6}$")]
# A caller-declared digest. Apply checks it against the bytes only for an
# `upload:` source, whose file is already on the server; for any other source
# it is a change-detection input and the source is never fetched to verify it.
#
# The exact length of 71 is a security bound. Python's `re`, used by the CLI's
# JSON Schema mirror of this pattern, lets `$` match before a trailing newline;
# pydantic-core anchors at the true end. Without the bound here and in the
# OpenAPI schema, a trailing-newline checksum could pass one validator and not
# the other. test_manifest_apply_api.py pins both.
#
# On a raster_cog source a changed checksum makes
# _validate_existing_dataset_update reject the update rather than skip it.
ManifestChecksum = Annotated[
    str,
    Field(
        min_length=71,
        max_length=71,
        pattern=r"^sha256:[0-9a-f]{64}$",
        description=(
            "Declared SHA-256 digest of the source bytes, as "
            "'sha256:<64 lowercase hex characters>'. Required on an "
            "`upload:` source, where apply checks it against the uploaded "
            "file and refuses the entry when they differ. On any other source "
            "apply uses it only as a change-detection input alongside the rest "
            "of the entry; it is not verified against the fetched bytes. For a "
            "vector source, "
            "bump it when the file under a stable URI changes, to force "
            "apply to reclassify the entry as an update instead of "
            "skipping it. Manifest raster updates are not supported: once a "
            "raster_cog entry has published, a changed checksum, a new "
            "upload's included, makes apply report that entry as an error "
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

# Mirrors the upload door's tier-1 vector formats. `.zip` covers both a
# Shapefile and a zipped File Geodatabase; `source_format.py` tells them apart
# by content.
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
            ".parquet",
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
            "csv, xlsx, xls, fgb, kml, kmz, or parquet; raster_cog sources require tif "
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
        """Reject a `..` segment anywhere in the URI path, remote schemes included."""
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
        """Keep the declared source modality aligned with its file path.

        An ``upload:`` URI has no path; apply checks the upload's own file
        name instead.
        """
        source_type = info.data.get("type")
        allowed = MANIFEST_SOURCE_EXTENSIONS.get(str(source_type))
        if allowed is None or uri.startswith(UPLOAD_URI_PREFIX):
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

    @model_validator(mode="after")
    def _upload_requires_checksum(self) -> "ManifestSource":
        if self.uri.startswith(UPLOAD_URI_PREFIX) and self.checksum is None:
            raise ValueError("An upload: source requires checksum")
        return self


class ManifestMetadata(_ManifestBaseModel):
    tags: list[NonEmptyString100] | None = None
    organization: NonEmptyString500 | None = None
    crs: ManifestCrs | None = None
    license: NonEmptyString500 | None = None
    attribution: NonEmptyString5000 | None = None
    bbox: ManifestBbox | None = None

    # The manifest also writes records.attribution, so it carries the dataset
    # PATCH's guard: markup fails apply with a 422 instead of being silently
    # dropped at commit.
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
    # Not a Literal: record_status is an open set an overlay may extend, so an
    # enum would 422 statuses the API accepts. `validate_publication_intent` in
    # manifest_sources.py checks it live. 20 chars matches the record_status
    # column.
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


class ManifestCollectionRef(_ManifestBaseModel):
    """A collection by id, or by name, which apply creates when the caller may."""

    id: uuid.UUID | None = None
    name: Annotated[str, Field(min_length=1, max_length=255)] | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "ManifestCollectionRef":
        if (self.id is None) == (self.name is None):
            raise ValueError("collection takes exactly one of id and name")
        return self


# The limits of the attribute-metadata update, which a test holds them to.
MAX_MANIFEST_ATTRIBUTES = 500


class ManifestAttribute(_ManifestBaseModel):
    """Per-column text for the column named ``source_name`` in the uploaded file."""

    source_name: Annotated[str, Field(min_length=1)]
    title: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=2000)
    units: str | None = Field(default=None, max_length=50)

    @field_validator("source_name", "title", "description", "units")
    @classmethod
    def _storable(cls, value: str | None) -> str | None:
        if value is not None and not is_storable_text(value):
            raise ValueError("must be valid UTF-8 text without NUL")
        return value


class ManifestDataset(_ManifestBaseModel):
    key: ManifestDatasetKey
    title: NonEmptyString500
    description: NonEmptyString5000 | None = None
    # Exactly one source per ingest job — extra entries would join the
    # idempotency fingerprint while silently being ignored.
    sources: list[ManifestSource] = Field(min_length=1, max_length=1)
    metadata: ManifestMetadata | None = None
    publication: ManifestPublication
    # Version 2 only, and after the version 1 fields so generated SDK
    # constructors keep their positional order.
    visibility: Literal["private", "internal", "public"] | None = Field(
        default=None,
        description=(
            "Who can see the dataset. Version 2 only. Omitted on create the "
            "dataset is private; omitted on update the current level is kept."
        ),
    )
    collection: ManifestCollectionRef | None = Field(
        default=None,
        description=(
            "Collection to add the dataset to. Version 2 only. Adding needs "
            "the manage_collections permission and ownership of the "
            "collection; otherwise the entry carries warning A033."
        ),
    )
    attributes: list[ManifestAttribute] | None = Field(
        default=None,
        max_length=MAX_MANIFEST_ATTRIBUTES,
        description=(
            "Per-column title, description and units, by column name in the "
            "uploaded file. Version 2 only. A null field keeps the stored "
            "text; a name matching no column is warning A092."
        ),
    )


class ManifestClient(_ManifestBaseModel):
    """The publishing client that built the manifest."""

    id: NonEmptyString100
    version: NonEmptyString100
    app: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    project: NonEmptyString500 | None = None


class ManifestApplyRequest(_ManifestBaseModel):
    manifest_version: Literal["1", "2"] = Field(
        description=(
            "Manifest format. Version 2 adds `client`, which it requires, and "
            "`upload:<job_id>` sources. Version 2 is a preview and may change "
            "in any release until the desktop connectors ship; version 1 is "
            "stable."
        )
    )
    catalog: ManifestCatalog
    # Keep one request from causing an unbounded number of remote downloads,
    # quota queries, transactions, and queued jobs. Callers can submit another
    # batch after this one completes.
    datasets: list[ManifestDataset] = Field(min_length=1, max_length=100)
    dry_run: bool = False
    # Last, so generated SDK constructors keep their positional order.
    client: ManifestClient | None = Field(
        default=None,
        description="The publishing client. Required in version 2, refused in 1.",
    )
    public_fallback: Literal["internal"] | None = Field(
        default=None,
        description=(
            "Version 2 only. When public visibility is refused for an entry, "
            "write it as internal with warning A020 instead of failing it."
        ),
    )

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

    @field_validator("datasets")
    @classmethod
    def upload_sources_must_be_unique(
        cls, datasets: list[ManifestDataset]
    ) -> list[ManifestDataset]:
        """An upload becomes at most one entry's import, so it may appear once."""
        seen: set[str] = set()
        repeated: list[str] = []
        for dataset in datasets:
            for source in dataset.sources:
                uri = source.uri
                if not uri.startswith(UPLOAD_URI_PREFIX):
                    continue
                if uri in seen and uri not in repeated:
                    repeated.append(uri)
                seen.add(uri)
        if repeated:
            raise ValueError(f"duplicate upload source(s): {', '.join(repeated)}")
        return datasets

    @model_validator(mode="after")
    def _fields_match_version(self) -> "ManifestApplyRequest":
        if self.manifest_version == "2":
            if self.client is None:
                raise ValueError("manifest_version '2' requires client")
            return self
        # Supplied at all, null included: version 1 had no such field.
        if "client" in self.model_fields_set:
            raise ValueError("client requires manifest_version '2'")
        if "public_fallback" in self.model_fields_set or any(
            {"visibility", "collection", "attributes"} & dataset.model_fields_set
            for dataset in self.datasets
        ):
            raise ValueError(
                "visibility, collection, attributes and public_fallback "
                "require manifest_version '2'"
            )
        if any(
            source.uri.startswith(UPLOAD_URI_PREFIX)
            for dataset in self.datasets
            for source in dataset.sources
        ):
            raise ValueError("upload: sources require manifest_version '2'")
        return self


class ManifestMessage(BaseModel):
    code: str = Field(description="Stable code, for example `A020`.")
    severity: Literal["error", "warning", "info"]
    message: str
    fix: str | None = None


class ManifestApplyEntryResult(BaseModel):
    dataset_key: str
    action: Literal["create", "update", "skip", "blocked", "error"] = Field(
        description=(
            "What apply did with the entry. `blocked` means the entry is "
            "unchanged since its last apply, whose replacement is held for "
            "review, so nothing was queued. Accept it by sending `run_id` as "
            "`accept_blocked_run_id` to the dataset's refresh endpoint, or "
            "change the entry."
        )
    )
    job_id: uuid.UUID | None = None
    dataset_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = Field(
        default=None,
        description="The blocked refresh run to accept, when action is `blocked`.",
    )
    review_reasons: list[str] = Field(
        default_factory=list,
        description="Why the blocked run needs review, when action is `blocked`.",
    )
    message: str
    errors: list[str] = Field(default_factory=list)
    messages: list[ManifestMessage] | None = Field(
        default=None,
        description="Coded messages for the entry. Left out in manifest version 1.",
    )

    @model_serializer(mode="wrap")
    def _leave_out_absent_messages(self, handler: SerializerFunctionWrapHandler):
        # A version 1 response stays as it was.
        data = handler(self)
        if self.messages is None:
            data.pop("messages", None)
        return data


class ManifestApplyResponse(BaseModel):
    accepted: bool
    dry_run: bool
    results: list[ManifestApplyEntryResult]
