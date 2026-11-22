"""Backend-local Pydantic models for manifest apply requests."""

import unicodedata
import uuid
from pathlib import Path
from typing import Annotated, Any, Literal
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
from pydantic_core import PydanticCustomError

from app.core.text import normalize_nfc, reject_html_markup
from app.platform.value_labels import is_storable_text

NonEmptyString100 = Annotated[str, Field(min_length=1, max_length=100)]
NonEmptyString500 = Annotated[str, Field(min_length=1, max_length=500)]
NonEmptyString5000 = Annotated[str, Field(min_length=1, max_length=5000)]

_MANIFEST_KEY_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,127}$"
ManifestDatasetKey = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        pattern=_MANIFEST_KEY_PATTERN,
        description="Stable dataset identity key used for idempotent apply operations.",
    ),
]
ManifestMapKey = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        pattern=_MANIFEST_KEY_PATTERN,
        description=(
            "Stable map identity key, unique across the server. A key on a "
            "map the caller can't edit answers A050."
        ),
    ),
]
ManifestMapLayerKey = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        pattern=_MANIFEST_KEY_PATTERN,
        description="Stable layer identity key, unique within its map.",
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

    @field_validator("name", mode="before")
    @classmethod
    def _normalize_nfc(cls, v: str | None) -> str | None:
        return normalize_nfc(v)

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


def _storable_text(value: str | None) -> str | None:
    if value is not None and not is_storable_text(value):
        raise ValueError("must be valid UTF-8 text without NUL")
    return value


# The map schema's own limit, which a test holds this to.
MAX_MANIFEST_MAP_LAYERS = 200

ManifestZoom = Annotated[float, Field(ge=0, le=24)]


class ManifestMapView(_ManifestBaseModel):
    center: tuple[
        Annotated[float, Field(ge=-180, le=180)],
        Annotated[float, Field(ge=-90, le=90)],
    ] = Field(description="Longitude and latitude, WGS84.")
    zoom: ManifestZoom
    bearing: float = Field(default=0, ge=-180, le=180)
    pitch: float = Field(default=0, ge=0, le=85)


class ManifestLossItem(_ManifestBaseModel):
    path: Annotated[str, Field(min_length=1)]
    kind: Annotated[str, Field(min_length=1)]
    detail: str | None = None

    _storable = field_validator("path", "kind", "detail")(_storable_text)

    @field_validator("path", "kind", "detail")
    @classmethod
    def _one_line(cls, value: str | None) -> str | None:
        # Each item is one line of the map notes, whose managed block ends at
        # the first line that is exactly `---`.
        if value is not None and any(
            unicodedata.category(char) in {"Cc", "Zl", "Zp"} for char in value
        ):
            raise ValueError("must be one line without control characters")
        return value


class ManifestLossReport(_ManifestBaseModel):
    # No count bound, as in the contract; the request body limit bounds it.
    items: list[ManifestLossItem] = Field(default_factory=list)
    summary: dict[str, Annotated[int, Field(ge=0)]] = Field(default_factory=dict)


class ManifestMapLayer(_ManifestBaseModel):
    """One map layer. Column names in its styling are the uploaded file's."""

    key: ManifestMapLayerKey
    dataset_key: ManifestDatasetKey | None = Field(
        default=None,
        description=(
            "A dataset the caller published under this key. Exactly one of "
            "dataset_key and dataset_id."
        ),
    )
    dataset_id: uuid.UUID | None = Field(
        default=None,
        description="A dataset already in GeoLens that the caller can read.",
    )
    display_name: Annotated[str, Field(max_length=255)] | None = None
    visible: bool = True
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    min_zoom: ManifestZoom | None = None
    max_zoom: ManifestZoom | None = None
    style_config: dict[str, Any] | None = Field(
        default=None,
        description=(
            "The builder's style description. Unknown top-level keys are "
            "dropped with info A062. A symbol's icon and its categories' "
            "icons are icon names; any other value is refused with A099."
        ),
    )
    paint: dict[str, Any] | None = None
    layout: dict[str, Any] | None = None
    filter: list[Any] | None = None
    label_config: dict[str, Any] | None = Field(
        default=None,
        description="Text labels. Unknown keys are dropped with info A062.",
    )
    popup_config: dict[str, Any] | None = None
    show_in_legend: bool = True

    _storable = field_validator("display_name")(_storable_text)

    @model_validator(mode="after")
    def _one_dataset_reference(self) -> "ManifestMapLayer":
        if (self.dataset_key is None) == (self.dataset_id is None):
            raise ValueError(
                "a map layer takes exactly one of dataset_key and dataset_id"
            )
        return self


class ManifestMap(_ManifestBaseModel):
    key: ManifestMapKey
    name: Annotated[str, Field(min_length=1, max_length=255)]
    description: Annotated[str, Field(max_length=2000)] | None = None
    view: ManifestMapView | None = None
    basemap_style: Annotated[str, Field(min_length=1, max_length=2000)] | None = Field(
        default=None, description="A basemap id from GET /capabilities."
    )
    styling: Literal["replace_if_unedited", "replace", "keep"] = Field(
        default="replace_if_unedited",
        description=(
            "Whether a republish replaces the map's styling: its view, "
            "basemap and its keyed layers' paint, layout, style, labels, "
            "popup, filter, opacity, visible flag and name. `replace` always "
            "does. `keep` never does, and keeps keyed layers the manifest no "
            "longer lists. `replace_if_unedited` does unless styling it would "
            "write was edited in GeoLens since the last publish that replaced "
            "it, and answers info A070 when it keeps it. A view or basemap "
            "edit counts only when the manifest sends a `view` or "
            "`basemap_style` that would overwrite it. A kept layer keeps its "
            "dataset too, with warning A073 when the manifest names another. "
            "Name, description, notes, visibility and new layers are applied "
            "in every mode, and a new map takes the manifest's styling."
        ),
    )
    thumbnail: (
        Annotated[
            str,
            Field(
                min_length=22,
                max_length=100_000,
                pattern=r"^data:image/(?:png|jpeg);base64,[A-Za-z0-9+/]+={0,2}$",
            ),
        ]
        | None
    ) = Field(
        default=None,
        description=(
            "A PNG or JPEG data URI, stored as the map's thumbnail once the "
            "map is written, with the thumbnail upload's checks, when the "
            "manifest's styling is applied. A publish that keeps the styling "
            "leaves the map's thumbnail as it is. One the storage step "
            "refuses or can't store is warning A072, and the map stays "
            "published."
        ),
    )
    loss_report: ManifestLossReport | None = Field(
        default=None,
        description=(
            "Written, one line per item, in a block at the top of the map's "
            "notes, above a `---` line. A republish replaces the leading "
            "block only when it is exactly a block some publish of this map "
            "wrote; all other text is kept whole. Left out when the styling "
            "is kept, and cut to what fits the notes limit. When the notes "
            "leave no room for the block, none is written (info A071)."
        ),
    )
    visibility: Literal["private", "internal", "public"] | None = Field(
        default=None,
        description=(
            "Who can see the map. Omitted on create the map is private; "
            "omitted on update the current level is kept."
        ),
    )
    layers: list[ManifestMapLayer] = Field(
        min_length=1, max_length=MAX_MANIFEST_MAP_LAYERS
    )

    _storable = field_validator("name", "description")(_storable_text)

    @field_validator("thumbnail")
    @classmethod
    def _whole_base64(cls, thumbnail: str | None) -> str | None:
        if thumbnail is not None and len(thumbnail.split(",", 1)[1]) % 4:
            raise ValueError("thumbnail base64 must be padded to a multiple of 4")
        return thumbnail

    @field_validator("layers")
    @classmethod
    def _layer_keys_unique(
        cls, layers: list[ManifestMapLayer]
    ) -> list[ManifestMapLayer]:
        keys = [layer.key for layer in layers]
        repeated = sorted({key for key in keys if keys.count(key) > 1})
        if repeated:
            raise ValueError(f"duplicate layer key(s): {', '.join(repeated)}")
        return layers


_MISSING_DATASETS = object()


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
    datasets: list[ManifestDataset] = Field(
        default_factory=list,
        max_length=100,
        description=(
            "Required, with at least one entry, in version 1. In version 2 it "
            "may be empty, or left out, when `maps` is not."
        ),
    )
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
    maps: list[ManifestMap] | None = Field(
        default=None,
        max_length=100,
        description=(
            "Version 2 only, which is a preview. Maps built from datasets "
            "the caller can read, created or updated by key after the "
            "request's datasets. A dry run answers for the whole publish, so "
            "a layer may name a dataset the same request publishes. An apply "
            "writes a layer only once its dataset's job is complete: a layer, "
            "by dataset key or id, on a dataset the request creates, replaces "
            "or holds, or on one with a job still running, answers A052, and "
            "the map is sent again once the jobs finish."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _version_1_marks_missing_datasets(cls, data: Any) -> Any:
        # The schema lets version 2 leave `datasets` out. Version 1 still
        # requires it, so its absence is marked here and refused by the
        # field's own validator, with the error a required field raises.
        if (
            isinstance(data, dict)
            and data.get("manifest_version") != "2"
            and "datasets" not in data
        ):
            return {**data, "datasets": _MISSING_DATASETS}
        return data

    @field_validator("datasets", mode="before")
    @classmethod
    def _version_1_requires_datasets(cls, datasets: Any) -> Any:
        if datasets is _MISSING_DATASETS:
            raise PydanticCustomError("missing", "Field required")
        return datasets

    @field_validator("datasets")
    @classmethod
    def version_1_needs_a_dataset(
        cls, datasets: list[ManifestDataset], info: ValidationInfo
    ) -> list[ManifestDataset]:
        # The error the field's former min_length=1 raised, so version 1
        # answers an empty list exactly as before.
        if not datasets and info.data.get("manifest_version") != "2":
            raise PydanticCustomError(
                "too_short",
                "List should have at least {min_length} item after validation, "
                "not {actual_length}",
                {"field_type": "List", "min_length": 1, "actual_length": 0},
            )
        return datasets

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

    @field_validator("maps")
    @classmethod
    def map_keys_must_be_unique(
        cls, maps: list[ManifestMap] | None
    ) -> list[ManifestMap] | None:
        keys = [entry.key for entry in maps or ()]
        repeated = sorted({key for key in keys if keys.count(key) > 1})
        if repeated:
            raise ValueError(f"duplicate map key(s): {', '.join(repeated)}")
        return maps

    @model_validator(mode="after")
    def _fields_match_version(self) -> "ManifestApplyRequest":
        if self.manifest_version == "2":
            if self.client is None:
                raise ValueError("manifest_version '2' requires client")
            if not self.datasets and not self.maps:
                raise ValueError(
                    "manifest_version '2' requires at least one dataset or map"
                )
            return self
        # Supplied at all, null included: version 1 had no such field.
        if "client" in self.model_fields_set:
            raise ValueError("client requires manifest_version '2'")
        if "maps" in self.model_fields_set:
            raise ValueError("maps require manifest_version '2'")
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
    layer: str | None = Field(
        default=None,
        description="The map layer key the message is about. Left out otherwise.",
    )

    @model_serializer(mode="wrap")
    def _leave_out_absent_layer(self, handler: SerializerFunctionWrapHandler):
        data = handler(self)
        if self.layer is None:
            data.pop("layer", None)
        return data


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


class ManifestRemovedLayer(BaseModel):
    key: str = Field(description="The removed layer's key.")
    dataset_id: uuid.UUID = Field(description="Its dataset, which stays on the server.")


class ManifestMapResult(BaseModel):
    map_key: str
    action: Literal["create", "update", "skip", "error"] = Field(
        description=(
            "What apply did, or in a dry run would do, with the map. A map "
            "with an error message is `error`, and nothing was written for it."
        )
    )
    map_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "The map the key names, when the caller may edit it, or the map "
            "an apply created."
        ),
    )
    messages: list[ManifestMessage] = Field(default_factory=list)
    visibility: str | None = Field(
        default=None,
        description=(
            "Who can see the map after the apply, or in a dry run would. Null "
            "for a map in error."
        ),
    )
    styling: Literal["applied", "kept"] | None = Field(
        default=None,
        description=(
            "`applied` when the manifest's styling replaced the map's, `kept` "
            "when the map kept its own. Null for a map in error."
        ),
    )
    removed_layers: list[ManifestRemovedLayer] = Field(
        default_factory=list,
        description=(
            "Keyed layers the manifest no longer lists and the caller can read, "
            "removed from the map (info A059). Their datasets stay. One on a "
            "dataset the caller can't read stays on the map."
        ),
    )


class ManifestApplyResponse(BaseModel):
    accepted: bool
    dry_run: bool
    results: list[ManifestApplyEntryResult]
    maps: list[ManifestMapResult] | None = Field(
        default=None,
        description="One result per map, in request order. Left out in version 1.",
    )

    @model_serializer(mode="wrap")
    def _leave_out_absent_maps(self, handler: SerializerFunctionWrapHandler):
        # A version 1 response stays as it was.
        data = handler(self)
        if self.maps is None:
            data.pop("maps", None)
        return data
