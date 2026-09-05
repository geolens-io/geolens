"""Integration tests for services probe and preview endpoints.

Tests cover: probe success/failure, preview success/failure, SSRF validation,
auth requirements, and error handling for various external service responses.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.modules.audit.models import AuditLog
from app.modules.catalog.sources.probe import ServiceNotRecognized
from app.modules.catalog.sources.schemas import LayerInfo, ProbeResponse
from app.platform.security import SSRFError, SSRFResolutionError


async def _preview_audit_rows(session, url: str) -> list[AuditLog]:
    """This test's `preview_service_layer` audit rows, oldest first.

    Scoped to the previewed URL for the same reason as `_probe_audit_rows`.
    """
    result = await session.execute(
        select(AuditLog)
        .where(
            AuditLog.action == "preview_service_layer",
            AuditLog.details["url"].astext == url,
        )
        .order_by(AuditLog.created_at)
    )
    return list(result.scalars().all())


async def _probe_audit_rows(session, url: str) -> list[AuditLog]:
    """This test's `probe_service` audit rows, oldest first.

    Scoped to the probed URL: one database is shared across every test on an
    xdist worker, so a query on the action alone would read rows written by
    tests that ran before this one.
    """
    result = await session.execute(
        select(AuditLog)
        .where(
            AuditLog.action == "probe_service",
            AuditLog.details["url"].astext == url,
        )
        .order_by(AuditLog.created_at)
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_validate_ssrf():
    """Patch SSRF validation to allow all URLs by default."""
    with patch("app.modules.catalog.sources.router.validate_url_for_ssrf") as mock:
        yield mock


@pytest.fixture
def mock_detect_service():
    """Patch detect_service_type to return a canned WFS response."""
    with patch(
        "app.modules.catalog.sources.router.detect_service_type", new_callable=AsyncMock
    ) as mock:
        mock.return_value = ProbeResponse(
            service_type="WFS 2.0.0",
            url="https://example.com/wfs",
            layers=[
                LayerInfo(
                    name="buildings",
                    title="Buildings Layer",
                    geometry_type="MultiPolygon",
                    feature_count=1000,
                    layer_id="buildings",
                ),
                LayerInfo(
                    name="roads",
                    title="Roads Layer",
                    geometry_type="MultiLineString",
                    feature_count=500,
                    layer_id="roads",
                ),
            ],
        )
        yield mock


@pytest.fixture
def mock_build_gdal_source():
    """Patch build_gdal_source to return a fake GDAL source string."""
    with patch("app.modules.catalog.sources.router.build_gdal_source") as mock:
        mock.return_value = ("WFS:https://example.com/wfs", "buildings")
        yield mock


@pytest.fixture
def mock_run_preview():
    """Patch run_service_preview to return canned preview data."""
    with patch(
        "app.modules.catalog.sources.router.run_service_preview", new_callable=AsyncMock
    ) as mock:
        mock.return_value = {
            "srid": 4326,
            "geometry_type": "MultiPolygon",
            "layer_name": "buildings",
            "feature_count": 1000,
            "columns": [
                {"name": "id", "type": "Integer"},
                {"name": "name", "type": "String"},
            ],
            "sample_rows": [
                {"id": 1, "name": "Building A"},
                {"id": 2, "name": "Building B"},
            ],
        }
        yield mock


@pytest.fixture
def mock_fetch_arcgis_preview():
    """Patch fetch_arcgis_layer_preview (the metadata-driven ArcGIS path)."""
    with patch(
        "app.modules.catalog.sources.router.fetch_arcgis_layer_preview",
        new_callable=AsyncMock,
    ) as mock:
        mock.return_value = {
            "srid": 4326,
            "geometry_type": "Point",
            "layer_name": "Bulletins",
            "feature_count": None,
            "columns": [
                {"name": "OBJECTID", "type": "Integer64"},
                {"name": "title", "type": "String"},
            ],
            "sample_rows": [
                {"OBJECTID": 1, "title": "Bulletin A"},
                {"OBJECTID": 2, "title": "Bulletin B"},
            ],
        }
        yield mock


# ---------------------------------------------------------------------------
# Probe endpoint
# ---------------------------------------------------------------------------


class TestProbeEndpoint:
    async def test_probe_success(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_validate_ssrf,
        mock_detect_service,
    ):
        """POST /services/probe/ with valid URL returns service info."""
        resp = await client.post(
            "/services/probe/",
            json={"url": "https://example.com/wfs"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["service_type"] == "WFS 2.0.0"
        assert len(data["layers"]) == 2
        assert data["layers"][0]["name"] == "buildings"
        assert data["layers"][1]["name"] == "roads"

    async def test_probe_with_token(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_validate_ssrf,
        mock_detect_service,
    ):
        """POST /services/probe/ with optional auth token is accepted."""
        resp = await client.post(
            "/services/probe/",
            json={"url": "https://example.com/wfs", "token": "my-secret-token"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200

    async def test_probe_unauthenticated(self, client: AsyncClient):
        """POST /services/probe/ without auth returns 401."""
        resp = await client.post(
            "/services/probe/",
            json={"url": "https://example.com/wfs"},
        )
        assert resp.status_code == 401

    async def test_probe_viewer_forbidden(
        self, client: AsyncClient, viewer_auth_header: dict
    ):
        """POST /services/probe/ as viewer returns 403."""
        resp = await client.post(
            "/services/probe/",
            json={"url": "https://example.com/wfs"},
            headers=viewer_auth_header,
        )
        assert resp.status_code == 403

    async def test_probe_ssrf_blocked(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """POST /services/probe/ with private IP is rejected (400)."""
        with patch(
            "app.modules.catalog.sources.router.validate_url_for_ssrf",
            side_effect=SSRFError(
                "URLs targeting private/internal networks are not allowed"
            ),
        ):
            resp = await client.post(
                "/services/probe/",
                json={"url": "http://192.168.1.1/wfs"},
                headers=admin_auth_header,
            )
            assert resp.status_code == 400
            assert "private" in resp.json()["detail"].lower()

    async def test_probe_ssrf_localhost(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """POST /services/probe/ targeting localhost is rejected."""
        with patch(
            "app.modules.catalog.sources.router.validate_url_for_ssrf",
            side_effect=SSRFError(
                "URLs targeting private/internal networks are not allowed"
            ),
        ):
            resp = await client.post(
                "/services/probe/",
                json={"url": "http://127.0.0.1:8080/wfs"},
                headers=admin_auth_header,
            )
            assert resp.status_code == 400

    async def test_probe_mid_probe_redirect_ssrf_does_not_echo_the_host(
        self, client: AsyncClient, admin_auth_header: dict, mock_validate_ssrf
    ) -> None:
        """fix(#1770 round 49 P3, `sources/router.py` mid-probe `SSRFError`).

        `SSRFResolutionError` (`platform/security.py`) interpolates the raw,
        unresolved hostname into its own message -- every other `SSRFError`
        raise site is a fixed policy string. Mid-probe (this except clause,
        not the door-level one at Step 1), that hostname is chosen by the
        SERVICE via its own redirect `Location` header, not by the caller,
        so reflecting it into the 400 body or the persisted audit reason is
        a provider-controlled reflection this codebase refuses everywhere
        else a document-chosen href/host could reach a response.
        """
        from unittest.mock import patch

        redirect_host = "attacker-chosen-redirect-target.invalid"
        with patch(
            "app.modules.catalog.sources.router.detect_service_type",
            side_effect=SSRFResolutionError(
                f"Could not resolve hostname: {redirect_host}"
            ),
        ):
            resp = await client.post(
                "/services/probe/",
                json={"url": "https://example.com/wfs"},
                headers=admin_auth_header,
            )

        assert resp.status_code == 400
        assert redirect_host not in resp.text

    async def test_probe_header_auth_ssrf_is_not_a_credential_refusal(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_validate_ssrf,
        test_db_session,
    ) -> None:
        """fix(#1858, `sources/probe.py::_header_auth_probe`).

        `SSRFError` subclasses `ValueError`, and the two header-auth adapters
        catch only httpx and endpoint-check failures, so a refused redirect
        hop reached `_header_auth_probe`'s `except ValueError` and was
        recorded as a credential refusal. This probe carries NO credential at
        all, so the old answer -- 422 `invalid_service_token` -- was untrue
        twice over, and `SSRFResolutionError`'s message put the
        redirect-chosen hostname into both the response body and the
        persisted audit reason, which is what the fixed `ssrf_policy_message`
        one clause below exists to prevent.
        """
        redirect_host = "sec6-redirect-chosen-target.invalid"
        probe_url = "https://sec6-header-auth.example.com/service"
        with (
            patch(
                "app.modules.catalog.sources.probe.probe_ogcapi",
                new_callable=AsyncMock,
                side_effect=SSRFResolutionError(
                    f"Could not resolve hostname: {redirect_host}"
                ),
            ),
            patch(
                "app.modules.catalog.sources.probe.probe_wfs",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.modules.catalog.sources.probe.probe_arcgis_service",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            resp = await client.post(
                "/services/probe/",
                json={"url": probe_url},
                headers=admin_auth_header,
            )

        assert resp.status_code == 400
        assert resp.json()["detail"] == "redirect target refused by SSRF policy"
        assert redirect_host not in resp.text

        rows = await _probe_audit_rows(test_db_session, probe_url)
        assert [row.details["result"] for row in rows] == ["ssrf_blocked"]
        assert redirect_host not in json.dumps(rows[0].details)

    async def test_probe_ogcapi_collections_ssrf_reaches_the_door(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_validate_ssrf,
        test_db_session,
    ) -> None:
        """fix(#1858 audit P2-2, `adapters/ogcapi.py` `/collections` step).

        That clause caught `SSRFError` and returned None, which is
        `probe_ogcapi` saying "not an OGC API service". The probe then tried
        WFS and ArcGIS against the same refused origin and the door answered
        `ServiceNotRecognized`, so a blocked redirect on the collections
        listing was indistinguishable from a URL that is simply not a
        service. The clause ends the adapter either way, so re-raising costs
        nothing and is the only truthful answer available.
        """
        redirect_host = "sec6-collections-redirect-target.invalid"
        probe_url = "https://sec6-oapif.example.com/service"
        landing = json.dumps(
            {
                "conformsTo": [
                    "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core"
                ]
            }
        ).encode()

        async def _read(_client, url, **_kwargs):
            if url.endswith("/collections"):
                raise SSRFResolutionError(
                    f"Could not resolve hostname: {redirect_host}"
                )
            return landing, url

        with (
            patch(
                "app.modules.catalog.sources.adapters.ogcapi.bounded_probe_read",
                new=_read,
            ),
            patch(
                "app.modules.catalog.sources.adapters.ogcapi.validate_url_for_ssrf",
                new_callable=AsyncMock,
            ),
            # The two sibling adapters are silenced so this clause is the ONLY
            # thing in the run that can raise `SSRFError`. Without that they
            # reach the network with a hostname that does not resolve, the
            # guard transport raises `SSRFResolutionError` of its own, and the
            # door answers 400 whether or not the clause under test re-raises
            # -- a test that passes on its own counterfactual.
            patch(
                "app.modules.catalog.sources.probe.probe_wfs",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.modules.catalog.sources.probe.probe_arcgis_service",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            resp = await client.post(
                "/services/probe/",
                json={"url": probe_url},
                headers=admin_auth_header,
            )

        assert resp.status_code == 400, resp.text
        assert resp.json()["detail"] == "redirect target refused by SSRF policy"
        assert redirect_host not in resp.text

        rows = await _probe_audit_rows(test_db_session, probe_url)
        assert [row.details["result"] for row in rows] == ["ssrf_blocked"]
        assert redirect_host not in json.dumps(rows[0].details)

    async def test_probe_timeout(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_validate_ssrf,
    ):
        """POST /services/probe/ that times out returns 504."""
        with patch(
            "app.modules.catalog.sources.router.detect_service_type",
            new_callable=AsyncMock,
            side_effect=httpx.TimeoutException("timed out"),
        ):
            resp = await client.post(
                "/services/probe/",
                json={"url": "https://slow-service.example.com/wfs"},
                headers=admin_auth_header,
            )
            assert resp.status_code == 504

    async def test_probe_remote_auth_required(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_validate_ssrf,
    ):
        """POST /services/probe/ where remote returns 401 gives 403."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_request = MagicMock()
        with patch(
            "app.modules.catalog.sources.router.detect_service_type",
            new_callable=AsyncMock,
            side_effect=httpx.HTTPStatusError(
                "Unauthorized", request=mock_request, response=mock_response
            ),
        ):
            resp = await client.post(
                "/services/probe/",
                json={"url": "https://protected.example.com/wfs"},
                headers=admin_auth_header,
            )
            assert resp.status_code == 403
            assert "authentication" in resp.json()["detail"].lower()

    async def test_probe_remote_server_error(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_validate_ssrf,
    ):
        """POST /services/probe/ where remote returns 500 gives 502."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_request = MagicMock()
        with patch(
            "app.modules.catalog.sources.router.detect_service_type",
            new_callable=AsyncMock,
            side_effect=httpx.HTTPStatusError(
                "Server Error", request=mock_request, response=mock_response
            ),
        ):
            resp = await client.post(
                "/services/probe/",
                json={"url": "https://broken.example.com/wfs"},
                headers=admin_auth_header,
            )
            assert resp.status_code == 502

    async def test_probe_unreachable(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_validate_ssrf,
    ):
        """POST /services/probe/ with unreachable host returns 502."""
        with patch(
            "app.modules.catalog.sources.router.detect_service_type",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("Connection refused"),
        ):
            resp = await client.post(
                "/services/probe/",
                json={"url": "https://unreachable.example.com/wfs"},
                headers=admin_auth_header,
            )
            assert resp.status_code == 502

    async def test_probe_unrecognized_service(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_validate_ssrf,
    ):
        """POST /services/probe/ with unrecognized service returns 400."""
        with patch(
            "app.modules.catalog.sources.router.detect_service_type",
            new_callable=AsyncMock,
            side_effect=ServiceNotRecognized(),
        ):
            resp = await client.post(
                "/services/probe/",
                json={"url": "https://not-a-service.example.com/"},
                headers=admin_auth_header,
            )
            assert resp.status_code == 400

    async def test_probe_editor_allowed(
        self,
        client: AsyncClient,
        editor_auth_header: dict,
        mock_validate_ssrf,
        mock_detect_service,
    ):
        """POST /services/probe/ as editor returns 200."""
        resp = await client.post(
            "/services/probe/",
            json={"url": "https://example.com/wfs"},
            headers=editor_auth_header,
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Preview endpoint
# ---------------------------------------------------------------------------


class TestPreviewEndpoint:
    async def test_preview_success(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_validate_ssrf,
        mock_build_gdal_source,
        mock_run_preview,
    ):
        """POST /services/preview/ with valid params returns preview data."""
        resp = await client.post(
            "/services/preview/",
            json={
                "url": "https://example.com/wfs",
                "service_type": "WFS 2.0.0",
                "layer_name": "buildings",
                "layer_title": "Buildings Layer",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert data["source_filename"] == "Buildings Layer"
        assert data["geometry_type"] == "MultiPolygon"
        assert data["crs"] == 4326
        assert data["feature_count"] == 1000
        assert len(data["columns"]) == 2
        assert len(data["sample_rows"]) == 2
        assert data["layer_name"] == "buildings"

    async def test_preview_unauthenticated(self, client: AsyncClient):
        """POST /services/preview/ without auth returns 401."""
        resp = await client.post(
            "/services/preview/",
            json={
                "url": "https://example.com/wfs",
                "service_type": "WFS 2.0.0",
                "layer_name": "buildings",
            },
        )
        assert resp.status_code == 401

    async def test_preview_viewer_forbidden(
        self, client: AsyncClient, viewer_auth_header: dict
    ):
        """POST /services/preview/ as viewer returns 403."""
        resp = await client.post(
            "/services/preview/",
            json={
                "url": "https://example.com/wfs",
                "service_type": "WFS 2.0.0",
                "layer_name": "buildings",
            },
            headers=viewer_auth_header,
        )
        assert resp.status_code == 403

    async def test_preview_ssrf_blocked(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """POST /services/preview/ with private IP is rejected."""
        with patch(
            "app.modules.catalog.sources.router.validate_url_for_ssrf",
            side_effect=SSRFError(
                "URLs targeting private/internal networks are not allowed"
            ),
        ):
            resp = await client.post(
                "/services/preview/",
                json={
                    "url": "http://10.0.0.1/wfs",
                    "service_type": "WFS 2.0.0",
                    "layer_name": "buildings",
                },
                headers=admin_auth_header,
            )
            assert resp.status_code == 400
            assert "private" in resp.json()["detail"].lower()

    async def test_preview_invalid_service_type(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_validate_ssrf,
    ):
        """POST /services/preview/ with unsupported service type returns 400."""
        with patch(
            "app.modules.catalog.sources.router.build_gdal_source",
            side_effect=ValueError("Unsupported service type: FTP"),
        ):
            resp = await client.post(
                "/services/preview/",
                json={
                    "url": "https://example.com/ftp",
                    "service_type": "FTP",
                    "layer_name": "data",
                },
                headers=admin_auth_header,
            )
            assert resp.status_code == 400

    async def test_preview_ogrinfo_failure(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_validate_ssrf,
        mock_build_gdal_source,
    ):
        """POST /services/preview/ when ogrinfo fails returns 502."""
        from app.processing.ingest.ogr import IngestionError

        with patch(
            "app.modules.catalog.sources.router.run_service_preview",
            new_callable=AsyncMock,
            side_effect=IngestionError("ogrinfo failed"),
        ):
            resp = await client.post(
                "/services/preview/",
                json={
                    "url": "https://example.com/wfs",
                    "service_type": "WFS 2.0.0",
                    "layer_name": "broken_layer",
                },
                headers=admin_auth_header,
            )
            assert resp.status_code == 502

    async def test_preview_unexpected_error(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_validate_ssrf,
        mock_build_gdal_source,
    ):
        """POST /services/preview/ with unexpected error returns 500."""
        with patch(
            "app.modules.catalog.sources.router.run_service_preview",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Something broke"),
        ):
            resp = await client.post(
                "/services/preview/",
                json={
                    "url": "https://example.com/wfs",
                    "service_type": "WFS 2.0.0",
                    "layer_name": "buildings",
                },
                headers=admin_auth_header,
            )
            assert resp.status_code == 500

    # -----------------------------------------------------------------
    # fix(#1755 item 9): one test per typed refusal `run_service_preview`
    # and its callees can raise, so `preview_service_layer`'s broad
    # `except Exception` never turns one into a 500 the way it turned
    # `RuntimeError` into one above. Each mocks `run_service_preview`
    # directly (as `test_preview_unexpected_error` and
    # `test_preview_ogrinfo_failure` already do above), bypassing the
    # internal wrapping the classes normally go through, which is exactly
    # what proves the ROUTER's own mapping — not a callee's — is what
    # answers. Counterfactual: with `_preview_refusal_response` deleted (or
    # its branch for the class under test removed), every one of these
    # falls through to `except Exception` and asserts 500, same as
    # `test_preview_unexpected_error`.
    # -----------------------------------------------------------------

    async def test_preview_cross_origin_endpoint_returns_422(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_validate_ssrf,
        mock_build_gdal_source,
    ):
        """A description naming a foreign operation endpoint is a 422, not a 500."""
        from app.platform.service_endpoints import CrossOriginEndpointError

        with patch(
            "app.modules.catalog.sources.router.run_service_preview",
            new_callable=AsyncMock,
            side_effect=CrossOriginEndpointError("https://evil.example.com"),
        ):
            resp = await client.post(
                "/services/preview/",
                json={
                    "url": "https://example.com/wfs",
                    "service_type": "WFS 2.0.0",
                    "layer_name": "buildings",
                    "auth": {"method": "basic", "username": "u", "password": "p"},
                },
                headers=admin_auth_header,
            )
            assert resp.status_code == 422, resp.text
            detail = resp.json()["detail"]
            assert detail["code"] == "cross_origin_endpoint"
            # The service-chosen credential value is never in the body.
            assert "p" != detail["message"]

    async def test_preview_endpoint_check_failed_returns_422(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_validate_ssrf,
        mock_build_gdal_source,
    ):
        """A description that could not be read is a 422, not a 500."""
        from app.platform.service_endpoints import EndpointCheckFailedError

        with patch(
            "app.modules.catalog.sources.router.run_service_preview",
            new_callable=AsyncMock,
            side_effect=EndpointCheckFailedError(
                "httpx.ConnectError: raw provider text"
            ),
        ):
            resp = await client.post(
                "/services/preview/",
                json={
                    "url": "https://example.com/wfs",
                    "service_type": "WFS 2.0.0",
                    "layer_name": "buildings",
                    "auth": {"method": "basic", "username": "u", "password": "p"},
                },
                headers=admin_auth_header,
            )
            assert resp.status_code == 422, resp.text
            detail = resp.json()["detail"]
            assert detail["code"] == "endpoint_check_failed"
            # `.reason` (the raw httpx text) never reaches the body.
            assert "raw provider text" not in resp.text

    async def test_preview_item_fetch_failed_returns_422(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_validate_ssrf,
        mock_build_gdal_source,
    ):
        """An OGC API items page that could not be read is a 422, not a 500.

        `ItemFetchFailedError` subclasses `EndpointCheckFailedError`
        (`platform/service_items.py`), so it matches the same `isinstance`
        branch — this test pins that the subclass relationship is what the
        mapping relies on, not a duplicated class list.
        """
        from app.platform.service_items import ItemFetchFailedError

        with patch(
            "app.modules.catalog.sources.router.run_service_preview",
            new_callable=AsyncMock,
            side_effect=ItemFetchFailedError("items link leaves the origin"),
        ):
            resp = await client.post(
                "/services/preview/",
                json={
                    "url": "https://example.com/collections/x",
                    "service_type": "OGC API Features",
                    "layer_name": "x",
                    "auth": {"method": "basic", "username": "u", "password": "p"},
                },
                headers=admin_auth_header,
            )
            assert resp.status_code == 422, resp.text
            assert resp.json()["detail"]["code"] == "endpoint_check_failed"

    async def test_preview_ssrf_error_mid_preview_returns_400(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_validate_ssrf,
        mock_build_gdal_source,
    ):
        """An SSRF refusal raised INSIDE run_service_preview (a redirect hop,
        not the door's pre-flight `validate_url_for_ssrf`) is a 400, and never
        echoes a redirect-chosen hostname (`SSRFResolutionError`'s own text).
        """
        with patch(
            "app.modules.catalog.sources.router.run_service_preview",
            new_callable=AsyncMock,
            side_effect=SSRFResolutionError(
                "Could not resolve hostname: internal-only.example.com (10.0.0.5)"
            ),
        ):
            resp = await client.post(
                "/services/preview/",
                json={
                    "url": "https://example.com/wfs",
                    "service_type": "WFS 2.0.0",
                    "layer_name": "buildings",
                },
                headers=admin_auth_header,
            )
            assert resp.status_code == 400, resp.text
            assert "10.0.0.5" not in resp.text
            assert "internal-only.example.com" not in resp.text

    async def test_preview_href_too_long_returns_422(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_validate_ssrf,
        mock_build_gdal_source,
    ):
        """An over-length service-advertised href is a 422, not a 500."""
        from app.platform.service_endpoints import HrefTooLongError

        with patch(
            "app.modules.catalog.sources.router.run_service_preview",
            new_callable=AsyncMock,
            side_effect=HrefTooLongError("next href exceeds 8192 bytes"),
        ):
            resp = await client.post(
                "/services/preview/",
                json={
                    "url": "https://example.com/wfs",
                    "service_type": "WFS 2.0.0",
                    "layer_name": "buildings",
                },
                headers=admin_auth_header,
            )
            assert resp.status_code == 422, resp.text

    async def test_preview_credential_header_value_error_returns_400(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_validate_ssrf,
        mock_build_gdal_source,
    ):
        """A plain ValueError from build_credential_header is a 400, not a 500."""
        with patch(
            "app.modules.catalog.sources.router.run_service_preview",
            new_callable=AsyncMock,
            side_effect=ValueError("unsupported credential method"),
        ):
            resp = await client.post(
                "/services/preview/",
                json={
                    "url": "https://example.com/wfs",
                    "service_type": "WFS 2.0.0",
                    "layer_name": "buildings",
                },
                headers=admin_auth_header,
            )
            assert resp.status_code == 400, resp.text

    async def test_preview_creates_ingest_job(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_validate_ssrf,
        mock_build_gdal_source,
        mock_run_preview,
    ):
        """POST /services/preview/ creates an IngestJob and returns its ID."""
        resp = await client.post(
            "/services/preview/",
            json={
                "url": "https://example.com/wfs",
                "service_type": "WFS 2.0.0",
                "layer_name": "buildings",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        # job_id should be a valid UUID
        job_uuid = uuid.UUID(data["job_id"])
        assert job_uuid is not None

    async def test_preview_editor_allowed(
        self,
        client: AsyncClient,
        editor_auth_header: dict,
        mock_validate_ssrf,
        mock_build_gdal_source,
        mock_run_preview,
    ):
        """POST /services/preview/ as editor returns 200."""
        resp = await client.post(
            "/services/preview/",
            json={
                "url": "https://example.com/wfs",
                "service_type": "WFS 2.0.0",
                "layer_name": "buildings",
            },
            headers=editor_auth_header,
        )
        assert resp.status_code == 200

    async def test_preview_arcgis_without_layer_id(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_validate_ssrf,
    ):
        """POST /services/preview/ for ArcGIS without layer_id returns 400."""
        with patch(
            "app.modules.catalog.sources.router.build_gdal_source",
            side_effect=ValueError("ArcGIS layer preview requires a layer ID"),
        ):
            resp = await client.post(
                "/services/preview/",
                json={
                    "url": "https://example.com/arcgis/rest/services/MyService/FeatureServer",
                    "service_type": "ArcGIS FeatureServer",
                    "layer_name": "buildings",
                },
                headers=admin_auth_header,
            )
            assert resp.status_code == 400
            assert "layer ID" in resp.json()["detail"]

    async def test_preview_arcgis_uses_metadata_path(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_validate_ssrf,
        mock_fetch_arcgis_preview,
    ):
        """ArcGIS preview goes through fetch_arcgis_layer_preview, not ogrinfo.

        Regression for the large-FeatureServer hang: GDAL's ESRIJSON driver
        ignores resultRecordCount and paginates the whole layer (millions of
        rows) → ogrinfo times out → empty preview. The metadata path returns
        fields + CRS from ?f=json in one fast call.
        """
        with patch(
            "app.modules.catalog.sources.router.run_service_preview",
            new_callable=AsyncMock,
        ) as run_preview:
            resp = await client.post(
                "/services/preview/",
                json={
                    "url": "https://services.arcgis.com/abc/rest/services/Big/FeatureServer",
                    "service_type": "ArcGIS FeatureServer",
                    "layer_name": "0",
                    "layer_id": 0,
                },
                headers=admin_auth_header,
            )
        assert resp.status_code == 200, resp.text
        # ogrinfo must NOT be invoked for ArcGIS layers.
        run_preview.assert_not_called()
        mock_fetch_arcgis_preview.assert_awaited_once()
        data = resp.json()
        assert data["crs"] == 4326
        assert data["geometry_type"] == "Point"
        assert len(data["columns"]) == 2
        assert data["columns"][0]["name"] == "OBJECTID"
        assert len(data["sample_rows"]) == 2
        # ArcGIS responses surface attributes (not GeoJSON properties).
        assert data["sample_rows"][0]["title"] == "Bulletin A"

    async def test_preview_arcgis_ssrf_is_not_an_ogrinfo_failure(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_validate_ssrf,
        test_db_session,
    ):
        """fix(#1858 audit P2-1, `sources/router.py` ArcGIS preview branch).

        `fetch_arcgis_layer_preview`'s metadata read has no local `except`, so
        an `SSRFError` from the redirect revalidation hook or the guard
        transport reached the branch's `except (..., ValueError, ...)` tuple
        and became `_fail_preview`'s 502 `ogrinfo_failed` -- naming a tool
        that never ran. The WFS and OGC API branches of the SAME door answer
        that event as a 400 with the fixed policy string, so one event was
        classified two ways depending on which adapter met it, and an
        operator grepping for blocked-redirect events saw neither.
        """
        redirect_host = "sec6-preview-redirect-target.invalid"
        preview_url = (
            "https://sec6-preview-ssrf.example.com/arcgis/rest/services/X/FeatureServer"
        )

        async def _refuse(*_args, **_kwargs):
            raise SSRFResolutionError(f"Could not resolve hostname: {redirect_host}")

        with patch(
            "app.modules.catalog.sources.adapters.arcgis.bounded_probe_read",
            new=_refuse,
        ):
            resp = await client.post(
                "/services/preview/",
                json={
                    "url": preview_url,
                    "service_type": "ArcGIS FeatureServer",
                    "layer_name": "0",
                    "layer_id": 0,
                },
                headers=admin_auth_header,
            )

        assert resp.status_code == 400, resp.text
        assert resp.json()["detail"] == "redirect target refused by SSRF policy"
        assert redirect_host not in resp.text

        rows = await _preview_audit_rows(test_db_session, preview_url)
        assert [row.details["result"] for row in rows] == ["refused"]
        assert rows[0].details["reason_class"] == "SSRFResolutionError"
        assert redirect_host not in json.dumps(rows[0].details)

    async def test_preview_wfs_ssrf_answers_the_same_way(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_validate_ssrf,
        mock_build_gdal_source,
        test_db_session,
    ):
        """The other half of the door, pinned beside it.

        Without this the test above could pass for a door that had started
        answering 400 for everything. Both branches now reach one helper, so
        the status, the message and the audit row are identical.
        """
        redirect_host = "sec6-wfs-redirect-target.invalid"
        preview_url = "https://sec6-preview-wfs.example.com/wfs"

        with patch(
            "app.modules.catalog.sources.router.run_service_preview",
            new_callable=AsyncMock,
            side_effect=SSRFResolutionError(
                f"Could not resolve hostname: {redirect_host}"
            ),
        ):
            resp = await client.post(
                "/services/preview/",
                json={
                    "url": preview_url,
                    "service_type": "WFS 2.0.0",
                    "layer_name": "buildings",
                },
                headers=admin_auth_header,
            )

        assert resp.status_code == 400, resp.text
        assert resp.json()["detail"] == "redirect target refused by SSRF policy"
        assert redirect_host not in resp.text

        rows = await _preview_audit_rows(test_db_session, preview_url)
        assert [row.details["result"] for row in rows] == ["refused"]
        assert rows[0].details["reason_class"] == "SSRFResolutionError"

    async def test_preview_arcgis_json_depth_bomb_is_coded_not_a_crash(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_validate_ssrf,
        test_db_session,
    ):
        """fix(#1858, backend audit 2026-09-04 P2-2).

        `read_arcgis_json` parsed the layer metadata document with a bare
        `json.loads`. A balanced nesting 300,000 deep is a ~600 KB body, so it
        clears every byte and structural-token bound the read applies, and
        `json.loads` answers `RecursionError` -- a `RuntimeError`, caught by
        neither this door's except chain nor the adapter's. The preview
        answered 500 and wrote no audit row, contradicting the handler
        docstring's promise that every attempt is audit-logged.
        """
        bomb = b"[" * 300_000 + b"]" * 300_000
        preview_url = (
            "https://sec6-bomb.example.com/arcgis/rest/services/X/FeatureServer"
        )

        async def _bomb_read(_client, url, **_kwargs):
            return bomb, url

        with patch(
            "app.modules.catalog.sources.adapters.arcgis.bounded_probe_read",
            new=_bomb_read,
        ):
            resp = await client.post(
                "/services/preview/",
                json={
                    "url": preview_url,
                    "service_type": "ArcGIS FeatureServer",
                    "layer_name": "0",
                    "layer_id": 0,
                },
                headers=admin_auth_header,
            )

        assert resp.status_code == 502, resp.text
        rows = await _preview_audit_rows(test_db_session, preview_url)
        assert [row.details["result"] for row in rows] == ["ogrinfo_failed"]

    async def test_preview_arcgis_persists_normalized_layer(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_validate_ssrf,
        mock_fetch_arcgis_preview,
    ):
        """An embedded-layer ArcGIS URL (.../FeatureServer/0) with no explicit
        layer_id must persist the NORMALIZED base URL + effective layer id on
        the pending job, so the commit/ingest step targets the right layer
        instead of rebuilding ".../FeatureServer/0/0/query" or a None layer
        (Codex P2 regression).
        """
        import uuid as _uuid
        from types import SimpleNamespace

        with patch(
            "app.modules.catalog.sources.router._create_preview_job",
            new_callable=AsyncMock,
        ) as create_job:
            create_job.return_value = SimpleNamespace(id=_uuid.uuid4())
            resp = await client.post(
                "/services/preview/",
                json={
                    "url": "https://services.arcgis.com/abc/rest/services/Embedded/FeatureServer/0",
                    "service_type": "ArcGIS FeatureServer",
                    "layer_name": "0",
                },
                headers=admin_auth_header,
            )
        assert resp.status_code == 200, resp.text
        create_job.assert_awaited_once()
        kwargs = create_job.await_args.kwargs
        assert (
            kwargs["source_url"]
            == "https://services.arcgis.com/abc/rest/services/Embedded/FeatureServer"
        )
        assert kwargs["layer_id"] == 0

    async def test_preview_arcgis_token_error_returns_403(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_validate_ssrf,
    ):
        """ArcGIS token error during metadata fetch surfaces as 403."""
        from app.modules.catalog.sources.adapters.arcgis import ArcGISTokenError

        with patch(
            "app.modules.catalog.sources.router.fetch_arcgis_layer_preview",
            new_callable=AsyncMock,
            side_effect=ArcGISTokenError(499, "Token Required"),
        ):
            resp = await client.post(
                "/services/preview/",
                json={
                    "url": "https://services.arcgis.com/abc/rest/services/Sec/FeatureServer",
                    "service_type": "ArcGIS FeatureServer",
                    "layer_name": "0",
                    "layer_id": 0,
                },
                headers=admin_auth_header,
            )
        assert resp.status_code == 403
        assert "authentication" in resp.json()["detail"].lower()

    async def test_preview_ogcapi_uri_form_crs_fallback(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_validate_ssrf,
        mock_build_gdal_source,
    ):
        """OGC API preview with no srid falls back to collection-metadata URI-form CRS.

        Regression for SMOKE-v1013-F2: ogrinfo on an OGC API collection often
        returns no coordinateSystem (GeoJSON features assume CRS84), but the
        collection metadata exposes ``crs: ["http://www.opengis.net/def/crs/OGC/1.3/CRS84"]``.
        Preview should parse that URI to EPSG:4326 rather than returning
        ``crs: null`` (which forces user to enter a manual CRS Override).
        """

        async def preview_returns_no_srid(*args, **kwargs):
            return {
                "srid": None,  # ogrinfo could not detect CRS
                "geometry_type": "Polygon",
                "layer_name": "lakes",
                "feature_count": 25,
                "columns": [{"name": "name", "type": "String"}],
                "sample_rows": [{"name": "Lake Baikal"}],
            }

        # Mock the OGC API collection metadata response with URI-form CRS84.
        #
        # fix(#1770 round 44): `_fetch_ogcapi_collection_srid` reads through
        # `bounded_probe_read` (round 43 P1), which calls `client.stream(...)`
        # rather than `client.get(...)`. A bare `MagicMock` for the client and
        # a `MagicMock` response (this test's shape before round 43) supports
        # neither the async-context-manager protocol `.stream()` returns nor a
        # real streaming read, so this is now a real `httpx.AsyncClient` over
        # `httpx.MockTransport`, with the response body served from a
        # generator so `aiter_raw()` can actually stream it rather than
        # raising `StreamConsumed` on an already-read double (see
        # `_as_stream`'s docstring in `test_service_auth_transport_1746.py`
        # for the same fix applied there in round 41).
        collection_body = httpx.Response(
            200,
            json={
                "id": "lakes",
                "crs": ["http://www.opengis.net/def/crs/OGC/1.3/CRS84"],
            },
        ).content

        def _handle_collection_request(request: httpx.Request) -> httpx.Response:
            async def _chunks():
                yield collection_body

            return httpx.Response(200, content=_chunks())

        mock_client = httpx.AsyncClient(
            transport=httpx.MockTransport(_handle_collection_request)
        )

        with (
            patch(
                "app.modules.catalog.sources.router.run_service_preview",
                new_callable=AsyncMock,
                side_effect=preview_returns_no_srid,
            ),
            patch(
                "app.modules.catalog.sources.router.httpx.AsyncClient",
                return_value=mock_client,
            ),
        ):
            resp = await client.post(
                "/services/preview/",
                json={
                    "url": "https://demo.pygeoapi.io/master/",
                    "service_type": "OGC API Features",
                    "layer_name": "lakes",
                },
                headers=admin_auth_header,
            )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        # Without the fallback this would be None; with the fix it's 4326.
        assert data["crs"] == 4326, (
            "OGC API preview should resolve URI-form CRS84 to EPSG:4326 via "
            "collection metadata when ogrinfo returns no coordinateSystem"
        )

    async def test_preview_wfs_namespace_retry(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_validate_ssrf,
        mock_build_gdal_source,
    ):
        """POST /services/preview/ retries with unqualified name on WFS namespace failure."""
        from app.processing.ingest.ogr import IngestionError

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise IngestionError("Layer not found")
            return {
                "srid": 4326,
                "geometry_type": "Point",
                "layer_name": "buildings",
                "feature_count": 50,
                "columns": [{"name": "id", "type": "Integer"}],
                "sample_rows": [{"id": 1}],
            }

        with patch(
            "app.modules.catalog.sources.router.run_service_preview",
            new_callable=AsyncMock,
            side_effect=side_effect,
        ):
            resp = await client.post(
                "/services/preview/",
                json={
                    "url": "https://example.com/wfs",
                    "service_type": "WFS 2.0.0",
                    "layer_name": "ns:buildings",
                },
                headers=admin_auth_header,
            )
            assert resp.status_code == 200
            assert call_count == 2


# ---------------------------------------------------------------------------
# SSRF validation unit tests (validate_url_for_ssrf)
# ---------------------------------------------------------------------------


class TestSSRFValidation:
    """Direct tests of the SSRF validation function."""

    @pytest.mark.asyncio
    async def test_ssrf_rejects_private_ip(self):
        """Private IPs (10.x, 172.16.x, 192.168.x) are blocked."""
        from app.platform.security import validate_url_for_ssrf

        for url in [
            "http://10.0.0.1/wfs",
            "http://172.16.0.1/wfs",
            "http://192.168.1.1/wfs",
        ]:
            with pytest.raises(SSRFError):
                await validate_url_for_ssrf(url)

    @pytest.mark.asyncio
    async def test_ssrf_rejects_localhost(self):
        """Localhost and 127.x addresses are blocked."""
        from app.platform.security import validate_url_for_ssrf

        with pytest.raises(SSRFError):
            await validate_url_for_ssrf("http://127.0.0.1/wfs")

    @pytest.mark.asyncio
    async def test_ssrf_rejects_bad_scheme(self):
        """Non-http(s) schemes are blocked."""
        from app.platform.security import validate_url_for_ssrf

        for url in ["ftp://example.com/data", "file:///etc/passwd"]:
            with pytest.raises(SSRFError):
                await validate_url_for_ssrf(url)

    @pytest.mark.asyncio
    async def test_ssrf_rejects_no_hostname(self):
        """URLs without a hostname are blocked."""
        from app.platform.security import validate_url_for_ssrf

        with pytest.raises(SSRFError):
            await validate_url_for_ssrf("http:///path")


# ---------------------------------------------------------------------------
# Duplicate source detection tests (260408-iny)
# ---------------------------------------------------------------------------


_ARCGIS_BASE = "https://services6.arcgis.com/EbVsqZ18sv1kVJ3k/arcgis/rest/services/TestService/FeatureServer"
_ARCGIS_LAYER_0_URL = f"{_ARCGIS_BASE}/0"
_ARCGIS_LAYER_1_URL = f"{_ARCGIS_BASE}/1"


async def _create_arcgis_dataset(
    session,
    *,
    created_by,
    source_url,
    name="Test ArcGIS Dataset",
    origin_uri=None,
    origin_ref=None,
):
    """Insert a Dataset simulating a previously registered ArcGIS FeatureServer layer.

    ``origin_uri``/``origin_ref`` default to unset, which is the shape of a
    row migration 0036 could not backfill (the un-backfilled fallback case);
    callers that want to simulate a fully-bound (post-#1218) dataset pass
    both explicitly.
    """
    import uuid as _uuid
    from app.modules.catalog.datasets.domain.models import Dataset, Record

    table_name = f"ds_{_uuid.uuid4().hex[:12]}"
    record = Record(
        title=name,
        summary="ArcGIS table test",
        visibility="public",
        record_status="published",
        created_by=created_by,
        record_type="table",
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=None,
        geometry_type=None,
        feature_count=29,
        source_format="arcgis_featureserver",
        source_filename="TestService",
        source_url=source_url,
        origin_uri=origin_uri,
        origin_ref=origin_ref,
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


@pytest.mark.anyio
class TestDuplicateSourceDetection:
    """Tests for 409 Conflict on duplicate ArcGIS service registration."""

    async def test_preview_rejects_duplicate_arcgis(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        mock_validate_ssrf,
        mock_build_gdal_source,
        mock_run_preview,
    ):
        """POST /services/preview/ with same source_url+format+user returns 409.

        fix(#1286): also the un-backfilled-row regression test for the
        origin_ref re-key — the dataset below carries neither ``origin_uri``
        nor ``origin_ref`` (a row migration 0036 could not backfill), so the
        guard can only catch it through the ``source_url`` fallback branch.
        """
        from tests.factories import get_user_id

        admin_id = await get_user_id(test_db_session, "admin")

        # Create an existing dataset with the same source URL (layer 0)
        await _create_arcgis_dataset(
            test_db_session,
            created_by=admin_id,
            source_url=_ARCGIS_LAYER_0_URL,
            name="Existing Bulletin Table",
        )

        resp = await client.post(
            "/services/preview/",
            json={
                "url": _ARCGIS_BASE,
                "service_type": "ArcGIS:FeatureServer",
                "layer_name": "0",
                "layer_id": 0,
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 409
        body = resp.json()
        assert body["detail"]["code"] == "duplicate_source"
        assert "existing_dataset_id" in body["detail"]
        assert "existing_title" in body["detail"]
        assert body["detail"]["existing_title"] == "Existing Bulletin Table"

    async def test_preview_allows_different_layer_same_service(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        mock_validate_ssrf,
        mock_build_gdal_source,
        mock_run_preview,
        mock_fetch_arcgis_preview,
    ):
        """POST /services/preview/ for FeatureServer/1 when /0 exists should NOT return 409."""
        from tests.factories import get_user_id

        admin_id = await get_user_id(test_db_session, "admin")

        # Create existing dataset for layer 0
        await _create_arcgis_dataset(
            test_db_session,
            created_by=admin_id,
            source_url=_ARCGIS_LAYER_0_URL,
            name="Layer 0 Dataset",
        )

        # Preview layer 1 — different layer, should not 409
        resp = await client.post(
            "/services/preview/",
            json={
                "url": _ARCGIS_BASE,
                "service_type": "ArcGIS:FeatureServer",
                "layer_name": "1",
                "layer_id": 1,
            },
            headers=admin_auth_header,
        )
        # Must not be 409; may be 200 (mocked preview) or another error
        assert resp.status_code != 409

    async def test_preview_allows_same_url_different_user(
        self,
        client: AsyncClient,
        editor_auth_header: dict,
        test_db_session,
        mock_validate_ssrf,
        mock_build_gdal_source,
        mock_run_preview,
        mock_fetch_arcgis_preview,
    ):
        """POST /services/preview/ as different user for same URL should NOT return 409.

        Dedup key includes created_by — different user can register same source.
        """
        from tests.factories import get_user_id

        admin_id = await get_user_id(test_db_session, "admin")

        # Existing dataset owned by admin for layer 0
        await _create_arcgis_dataset(
            test_db_session,
            created_by=admin_id,
            source_url=_ARCGIS_LAYER_0_URL,
            name="Admin Layer 0",
        )

        # Editor registers the same URL — should NOT 409
        resp = await client.post(
            "/services/preview/",
            json={
                "url": _ARCGIS_BASE,
                "service_type": "ArcGIS:FeatureServer",
                "layer_name": "0",
                "layer_id": 0,
            },
            headers=editor_auth_header,
        )
        assert resp.status_code != 409

    async def test_an_edited_source_url_does_not_get_past_the_guard(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        mock_validate_ssrf,
        mock_build_gdal_source,
        mock_run_preview,
        mock_fetch_arcgis_preview,
    ):
        """fix(#1286): the guard keys on ``origin_ref``, not ``origin_uri``.

        ``source_url`` is reachable through the metadata PATCH, so keying the
        guard on it alone let an owner edit their way past it and register the
        same layer a second time. ``origin_ref`` appears in no field map and
        only ingest/refresh write it, which is what makes it the honest key.
        The preceding tests keep the ``source_url`` fallback honest for rows
        migration 0036 could not backfill.
        """
        from tests.factories import get_user_id

        # Its own service, because the worker's database is shared across the
        # whole session and the sibling tests above register _ARCGIS_BASE —
        # a `.limit(1)` match against a URL two tests use proves nothing about
        # which row the guard found.
        base = f"{_ARCGIS_BASE.replace('TestService', 'EditedUrlService')}"
        admin_id = await get_user_id(test_db_session, "admin")
        existing = await _create_arcgis_dataset(
            test_db_session,
            created_by=admin_id,
            source_url=f"{base}/0",
            name="Bulletin Table",
            origin_uri=f"{base}/0",
            origin_ref={
                "kind": "service",
                "service_type": "arcgis_featureserver",
                "url": base,
                "layer_id": "0",
            },
        )
        existing.source_url = "https://example.invalid/edited-by-the-owner"
        await test_db_session.commit()

        resp = await client.post(
            "/services/preview/",
            json={
                "url": base,
                "service_type": "ArcGIS:FeatureServer",
                "layer_name": "0",
                "layer_id": 0,
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "duplicate_source"
        assert resp.json()["detail"]["existing_dataset_id"] == str(existing.id)

    async def test_a_true_cross_dataset_duplicate_still_conflicts(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        mock_validate_ssrf,
        mock_build_gdal_source,
        mock_run_preview,
        mock_fetch_arcgis_preview,
    ):
        """The re-key must not turn the guard off.

        #1220 makes a dataset refreshable from its own origin, which is a
        different door entirely — the refresh endpoint never consults this
        query. Importing somebody's already-registered layer as a SECOND
        dataset is still the thing the guard exists to refuse, and the message
        now points at refresh rather than at deleting the existing dataset.
        """
        from tests.factories import get_user_id

        base = f"{_ARCGIS_BASE.replace('TestService', 'CrossDatasetService')}"
        admin_id = await get_user_id(test_db_session, "admin")
        await _create_arcgis_dataset(
            test_db_session,
            created_by=admin_id,
            source_url=f"{base}/0",
            name="Already Imported",
        )

        resp = await client.post(
            "/services/preview/",
            json={
                "url": base,
                "service_type": "ArcGIS:FeatureServer",
                "layer_name": "0",
                "layer_id": 0,
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 409
        message = resp.json()["detail"]["message"]
        assert "refresh that dataset" in message
        assert "delete the existing dataset" not in message

    async def test_preview_catches_a_never_refreshed_dataset_bound_via_origin_ref(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        mock_validate_ssrf,
        mock_build_gdal_source,
        mock_run_preview,
        mock_fetch_arcgis_preview,
    ):
        """fix(#1286): a fully-bound, never-refreshed dataset is still caught.

        ``origin_uri`` and ``origin_ref`` agree (the ordinary post-#1218
        shape — no writer has touched the binding since import), so the
        primary origin_ref-keyed branch must match on its own, with no help
        from the source_url fallback.
        """
        from tests.factories import get_user_id

        base = f"{_ARCGIS_BASE.replace('TestService', 'NeverRefreshedService')}"
        admin_id = await get_user_id(test_db_session, "admin")
        await _create_arcgis_dataset(
            test_db_session,
            created_by=admin_id,
            source_url=f"{base}/0",
            name="Never Refreshed",
            origin_uri=f"{base}/0",
            origin_ref={
                "kind": "service",
                "service_type": "arcgis_featureserver",
                "url": base,
                "layer_id": "0",
            },
        )

        resp = await client.post(
            "/services/preview/",
            json={
                "url": base,
                "service_type": "ArcGIS:FeatureServer",
                "layer_name": "0",
                "layer_id": 0,
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "duplicate_source"

    async def test_preview_catches_a_respelled_origin_uri(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        mock_validate_ssrf,
        mock_build_gdal_source,
        mock_run_preview,
        mock_fetch_arcgis_preview,
    ):
        """fix(#1286): a respelled origin_uri can no longer open the hole.

        Reproduces the PR #1277 round-11 class of bug: a writer (e.g. a
        refresh) rewrites ``origin_uri`` to a different spelling of the same
        origin — here a bare base URL instead of ``base_url/layer_id`` —
        while ``origin_ref`` still names the identical (service_type, url,
        layer_id) triple. An ``origin_uri``-keyed guard stops matching this
        row; the origin_ref-keyed guard must not, because the canonical
        identity never changed.
        """
        from tests.factories import get_user_id

        base = f"{_ARCGIS_BASE.replace('TestService', 'RespelledUriService')}"
        admin_id = await get_user_id(test_db_session, "admin")
        await _create_arcgis_dataset(
            test_db_session,
            created_by=admin_id,
            source_url=f"{base}/0",
            name="Respelled Pointer",
            # The respelling: origin_uri drifted to the bare base URL, with
            # no /0 layer suffix, even though this row is still layer 0.
            origin_uri=base,
            origin_ref={
                "kind": "service",
                "service_type": "arcgis_featureserver",
                "url": base,
                "layer_id": "0",
            },
        )

        resp = await client.post(
            "/services/preview/",
            json={
                "url": base,
                "service_type": "ArcGIS:FeatureServer",
                "layer_name": "0",
                "layer_id": 0,
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "duplicate_source"

    async def test_preview_catches_a_partially_backfilled_dataset(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        mock_validate_ssrf,
        mock_build_gdal_source,
        mock_run_preview,
        mock_fetch_arcgis_preview,
    ):
        """fix(#1286 codex review, PR #1320): an incomplete origin_ref still
        falls through to the source_url fallback.

        Migration 0036's service backfill can populate ``origin_uri`` from
        the legacy enriched ``source_url`` while leaving ``origin_ref``
        without ``url``/``layer_id`` — a WFS/OGC row with no surviving
        ingest job to recover the typename from. Gating the fallback on
        ``origin_uri IS NULL`` alone would miss this row entirely: it is
        matched by neither the (incomplete) structured identity nor an
        origin_uri-null fallback. The fallback keys off an incomplete
        structured identity instead.
        """
        from tests.factories import get_user_id

        base = f"{_ARCGIS_BASE.replace('TestService', 'PartiallyBackfilledService')}"
        admin_id = await get_user_id(test_db_session, "admin")
        await _create_arcgis_dataset(
            test_db_session,
            created_by=admin_id,
            source_url=f"{base}/0",
            name="Partially Backfilled Row",
            origin_uri=f"{base}/0",
            # Migration 0036's degraded shape: kind + service_type only, no
            # url or layer_id — jsonb_strip_nulls dropped both because no
            # surviving ingest job could supply the base/typename.
            origin_ref={"kind": "service", "service_type": "arcgis_featureserver"},
        )

        resp = await client.post(
            "/services/preview/",
            json={
                "url": base,
                "service_type": "ArcGIS:FeatureServer",
                "layer_name": "0",
                "layer_id": 0,
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "duplicate_source"
