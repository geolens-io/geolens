"""A service credential is never sent to a plain http address the operator didn't list.

Every door that takes a service credential refuses one bound for an http URL
with a coded 422 before any request, and the sites that put a credential on
the wire refuse it again. ``SERVICE_CREDENTIALS_ALLOW_HTTP_HOSTS`` exempts the
hosts an operator lists.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.core.service_tokens import CredentialMethod, ServiceCredential
from app.modules.catalog.sources.adapters.arcgis import read_arcgis_json
from app.modules.catalog.sources.preview import build_gdal_source, run_service_preview
from app.modules.catalog.sources.schemas import ProbeResponse
from app.platform.jobs.models import IngestJob
from app.platform.refresh.execution import execute_admitted_refresh
from app.platform.refresh.models import DatasetRefreshRun
from app.platform.service_auth import (
    CREDENTIAL_OVER_HTTP_CODE,
    CREDENTIAL_OVER_HTTP_POLICY,
    CredentialOverHttpError,
    credential_over_http_or_422,
    refuse_credential_over_http,
)
from app.processing.ingest import arcgis_errors
from app.processing.ingest.ogr import run_ogr2ogr_service
from tests.factories import create_dataset, get_user_id
from tests.test_import_token_lease_1676 import _reupload_harness
from tests.test_scheduled_refresh_execution import _scheduled_run
from tests.test_service_auth_contract_1746 import _wfs_reupload_job
from tests.test_service_refresh_1220 import (  # noqa: F401
    _dispatch_harness,
    _service_dataset,
    credential_backend,
)
from tests.test_stac_refresh_1266 import _dispatch_harness as _stac_dispatch_harness
from tests.test_stac_refresh_1266 import _stac_dataset

pytestmark = pytest.mark.anyio

_HTTP_ARCGIS = "http://services.example.test/rest/services/Parcels/FeatureServer"
_HTTP_WFS = "http://services.example.test/geoserver/wfs"
_HTTP_STAC = "http://stac.example.test/stac"


def _token() -> str:
    return "tok" + uuid.uuid4().hex


def _basic() -> dict:
    return {"method": "basic", "username": "u", "password": uuid.uuid4().hex}


def _header() -> dict:
    return {"method": "header", "header_name": "X-Api-Key", "header_value": _token()}


def _assert_refused(resp, secret: str) -> None:
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == {
        "code": CREDENTIAL_OVER_HTTP_CODE,
        "message": CREDENTIAL_OVER_HTTP_POLICY,
        "field": "url",
    }
    assert secret not in resp.text


@pytest.fixture
def allow_http_hosts(monkeypatch):
    def allow(value: str) -> None:
        monkeypatch.setattr(settings, "service_credentials_allow_http_hosts", value)

    return allow


class TestThePolicy:
    @pytest.mark.parametrize(
        ("url", "credential", "refused"),
        [
            ("http://h.test/x", "t", True),
            ("HTTP://h.test/x", "t", True),
            ("ftp://h.test/x", "t", True),
            ("https://h.test/x", "t", False),
            ("HTTPS://h.test/x", "t", False),
            ("http://h.test/x", None, False),
            ("http://h.test/x", "", False),
            (None, "t", False),
            ("", "t", False),
            (
                "http://h.test/x",
                ServiceCredential(method=CredentialMethod.BASIC, password="p"),
                True,
            ),
            ("http://h.test/x", ServiceCredential(method=CredentialMethod.NONE), False),
        ],
    )
    def test_only_https_takes_a_credential(self, url, credential, refused):
        if refused:
            with pytest.raises(CredentialOverHttpError):
                refuse_credential_over_http(url, credential)
        else:
            refuse_credential_over_http(url, credential)

    @pytest.mark.parametrize(
        ("allowed", "url", "refused"),
        [
            ("gis.internal", "http://gis.internal:8080/wfs", False),
            ("GIS.internal", "http://gis.internal/wfs", False),
            ("gis.internal:8080", "http://gis.internal:8080/wfs", False),
            ("gis.internal:8080", "http://gis.internal/wfs", True),
            ("other.internal, gis.internal:80", "http://gis.internal/wfs", False),
            ("gis.internal", "http://gis.internal.evil.test/wfs", True),
            ("gis.internal", "ftp://gis.internal/wfs", True),
            ("", "http://gis.internal/wfs", True),
            ("b\u00fccher.test", "http://xn--bcher-kva.test/wfs", False),
            ("xn--bcher-kva.test", "http://b\u00fccher.test/wfs", False),
            ("[0:0::1]:8080", "http://[::1]:8080/wfs", False),
            ("[::1]", "http://[0:0:0:0:0:0:0:1]/wfs", False),
            ("[::1]:8080", "http://[::1]:8081/wfs", True),
        ],
    )
    def test_a_listed_host_may_take_one_over_http(
        self, allow_http_hosts, allowed, url, refused
    ):
        allow_http_hosts(allowed)
        if refused:
            with pytest.raises(CredentialOverHttpError):
                refuse_credential_over_http(url, "t")
        else:
            refuse_credential_over_http(url, "t")

    def test_a_door_with_no_url_never_reads_as_plain_http(self):
        credential_over_http_or_422(None, "t")
        credential_over_http_or_422("", "t")

    @pytest.mark.parametrize(
        "value",
        [
            "http://gis.internal",
            "gis.internal/wfs",
            "*.internal",
            "u@h.test",
            "x y",
            "x;y",
            "x\\y",
            "x%2ey",
            ".x",
            "x..",
            "x:",
            "x.",
            "::1",
            "[fe80::1%eth0]",
            "gis.internal:99999",
        ],
    )
    def test_the_setting_takes_hosts_only(self, value):
        from app.core.config import Settings

        with pytest.raises(ValueError, match="SERVICE_CREDENTIALS_ALLOW_HTTP_HOSTS"):
            Settings.validate_service_credentials_allow_http_hosts(value)


class TestTheDoors:
    @pytest.mark.parametrize(
        "auth", [{"method": "bearer", "token": _token()}, _basic(), _header()]
    )
    async def test_probe(self, client: AsyncClient, admin_auth_header: dict, auth):
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
                json={"url": _HTTP_WFS, "auth": auth},
                headers=admin_auth_header,
            )

        _assert_refused(resp, auth.get("token") or auth.get("password") or "-")
        detect.assert_not_awaited()

    async def test_probe_of_a_listed_host_goes_ahead(
        self, client: AsyncClient, admin_auth_header: dict, allow_http_hosts
    ):
        allow_http_hosts("services.example.test")
        detect = AsyncMock(
            return_value=ProbeResponse(service_type="WFS", url=_HTTP_WFS, layers=[])
        )
        with (
            patch(
                "app.modules.catalog.sources.router.validate_url_for_ssrf",
                new_callable=AsyncMock,
            ),
            patch("app.modules.catalog.sources.router.detect_service_type", detect),
            patch(
                "app.modules.catalog.sources.router.assert_endpoints_stay_on_origin",
                new_callable=AsyncMock,
            ),
        ):
            resp = await client.post(
                "/services/probe",
                json={"url": _HTTP_WFS, "auth": _basic()},
                headers=admin_auth_header,
            )

        assert resp.status_code == 200, resp.text
        detect.assert_awaited_once()

    @pytest.mark.parametrize(
        ("service_type", "url", "auth"),
        [
            (
                "ArcGIS FeatureServer",
                _HTTP_ARCGIS,
                {"method": "bearer", "token": _token()},
            ),
            ("WFS 2.0.0", _HTTP_WFS, {"method": "bearer", "token": _token()}),
            ("WFS 2.0.0", _HTTP_WFS, _basic()),
            ("WFS 2.0.0", _HTTP_WFS, _header()),
        ],
    )
    async def test_preview(
        self, client: AsyncClient, admin_auth_header: dict, service_type, url, auth
    ):
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
                    "auth": auth,
                },
                headers=admin_auth_header,
            )

        _assert_refused(resp, auth.get("token") or auth.get("password") or "-")
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
        auth = _basic()
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(
            test_db_session, created_by=admin_id, base_url=_HTTP_WFS
        )
        async with _dispatch_harness() as task:
            resp = await client.post(
                f"/datasets/{dataset.id}/refresh",
                json={"auth": auth},
                headers=admin_auth_header,
            )

        _assert_refused(resp, auth["password"])
        task.defer_async.assert_not_awaited()
        assert credential_backend.puts == []

    async def test_stac_refresh(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        credential_backend,  # noqa: F811
    ):
        token = _token()
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(
            test_db_session,
            created_by=admin_id,
            url=_HTTP_STAC,
            item_href=f"{_HTTP_STAC}/collections/scenes/items/scene-1",
        )
        async with _stac_dispatch_harness() as task:
            resp = await client.post(
                f"/datasets/{dataset.id}/refresh",
                json={"auth": {"method": "bearer", "token": token}},
                headers=admin_auth_header,
            )

        _assert_refused(resp, token)
        task.defer_async.assert_not_awaited()
        assert credential_backend.puts == []

    @pytest.mark.parametrize(
        ("path", "module", "extra"),
        [
            ("/services/stac/connect", "stac_router", {}),
            ("/services/stac/collections", "stac_router", {}),
            ("/services/stac/search", "stac_router", {}),
            (
                "/services/stac/asset-sizes",
                "stac_asset_size_router",
                {"assets": [{"id": "a", "href": f"{_HTTP_STAC}/a.tif"}]},
            ),
        ],
    )
    async def test_stac(
        self, client: AsyncClient, admin_auth_header: dict, path, module, extra
    ):
        token = _token()
        ssrf = AsyncMock()
        with patch(f"app.modules.catalog.sources.{module}.validate_url_for_ssrf", ssrf):
            resp = await client.post(
                path,
                json={
                    "url": _HTTP_STAC,
                    "auth": {"method": "bearer", "token": token},
                    **extra,
                },
                headers=admin_auth_header,
            )

        _assert_refused(resp, token)
        ssrf.assert_not_awaited()


class TestTheSitesThatSendACredential:
    def test_the_gdal_source_builder(self):
        with pytest.raises(CredentialOverHttpError):
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
            with pytest.raises(CredentialOverHttpError):
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

    @pytest.mark.parametrize(
        ("source", "service_type"),
        [(f"WFS:{_HTTP_WFS}", "wfs"), (f"OAPIF:{_HTTP_WFS}", "ogcapi_features")],
    )
    async def test_the_import_subprocess(self, monkeypatch, source, service_type):
        spawn = AsyncMock()
        monkeypatch.setattr("asyncio.create_subprocess_exec", spawn)
        with pytest.raises(CredentialOverHttpError):
            await run_ogr2ogr_service(
                source,
                "parcels",
                "never_created",
                "PG:dbname=never_opened",
                service_type,
                token=f"X-Api-Key: {_token()}",
                timeout=5.0,
                schema="data",
            )
        spawn.assert_not_awaited()

    async def test_the_preview_subprocess(self, monkeypatch):
        spawn = AsyncMock()
        monkeypatch.setattr("asyncio.create_subprocess_exec", spawn)
        credential = ServiceCredential(
            method=CredentialMethod.BASIC,
            service_format="wfs",
            username="u",
            password=uuid.uuid4().hex,
        )
        with pytest.raises(CredentialOverHttpError):
            await run_service_preview(
                f"WFS:{_HTTP_WFS}", "parcels", credential=credential
            )
        spawn.assert_not_awaited()

    async def test_a_scheduled_refresh(self, test_db_session):
        run, job = await _scheduled_run(test_db_session)
        run.credential_reference = "credential-1"
        job.source_url = _HTTP_WFS
        await test_db_session.commit()
        run_id = run.id

        @asynccontextmanager
        async def session_factory():
            yield test_db_session

        async def credential_resolver(_reference: str, _version: str | None) -> str:
            return f"X-Api-Key: {_token()}"

        with (
            patch("app.core.db.async_session", session_factory),
            patch("app.platform.extensions.get_catalog_port") as catalog_port,
        ):
            result = await execute_admitted_refresh(
                job.id,
                str(run.execution_key),
                credential_resolver=credential_resolver,
            )

        assert result.status == "rejected"
        catalog_port.assert_not_called()
        test_db_session.expire_all()
        persisted = await test_db_session.get(DatasetRefreshRun, run_id)
        assert persisted.error_code == CREDENTIAL_OVER_HTTP_CODE
