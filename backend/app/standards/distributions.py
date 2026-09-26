"""The access surfaces a catalog feed publishes for a dataset.

Mapping ``record.distributions`` straight onto ``dcat:Distribution`` nodes
fails for raster/VRT rows whose ``url`` is an object-storage key, which is
unresolvable and leaks internal storage layout, and gives STAC-imported
rasters, which have no distribution row, no access method at all.

This module decides what a feed may publish: ``is_publishable_url``
rejects internal pointers (only http(s) or root-relative API paths
pass); ``published_distributions`` adds, for the raster family, the
tile template the product serves anonymously (plus the COG download for a
public, published raster), derived per request since it lives at the APP
origin, nginx-rewritten to the tile proxy, and carries the tile cache-key
params, values a stored row can't hold. A 3D Tiles dataset gets its
tileset.json the same way, and a point cloud its COPC file, with no stored
row. Mirrors ``build_assets`` in ``modules/catalog/search/service_records.py``,
which is what STAC advertises for the same datasets.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from app.core.pointcloud import POINTCLOUD_MEDIA_TYPE, pointcloud_path
from app.core.record_types import is_raster_family
from app.core.tile_scope import republished_tile_url, tile_template_query
from app.core.tiles3d import TILESET_MEDIA_TYPE, tileset_path

if TYPE_CHECKING:
    from app.modules.catalog.datasets.domain.models import Dataset

# The tile template's distribution type. Not in ``chk_distribution_type``
# because these entries are synthesized per request and never persisted --
# see the module docstring for why they cannot be. It is listed in each
# profile's ``SERVICE_DISTRIBUTION_TYPES`` beside ``vector_tiles``, so the
# two tile surfaces serialize alike.
RASTER_TILES_DISTRIBUTION_TYPE = "raster_tiles"

# The tileset's distribution type, synthesized per request like the raster one.
TILESET_DISTRIBUTION_TYPE = "tiles3d"

_RASTER_TILES_MEDIA_TYPE = "image/png"

_COG_MEDIA_TYPE = "image/tiff; application=geotiff; profile=cloud-optimized"

_PUBLISHABLE_SCHEMES = frozenset({"http", "https"})


@dataclass(frozen=True)
class PublishedDistribution:
    """One access surface, with its URL already resolved to absolute form.

    Field-compatible with the ``RecordDistribution`` attributes the profile
    serializers read, so each of them maps over this type instead of the ORM
    rows and no longer resolves URLs itself.
    """

    distribution_type: str
    format: str | None
    url: str
    title: str | None
    description: str | None
    media_type: str | None


def is_publishable_url(url: str) -> bool:
    """Whether a stored distribution URL may be handed to a consumer.

    Root-relative paths (what ``generate_distributions`` writes) and absolute
    http(s) URLs (all ``DistributionCreate`` accepts) qualify. A bare
    object-storage key does not.
    """
    if url.startswith("/"):
        return True
    return urlsplit(url).scheme in _PUBLISHABLE_SCHEMES


def _absolute(url: str, base_url: str) -> str:
    return base_url + url if url.startswith("/") else url


def raster_tiles_path(dataset: Dataset) -> str:
    """The XYZ template for a raster dataset, versioned like every renderer.

    fix(#1372) and fix(#2007) version the template on the content and the
    publication counters, so a replace or a publication transition rolls the
    shared tile cache. Kept identical to ``build_assets``: a client that reads
    both the STAC asset and the DCAT distribution must get the same URL.
    """
    path = f"/raster-tiles/{dataset.id}/tiles/{{z}}/{{x}}/{{y}}.png"
    return path + tile_template_query(
        getattr(dataset, "tile_cache_version", None),
        getattr(dataset, "publication_version", None),
    )


def cog_download_path(dataset_id: object) -> str:
    """A raster dataset's COG download route, relative to the API root."""
    return f"/datasets/{dataset_id}/download/cog"


def _raster_tiles_distribution(
    dataset: Dataset, *, app_base_url: str
) -> PublishedDistribution:
    """The raster access surface every raster-family dataset can advertise."""
    return PublishedDistribution(
        distribution_type=RASTER_TILES_DISTRIBUTION_TYPE,
        format="png",
        url=app_base_url + raster_tiles_path(dataset),
        title="Raster Tiles",
        description=None,
        media_type=_RASTER_TILES_MEDIA_TYPE,
    )


def _cog_download_distribution(
    dataset: Dataset, *, api_base_url: str
) -> PublishedDistribution:
    """The COG download, advertised only where an anonymous harvester can use it.

    A feed has one URL per distribution and no per-caller variant, so the
    link is published for public, published rasters only: the route serves
    those without credentials and 404s or 403s the rest. VRTs have no single
    COG to download, and a STAC import's COG is not served by GeoLens.
    """
    return PublishedDistribution(
        distribution_type="download",
        format="cog",
        url=api_base_url + cog_download_path(dataset.id),
        title="Cloud-Optimized GeoTIFF",
        description=None,
        media_type=_COG_MEDIA_TYPE,
    )


def is_cog_download_eligible(dataset: Dataset) -> bool:
    """Whether *dataset* could ever advertise a COG download link.

    Independent of whether its RasterAsset row exists, so a caller resolving
    that row in bulk can skip datasets this predicate already refuses --
    a feed page can hold many more of those than of eligible rasters.
    """
    record = dataset.record
    return (
        record.record_type == "raster_dataset"
        and record.visibility == "public"
        and record.record_status == "published"
        # A STAC import's COG stays at its origin, which the route redirects
        # to and which may require credentials.
        and dataset.source_format != "stac"
    )


def _anonymous_cog_download(dataset: Dataset, *, has_raster_asset: bool) -> bool:
    """Whether an anonymous COG download link may be advertised for *dataset*.

    ``has_raster_asset`` is the caller's per-page bulk answer to whether the
    download route's RasterAsset row exists -- the route 404s without one, so
    an incomplete or pre-backfill upload must not advertise the link either.
    """
    return has_raster_asset and is_cog_download_eligible(dataset)


def _tileset_distribution(
    dataset: Dataset, *, api_base_url: str
) -> PublishedDistribution:
    """A 3D Tiles dataset's one access surface: its tileset.json."""
    return PublishedDistribution(
        distribution_type=TILESET_DISTRIBUTION_TYPE,
        format="3dtiles",
        url=api_base_url + tileset_path(dataset.id),
        title="3D Tiles",
        description=None,
        media_type=TILESET_MEDIA_TYPE,
    )


def _pointcloud_distribution(
    dataset: Dataset, *, api_base_url: str
) -> PublishedDistribution:
    """A point cloud's live COPC file, which any caller who can view it may read."""
    return PublishedDistribution(
        distribution_type="download",
        format="copc",
        url=api_base_url + pointcloud_path(dataset.id, dataset.pointcloud_attempt_id),
        title="COPC point cloud",
        description=None,
        media_type=POINTCLOUD_MEDIA_TYPE,
    )


def published_distributions(
    dataset: Dataset,
    *,
    api_base_url: str,
    app_base_url: str,
    has_raster_asset: bool = False,
) -> list[PublishedDistribution]:
    """Every distribution a catalog feed should publish for *dataset*.

    Stored rows that resolve for a consumer, plus the derived raster,
    tileset or point cloud access surface. Requires
    ``dataset.record.distributions`` to be loaded. ``has_raster_asset`` gates
    the COG download entry and defaults closed; the caller resolves it once
    per page (see the dcat/dcat_us/geodcat_ap catalog serializers).
    """
    record = dataset.record
    entries: list[PublishedDistribution] = []

    if is_raster_family(record.record_type):
        entries.append(_raster_tiles_distribution(dataset, app_base_url=app_base_url))
        if _anonymous_cog_download(dataset, has_raster_asset=has_raster_asset):
            entries.append(
                _cog_download_distribution(dataset, api_base_url=api_base_url)
            )
    elif record.record_type == "tiles3d_dataset":
        entries.append(_tileset_distribution(dataset, api_base_url=api_base_url))
    elif record.record_type == "pointcloud_dataset" and dataset.pointcloud_attempt_id:
        entries.append(_pointcloud_distribution(dataset, api_base_url=api_base_url))

    for row in record.distributions or ():
        if not is_publishable_url(row.url):
            continue
        entries.append(
            PublishedDistribution(
                distribution_type=row.distribution_type,
                format=row.format,
                # fix(#2007): a stored vector-tile template predates every
                # transition since ingest, so republish it at the row's counter.
                url=_absolute(
                    republished_tile_url(
                        row.url, getattr(dataset, "publication_version", None)
                    ),
                    api_base_url,
                ),
                title=row.title,
                description=row.description,
                media_type=row.media_type,
            )
        )

    return entries
