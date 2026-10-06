"""On-demand STAC asset size lookup: probe order, bounds and SSRF refusals."""

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import AsyncClient

from app.core.service_tokens import CredentialMethod, ServiceCredential
from app.modules.catalog.sources.adapters import stac_asset_size
from app.modules.catalog.sources.adapters.stac_asset_size import probe_asset_sizes
from app.platform import security

CATALOG = "https://stac.example.com/v1"
ASSET = "https://data.example.com/a.tif"


def _client(handler, **kwargs) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
        event_hooks={"response": [security._revalidate_redirect]},
        **kwargs,
    )


@pytest.fixture
def no_dns():
    with patch.object(stac_asset_size, "validate_url_for_ssrf", new=AsyncMock()):
        yield


def _patched(handler):
    return patch.object(
        stac_asset_size, "make_safe_client", side_effect=lambda **kw: _client(handler)
    )


class TestProbeOrder:
    async def test_head_content_length_is_used(self, no_dns):
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.method)
            return httpx.Response(200, headers={"content-length": "4096"})

        with _patched(handler):
            sizes = await probe_asset_sizes(CATALOG, [ASSET])
        assert sizes == [4096]
        assert seen == ["HEAD"]

    async def test_range_get_total_when_head_is_refused(self, no_dns):
        seen: list[tuple[str, str | None]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append((request.method, request.headers.get("range")))
            if request.method == "HEAD":
                return httpx.Response(405)
            return httpx.Response(206, headers={"content-range": "bytes 0-0/987654"})

        with _patched(handler):
            sizes = await probe_asset_sizes(CATALOG, [ASSET])
        assert sizes == [987654]
        assert seen == [("HEAD", None), ("GET", "bytes=0-0")]

    async def test_size_stays_unknown_when_the_server_reports_none(self, no_dns):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "HEAD":
                return httpx.Response(200)
            return httpx.Response(206, headers={"content-range": "bytes 0-0/*"})

        with _patched(handler):
            sizes = await probe_asset_sizes(CATALOG, [ASSET])
        assert sizes == [None]


class TestHostileLengths:
    async def test_an_enormous_content_range_total_is_unknown(self, no_dns):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "HEAD":
                return httpx.Response(405)
            return httpx.Response(
                206, headers={"content-range": f"bytes 0-0/{'9' * 5000}"}
            )

        with _patched(handler):
            sizes = await probe_asset_sizes(CATALOG, [ASSET])
        assert sizes == [None]

    async def test_an_enormous_content_length_is_unknown(self, no_dns):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "HEAD":
                return httpx.Response(200, headers={"content-length": "9" * 5000})
            return httpx.Response(405)

        with _patched(handler):
            sizes = await probe_asset_sizes(CATALOG, [ASSET])
        assert sizes == [None]


class TestRefusals:
    async def test_redirect_to_a_private_ip_is_refused(self, no_dns):
        reached: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            reached.append(str(request.url))
            if request.url.host == "data.example.com":
                return httpx.Response(
                    302, headers={"location": "http://169.254.169.254/latest"}
                )
            return httpx.Response(200, headers={"content-length": "1"})

        with _patched(handler):
            sizes = await probe_asset_sizes(CATALOG, [ASSET])
        assert sizes == [None]
        assert reached == [ASSET]

    async def test_private_asset_href_is_never_requested(self):
        reached: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            reached.append(str(request.url))
            return httpx.Response(200, headers={"content-length": "1"})

        with _patched(handler):
            sizes = await probe_asset_sizes(CATALOG, ["http://127.0.0.1/a.tif"])
        assert sizes == [None]
        assert reached == []


class TestCredentialScope:
    CREDENTIAL = ServiceCredential(
        method=CredentialMethod.HEADER_KEY,
        service_format="stac",
        header_name="X-Api-Key",
        header_value="s3cret-value",
    )

    async def test_key_goes_only_to_the_catalog_origin(self, no_dns):
        sent: dict[str, str | None] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            sent[request.url.host] = request.headers.get("x-api-key")
            return httpx.Response(200, headers={"content-length": "7"})

        with _patched(handler):
            await probe_asset_sizes(
                CATALOG,
                ["https://stac.example.com/a.tif", ASSET],
                self.CREDENTIAL,
            )
        assert sent == {"stac.example.com": "s3cret-value", "data.example.com": None}


class TestBounds:
    async def test_a_hung_server_leaves_the_size_unknown(self, no_dns):
        async def handler(request: httpx.Request) -> httpx.Response:
            await asyncio.sleep(5)
            return httpx.Response(200, headers={"content-length": "1"})

        with _patched(handler), patch.object(stac_asset_size, "PROBE_TIMEOUT", 0.05):
            sizes = await probe_asset_sizes(CATALOG, [ASSET])
        assert sizes == [None]

    async def test_probes_run_under_the_concurrency_cap(self, no_dns):
        live = peak = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal live, peak
            live += 1
            peak = max(peak, live)
            await asyncio.sleep(0.02)
            live -= 1
            return httpx.Response(200, headers={"content-length": "1"})

        assets = [f"https://data.example.com/{n}.tif" for n in range(12)]
        with _patched(handler):
            sizes = await probe_asset_sizes(CATALOG, assets)
        assert sizes == [1] * 12
        assert peak == stac_asset_size.MAX_CONCURRENT_PROBES


class TestBatchDeadline:
    async def test_slow_assets_past_the_deadline_come_back_unknown(self, no_dns):
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/slow.tif":
                await asyncio.sleep(5)
            return httpx.Response(200, headers={"content-length": "9"})

        assets = [
            "https://data.example.com/fast.tif",
            "https://data.example.com/slow.tif",
        ]
        with _patched(handler), patch.object(stac_asset_size, "BATCH_DEADLINE", 0.2):
            sizes = await probe_asset_sizes(CATALOG, assets)
        assert sizes == [9, None]

    async def test_assets_queued_behind_the_cap_are_cut_off_too(self, no_dns):
        async def handler(request: httpx.Request) -> httpx.Response:
            await asyncio.sleep(5)
            return httpx.Response(200, headers={"content-length": "1"})

        assets = [f"https://data.example.com/{n}.tif" for n in range(10)]
        with _patched(handler), patch.object(stac_asset_size, "BATCH_DEADLINE", 0.2):
            sizes = await asyncio.wait_for(probe_asset_sizes(CATALOG, assets), 3)
        assert sizes == [None] * 10


class TestEndpoint:
    async def test_returns_a_size_per_asset(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        with (
            patch(
                "app.modules.catalog.sources.stac_asset_size_router.validate_url_for_ssrf",
                new=AsyncMock(),
            ),
            patch(
                "app.modules.catalog.sources.stac_asset_size_router.probe_asset_sizes",
                new=AsyncMock(return_value=[10, None]),
            ),
        ):
            resp = await client.post(
                "/services/stac/asset-sizes",
                json={
                    "url": CATALOG,
                    "assets": [
                        {"id": "i1", "href": ASSET},
                        {"id": "i2", "href": "https://data.example.com/b.tif"},
                    ],
                },
                headers=admin_auth_header,
            )
        assert resp.status_code == 200
        assert resp.json()["sizes"] == [
            {"id": "i1", "size_bytes": 10},
            {"id": "i2", "size_bytes": None},
        ]

    async def test_duplicate_item_ids_each_get_an_entry(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        probe = AsyncMock(return_value=[1, 2])
        with (
            patch(
                "app.modules.catalog.sources.stac_asset_size_router.validate_url_for_ssrf",
                new=AsyncMock(),
            ),
            patch(
                "app.modules.catalog.sources.stac_asset_size_router.probe_asset_sizes",
                new=probe,
            ),
        ):
            resp = await client.post(
                "/services/stac/asset-sizes",
                json={
                    "url": CATALOG,
                    "assets": [
                        {"id": "same", "href": ASSET},
                        {"id": "same", "href": "https://data.example.com/b.tif"},
                    ],
                },
                headers=admin_auth_header,
            )
        assert resp.json()["sizes"] == [
            {"id": "same", "size_bytes": 1},
            {"id": "same", "size_bytes": 2},
        ]
        assert probe.await_args.args[1] == [ASSET, "https://data.example.com/b.tif"]

    async def test_slow_catalog_validation_is_cut_off(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        async def slow(_url):
            await asyncio.sleep(5)

        probe = AsyncMock(return_value=[None])
        with (
            patch(
                "app.modules.catalog.sources.stac_asset_size_router.validate_url_for_ssrf",
                new=slow,
            ),
            patch(
                "app.modules.catalog.sources.stac_asset_size_router.BATCH_DEADLINE",
                0.1,
            ),
            patch(
                "app.modules.catalog.sources.stac_asset_size_router.probe_asset_sizes",
                new=probe,
            ),
        ):
            resp = await client.post(
                "/services/stac/asset-sizes",
                json={"url": CATALOG, "assets": [{"id": "i1", "href": ASSET}]},
                headers=admin_auth_header,
            )
        assert resp.status_code == 504
        probe.assert_not_awaited()

    async def test_probing_gets_only_the_time_validation_left(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        async def slowish(_url):
            await asyncio.sleep(0.15)

        probe = AsyncMock(return_value=[None])
        with (
            patch(
                "app.modules.catalog.sources.stac_asset_size_router.validate_url_for_ssrf",
                new=slowish,
            ),
            patch(
                "app.modules.catalog.sources.stac_asset_size_router.BATCH_DEADLINE",
                0.5,
            ),
            patch(
                "app.modules.catalog.sources.stac_asset_size_router.probe_asset_sizes",
                new=probe,
            ),
        ):
            await client.post(
                "/services/stac/asset-sizes",
                json={"url": CATALOG, "assets": [{"id": "i1", "href": ASSET}]},
                headers=admin_auth_header,
            )
        assert probe.await_args.kwargs["deadline"] < 0.4

    async def test_private_catalog_url_is_refused(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        resp = await client.post(
            "/services/stac/asset-sizes",
            json={
                "url": "http://127.0.0.1/stac",
                "assets": [{"id": "i1", "href": ASSET}],
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 400

    async def test_requires_authentication(self, client: AsyncClient):
        resp = await client.post(
            "/services/stac/asset-sizes",
            json={"url": CATALOG, "assets": [{"id": "i1", "href": ASSET}]},
        )
        assert resp.status_code in (401, 403)
