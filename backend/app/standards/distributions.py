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
tile template the product serves anonymously — derived per request
since it lives at the APP origin, nginx-rewritten to the tile proxy, and
carries the tile cache-key params, values a stored row can't hold. Mirrors
``build_assets`` in ``modules/catalog/search/service_records.py`` (what
STAC advertises for the same datasets) — the discrepancy #1469 reported.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from app.core.record_types import is_raster_family
from app.core.tile_scope import tile_template_query

if TYPE_CHECKING:
    from app.modules.catalog.datasets.domain.models import Dataset

# The tile template's distribution type. Not in ``chk_distribution_type``
# because these entries are synthesized per request and never persisted --
# see the module docstring for why they cannot be. It is listed in each
# profile's ``SERVICE_DISTRIBUTION_TYPES`` beside ``vector_tiles``, so the
# two tile surfaces serialize alike.
RASTER_TILES_DISTRIBUTION_TYPE = "raster_tiles"

_RASTER_TILES_MEDIA_TYPE = "image/png"

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


def _raster_tiles_distribution(
    dataset: Dataset, *, app_base_url: str
) -> PublishedDistribution:
    """The one raster access surface these feeds can honestly advertise.

    Deliberately NOT joined by a ``/datasets/{id}/download/cog`` entry
    (#1469): ``_resolve_download_user`` 401s a caller with neither
    credentials nor a download-scoped ``?token=``, and minting one needs
    a separate POST no generic DCAT client will make — publishing it as
    ``dcat:downloadURL`` would advertise a link that fails anonymous
    harvesters. The tile template has no such gate (see
    ``TestRasterAuthCheck::test_auth_check_returns_open_path_for_public_raster``).

    Keeps the surface exactly equal to ``build_assets``, which
    advertises ``raster_tiles`` and no COG download for the same
    datasets.
    """
    return PublishedDistribution(
        distribution_type=RASTER_TILES_DISTRIBUTION_TYPE,
        format="png",
        url=app_base_url + raster_tiles_path(dataset),
        title="Raster Tiles",
        description=None,
        media_type=_RASTER_TILES_MEDIA_TYPE,
    )


def published_distributions(
    dataset: Dataset,
    *,
    api_base_url: str,
    app_base_url: str,
) -> list[PublishedDistribution]:
    """Every distribution a catalog feed should publish for *dataset*.

    Stored rows that resolve for a consumer, plus the derived raster access
    surface. Requires ``dataset.record.distributions`` to be loaded.
    """
    record = dataset.record
    entries: list[PublishedDistribution] = []

    if is_raster_family(record.record_type):
        entries.append(_raster_tiles_distribution(dataset, app_base_url=app_base_url))

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
