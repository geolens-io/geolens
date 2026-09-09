"""fix(#2007): a cached tile response is keyed on the publication version.

#2005 retired outstanding signatures on a publication-status or visibility
transition, which stops the application from serving a tile to the holder of an
old template. It does not reach the caches in front of the application: an
entry stored while the dataset was public and published stayed readable for its
TTL afterwards, because the key carried the caller's own ``v`` and signature
rather than the counter.

The counter now keys both layers. The application's own vector and cluster tile
keys are derived from the row, so an entry stored at version N is unreachable
the moment the row moves to N+1. nginx keys ``$arg_pv``, and every raster
template the product emits carries it, so a URL emitted after the transition
addresses a different entry from one emitted before it.
"""

import gzip
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.core.tile_scope import (
    TILE_PUBLICATION_VERSION_PARAM,
    republished_tile_url,
)
from app.modules.catalog.maps.style_json import build_maplibre_style
from app.modules.catalog.datasets.domain.models import RecordDistribution
from app.standards.distributions import published_distributions

from tests.test_maps_style_json import _layer, _map
from tests.test_nginx_raster_stretch_cache_key_1778 import (
    _PROXY_CACHE_KEY,
    RASTER_TILES_LOCATION,
    _conf,
    _derive,
    _location_block,
    _nginx_arg,
)
from tests.test_tile_signature_revocation_1963 import (
    _admin_id,
    _drop_table,
    _evict_tile_meta,
    _make_raster,
    _make_vector,
    _mint,
    _patch_dataset,
    _set_status,
)

_SENTINEL = b"bytes stored while the dataset was public and published"


def _nginx_cache_key(query: str) -> str:
    """The raster_cache entry a request with ``query`` would address.

    Renders frontend/nginx.conf's own ``proxy_cache_key`` rather than a copy of
    it, so the pin fails if the directive stops holding the param.
    """
    conf = _conf()
    match = _PROXY_CACHE_KEY.search(_location_block(conf, RASTER_TILES_LOCATION))
    assert match, "expected a proxy_cache_key in the /raster-tiles/ location"
    fixed = {
        "dataset_id": "00000000-0000-0000-0000-0000000000ff",
        "z": "1",
        "x": "2",
        "y": "3",
        "fmt": "png",
        "geolens_raster_pmin": _derive(conf, "pmin", query),
        "geolens_raster_pmax": _derive(conf, "pmax", query),
        "geolens_raster_sigma": _derive(conf, "sigma", query),
    }

    def _resolve(m: re.Match) -> str:
        name = m.group(1)
        if name.startswith("arg_"):
            return _nginx_arg(query, name[len("arg_") :])
        return fixed[name]

    return re.sub(r"\$(\w+)", _resolve, match.group(1))


async def _serve_with_cache(
    client: AsyncClient, url: str, params: dict, stored: dict[str, bytes]
) -> tuple[object, str]:
    """Answer the route's one cache read from ``stored``; report the key it used."""
    read_keys: list[str] = []

    async def _get(key, z, x, y, cols_key="", label=None):
        read_keys.append(key)
        return stored.get(key)

    cache = AsyncMock()
    cache.get.side_effect = _get
    with patch("app.processing.tiles.router.get_tile_cache", return_value=cache):
        response = await client.get(url, params=params)
    assert len(read_keys) == 1, read_keys
    return response, read_keys[0]


async def _publication_version(session, dataset_id) -> int:
    row = await session.execute(
        text("SELECT publication_version FROM catalog.datasets WHERE id = :id"),
        {"id": dataset_id},
    )
    return row.scalar_one()


async def _tile_cache_version(session, dataset_id) -> int:
    row = await session.execute(
        text("SELECT tile_cache_version FROM catalog.datasets WHERE id = :id"),
        {"id": dataset_id},
    )
    return row.scalar_one()


class TestTheEdgeKeyHoldsThePublicationVersion:
    def test_the_raster_cache_key_holds_the_param_the_api_emits(self):
        conf = _conf()
        match = _PROXY_CACHE_KEY.search(_location_block(conf, RASTER_TILES_LOCATION))
        assert match
        assert f"$arg_{TILE_PUBLICATION_VERSION_PARAM}" in match.group(1), (
            "the edge and the api must agree on one param name, or the key "
            f"never moves: {match.group(1)!r}"
        )

    def test_two_publication_versions_address_different_entries(self):
        assert _nginx_cache_key("v=4&pv=0") != _nginx_cache_key("v=4&pv=1")

    def test_the_param_is_read_the_way_nginx_reads_it(self):
        """nginx takes the FIRST occurrence and matches the name case-insensitively.

        ``$arg_v`` must not resolve out of ``pv=``: nginx requires the byte
        before a match to start the query string or be ``&``.
        """
        assert _nginx_arg("pv=7", "v") == ""
        assert _nginx_arg("PV=7&pv=8", "pv") == "7"


@pytest.mark.usefixtures("_init_tile_pool_for_tests")
class TestTheApplicationKeyRollsWithThePublicationVersion:
    async def test_a_vector_tile_cached_before_an_unpublish_is_not_served_after(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        dataset = await _make_vector(
            test_db_session, created_by=await _admin_id(test_db_session)
        )
        url = f"/tiles/data.{dataset.table_name}/0/0/0.pbf"
        try:
            params = await _mint(client, dataset.id, admin_auth_header)
            _, published_key = await _serve_with_cache(client, url, params, {})
            stored = {published_key: gzip.compress(_SENTINEL)}

            hit, _ = await _serve_with_cache(client, url, params, stored)
            assert hit.content == _SENTINEL

            await _set_status(client, dataset.id, admin_auth_header, "internal")
            _evict_tile_meta()
            fresh = await _mint(client, dataset.id, admin_auth_header)
            after, unpublished_key = await _serve_with_cache(client, url, fresh, stored)

            assert unpublished_key != published_key
            assert after.content != _SENTINEL
        finally:
            await _drop_table(test_db_session, dataset.table_name)

    async def test_a_cluster_tile_cached_before_a_move_to_private_is_not_served_after(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        dataset = await _make_vector(
            test_db_session, created_by=await _admin_id(test_db_session)
        )
        url = f"/tiles/clusters/data.{dataset.table_name}/0/0/0.pbf"
        try:
            params = await _mint(client, dataset.id, admin_auth_header)
            _, public_key = await _serve_with_cache(client, url, params, {})
            stored = {public_key: gzip.compress(_SENTINEL)}

            hit, _ = await _serve_with_cache(client, url, params, stored)
            assert hit.content == _SENTINEL

            await _patch_dataset(
                client, dataset.id, admin_auth_header, {"visibility": "private"}
            )
            _evict_tile_meta()
            fresh = await _mint(client, dataset.id, admin_auth_header)
            after, private_key = await _serve_with_cache(client, url, fresh, stored)

            assert private_key != public_key
            assert after.content != _SENTINEL
        finally:
            await _drop_table(test_db_session, dataset.table_name)

    async def test_the_metadata_snapshot_bounds_the_roll(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Without an eviction the pre-transition snapshot still keys the read.

        The counter comes off the same 60 s snapshot that decides visibility
        and record_status, so the key is never staler than the authorization
        that admitted the request and both age out together. Pinned rather
        than hidden: the cases around this one evict first so they assert the
        key rather than this bound.
        """
        dataset = await _make_vector(
            test_db_session, created_by=await _admin_id(test_db_session)
        )
        url = f"/tiles/data.{dataset.table_name}/0/0/0.pbf"
        try:
            params = await _mint(client, dataset.id, admin_auth_header)
            _, published_key = await _serve_with_cache(client, url, params, {})
            stored = {published_key: gzip.compress(_SENTINEL)}

            await _set_status(client, dataset.id, admin_auth_header, "internal")
            after, key = await _serve_with_cache(client, url, params, stored)

            assert key == published_key
            assert after.content == _SENTINEL
        finally:
            await _drop_table(test_db_session, dataset.table_name)

    async def test_the_key_carries_the_row_not_the_request(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """A supplied ``pv`` cannot address another row state's entry.

        The vector key is derived from the row, which is what makes the old
        entry unreachable rather than merely unaddressed by emitted URLs.
        """
        dataset = await _make_vector(
            test_db_session, created_by=await _admin_id(test_db_session)
        )
        url = f"/tiles/data.{dataset.table_name}/0/0/0.pbf"
        try:
            params = await _mint(client, dataset.id, admin_auth_header)
            _, honest_key = await _serve_with_cache(client, url, params, {})
            _, claimed_key = await _serve_with_cache(
                client, url, {**params, TILE_PUBLICATION_VERSION_PARAM: "9"}, {}
            )
            assert claimed_key == honest_key
            assert honest_key.endswith(":p0")
        finally:
            await _drop_table(test_db_session, dataset.table_name)


@pytest.mark.usefixtures("_init_tile_pool_for_tests")
class TestTheSharedCacheIsRefusedToAMismatchedRequest:
    """A response may only be stored under the state that produced it.

    Without this the counter would be a way IN rather than out: a caller
    supplying the version an unpublish is about to make current would fill that
    key with bytes from before the transition.
    """

    async def _cache_status(self, client, dataset_id, params) -> str:
        resp = await client.get(
            "/tiles/raster-auth-check/",
            params=[("dataset_id", str(dataset_id)), *params],
        )
        assert resp.status_code == 200, resp.text
        return resp.headers["X-GeoLens-Cache-Status"]

    async def test_the_current_publication_version_is_publicly_cacheable(
        self, client: AsyncClient, test_db_session
    ):
        dataset = await _make_raster(
            test_db_session, created_by=await _admin_id(test_db_session)
        )
        version = await _tile_cache_version(test_db_session, dataset.id)
        current = await _publication_version(test_db_session, dataset.id)

        status_header = await self._cache_status(
            client,
            dataset.id,
            [("v", str(version)), (TILE_PUBLICATION_VERSION_PARAM, str(current))],
        )

        assert status_header == "public"

    async def test_a_publication_version_naming_another_state_is_not(
        self, client: AsyncClient, test_db_session
    ):
        dataset = await _make_raster(
            test_db_session, created_by=await _admin_id(test_db_session)
        )
        current = await _publication_version(test_db_session, dataset.id)

        status_header = await self._cache_status(
            client,
            dataset.id,
            [(TILE_PUBLICATION_VERSION_PARAM, str(current + 1))],
        )

        assert status_header == "private"

    async def test_a_duplicated_publication_version_is_not(
        self, client: AsyncClient, test_db_session
    ):
        """The two layers would read different occurrences of a repeated name."""
        dataset = await _make_raster(
            test_db_session, created_by=await _admin_id(test_db_session)
        )
        current = await _publication_version(test_db_session, dataset.id)

        status_header = await self._cache_status(
            client,
            dataset.id,
            [
                (TILE_PUBLICATION_VERSION_PARAM, str(current)),
                (TILE_PUBLICATION_VERSION_PARAM, str(current + 1)),
            ],
        )

        assert status_header == "private"

    async def test_an_absent_publication_version_keeps_the_old_behaviour(
        self, client: AsyncClient, test_db_session
    ):
        """A copied connect URL keys on the empty segment, as it always has."""
        dataset = await _make_raster(
            test_db_session, created_by=await _admin_id(test_db_session)
        )

        assert await self._cache_status(client, dataset.id, []) == "public"


@pytest.mark.usefixtures("_init_tile_pool_for_tests")
class TestEmittedTemplatesCarryTheCurrentCounter:
    async def test_the_raster_token_url_rolls_after_an_unpublish(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        dataset = await _make_raster(
            test_db_session, created_by=await _admin_id(test_db_session)
        )
        before = await client.get(
            f"/tiles/token/{dataset.id}/", headers=admin_auth_header
        )
        assert before.status_code == 200, before.text
        assert f"&{TILE_PUBLICATION_VERSION_PARAM}=0" in before.json()["tile_url"]

        await _set_status(client, dataset.id, admin_auth_header, "internal")
        _evict_tile_meta()

        after = await client.get(
            f"/tiles/token/{dataset.id}/", headers=admin_auth_header
        )
        assert after.status_code == 200, after.text
        assert f"&{TILE_PUBLICATION_VERSION_PARAM}=1" in after.json()["tile_url"]


class TestTheStyleDocument:
    def test_it_keys_a_vector_layer_on_its_signed_counter(self):
        layer = _layer().model_copy(update={"publication_version": 5})
        style = build_maplibre_style(_map(), [layer])
        url = style["sources"][f"geolens-{layer.dataset_id}"]["tiles"][0]

        assert f"{TILE_PUBLICATION_VERSION_PARAM}=5" in url
        assert "%3Ap5" in url or ":p5" in url


class TestAStoredTemplateIsRepublishedAtTheCurrentCounter:
    """A ``record_distributions`` row is written once at ingest.

    It predates every transition since, so a feed that passed it through as
    stored would hand a consumer a URL addressing a pre-transition entry.
    """

    def test_the_auto_generated_vector_template_gains_the_counter(self):
        url = republished_tile_url("/tiles/data.roads/{z}/{x}/{y}.pbf", 4)
        assert url == "/tiles/data.roads/{z}/{x}/{y}.pbf?pv=4"

    def test_a_cluster_template_gains_it_too(self):
        url = republished_tile_url("/tiles/clusters/data.roads/{z}/{x}/{y}.pbf", 4)
        assert url.endswith("?pv=4")

    def test_a_stale_counter_on_the_row_is_replaced_not_repeated(self):
        url = republished_tile_url("/tiles/data.roads/{z}/{x}/{y}.pbf?pv=1", 4)
        assert url.count("pv=") == 1
        assert url.endswith("pv=4")

    def test_other_params_on_the_row_survive(self):
        url = republished_tile_url("/tiles/data.roads/{z}/{x}/{y}.pbf?cols=name", 4)
        assert "cols=name" in url
        assert url.endswith("pv=4")

    def test_a_link_to_another_service_is_untouched(self):
        """Only our own tile routes are rewritten; an operator's URL is theirs."""
        other = "https://tiles.example.org/roads/{z}/{x}/{y}.pbf"
        assert republished_tile_url(other, 4) == other
        assert republished_tile_url("/datasets/x/export?format=gpkg", 4) == (
            "/datasets/x/export?format=gpkg"
        )


def _stored_vector_tiles_row(table_name: str) -> SimpleNamespace:
    return SimpleNamespace(
        distribution_type="vector_tiles",
        format="pbf",
        url=f"/tiles/data.{table_name}/{{z}}/{{x}}/{{y}}.pbf",
        title="Vector Tiles",
        description=None,
        media_type="application/vnd.mapbox-vector-tile",
    )


class TestTheDcatFeedRepublishesAStoredTemplate:
    def test_the_published_distribution_carries_the_current_counter(self):
        record = SimpleNamespace(
            record_type="vector_dataset",
            distributions=[_stored_vector_tiles_row("roads")],
        )
        dataset = SimpleNamespace(
            id="00000000-0000-0000-0000-0000000000ff",
            record=record,
            tile_cache_version=1,
            publication_version=4,
        )

        entries = published_distributions(
            dataset,
            api_base_url="https://api.example.org",
            app_base_url="https://app.example.org",
        )

        assert [e.url for e in entries] == [
            "https://api.example.org/tiles/data.roads/{z}/{x}/{y}.pbf?pv=4"
        ]


@pytest.mark.usefixtures("_init_tile_pool_for_tests")
class TestTheRecordDocumentRepublishesAStoredTemplate:
    async def _distribution_urls(
        self, client: AsyncClient, dataset_id, admin_auth_header: dict
    ) -> list[str]:
        resp = await client.get(
            f"/collections/datasets/items/{dataset_id}", headers=admin_auth_header
        )
        assert resp.status_code == 200, resp.text
        return [d["url"] for d in resp.json()["properties"]["distributions"]]

    async def test_it_rolls_after_an_unpublish(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        dataset = await _make_vector(
            test_db_session, created_by=await _admin_id(test_db_session)
        )
        try:
            test_db_session.add(
                RecordDistribution(
                    record_id=dataset.record_id,
                    distribution_type="vector_tiles",
                    format="pbf",
                    url=f"/tiles/data.{dataset.table_name}/{{z}}/{{x}}/{{y}}.pbf",
                    title="Vector Tiles",
                    media_type="application/vnd.mapbox-vector-tile",
                    auto_generated=True,
                )
            )
            await test_db_session.commit()

            before = await self._distribution_urls(
                client, dataset.id, admin_auth_header
            )
            assert any(u.endswith(".pbf?pv=0") for u in before), before

            await _set_status(client, dataset.id, admin_auth_header, "internal")
            after = await self._distribution_urls(client, dataset.id, admin_auth_header)

            assert any(u.endswith(".pbf?pv=1") for u in after), after
            assert not any(u.endswith(".pbf?pv=0") for u in after), after
        finally:
            await _drop_table(test_db_session, dataset.table_name)


@pytest.mark.usefixtures("_init_tile_pool_for_tests")
class TestTheConnectEndpointRepublishesAStoredTemplate:
    """The Connect panel copies its vector template out of this endpoint.

    Versioning it is safe in a way the raster Connect template is not: a frozen
    counter there would pin an edge entry, while the vector key is derived from
    the row, so a stale one costs shared caching and never stale bytes.
    """

    async def _urls(
        self, client: AsyncClient, record_id, admin_auth_header: dict
    ) -> dict[str, str]:
        resp = await client.get(
            f"/records/{record_id}/distributions/", headers=admin_auth_header
        )
        assert resp.status_code == 200, resp.text
        return {d["distribution_type"]: d["url"] for d in resp.json()["distributions"]}

    async def test_it_rolls_after_an_unpublish(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        dataset = await _make_vector(
            test_db_session, created_by=await _admin_id(test_db_session)
        )
        download_url = f"/datasets/{dataset.id}/export?format=gpkg"
        try:
            for row in (
                RecordDistribution(
                    record_id=dataset.record_id,
                    distribution_type="vector_tiles",
                    format="pbf",
                    url=f"/tiles/data.{dataset.table_name}/{{z}}/{{x}}/{{y}}.pbf",
                    title="Vector Tiles",
                    media_type="application/vnd.mapbox-vector-tile",
                    auto_generated=True,
                ),
                RecordDistribution(
                    record_id=dataset.record_id,
                    distribution_type="download",
                    format="gpkg",
                    url=download_url,
                    title="Download as GPKG",
                    media_type="application/geopackage+sqlite3",
                    auto_generated=True,
                ),
            ):
                test_db_session.add(row)
            await test_db_session.commit()

            before = await self._urls(client, dataset.record_id, admin_auth_header)
            assert before["vector_tiles"].endswith(".pbf?pv=0"), before
            assert before["download"] == download_url

            await _set_status(client, dataset.id, admin_auth_header, "internal")
            after = await self._urls(client, dataset.record_id, admin_auth_header)

            assert after["vector_tiles"].endswith(".pbf?pv=1"), after
            assert "pv=0" not in after["vector_tiles"]
            assert after["download"] == download_url
        finally:
            await _drop_table(test_db_session, dataset.table_name)
