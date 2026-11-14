"""A remote COG gets quicklooks drawn by Titiler at STAC import and on refresh.

Titiler is stubbed at its HTTP client, as ``test_cog_info.py`` stubs it, so the
relay address handed to it, the reads it answers and the bytes stored are all
the production path's.

Requirements: the test database (``set -a && source ../.env.test && set +a``).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import structlog
from httpx import AsyncClient
from sqlalchemy import update

from app.platform.storage import remote_quicklook
from app.platform.storage.provider import get_storage
from app.platform.storage.raster_relay import is_relay_url
from app.processing.raster.models import RasterAsset
from tests.factories import get_user_id
from tests.test_cog_info import _TITILER_INFO, _install as _install_cog_info
from tests.test_stac_refresh_1266 import (
    _ASSET,
    _ITEM,
    _MOVED_ASSET,
    _dispatch,
    _dispatch_with_credential,
    _execute,
    _execute_with_credential,
    _item_doc,
    _raster_asset,
    _run_for,
    _stac_dataset,
)
from tests import test_stac_refresh_1266 as refresh_suite
from tests.test_vrt_source_authz_1172 import _make_editor

pytestmark = pytest.mark.anyio

# The refresh suite's fixtures: its catalog transport, Titiler's reading of a
# moved COG, and the single-use credential store.
stac_transport = refresh_suite.stac_transport
cog_info = refresh_suite.cog_info
credential_backend = refresh_suite.credential_backend

_PNG = {
    256: b"\x89PNG\r\n\x1a\nremote quicklook 256",
    512: b"\x89PNG\r\n\x1a\nremote quicklook 512",
}


def _titiler(monkeypatch, handler=None) -> list[httpx.Request]:
    """Answer the quicklook draws' Titiler reads; return the requests made."""
    seen: list[httpx.Request] = []

    async def _handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if handler is not None:
            return await handler(request)
        size = int(request.url.params["max_size"])
        return httpx.Response(
            200, content=_PNG[size], headers={"content-type": "image/png"}
        )

    def _client(*args, **kwargs) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(_handle))

    monkeypatch.setattr(
        "app.platform.storage.remote_quicklook.httpx",
        SimpleNamespace(
            AsyncClient=_client, Timeout=httpx.Timeout, HTTPError=httpx.HTTPError
        ),
    )
    return seen


async def _import(client: AsyncClient, headers: dict, href: str) -> uuid.UUID:
    with patch("app.modules.catalog.sources.stac_router.validate_url_for_ssrf"):
        resp = await client.post(
            "/services/stac/import",
            json={
                "url": "https://stac.example.com/v1",
                "items": [
                    {
                        "id": f"scene-{uuid.uuid4().hex[:8]}",
                        "collection": "imagery",
                        "title": "Remote COG",
                        "data_asset_href": href,
                        "bbox": [-1, -1, 1, 1],
                        "epsg": 32621,
                    }
                ],
                "visibility": "private",
            },
            headers=headers,
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] == 1, resp.text
    return uuid.UUID(resp.json()["results"][0]["dataset_id"])


def _path(href: str) -> str:
    return href[href.index("/datasets/") :]


async def _stored_quicklooks() -> list[str]:
    """Every remote quicklook object in the test's storage."""
    return [
        entry.key
        async for page in get_storage().iter_object_pages("rasters/")
        for entry in page
        if "remote-quicklook" in entry.key
    ]


def _slow_storage(monkeypatch, *, put: float = 0.0, delete: float = 0.0) -> None:
    """Delay the storage provider's writes and deletes by these many seconds."""
    storage = get_storage()
    real_put, real_delete = storage.put, storage.delete

    async def slow_put(key, data):
        await asyncio.sleep(put)
        return await real_put(key, data)

    async def slow_delete(key):
        await asyncio.sleep(delete)
        return await real_delete(key)

    monkeypatch.setattr(storage, "put", slow_put)
    monkeypatch.setattr(storage, "delete", slow_delete)


def test_bands_and_stretch_follow_the_probe() -> None:
    """Three bands of uint16 draw as RGB stretched over each band's own range."""
    query = remote_quicklook._render_query(
        {
            "band_count": 4,
            "dtype": "uint16",
            "band_info": [{"min": 10, "max": 900}, {"min": 0, "max": 0}, None],
        }
    )
    assert query == [
        ("bidx", "1"),
        ("bidx", "2"),
        ("bidx", "3"),
        ("rescale", "10,900"),
        ("rescale", "0,65535"),
        ("rescale", "0,65535"),
    ]
    assert remote_quicklook._render_query({"band_count": 1, "dtype": "uint8"}) == []


class TestImport:
    async def test_an_imported_remote_cog_has_a_thumbnail_that_returns_a_png(
        self, client, admin_auth_header, monkeypatch
    ) -> None:
        """The item's thumbnail and overview hrefs answer the drawn PNGs."""
        _install_cog_info(monkeypatch, _TITILER_INFO)
        seen = _titiler(monkeypatch)
        dataset_id = await _import(
            client, admin_auth_header, "https://cogs.example.com/scene.tif"
        )

        # Titiler is handed the relay address, never the asset URL.
        assert sorted(int(r.url.params["max_size"]) for r in seen) == [256, 512]
        for request in seen:
            assert request.url.path == "/cog/preview.png"
            assert is_relay_url(request.url.params["url"])
            assert "cogs.example.com" not in str(request.url)

        raster = await _raster_asset(dataset_id)
        for key in (raster.quicklook_256_uri, raster.quicklook_512_uri):
            assert key.startswith(f"rasters/{dataset_id}/")

        item = await client.get(f"/stac/items/{dataset_id}", headers=admin_auth_header)
        assert item.status_code == 200, item.text
        assets = item.json()["assets"]
        for key, size in (("thumbnail", 256), ("overview", 512)):
            assert assets[key]["type"] == "image/png"
            png = await client.get(
                _path(assets[key]["href"]), headers=admin_auth_header
            )
            assert png.status_code == 200
            assert png.headers["content-type"] == "image/png"
            assert png.content == _PNG[size]

    async def test_a_private_thumbnail_answers_whoever_its_item_answers(
        self, client, admin_auth_header, monkeypatch
    ) -> None:
        """Owner reads both; another user and an anonymous caller get 404 for both."""
        _install_cog_info(monkeypatch, _TITILER_INFO)
        _titiler(monkeypatch)
        dataset_id = await _import(
            client, admin_auth_header, "https://cogs.example.com/private.tif"
        )
        item = await client.get(f"/stac/items/{dataset_id}", headers=admin_auth_header)
        thumbnail = _path(item.json()["assets"]["thumbnail"]["href"])
        editor_headers, _ = await _make_editor(client, admin_auth_header)

        for headers, expected in (
            (admin_auth_header, 200),
            (editor_headers, 404),
            ({}, 404),
        ):
            item = await client.get(f"/stac/items/{dataset_id}", headers=headers)
            png = await client.get(thumbnail, headers=headers)
            assert (item.status_code, png.status_code) == (expected, expected)

    async def test_a_draw_that_times_out_leaves_the_import_without_a_thumbnail(
        self, client, admin_auth_header, monkeypatch
    ) -> None:
        """The import answers within the draw budget and stores no quicklook."""
        _install_cog_info(monkeypatch, _TITILER_INFO)
        monkeypatch.setattr(remote_quicklook, "DRAW_BUDGET_S", 0.3)

        async def _hang(request: httpx.Request) -> httpx.Response:
            await asyncio.sleep(30)
            return httpx.Response(200, content=_PNG[256])

        _titiler(monkeypatch, _hang)
        started = time.monotonic()
        with structlog.testing.capture_logs() as logs:
            dataset_id = await _import(
                client, admin_auth_header, "https://cogs.example.com/slow.tif"
            )
        assert time.monotonic() - started < 10

        raster = await _raster_asset(dataset_id)
        assert (raster.quicklook_256_uri, raster.quicklook_512_uri) == (None, None)
        item = await client.get(f"/stac/items/{dataset_id}", headers=admin_auth_header)
        assert "thumbnail" not in item.json()["assets"]
        failures = [e for e in logs if e["event"] == "remote_quicklook_not_drawn"]
        assert [e["reason"] for e in failures] == ["timeout"]

    async def test_a_quicklook_titiler_cannot_draw_is_skipped_once(
        self, client, admin_auth_header, monkeypatch
    ) -> None:
        """A non-200 from Titiler logs one reason code and stores nothing."""
        _install_cog_info(monkeypatch, _TITILER_INFO)

        async def _refuse(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        _titiler(monkeypatch, _refuse)
        with structlog.testing.capture_logs() as logs:
            dataset_id = await _import(
                client, admin_auth_header, "https://cogs.example.com/bad.tif"
            )
        raster = await _raster_asset(dataset_id)
        assert raster.quicklook_256_uri is None
        failures = [e for e in logs if e["event"] == "remote_quicklook_not_drawn"]
        assert [(e["reason"], e["status"]) for e in failures] == [
            ("titiler_status", 500)
        ]

    async def test_a_write_slower_than_the_budget_is_awaited_not_dropped(
        self, client, admin_auth_header, monkeypatch
    ) -> None:
        """The deadline ends Titiler reads; a slow store still lands."""
        _install_cog_info(monkeypatch, _TITILER_INFO)
        _titiler(monkeypatch)
        monkeypatch.setattr(remote_quicklook, "DRAW_BUDGET_S", 0.2)
        _slow_storage(monkeypatch, put=0.4)
        started = time.monotonic()
        dataset_id = await _import(
            client, admin_auth_header, "https://cogs.example.com/slowstore.tif"
        )
        assert time.monotonic() - started >= 0.8
        raster = await _raster_asset(dataset_id)
        assert await get_storage().get(raster.quicklook_512_uri) == _PNG[512]

    async def test_an_item_not_created_has_its_images_deleted_even_slowly(
        self, client, admin_auth_header, monkeypatch
    ) -> None:
        """A refused item's drawn images are gone when the request returns."""
        from app.modules.quota.service import DatasetQuotaExceededError

        _install_cog_info(monkeypatch, _TITILER_INFO)
        seen = _titiler(monkeypatch)
        _slow_storage(monkeypatch, delete=0.4)
        with (
            patch(
                "app.modules.quota.service.reserve_dataset_slot",
                AsyncMock(side_effect=DatasetQuotaExceededError("full")),
            ),
            patch("app.modules.catalog.sources.stac_router.validate_url_for_ssrf"),
        ):
            resp = await client.post(
                "/services/stac/import",
                json={
                    "url": "https://stac.example.com/v1",
                    "items": [
                        {
                            "id": "over-quota",
                            "title": "Over quota",
                            "data_asset_href": "https://cogs.example.com/q.tif",
                        }
                    ],
                },
                headers=admin_auth_header,
            )
        assert resp.status_code == 200, resp.text
        assert resp.json()["errors"] == 1
        assert len(seen) == 2
        assert await _stored_quicklooks() == []

    async def test_an_import_rolled_back_after_its_items_leaves_no_images(
        self, client, admin_auth_header, monkeypatch
    ) -> None:
        _install_cog_info(monkeypatch, _TITILER_INFO)
        seen = _titiler(monkeypatch)
        with (
            patch(
                "app.modules.catalog.sources.stac_router.audit_emit",
                AsyncMock(side_effect=RuntimeError("audit down")),
            ),
            pytest.raises(RuntimeError, match="audit down"),
        ):
            await _import(
                client, admin_auth_header, "https://cogs.example.com/rolled.tif"
            )
        assert len(seen) == 2
        assert await _stored_quicklooks() == []


async def test_a_cancelled_batch_deletes_what_it_already_stored(
    client, monkeypatch
) -> None:
    """One draw finished, one still reading: cancelling the batch keeps neither."""
    released = asyncio.Event()

    async def _one_quick_one_stuck(request: httpx.Request) -> httpx.Response:
        if "bidx" in request.url.params:
            await released.wait()
        size = int(request.url.params["max_size"])
        return httpx.Response(200, content=_PNG[size])

    _titiler(monkeypatch, _one_quick_one_stuck)
    batch = asyncio.ensure_future(
        remote_quicklook.draw_remote_quicklooks(
            {
                uuid.uuid4(): ("https://cogs.example.com/a.tif", {"band_count": 1}),
                uuid.uuid4(): ("https://cogs.example.com/b.tif", {"band_count": 3}),
            }
        )
    )
    for _ in range(100):
        if len(await _stored_quicklooks()) == 2:
            break
        await asyncio.sleep(0.02)
    assert len(await _stored_quicklooks()) == 2
    batch.cancel()
    with pytest.raises(asyncio.CancelledError):
        await batch
    assert await _stored_quicklooks() == []


class TestRefresh:
    async def test_an_existing_remote_cog_gets_its_thumbnail_on_refresh(
        self, client, admin_auth_header, test_db_session, stac_transport, monkeypatch
    ) -> None:
        """An unmoved asset with no quicklook is drawn from its stored description."""
        install, _ = stac_transport
        install({_ITEM: (200, _item_doc()), _ASSET: (206, None)})
        seen = _titiler(monkeypatch)
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(test_db_session, created_by=admin_id)

        await _execute(
            test_db_session, await _dispatch(client, admin_auth_header, dataset.id)
        )

        assert (await _run_for(dataset.id)).status == "succeeded"
        assert len(seen) == 2
        raster = await _raster_asset(dataset.id)
        assert await get_storage().get(raster.quicklook_256_uri) == _PNG[256]
        assert await get_storage().get(raster.quicklook_512_uri) == _PNG[512]
        item = await client.get(f"/stac/items/{dataset.id}", headers=admin_auth_header)
        assert {"thumbnail", "overview"} <= set(item.json()["assets"])

    async def test_an_unchanged_asset_with_a_quicklook_is_not_drawn_again(
        self, client, admin_auth_header, test_db_session, stac_transport, monkeypatch
    ) -> None:
        install, _ = stac_transport
        install({_ITEM: (200, _item_doc()), _ASSET: (206, None)})
        seen = _titiler(monkeypatch)
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(test_db_session, created_by=admin_id)
        await test_db_session.execute(
            update(RasterAsset)
            .where(RasterAsset.dataset_id == dataset.id)
            .values(
                quicklook_256_uri=f"rasters/{dataset.id}/q/quicklook_256.png",
                quicklook_512_uri=f"rasters/{dataset.id}/q/quicklook_512.png",
            )
        )
        await test_db_session.commit()

        await _execute(
            test_db_session, await _dispatch(client, admin_auth_header, dataset.id)
        )

        assert (await _run_for(dataset.id)).status == "succeeded"
        assert seen == []
        raster = await _raster_asset(dataset.id)
        assert raster.quicklook_256_uri == f"rasters/{dataset.id}/q/quicklook_256.png"

    async def test_a_moved_asset_is_redrawn_and_the_old_images_removed(
        self,
        client,
        admin_auth_header,
        test_db_session,
        stac_transport,
        cog_info,
        monkeypatch,
    ) -> None:
        install, _ = stac_transport
        install(
            {
                _ITEM: (200, _item_doc(asset_href=_MOVED_ASSET)),
                _MOVED_ASSET: (206, None),
            }
        )
        seen = _titiler(monkeypatch)
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(test_db_session, created_by=admin_id)
        _slow_storage(monkeypatch, delete=0.3)
        old = f"rasters/{dataset.id}/old/quicklook_256.png"
        old_512 = f"rasters/{dataset.id}/old/quicklook_512.png"
        await get_storage().put(old, b"\x89PNG\r\n\x1a\nold")
        await get_storage().put(old_512, b"\x89PNG\r\n\x1a\nold")
        await test_db_session.execute(
            update(RasterAsset)
            .where(RasterAsset.dataset_id == dataset.id)
            .values(quicklook_256_uri=old, quicklook_512_uri=old_512)
        )
        await test_db_session.commit()

        with patch("app.processing.embeddings.helpers.defer_embedding", AsyncMock()):
            await _execute(
                test_db_session, await _dispatch(client, admin_auth_header, dataset.id)
            )

        assert (await _run_for(dataset.id)).status == "succeeded"
        # The moved asset's own probe chooses the stretch.
        assert {r.url.params["rescale"] for r in seen} == {"0,4095"}
        raster = await _raster_asset(dataset.id)
        assert raster.quicklook_256_uri != old
        assert await get_storage().get(raster.quicklook_256_uri) == _PNG[256]
        for key in (old, old_512):
            with pytest.raises(FileNotFoundError):
                await get_storage().get(key)

    async def test_a_moved_asset_that_cannot_be_drawn_is_drawn_next_time(
        self,
        client,
        admin_auth_header,
        test_db_session,
        stac_transport,
        cog_info,
        monkeypatch,
    ) -> None:
        """The old images go with the old asset; the next refresh draws the new one."""
        install, _ = stac_transport
        install(
            {
                _ITEM: (200, _item_doc(asset_href=_MOVED_ASSET)),
                _MOVED_ASSET: (206, None),
            }
        )
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(test_db_session, created_by=admin_id)
        old = (
            f"rasters/{dataset.id}/old/quicklook_256.png",
            f"rasters/{dataset.id}/old/quicklook_512.png",
        )
        for key in old:
            await get_storage().put(key, b"\x89PNG\r\n\x1a\nold")
        await test_db_session.execute(
            update(RasterAsset)
            .where(RasterAsset.dataset_id == dataset.id)
            .values(quicklook_256_uri=old[0], quicklook_512_uri=old[1])
        )
        await test_db_session.commit()

        with patch("app.processing.embeddings.helpers.defer_embedding", AsyncMock()):
            await _execute(
                test_db_session, await _dispatch(client, admin_auth_header, dataset.id)
            )

        raster = await _raster_asset(dataset.id)
        assert (raster.quicklook_256_uri, raster.quicklook_512_uri) == (None, None)
        for key in old:
            with pytest.raises(FileNotFoundError):
                await get_storage().get(key)
        item = await client.get(f"/stac/items/{dataset.id}", headers=admin_auth_header)
        assert "thumbnail" not in item.json()["assets"]
        quicklook = await client.get(
            f"/datasets/{dataset.id}/quicklook?size=256", headers=admin_auth_header
        )
        assert quicklook.status_code == 404

        seen = _titiler(monkeypatch)
        await _execute(
            test_db_session, await _dispatch(client, admin_auth_header, dataset.id)
        )
        assert len(seen) == 2
        raster = await _raster_asset(dataset.id)
        assert await get_storage().get(raster.quicklook_256_uri) == _PNG[256]
        item = await client.get(f"/stac/items/{dataset.id}", headers=admin_auth_header)
        assert {"thumbnail", "overview"} <= set(item.json()["assets"])

    async def test_a_refresh_awaits_a_slow_write(
        self, client, admin_auth_header, test_db_session, stac_transport, monkeypatch
    ) -> None:
        install, _ = stac_transport
        install({_ITEM: (200, _item_doc()), _ASSET: (206, None)})
        _titiler(monkeypatch)
        monkeypatch.setattr(remote_quicklook, "DRAW_BUDGET_S", 0.2)
        _slow_storage(monkeypatch, put=0.4)
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(test_db_session, created_by=admin_id)

        await _execute(
            test_db_session, await _dispatch(client, admin_auth_header, dataset.id)
        )

        raster = await _raster_asset(dataset.id)
        assert await get_storage().get(raster.quicklook_256_uri) == _PNG[256]

    async def test_a_credentialed_refresh_never_hands_its_secret_to_the_draw(
        self,
        client,
        admin_auth_header,
        test_db_session,
        stac_transport,
        credential_backend,
        monkeypatch,
    ) -> None:
        """The catalog credential reaches no Titiler read, stored key or log line."""
        install, _ = stac_transport
        install({_ITEM: (200, _item_doc()), _ASSET: (206, None)})
        seen = _titiler(monkeypatch)
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(test_db_session, created_by=admin_id)
        secret = "sentinel-" + uuid.uuid4().hex

        payload, ref = await _dispatch_with_credential(
            client,
            admin_auth_header,
            dataset.id,
            {"method": "header", "header_name": "X-Api-Key", "header_value": secret},
        )
        with structlog.testing.capture_logs() as logs:
            await _execute_with_credential(test_db_session, payload, ref)

        assert len(seen) == 2
        for request in seen:
            assert secret not in str(request.url)
            assert secret not in str(request.headers)
        raster = await _raster_asset(dataset.id)
        assert raster.quicklook_256_uri is not None
        assert secret not in raster.quicklook_256_uri + raster.quicklook_512_uri
        assert not any(secret in str(entry) for entry in logs)

    async def test_a_failed_draw_does_not_fail_the_refresh(
        self, client, admin_auth_header, test_db_session, stac_transport
    ) -> None:
        """The suite's default Titiler answers 503, so the draw fails here."""
        install, _ = stac_transport
        install({_ITEM: (200, _item_doc()), _ASSET: (206, None)})
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(test_db_session, created_by=admin_id)

        with structlog.testing.capture_logs() as logs:
            await _execute(
                test_db_session, await _dispatch(client, admin_auth_header, dataset.id)
            )

        run = await _run_for(dataset.id)
        assert (run.status, run.error_code) == ("succeeded", None)
        raster = await _raster_asset(dataset.id)
        assert raster.quicklook_256_uri is None
        failures = [e for e in logs if e["event"] == "remote_quicklook_not_drawn"]
        assert [e["reason"] for e in failures] == ["titiler_status"]
