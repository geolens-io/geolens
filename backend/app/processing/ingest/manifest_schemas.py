"""Backend-local Pydantic models for manifest apply requests."""

import unicodedata
import uuid
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

from pydantic import (
    AfterValidator,
    PrivateAttr,
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
from app.platform.map_bookmarks import MAX_MAP_BOOKMARKS, MapBookmark
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
            "of the entry; it is not verified against the fetched bytes. Bump "
            "it when the file under a stable URI changes, to force apply to "
            "reclassify the entry as an update instead of skipping it. An "
            "update of a raster_cog entry replaces the raster's data on the "
            "same dataset. A publish key can't replace a raster, because a "
            "replaced raster can't be restored: apply reports that entry as "
            "an error (A054 in version 2) and queues nothing."
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


MAX_MANIFEST_GROUPS = 100


def _distinct_groups(groups: list[uuid.UUID] | None) -> list[uuid.UUID] | None:
    # In one order, so the same groups give an entry the same fingerprint.
    return None if groups is None else sorted(set(groups), key=str)


ManifestGroups = Annotated[
    list[uuid.UUID] | None,
    Field(max_length=MAX_MANIFEST_GROUPS),
    AfterValidator(_distinct_groups),
]
_GROUPS_DESCRIPTION = (
    "Version 2 only. Share with exactly these groups, by id from "
    "`capabilities.me.groups`; omitted keeps the current groups, and an "
    "empty list removes them all. A dataset's new data is never published "
    "while a group outside the list still has it shared: if such a group "
    "can't be removed, the entry or its job fails and the dataset keeps its "
    "data and groups. A private item with groups is restricted: "
    "its owner, admins and the groups' members read it. A group that "
    "doesn't exist, or that the caller isn't a member of (an admin may use "
    "any), is left off with warning A058 and the publish goes ahead. A "
    "publish key can't add groups to an existing private or restricted item, "
    "which is warning A056 and keeps the item's groups; an item that "
    "would then keep a group the list leaves out is refused with error A056."
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
    groups: ManifestGroups = Field(default=None, description=_GROUPS_DESCRIPTION)


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
            "basemap, bookmarks and its keyed layers' paint, layout, style, labels, "
            "popup, filter, opacity, visible flag and name. `replace` always "
            "does. `keep` never does, and keeps keyed layers the manifest no "
            "longer lists. `replace_if_unedited` does unless styling it would "
            "write was edited in GeoLens since the last publish that replaced "
            "it, and answers info A070 when it keeps it. A view or basemap "
            "edit counts only when the manifest sends a `view` or "
            "`basemap_style` that would overwrite it, and a bookmarks edit "
            "only when it sends `bookmarks`. A kept layer the manifest points "
            "at another dataset moves to it and keeps its styling when that "
            "fits there: by the datasets' sharing rules, everyone who can "
            "read the new dataset can read the old one, the same geometry "
            "type (for a raster, the same DEM "
            "kind and one band under a colormap), and every column its "
            "styling and dashboard widgets read, in the type family it had "
            "and of the type each use needs. A move clears the map's "
            "thumbnail and social card image. "
            "Otherwise it takes the manifest's styling, with warning "
            "A073 naming what didn't fit. "
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
            "leaves the map's thumbnail as it is unless it moves a layer to "
            "another dataset, which clears it. One the storage step "
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
            "leave no room for the block, none is written, and an earlier "
            "publish's block is removed if the notes start with one; the "
            "rest of the notes is untouched (info A071)."
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
    bookmarks: list[MapBookmark] | None = Field(
        default=None,
        max_length=MAX_MAP_BOOKMARKS,
        description=(
            f"Named areas, in display order (max {MAX_MAP_BOOKMARKS}). Part of "
            "the map's styling: a republish that applies styling replaces the "
            "map's bookmarks with these, and an empty list removes them. Left "
            "out, the map's bookmarks are kept."
        ),
    )
    groups: ManifestGroups = Field(default=None, description=_GROUPS_DESCRIPTION)

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
            {"visibility", "collection", "attributes", "groups"}
            & dataset.model_fields_set
            for dataset in self.datasets
        ):
            raise ValueError(
                "visibility, collection, attributes, groups and public_fallback "
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


class ManifestDatasetLinks(BaseModel):
    """Absolute links to a dataset, each one a route the server serves."""

    page: str = Field(description="The dataset's page in the web app.")
    items: str | None = Field(
        default=None,
        description="The OGC API Features items. Null for a dataset with no items.",
    )
    tiles: str | None = Field(
        default=None,
        description=(
            "The vector tile URL template, with {z}, {x} and {y}. Null for a "
            "dataset with no vector tiles, and while a job is still writing "
            "the dataset (queued, running or held): read the template again "
            "once it completes. A private dataset's tiles need the caller's "
            "API key header."
        ),
    )


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
    visibility: str | None = Field(
        default=None,
        description=(
            "Who can see the dataset once the entry's job finishes: the level "
            "the entry writes, or the stored one when it writes none. Null "
            "when the entry failed or the dataset can't be read. Left out in "
            "manifest version 1."
        ),
    )
    links: ManifestDatasetLinks | None = Field(
        default=None,
        description=(
            "Links to the dataset. Null when there is no dataset yet or the "
            "caller can't read it. Left out in manifest version 1."
        ),
    )
    groups: list[str] | None = Field(
        default=None,
        description=(
            "Names of the groups the dataset is shared with once the entry's "
            "job finishes. Empty for a private dataset, whose earlier grants "
            "admit nobody until it is shared again. Null when the entry "
            "failed or the caller can't see the dataset's groups. Left out "
            "in manifest version 1."
        ),
    )

    # Set when the entry matched a job still queued or running, or a held
    # replacement, whose publication this entry answers for. Not part of the
    # response.
    _pending: bool = PrivateAttr(default=False)
    _pending_visibility: str | None = PrivateAttr(default=None)
    # What a version 2 entry decided, once it has: the visibility its job
    # writes (None keeps the dataset's), the groups it shares with, by name
    # and by id (None keeps the dataset's groups), and whether a role grant
    # keeps the dataset restricted without groups. Not part of the response.
    _decided: bool = PrivateAttr(default=False)
    _decided_visibility: str | None = PrivateAttr(default=None)
    _planned_groups: list[str] | None = PrivateAttr(default=None)
    _planned_group_ids: list[uuid.UUID] | None = PrivateAttr(default=None)
    _role_granted: bool = PrivateAttr(default=False)

    def mark_pending(self, visibility: str | None) -> None:
        """Record the visibility the matched job publishes."""
        self._pending = True
        self._pending_visibility = visibility

    @property
    def pending(self) -> bool:
        return self._pending

    @property
    def pending_visibility(self) -> str | None:
        return self._pending_visibility

    def decide(
        self,
        visibility: str | None,
        groups: list[str] | None,
        role_granted: bool,
        group_ids: list[uuid.UUID] | None = None,
    ) -> None:
        """Record what the entry decided its job publishes."""
        self._decided = True
        self._decided_visibility = visibility
        self._planned_groups = groups
        self._planned_group_ids = group_ids
        self._role_granted = role_granted

    @property
    def decided(self) -> bool:
        return self._decided

    @property
    def decided_visibility(self) -> str | None:
        return self._decided_visibility

    @property
    def planned_groups(self) -> list[str] | None:
        return self._planned_groups

    @property
    def planned_group_ids(self) -> list[uuid.UUID] | None:
        return self._planned_group_ids

    @property
    def role_granted(self) -> bool:
        return self._role_granted

    @model_serializer(mode="wrap")
    def _leave_out_absent_version_2_fields(
        self, handler: SerializerFunctionWrapHandler
    ):
        # A version 1 response stays as it was. A version 2 entry sets all of
        # them, null included, so a client can tell "none" from "not sent".
        data = handler(self)
        if self.messages is None:
            data.pop("messages", None)
        for name in ("visibility", "links", "groups"):
            if name not in self.model_fields_set:
                data.pop(name, None)
        return data


class ManifestRemovedLayer(BaseModel):
    key: str = Field(description="The removed layer's key.")
    dataset_id: uuid.UUID = Field(description="Its dataset, which stays on the server.")
    layer_id: uuid.UUID | None = Field(
        default=None,
        description="The removed layer's id, which no longer names a layer.",
    )
    link: str | None = Field(
        default=None,
        description="The dataset's page in the web app, to delete it there.",
    )


class ManifestMapLinks(BaseModel):
    """Absolute links to a map."""

    viewer: str = Field(description="The map in the web app.")
    share: str | None = Field(
        default=None,
        description=(
            "The public map's share link, sent once, by the publish that "
            "created it. Share links are stored hashed and can't be read back, "
            "so keep it: later publishes send null, as does a publish of a map "
            "that isn't public, a dry run and a map in error. When no web app "
            "address is configured (PUBLIC_APP_URL, or a hosted tenant's own "
            "origin), no link is created, this is null, and the map answers "
            "info A074."
        ),
    )
    embed: str | None = Field(
        default=None,
        description=(
            "An iframe snippet that embeds the share link, sent with `share` "
            "and null whenever it is."
        ),
    )


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
    groups: list[str] = Field(
        default_factory=list,
        description="Names of the groups the map is shared with.",
    )
    links: ManifestMapLinks | None = Field(
        default=None,
        description="Links to the map. Null while the map doesn't exist yet.",
    )
    removed_layers: list[ManifestRemovedLayer] = Field(
        default_factory=list,
        description=(
            "Keyed layers the manifest no longer lists and the caller can read, "
            "removed from the map (info A059). Their datasets stay. One on a "
            "dataset the caller can't read stays on the map."
        ),
    )
    # The links of a share link this apply minted, built as soon as the apply
    # returned, since the raw token can't be read back.
    _minted_links: ManifestMapLinks | None = PrivateAttr(default=None)


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
