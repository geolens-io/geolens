"""The access surfaces a catalog feed publishes for a dataset.

fix(#1469): the DCAT-family serializers used to map
``record.distributions`` straight onto ``dcat:Distribution`` nodes,
which breaks for raster/VRT rows whose ``url`` is an object-storage KEY
— unresolvable and leaking internal storage layout. STAC-imported
rasters had no distribution row at all, so they appeared with no access
method whatsoever.

This module decides what a feed may publish: ``is_publishable_url``
rejects internal pointers (only http(s) or root-relative API paths
pass); ``published_distributions`` adds, for the raster family, the
tile template the product serves anonymously (plus the COG download for a
public, published raster) — derived per request
since it lives at the APP origin, nginx-rewritten to the tile proxy, and
carries the tile cache-key params, values a stored row can't hold. A 3D
Tiles dataset gets its tileset.json the same way, with no stored row.
Mirrors ``build_assets`` in ``modules/catalog/search/service_records.py``
(what STAC advertises for the same datasets) — the discrepancy #1469
reported.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

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


def _anonymous_cog_download(dataset: Dataset) -> bool:
    record = dataset.record
    return (
        record.record_type == "raster_dataset"
        and record.visibility == "public"
        and record.record_status == "published"
        # A STAC import's COG stays at its origin, which the route redirects
        # to and which may require credentials.
        and dataset.source_format != "stac"
    )


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


def published_distributions(
    dataset: Dataset,
    *,
    api_base_url: str,
    app_base_url: str,
) -> list[PublishedDistribution]:
    """Every distribution a catalog feed should publish for *dataset*.

    Stored rows that resolve for a consumer, plus the derived raster or
    tileset access surface. Requires ``dataset.record.distributions`` to be
    loaded.
    """
    record = dataset.record
    entries: list[PublishedDistribution] = []

    if is_raster_family(record.record_type):
        entries.append(_raster_tiles_distribution(dataset, app_base_url=app_base_url))
        if _anonymous_cog_download(dataset):
            entries.append(
                _cog_download_distribution(dataset, api_base_url=api_base_url)
            )
    elif record.record_type == "tiles3d_dataset":
        entries.append(_tileset_distribution(dataset, api_base_url=api_base_url))

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
