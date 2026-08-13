"""The access surfaces a catalog feed publishes for a dataset.

fix(#1469): the DCAT-family serializers used to map ``record.distributions``
straight onto ``dcat:Distribution`` nodes. That works for vector datasets,
whose rows are written by ``generate_distributions`` and hold root-relative
API paths, but the raster and VRT ingest tails write a row whose ``url`` is
the object-storage KEY of the COG (``rasters/<id>/<hash>/source.cog.tif``).
A storage key is not an access URL: it has no scheme and no host, so no
consumer can resolve it, and publishing it exposes the internal storage
layout. STAC-imported rasters have no distribution row at all, so they
appeared in the feeds as datasets with no access method whatsoever.

This module is the one place that decides what a feed may publish:

- ``is_publishable_url`` rejects the internal pointers. Everything a user
  can author goes through ``DistributionCreate``, whose validator requires
  an http(s) URL, and everything ``generate_distributions`` writes is a
  root-relative API path — so the rule drops storage keys and nothing else.
- ``published_distributions`` adds, for the raster family, the access
  surfaces the product actually serves. Those are derived per request rather
  than stored, because both depend on values a row cannot hold: the tile
  template lives at the APP origin (``/raster-tiles/...`` is nginx-rewritten
  to the tile proxy; the API origin has no such route) and carries the
  dataset's current ``tile_cache_version``.

The raster entries deliberately mirror ``build_assets`` in
``modules/catalog/search/service_records.py``, which is what STAC advertises
for the same datasets. The two surfaces describing one dataset differently
is the discrepancy #1469 reported.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from app.core.record_types import is_raster_family

if TYPE_CHECKING:
    from app.modules.catalog.datasets.domain.models import Dataset

# The tile template's distribution type. Not in ``chk_distribution_type``
# because these entries are synthesized per request and never persisted --
# see the module docstring for why they cannot be. It is listed in each
# profile's ``SERVICE_DISTRIBUTION_TYPES`` beside ``vector_tiles``, so the
# two tile surfaces serialize alike.
RASTER_TILES_DISTRIBUTION_TYPE = "raster_tiles"

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

    fix(#1372) versions the template so a replace that bumps
    ``tile_cache_version`` rolls the shared tile cache. Kept identical to
    ``build_assets``: a client that reads both the STAC asset and the DCAT
    distribution must get the same URL.
    """
    path = f"/raster-tiles/{dataset.id}/tiles/{{z}}/{{x}}/{{y}}.png"
    version = getattr(dataset, "tile_cache_version", None)
    return f"{path}?v={version}" if version else path


def _raster_distributions(
    dataset: Dataset,
    *,
    api_base_url: str,
    app_base_url: str,
) -> list[PublishedDistribution]:
    """Access surfaces for a raster-family dataset, best first."""
    entries = [
        PublishedDistribution(
            distribution_type=RASTER_TILES_DISTRIBUTION_TYPE,
            format="png",
            url=app_base_url + raster_tiles_path(dataset),
            title="Raster Tiles",
            description=None,
            media_type=_RASTER_TILES_MEDIA_TYPE,
        )
    ]

    # ``download_cog`` (datasets/api/router_export.py) rejects anything that
    # is not a ``raster_dataset``, so a VRT gets the tile template alone --
    # a mosaic is composed from other datasets and has no single COG to hand
    # out. Advertised for STAC-origin rasters too: their asset lives on a
    # remote host and the endpoint redirects to it.
    if dataset.record.record_type == "raster_dataset":
        entries.append(
            PublishedDistribution(
                distribution_type="download",
                format="cog",
                url=f"{api_base_url}/datasets/{dataset.id}/download/cog",
                title="Cloud-Optimized GeoTIFF Download",
                description=None,
                media_type=_COG_MEDIA_TYPE,
            )
        )
    return entries


def published_distributions(
    dataset: Dataset,
    *,
    api_base_url: str,
    app_base_url: str,
) -> list[PublishedDistribution]:
    """Every distribution a catalog feed should publish for *dataset*.

    Stored rows that resolve for a consumer, plus the derived raster access
    surfaces. Requires ``dataset.record.distributions`` to be loaded.
    """
    record = dataset.record
    entries: list[PublishedDistribution] = []

    if is_raster_family(record.record_type):
        entries.extend(
            _raster_distributions(
                dataset, api_base_url=api_base_url, app_base_url=app_base_url
            )
        )

    for row in record.distributions or ():
        if not is_publishable_url(row.url):
            continue
        entries.append(
            PublishedDistribution(
                distribution_type=row.distribution_type,
                format=row.format,
                url=_absolute(row.url, api_base_url),
                title=row.title,
                description=row.description,
                media_type=row.media_type,
            )
        )

    return entries
