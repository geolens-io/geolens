"""On-demand origin health probes for STAC and service datasets (#1222).

Six properties this suite exists to hold:

1. ``missing`` means the origin answered authoritatively that the resource
   is gone. Everything else that fails is ``inaccessible``. The 401/403 case
   is pinned on its own because collapsing it is the easy mistake: an
   upstream that newly requires auth answers just like one that deleted the
   file, and calling that ``missing`` sends an operator to re-import data
   that is still sitting there.
2. ``last_checked_at`` is written on FAILURE, not only on success. That is
   the whole meaning of the column ("last time GeoLens contacted the origin
   at all"), it is the case an operator most needs dated, and it is the one
   an implementation drifts away from first because the happy path is what
   gets clicked.
3. ``source_health_detail`` only ever holds a member of the closed
   ``DETAIL_CODES`` vocabulary. The field is served on every dataset read, so
   the guarantee has to be structural: the test enumerates the codes rather
   than spot-checking for the absence of a URL, because "no URL in this
   particular string" is not the same claim as "no provider text can ever
   land here".
4. Probing is owner-or-admin, in both directions. A non-owner who can READ
   the dataset must not be able to make GeoLens issue outbound requests on
   its origin, and the owner must still be able to. A refusal assertion alone
   cannot notice that the guard started rejecting valid callers.
5. Readers still get the stored state, from ``GET /datasets/{id}``. That is
   why point 4 costs them nothing, and it is worth pinning here so nobody
   "fixes" the authorization by adding a second read endpoint.
6. Origins with nothing to contact 409 rather than reporting a health state.
   "Nothing to probe" and "probe could not tell" must stay distinguishable;
   collapsing them is exactly what the NULL-means-unknown rule forbids.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from httpx import AsyncClient

from app.modules.catalog.sources.adapters.stac import _self_link_href
from app.modules.catalog.sources.origin_probe import (
    BLOCKED_BY_POLICY,
    DETAIL_CODES,
    HEALTHY,
    INACCESSIBLE,
    ITEM_WITHDRAWN,
    MISSING,
    NETWORK_ERROR,
    NOT_FOUND,
    SERVER_ERROR,
    TIMEOUT,
    UNAUTHORIZED,
    UNEXPECTED_STATUS,
    probe_remote_uri,
    remote_asset_exists,
)
from app.modules.catalog.sources.security import SSRFError
from app.platform.dataset_origin import build_origin_ref
from tests.factories import create_dataset as _create_dataset, get_user_id

pytestmark = pytest.mark.anyio

_ASSET = "https://origin.test/tiles/scene.tif"
_ITEM = "https://origin.test/collections/c/items/scene"


# ---------------------------------------------------------------------------
# Transport doubles
# ---------------------------------------------------------------------------


def _client_factory(handler, recorded: list[httpx.Request]):
    """A stand-in for ``make_safe_client`` backed by ``httpx.MockTransport``.

    The real client is exercised end to end apart from its transport, so the
    ranged-GET shape, the streaming context manager, and the status handling
    are the production ones. ``handler`` receives the request and either
    returns a response or raises, which is how the failure branches are
    driven without a real socket.
    """

    def factory(timeout: float = 10.0, **_kwargs) -> httpx.AsyncClient:
        async def _handle(request: httpx.Request) -> httpx.Response:
            recorded.append(request)
            return handler(request)

        return httpx.AsyncClient(
            transport=httpx.MockTransport(_handle), timeout=timeout
        )

    return factory


def _status_map(mapping: dict[str, int], default: int = 200):
    """Handler answering each URL with a fixed status and an empty body."""

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(mapping.get(str(request.url), default))

    return _handler


def _raising(exc_factory):
    def _handler(request: httpx.Request) -> httpx.Response:
        raise exc_factory(request)

    return _handler


@pytest.fixture
def probe_transport(monkeypatch):
    """Install a mock transport for the probe and hand back the request log.

    Yields an ``(install, recorded)`` pair: call ``install(handler)`` with a
    request handler, then read ``recorded`` to assert on what went out.
    """
    recorded: list[httpx.Request] = []

    def install(handler) -> None:
        monkeypatch.setattr(
            "app.modules.catalog.sources.origin_probe.make_safe_client",
            _client_factory(handler, recorded),
        )

    return install, recorded


# ---------------------------------------------------------------------------
# The probe primitive
# ---------------------------------------------------------------------------


class TestProbeStatusMapping:
    @pytest.mark.parametrize("code", [200, 206, 304])
    async def test_sub_400_is_healthy_with_no_detail(
        self, probe_transport, code: int
    ) -> None:
        install, _ = probe_transport
        install(_status_map({}, default=code))
        result = await probe_remote_uri(_ASSET)
        assert result.health == HEALTHY
        assert result.detail is None
        assert result.ok is True

    @pytest.mark.parametrize("code", [404, 410])
    async def test_gone_statuses_are_missing(self, probe_transport, code: int) -> None:
        install, _ = probe_transport
        install(_status_map({}, default=code))
        result = await probe_remote_uri(_ASSET)
        assert result.health == MISSING
        assert result.detail == NOT_FOUND
        assert result.ok is False

    @pytest.mark.parametrize("code", [401, 403])
    async def test_denied_statuses_are_inaccessible_not_missing(
        self, probe_transport, code: int
    ) -> None:
        """The distinction this whole vocabulary exists for.

        An upstream that added authentication has not deleted anything.
        Reporting ``missing`` here tells an operator to replace data that is
        still there, which is a worse error than saying "could not tell".
        """
        install, _ = probe_transport
        install(_status_map({}, default=code))
        result = await probe_remote_uri(_ASSET)
        assert result.health == INACCESSIBLE
        assert result.detail == UNAUTHORIZED

    @pytest.mark.parametrize(
        ("code", "expected_detail"),
        [
            (500, SERVER_ERROR),
            (503, SERVER_ERROR),
            (400, UNEXPECTED_STATUS),
            (418, UNEXPECTED_STATUS),
            (429, UNEXPECTED_STATUS),
        ],
    )
    async def test_other_error_statuses_are_inaccessible(
        self, probe_transport, code: int, expected_detail: str
    ) -> None:
        install, _ = probe_transport
        install(_status_map({}, default=code))
        result = await probe_remote_uri(_ASSET)
        assert result.health == INACCESSIBLE
        assert result.detail == expected_detail

    @pytest.mark.parametrize(
        ("exc_factory", "expected_detail"),
        [
            (lambda req: httpx.ReadTimeout("boom", request=req), TIMEOUT),
            (lambda req: httpx.ConnectTimeout("boom", request=req), TIMEOUT),
            (lambda req: httpx.ConnectError("boom", request=req), NETWORK_ERROR),
            (lambda req: httpx.RemoteProtocolError("boom", request=req), NETWORK_ERROR),
            (lambda req: SSRFError("private range"), BLOCKED_BY_POLICY),
        ],
    )
    async def test_transport_failures_classify_into_the_vocabulary(
        self, probe_transport, exc_factory, expected_detail: str
    ) -> None:
        """SSRFError is checked first because it is a ValueError.

        It arrives from two places: the guard transport at connect time, and
        the redirect-revalidation hook mid-chain. Either way the answer is
        that GeoLens refused to look, which is not the same as the network
        failing.
        """
        install, _ = probe_transport
        install(_raising(exc_factory))
        result = await probe_remote_uri(_ASSET)
        assert result.health == INACCESSIBLE
        assert result.detail == expected_detail

    @pytest.mark.parametrize(
        "handler",
        [
            _status_map({}, default=404),
            _status_map({}, default=403),
            _status_map({}, default=500),
            _status_map({}, default=418),
            _raising(lambda req: httpx.ReadTimeout("boom", request=req)),
            _raising(
                lambda req: httpx.ConnectError(
                    "failed connecting to https://origin.test/x?token=super-secret",
                    request=req,
                )
            ),
        ],
    )
    async def test_every_failure_detail_is_a_closed_vocabulary_code(
        self, probe_transport, handler
    ) -> None:
        """The redaction guarantee, stated as a closed set rather than a scan.

        Asserting "the URL is not in this string" would pass for any wording
        that happens not to include it today. Asserting membership in
        DETAIL_CODES is the property that actually holds: nothing the origin
        sent can be a member, so nothing the origin sent can be persisted.
        """
        install, _ = probe_transport
        install(handler)
        result = await probe_remote_uri(
            "https://origin.test/scene.tif?token=super-secret-value"
        )
        assert result.detail in DETAIL_CODES
        assert "super-secret-value" not in result.detail
        assert "origin.test" not in result.detail

    async def test_probe_is_a_bounded_ranged_get(self, probe_transport) -> None:
        install, recorded = probe_transport
        install(_status_map({}, default=206))
        await probe_remote_uri(_ASSET)
        assert len(recorded) == 1
        assert recorded[0].method == "GET"
        assert str(recorded[0].url) == _ASSET
        assert recorded[0].headers["Range"] == "bytes=0-0"

    @pytest.mark.parametrize(
        ("code", "expected"), [(206, True), (404, False), (403, False), (500, False)]
    )
    async def test_remote_asset_exists_is_the_boolean_projection(
        self, probe_transport, code: int, expected: bool
    ) -> None:
        """The VRT flow's contract, unchanged by the extraction.

        ``_remote_asset_exists`` returned ``status_code < 400``; every value
        the richer probe reports maps back onto that same line.
        """
        install, _ = probe_transport
        install(_status_map({}, default=code))
        assert await remote_asset_exists(_ASSET) is expected


# ---------------------------------------------------------------------------
# STAC item href capture (the reserved origin_ref key, #1261 follow-up)
# ---------------------------------------------------------------------------


_SEARCH_URL = "https://origin.test/stac/search"


class TestStacItemHrefCapture:
    def test_self_link_is_picked_out_of_the_item_links(self) -> None:
        feature = {
            "links": [
                {"rel": "collection", "href": "https://origin.test/collections/c"},
                {"rel": "self", "href": _ITEM},
            ]
        }
        assert _self_link_href(feature, _SEARCH_URL) == _ITEM

    def test_relative_self_link_resolves_against_the_search_url(self) -> None:
        """fix(#1271 review): a relative self href is legal STAC. Dropping it
        left item_href unwritten, so health reported healthy off the asset
        even after the item was withdrawn."""
        feature = {"links": [{"rel": "self", "href": "/collections/c/items/scene"}]}
        assert (
            _self_link_href(feature, _SEARCH_URL)
            == "https://origin.test/collections/c/items/scene"
        )

    @pytest.mark.parametrize(
        "links",
        [
            [],
            [{"rel": "parent", "href": "https://origin.test/x"}],
            # Non-HTTP self links are dropped: the probe would have nothing
            # safe to fetch, and a stored value the probe must then
            # special-case is worse than an absent one.
            [{"rel": "self", "href": "s3://bucket/items/scene.json"}],
            [{"rel": "self"}],
            [{"rel": "self", "href": "   "}],
            ["not-a-dict"],
            # A signed self link is dropped at capture, not passed on: the
            # import validator refuses credentialed URLs outright, so
            # surfacing one would 422 the caller's whole batch over a field
            # they never asked for.
            [{"rel": "self", "href": "https://origin.test/items/x?token=abc"}],
            [{"rel": "self", "href": "https://user:pw@origin.test/items/x"}],
            # Credential checks run on the RESOLVED value, so a relative href
            # cannot smuggle userinfo past them either.
            [{"rel": "self", "href": "//user:pw@origin.test/items/x"}],
        ],
    )
    def test_unusable_self_links_yield_none(self, links: list) -> None:
        assert _self_link_href({"links": links}, _SEARCH_URL) is None

    def test_missing_links_key_yields_none(self) -> None:
        assert _self_link_href({}, _SEARCH_URL) is None


class TestPinnedUrlRestoration:
    """fix(#1271 review): the SSRF transport pins the request URL to the
    validated IP for the duration of the connect, and must restore it after.
    A pinned URL that outlives the hop leaks the IP into relative-redirect
    resolution (next hop connects to the IP with SNI set to the IP — TLS
    failure), into resp.url, and into any item_href derived from it."""

    async def test_pinned_url_is_restored_after_the_hop(self, monkeypatch) -> None:
        from app.modules.catalog.sources import security

        async def fake_resolve(host: str, port) -> str:
            return "93.184.216.34"

        monkeypatch.setattr(security, "_resolve_and_validate", fake_resolve)

        seen: dict[str, str] = {}

        async def fake_send(self, request: httpx.Request) -> httpx.Response:
            seen["connect_host"] = request.url.host
            return httpx.Response(200, request=request)

        monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", fake_send)

        transport = security._SSRFGuardTransport()
        request = httpx.Request("POST", "https://origin.test:8443/stac/search")
        await transport.handle_async_request(request)

        # The connection itself went to the validated IP...
        assert seen["connect_host"] == "93.184.216.34"
        # ...but nothing downstream of the hop can see the mutation: a
        # relative Location resolves against the logical URL, and SNI on the
        # next hop is set from a hostname, not an IP.
        assert request.url.host == "origin.test"
        assert str(request.url) == "https://origin.test:8443/stac/search"
        assert request.extensions["sni_hostname"] == "origin.test"

    async def test_url_is_restored_even_when_the_connect_fails(
        self, monkeypatch
    ) -> None:
        from app.modules.catalog.sources import security

        async def fake_resolve(host: str, port) -> str:
            return "93.184.216.34"

        monkeypatch.setattr(security, "_resolve_and_validate", fake_resolve)

        async def fake_send(self, request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom", request=request)

        monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", fake_send)

        transport = security._SSRFGuardTransport()
        request = httpx.Request("GET", "https://origin.test/wfs")
        with pytest.raises(httpx.ConnectError):
            await transport.handle_async_request(request)
        assert request.url.host == "origin.test"

    def test_item_href_is_an_accepted_origin_ref_key(self) -> None:
        ref = build_origin_ref(
            "stac", item_href=_ITEM, asset_href=_ASSET, collection_id="c"
        )
        assert ref == {
            "kind": "stac",
            "asset_href": _ASSET,
            "collection_id": "c",
            "item_href": _ITEM,
        }

    async def test_import_records_the_item_href_when_search_supplied_one(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """End to end: search surfaces it, the request echoes it, import stores it.

        Without this the key stays permanently unwritten — which is exactly
        the state #1261 shipped and this issue was asked to close.
        """
        from unittest.mock import patch

        from app.modules.catalog.datasets.domain.models import Dataset

        item_id = f"href-{uuid.uuid4().hex[:8]}"
        with patch("app.modules.catalog.sources.stac_router.validate_url_for_ssrf"):
            resp = await client.post(
                "/services/stac/import",
                json={
                    "url": "https://origin.test/v1",
                    "items": [
                        {
                            "id": item_id,
                            "collection": "scenes",
                            "title": "Item href capture",
                            "data_asset_href": f"https://origin.test/{item_id}.tif",
                            "item_href": f"https://origin.test/items/{item_id}",
                            "bbox": [-1, -1, 1, 1],
                            "epsg": 4326,
                            "keywords": [],
                        }
                    ],
                    "visibility": "private",
                },
                headers=admin_auth_header,
            )
        assert resp.status_code == 200, resp.text
        dataset_id = resp.json()["results"][0]["dataset_id"]
        assert dataset_id is not None

        dataset = await test_db_session.get(Dataset, uuid.UUID(dataset_id))
        await test_db_session.refresh(dataset)
        assert dataset.origin_ref["item_href"] == f"https://origin.test/items/{item_id}"
        assert dataset.origin_ref["asset_href"] == f"https://origin.test/{item_id}.tif"

    async def test_import_without_an_item_href_still_succeeds(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """The admission half: catalogs with no rel=self link must still import.

        ``item_href`` is optional on purpose. A validator that ran on an
        explicit ``None`` would have rejected every one of these.
        """
        from unittest.mock import patch

        from app.modules.catalog.datasets.domain.models import Dataset

        item_id = f"nohref-{uuid.uuid4().hex[:8]}"
        with patch("app.modules.catalog.sources.stac_router.validate_url_for_ssrf"):
            resp = await client.post(
                "/services/stac/import",
                json={
                    "url": "https://origin.test/v1",
                    "items": [
                        {
                            "id": item_id,
                            "collection": "scenes",
                            "title": "No item href",
                            "data_asset_href": f"https://origin.test/{item_id}.tif",
                            "item_href": None,
                            "bbox": [-1, -1, 1, 1],
                            "epsg": 4326,
                            "keywords": [],
                        }
                    ],
                    "visibility": "private",
                },
                headers=admin_auth_header,
            )
        assert resp.status_code == 200, resp.text
        dataset_id = resp.json()["results"][0]["dataset_id"]
        dataset = await test_db_session.get(Dataset, uuid.UUID(dataset_id))
        await test_db_session.refresh(dataset)
        assert "item_href" not in dataset.origin_ref

    async def test_a_credentialed_item_href_is_refused_at_the_api(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        """The other half of the split: capture drops, the API still refuses.

        A hand-crafted client can still try, and a signed URL must never land
        in ``origin_ref`` (ADR-002 invariant 4).
        """
        from unittest.mock import patch

        with patch("app.modules.catalog.sources.stac_router.validate_url_for_ssrf"):
            resp = await client.post(
                "/services/stac/import",
                json={
                    "url": "https://origin.test/v1",
                    "items": [
                        {
                            "id": "signed-item",
                            "collection": "scenes",
                            "title": "Signed item href",
                            "data_asset_href": "https://origin.test/signed.tif",
                            "item_href": "https://origin.test/items/x?token=abc",
                            "keywords": [],
                        }
                    ],
                    "visibility": "private",
                },
                headers=admin_auth_header,
            )
        assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# The endpoint
# ---------------------------------------------------------------------------


async def _stac_dataset(
    session,
    *,
    created_by: uuid.UUID,
    asset_uri: str | None = _ASSET,
    item_href: str | None = None,
    visibility: str = "public",
) -> object:
    """A standalone STAC dataset with a remote raster asset, like import makes."""
    from app.processing.raster.models import RasterAsset

    dataset = await _create_dataset(
        session,
        created_by=created_by,
        name=f"STAC Origin {uuid.uuid4().hex[:6]}",
        source_format="stac",
        visibility=visibility,
    )
    dataset.record.record_type = "raster_dataset"
    dataset.origin_uri = asset_uri
    dataset.origin_ref = build_origin_ref(
        "stac", asset_href=asset_uri, item_href=item_href, collection_id="scenes"
    )
    if asset_uri is not None:
        session.add(
            RasterAsset(
                dataset_id=dataset.id,
                asset_uri=asset_uri,
                storage_backend="remote",
                cog_status="verified",
            )
        )
    await session.commit()
    return dataset


async def _service_dataset(
    session,
    *,
    created_by: uuid.UUID,
    origin_uri: str | None = "https://origin.test/FeatureServer/0",
    visibility: str = "public",
    service_type: str = "arcgis_featureserver",
    service_url: str | None = "https://origin.test/FeatureServer",
    layer_id: str | None = "0",
) -> object:
    dataset = await _create_dataset(
        session,
        created_by=created_by,
        name=f"Service Origin {uuid.uuid4().hex[:6]}",
        source_format=service_type,
        visibility=visibility,
    )
    dataset.origin_uri = origin_uri
    dataset.origin_ref = build_origin_ref(
        "service",
        service_type=service_type,
        url=service_url if origin_uri else None,
        layer_id=layer_id if origin_uri else None,
    )
    await session.commit()
    return dataset


class TestStacOriginProbe:
    async def test_live_asset_is_healthy_and_persisted(
        self, client, admin_auth_header, test_db_session, probe_transport
    ) -> None:
        install, recorded = probe_transport
        install(_status_map({_ASSET: 206}))
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(test_db_session, created_by=admin_id)

        before = datetime.now(timezone.utc)
        resp = await client.post(
            f"/datasets/{dataset.id}/source-health/", headers=admin_auth_header
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["source_health"] == HEALTHY
        assert body["source_health_detail"] is None
        assert body["origin"] == "stac"
        assert [str(r.url) for r in recorded] == [_ASSET]

        await test_db_session.refresh(dataset)
        assert dataset.source_health == HEALTHY
        assert dataset.source_health_detail is None
        assert dataset.last_checked_at is not None
        assert dataset.last_checked_at >= before - timedelta(seconds=5)

    async def test_dead_upstream_is_reported_without_a_tile_request(
        self, client, admin_auth_header, test_db_session, probe_transport
    ) -> None:
        """The acceptance criterion, stated as the issue states it."""
        install, _ = probe_transport
        install(_status_map({_ASSET: 404}))
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(test_db_session, created_by=admin_id)

        resp = await client.post(
            f"/datasets/{dataset.id}/source-health/", headers=admin_auth_header
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["source_health"] == MISSING

        await test_db_session.refresh(dataset)
        assert dataset.source_health == MISSING
        assert dataset.source_health_detail == NOT_FOUND

    async def test_unreachable_origin_still_stamps_last_checked_at(
        self, client, admin_auth_header, test_db_session, probe_transport
    ) -> None:
        """The failure half of ``last_checked_at``'s contract.

        A success-only writer passes every happy-path test and leaves the
        column silent in exactly the situation someone is investigating.
        """
        install, _ = probe_transport
        install(_raising(lambda req: httpx.ConnectTimeout("no route", request=req)))
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(test_db_session, created_by=admin_id)
        assert dataset.last_checked_at is None

        resp = await client.post(
            f"/datasets/{dataset.id}/source-health/", headers=admin_auth_header
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["source_health"] == INACCESSIBLE
        assert resp.json()["source_health_detail"] == TIMEOUT
        assert resp.json()["last_checked_at"] is not None

        await test_db_session.refresh(dataset)
        assert dataset.last_checked_at is not None
        assert dataset.source_health == INACCESSIBLE

    async def test_persisted_detail_is_always_a_vocabulary_code(
        self, client, admin_auth_header, test_db_session, probe_transport
    ) -> None:
        """The column-level statement of the redaction guarantee."""
        install, _ = probe_transport
        install(
            _raising(
                lambda req: httpx.ConnectError(
                    "failed connecting to https://origin.test/x?token=leak", request=req
                )
            )
        )
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(test_db_session, created_by=admin_id)

        resp = await client.post(
            f"/datasets/{dataset.id}/source-health/", headers=admin_auth_header
        )
        assert resp.status_code == 200, resp.text

        await test_db_session.refresh(dataset)
        assert dataset.source_health_detail in DETAIL_CODES
        assert dataset.source_health_detail == NETWORK_ERROR

    async def test_withdrawn_item_outranks_a_still_served_asset(
        self, client, admin_auth_header, test_db_session, probe_transport
    ) -> None:
        """The state an asset-only probe cannot see.

        The publisher pulled the item; the bucket still serves the bytes.
        Reporting ``healthy`` here would hide a catalog entry that no longer
        exists upstream and can never be refreshed.
        """
        install, recorded = probe_transport
        install(_status_map({_ASSET: 200, _ITEM: 404}))
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(
            test_db_session, created_by=admin_id, item_href=_ITEM
        )

        resp = await client.post(
            f"/datasets/{dataset.id}/source-health/", headers=admin_auth_header
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["source_health"] == MISSING
        assert body["source_health_detail"] == ITEM_WITHDRAWN
        assert {str(r.url) for r in recorded} == {_ASSET, _ITEM}

    async def test_an_unreachable_item_does_not_count_as_withdrawn(
        self, client, admin_auth_header, test_db_session, probe_transport
    ) -> None:
        """The same 401-is-not-404 rule, one level up.

        A 403 on the item document says GeoLens lost access to the catalog,
        not that the publisher withdrew the item. The asset is serving, so
        the dataset is healthy.
        """
        install, _ = probe_transport
        install(_status_map({_ASSET: 200, _ITEM: 403}))
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(
            test_db_session, created_by=admin_id, item_href=_ITEM
        )

        resp = await client.post(
            f"/datasets/{dataset.id}/source-health/", headers=admin_auth_header
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["source_health"] == HEALTHY

    async def test_live_item_leaves_the_asset_verdict_standing(
        self, client, admin_auth_header, test_db_session, probe_transport
    ) -> None:
        """The other direction: a healthy item cannot mask a deleted asset."""
        install, _ = probe_transport
        install(_status_map({_ASSET: 404, _ITEM: 200}))
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(
            test_db_session, created_by=admin_id, item_href=_ITEM
        )

        resp = await client.post(
            f"/datasets/{dataset.id}/source-health/", headers=admin_auth_header
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["source_health"] == MISSING
        assert resp.json()["source_health_detail"] == NOT_FOUND


class TestServiceOriginProbe:
    async def test_reachable_service_endpoint_is_healthy(
        self, client, admin_auth_header, test_db_session, probe_transport
    ) -> None:
        install, recorded = probe_transport
        install(_status_map({}, default=200))
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(test_db_session, created_by=admin_id)

        resp = await client.post(
            f"/datasets/{dataset.id}/source-health/", headers=admin_auth_header
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["origin"] == "service"
        assert resp.json()["source_health"] == HEALTHY
        # Bounded: the layer endpoint, once, ranged. For ArcGIS the enriched
        # origin_uri IS the layer resource, so it is the sharper probe target.
        assert len(recorded) == 1
        assert str(recorded[0].url) == "https://origin.test/FeatureServer/0"
        assert recorded[0].headers["Range"] == "bytes=0-0"

    async def test_wfs_probe_targets_the_canonical_service_url(
        self, client, admin_auth_header, test_db_session, probe_transport
    ) -> None:
        """fix(#1271 review): WFS addresses layers by typename, so the
        enriched ``<base>/<layer name>`` origin_uri is provenance, not an
        endpoint — and the base alone is not enough either, since many
        servers 4xx a request without the capabilities parameters. The probe
        must ask the same question the import adapter asks."""
        install, recorded = probe_transport
        install(_status_map({}, default=200))
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(
            test_db_session,
            created_by=admin_id,
            service_type="wfs",
            origin_uri="https://origin.test/wfs/topp:roads",
            service_url="https://origin.test/wfs",
            layer_id="topp:roads",
        )

        resp = await client.post(
            f"/datasets/{dataset.id}/source-health/", headers=admin_auth_header
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["source_health"] == HEALTHY
        assert len(recorded) == 1
        assert (
            str(recorded[0].url)
            == "https://origin.test/wfs?service=WFS&request=GetCapabilities"
        )

    async def test_legacy_wfs_row_without_a_base_url_refuses_to_probe(
        self, client, admin_auth_header, test_db_session, probe_transport
    ) -> None:
        """fix(#1271 review): migration 0036's legacy branch leaves
        origin_ref.url unset when the service base is not derivable. The only
        value on hand is the enriched non-endpoint, and probing it would
        persist a false result — refuse instead, like every pointerless row."""
        install, recorded = probe_transport
        install(_status_map({}, default=200))
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(
            test_db_session,
            created_by=admin_id,
            service_type="wfs",
            origin_uri="https://origin.test/wfs/topp:roads",
            service_url=None,
            layer_id=None,
        )

        resp = await client.post(
            f"/datasets/{dataset.id}/source-health/", headers=admin_auth_header
        )
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"]["code"] == "origin_pointer_missing"
        assert recorded == []

    async def test_ogcapi_probe_targets_the_canonical_service_url(
        self, client, admin_auth_header, test_db_session, probe_transport
    ) -> None:
        install, recorded = probe_transport
        install(_status_map({}, default=200))
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(
            test_db_session,
            created_by=admin_id,
            service_type="ogcapi_features",
            origin_uri="https://origin.test/ogc/roads",
            service_url="https://origin.test/ogc",
            layer_id="roads",
        )

        resp = await client.post(
            f"/datasets/{dataset.id}/source-health/", headers=admin_auth_header
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["source_health"] == HEALTHY
        assert len(recorded) == 1
        assert str(recorded[0].url) == "https://origin.test/ogc"

    async def test_gone_service_endpoint_is_missing(
        self, client, admin_auth_header, test_db_session, probe_transport
    ) -> None:
        install, _ = probe_transport
        install(_status_map({}, default=410))
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(test_db_session, created_by=admin_id)

        resp = await client.post(
            f"/datasets/{dataset.id}/source-health/", headers=admin_auth_header
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["source_health"] == MISSING
        assert resp.json()["source_health_detail"] == NOT_FOUND

    async def test_service_behind_new_auth_is_inaccessible(
        self, client, admin_auth_header, test_db_session, probe_transport
    ) -> None:
        install, _ = probe_transport
        install(_status_map({}, default=401))
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(test_db_session, created_by=admin_id)

        resp = await client.post(
            f"/datasets/{dataset.id}/source-health/", headers=admin_auth_header
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["source_health"] == INACCESSIBLE
        assert resp.json()["source_health_detail"] == UNAUTHORIZED


class TestNotApplicableOrigins:
    async def test_upload_origin_is_409_and_writes_nothing(
        self, client, admin_auth_header, test_db_session, probe_transport
    ) -> None:
        install, recorded = probe_transport
        install(_status_map({}, default=200))
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name=f"Uploaded {uuid.uuid4().hex[:6]}",
            source_format="gpkg",
        )
        await test_db_session.commit()

        resp = await client.post(
            f"/datasets/{dataset.id}/source-health/", headers=admin_auth_header
        )
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"]["code"] == "health_check_not_applicable"
        assert resp.json()["detail"]["origin"] == "upload"
        assert recorded == []

        await test_db_session.refresh(dataset)
        assert dataset.last_checked_at is None
        assert dataset.source_health is None

    async def test_probeable_origin_without_a_pointer_is_409(
        self, client, admin_auth_header, test_db_session, probe_transport
    ) -> None:
        """Nothing was contacted, so ``last_checked_at`` must stay NULL.

        Reporting ``inaccessible`` instead would date a conversation that
        never happened.
        """
        install, recorded = probe_transport
        install(_status_map({}, default=200))
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(
            test_db_session, created_by=admin_id, origin_uri=None
        )

        resp = await client.post(
            f"/datasets/{dataset.id}/source-health/", headers=admin_auth_header
        )
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"]["code"] == "origin_pointer_missing"
        assert recorded == []

        await test_db_session.refresh(dataset)
        assert dataset.last_checked_at is None

    async def test_unknown_dataset_is_404(
        self, client, admin_auth_header, probe_transport
    ) -> None:
        install, _ = probe_transport
        install(_status_map({}, default=200))
        resp = await client.post(
            f"/datasets/{uuid.uuid4()}/source-health/", headers=admin_auth_header
        )
        assert resp.status_code == 404


class TestAccessControl:
    """Probing is a mutation, so it is owner-or-admin, not a visibility read."""

    async def test_anonymous_caller_is_rejected(
        self, client, test_db_session, probe_transport
    ) -> None:
        install, recorded = probe_transport
        install(_status_map({}, default=200))
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )

        resp = await client.post(f"/datasets/{dataset.id}/source-health/")
        assert resp.status_code == 401
        # The probe must not fire before the guard decides.
        assert recorded == []

        await test_db_session.refresh(dataset)
        assert dataset.last_checked_at is None

    async def test_a_reader_who_is_not_the_owner_cannot_probe(
        self, client, test_db_session, editor_auth_header, probe_transport
    ) -> None:
        """The amplification surface, closed.

        This caller can READ the dataset: it is public and published. What
        they must not be able to do is make GeoLens issue outbound requests
        at the origin, repeatedly, on a row they do not own.
        """
        install, recorded = probe_transport
        install(_status_map({}, default=200))
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )

        readable = await client.get(
            f"/datasets/{dataset.id}", headers=editor_auth_header
        )
        assert readable.status_code == 200, "precondition: this caller can read it"

        resp = await client.post(
            f"/datasets/{dataset.id}/source-health/", headers=editor_auth_header
        )
        assert resp.status_code == 403, resp.text
        assert recorded == []

        await test_db_session.refresh(dataset)
        assert dataset.last_checked_at is None

    async def test_the_owner_can_probe_their_own_dataset(
        self, client, test_db_session, editor_auth_header, probe_transport
    ) -> None:
        """The admission half.

        A guard that started refusing every non-admin would make the refusal
        test above pass more emphatically and nothing else would notice.
        """
        install, _ = probe_transport
        install(_status_map({_ASSET: 200}))
        me = await client.get("/auth/me", headers=editor_auth_header)
        assert me.status_code == 200, me.text
        dataset = await _stac_dataset(
            test_db_session, created_by=uuid.UUID(me.json()["id"])
        )

        resp = await client.post(
            f"/datasets/{dataset.id}/source-health/", headers=editor_auth_header
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["source_health"] == HEALTHY

    async def test_readers_still_get_the_stored_state_from_the_dataset_read(
        self,
        client,
        admin_auth_header,
        editor_auth_header,
        test_db_session,
        probe_transport,
    ) -> None:
        """Why closing the write path costs readers nothing.

        The health fields have been on DatasetResponse since #1218, so no
        second GET endpoint is needed and none should be added.
        """
        install, _ = probe_transport
        install(_status_map({_ASSET: 404}))
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(test_db_session, created_by=admin_id)

        probed = await client.post(
            f"/datasets/{dataset.id}/source-health/", headers=admin_auth_header
        )
        assert probed.status_code == 200, probed.text

        read = await client.get(f"/datasets/{dataset.id}", headers=editor_auth_header)
        assert read.status_code == 200, read.text
        body = read.json()
        assert body["source_health"] == MISSING
        assert body["source_health_detail"] == NOT_FOUND
        assert body["last_checked_at"] is not None
