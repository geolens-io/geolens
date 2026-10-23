"""A service token is never sent to a plain http address.

Every door that takes a service credential refuses a bearer token bound for an
http URL with a coded 422 before any request, and the sites that put an ArcGIS
token on the wire refuse it again.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import AsyncClient

from app.modules.catalog.sources.adapters.arcgis import read_arcgis_json
from app.modules.catalog.sources.preview import build_gdal_source
from app.modules.catalog.sources.schemas import ProbeResponse
from app.platform.jobs.models import IngestJob
from app.platform.service_auth import (
    TOKEN_OVER_HTTP_CODE,
    TOKEN_OVER_HTTP_POLICY,
    TokenOverHttpError,
    refuse_token_over_http,
)
from app.processing.ingest import arcgis_errors
from tests.factories import create_dataset, get_user_id
from tests.test_import_token_lease_1676 import _reupload_harness
from tests.test_service_auth_contract_1746 import _wfs_reupload_job
from tests.test_service_refresh_1220 import (  # noqa: F401
    _dispatch_harness,
    _service_dataset,
    credential_backend,
)

pytestmark = pytest.mark.anyio

_HTTP_ARCGIS = "http://services.example.test/rest/services/Parcels/FeatureServer"
_HTTP_WFS = "http://services.example.test/geoserver/wfs"


def _token() -> str:
    return "tok" + uuid.uuid4().hex


def _assert_refused(resp, token: str) -> None:
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == {
        "code": TOKEN_OVER_HTTP_CODE,
        "message": TOKEN_OVER_HTTP_POLICY,
        "field": "url",
    }
    assert token not in resp.text


@pytest.mark.parametrize(
    ("url", "token", "refused"),
    [
        ("http://h.test/x", "t", True),
        ("HTTP://h.test/x", "t", True),
        ("ftp://h.test/x", "t", True),
        ("https://h.test/x", "t", False),
        ("HTTPS://h.test/x", "t", False),
        ("http://h.test/x", None, False),
        ("http://h.test/x", "", False),
    ],
)
def test_only_https_takes_a_token(url, token, refused):
    if refused:
        with pytest.raises(TokenOverHttpError):
            refuse_token_over_http(url, token)
    else:
        refuse_token_over_http(url, token)


class TestTheDoors:
    async def test_probe(self, client: AsyncClient, admin_auth_header: dict):
        token = _token()
        detect = AsyncMock(
            return_value=ProbeResponse(service_type="WFS", url=_HTTP_WFS, layers=[])
        )
        with (
            patch(
                "app.modules.catalog.sources.router.validate_url_for_ssrf",
                new_callable=AsyncMock,
            ),
            patch("app.modules.catalog.sources.router.detect_service_type", detect),
        ):
            resp = await client.post(
                "/services/probe",
                json={"url": _HTTP_ARCGIS, "token": token},
                headers=admin_auth_header,
            )

        _assert_refused(resp, token)
        detect.assert_not_awaited()

    @pytest.mark.parametrize(
        ("service_type", "url"),
        [("ArcGIS FeatureServer", _HTTP_ARCGIS), ("WFS 2.0.0", _HTTP_WFS)],
    )
    async def test_preview(
        self, client: AsyncClient, admin_auth_header: dict, service_type, url
    ):
        token = _token()
        preview = AsyncMock()
        arcgis_preview = AsyncMock()
        with (
            patch(
                "app.modules.catalog.sources.router.validate_url_for_ssrf",
                new_callable=AsyncMock,
            ),
            patch("app.modules.catalog.sources.router.run_service_preview", preview),
            patch(
                "app.modules.catalog.sources.router.fetch_arcgis_layer_preview",
                arcgis_preview,
            ),
        ):
            resp = await client.post(
                "/services/preview",
                json={
                    "url": url,
                    "service_type": service_type,
                    "layer_name": "parcels",
                    "layer_id": 0,
                    "auth": {"method": "bearer", "token": token},
                },
                headers=admin_auth_header,
            )

        _assert_refused(resp, token)
        preview.assert_not_awaited()
        arcgis_preview.assert_not_awaited()

    async def test_import_commit(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        token = _token()
        admin_id = await get_user_id(test_db_session, "admin")
        job = IngestJob(
            source_filename="Parcels",
            source_url=_HTTP_ARCGIS,
            source_layer="parcels",
            created_by=admin_id,
            status="pending",
            user_metadata={"service_type": "ArcGIS FeatureServer", "layer_id": 0},
        )
        test_db_session.add(job)
        await test_db_session.commit()
        task = AsyncMock()
        with (
            patch("app.platform.security.validate_url_for_ssrf", new=AsyncMock()),
            patch("app.processing.ingest.tasks.ingest_service") as ingest_service,
        ):
            ingest_service.defer_async = task
            ingest_service.configure = MagicMock(return_value=ingest_service)
            resp = await client.post(
                f"/ingest/commit/{job.id}",
                json={"title": "Parcels", "token": token},
                headers=admin_auth_header,
            )

        _assert_refused(resp, token)
        task.assert_not_awaited()
        await test_db_session.refresh(job)
        assert job.status == "pending"

    async def test_reupload_preview(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        token = _token()
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(
            test_db_session, created_by=admin_id, source_url=_HTTP_ARCGIS
        )
        preview = AsyncMock()
        with patch(
            "app.modules.catalog.datasets.api.router_reupload.run_service_preview",
            preview,
        ):
            resp = await client.post(
                f"/datasets/{dataset.id}/reupload/service/preview",
                json={
                    "url": _HTTP_ARCGIS,
                    "service_type": "ArcGIS FeatureServer",
                    "layer_name": "parcels",
                    "layer_id": 0,
                    "token": token,
                },
                headers=admin_auth_header,
            )

        _assert_refused(resp, token)
        preview.assert_not_awaited()

    async def test_reupload_commit(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        token = _token()
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(
            test_db_session, created_by=admin_id, source_url=_HTTP_ARCGIS
        )
        job = await _wfs_reupload_job(
            test_db_session,
            dataset_id=dataset.id,
            created_by=admin_id,
            service_type="ArcGIS FeatureServer",
            source_url=_HTTP_ARCGIS,
        )
        async with _reupload_harness() as task:
            resp = await client.post(
                f"/datasets/{dataset.id}/reupload/{job.id}/commit",
                json={"token": token},
                headers=admin_auth_header,
            )

        _assert_refused(resp, token)
        task.defer_async.assert_not_awaited()

    async def test_refresh(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        credential_backend,  # noqa: F811
    ):
        token = _token()
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(
            test_db_session,
            created_by=admin_id,
            source_format="arcgis_featureserver",
            base_url=_HTTP_ARCGIS,
            layer_id=0,
        )
        async with _dispatch_harness() as task:
            resp = await client.post(
                f"/datasets/{dataset.id}/refresh",
                json={"auth": {"method": "bearer", "token": token}},
                headers=admin_auth_header,
            )

        _assert_refused(resp, token)
        task.defer_async.assert_not_awaited()
        assert credential_backend.puts == []


class TestTheSitesThatSendAToken:
    def test_the_gdal_source_builder(self):
        with pytest.raises(TokenOverHttpError):
            build_gdal_source(
                "ArcGIS FeatureServer", _HTTP_ARCGIS, "parcels", 0, token="t"
            )
        source, _ = build_gdal_source("ArcGIS FeatureServer", _HTTP_ARCGIS, "p", 0)
        assert source.startswith("ESRIJSON:http://")

    @pytest.mark.parametrize("version", [None, 10.0])
    async def test_the_adapter_read(self, version):
        sent: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            sent.append(request)
            return httpx.Response(200, json={})

        def build_url(query_token: str | None) -> str:
            suffix = f"&token={query_token}" if query_token else ""
            return f"{_HTTP_ARCGIS}?f=json{suffix}"

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(TokenOverHttpError):
                await read_arcgis_json(
                    client, build_url, _token(), current_version=version
                )

        assert sent == []

    async def test_the_import_error_rerun(self, monkeypatch):
        read = AsyncMock()
        monkeypatch.setattr(arcgis_errors, "bounded_probe_read", read)
        token = _token()

        detail = await arcgis_errors.fetch_arcgis_error_detail(
            f"ESRIJSON:{_HTTP_ARCGIS}/0/query?f=json&token={token}", token
        )

        assert detail is None
        read.assert_not_awaited()
