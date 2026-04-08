"""Integration tests for services probe and preview endpoints.

Tests cover: probe success/failure, preview success/failure, SSRF validation,
auth requirements, and error handling for various external service responses.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import AsyncClient

from app.services.probe import ServiceNotRecognized
from app.services.schemas import LayerInfo, ProbeResponse
from app.services.security import SSRFError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_validate_ssrf():
    """Patch SSRF validation to allow all URLs by default."""
    with patch("app.services.router.validate_url_for_ssrf") as mock:
        yield mock


@pytest.fixture
def mock_detect_service():
    """Patch detect_service_type to return a canned WFS response."""
    with patch(
        "app.services.router.detect_service_type", new_callable=AsyncMock
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
    with patch("app.services.router.build_gdal_source") as mock:
        mock.return_value = ("WFS:https://example.com/wfs", "buildings")
        yield mock


@pytest.fixture
def mock_run_preview():
    """Patch run_service_preview to return canned preview data."""
    with patch(
        "app.services.router.run_service_preview", new_callable=AsyncMock
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
            "app.services.router.validate_url_for_ssrf",
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
            "app.services.router.validate_url_for_ssrf",
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

    async def test_probe_timeout(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_validate_ssrf,
    ):
        """POST /services/probe/ that times out returns 504."""
        with patch(
            "app.services.router.detect_service_type",
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
            "app.services.router.detect_service_type",
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
            "app.services.router.detect_service_type",
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
            "app.services.router.detect_service_type",
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
        """POST /services/probe/ with unrecognized service returns 422."""
        with patch(
            "app.services.router.detect_service_type",
            new_callable=AsyncMock,
            side_effect=ServiceNotRecognized(),
        ):
            resp = await client.post(
                "/services/probe/",
                json={"url": "https://not-a-service.example.com/"},
                headers=admin_auth_header,
            )
            assert resp.status_code == 422

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
            "app.services.router.validate_url_for_ssrf",
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
            "app.services.router.build_gdal_source",
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
        from app.ingest.ogr import IngestionError

        with patch(
            "app.services.router.run_service_preview",
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
            "app.services.router.run_service_preview",
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
            "app.services.router.build_gdal_source",
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

    async def test_preview_wfs_namespace_retry(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_validate_ssrf,
        mock_build_gdal_source,
    ):
        """POST /services/preview/ retries with unqualified name on WFS namespace failure."""
        from app.ingest.ogr import IngestionError

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
            "app.services.router.run_service_preview",
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

    def test_ssrf_rejects_private_ip(self):
        """Private IPs (10.x, 172.16.x, 192.168.x) are blocked."""
        from app.services.security import validate_url_for_ssrf

        for url in [
            "http://10.0.0.1/wfs",
            "http://172.16.0.1/wfs",
            "http://192.168.1.1/wfs",
        ]:
            with pytest.raises(SSRFError):
                validate_url_for_ssrf(url)

    def test_ssrf_rejects_localhost(self):
        """Localhost and 127.x addresses are blocked."""
        from app.services.security import validate_url_for_ssrf

        with pytest.raises(SSRFError):
            validate_url_for_ssrf("http://127.0.0.1/wfs")

    def test_ssrf_rejects_bad_scheme(self):
        """Non-http(s) schemes are blocked."""
        from app.services.security import validate_url_for_ssrf

        for url in ["ftp://example.com/data", "file:///etc/passwd"]:
            with pytest.raises(SSRFError):
                validate_url_for_ssrf(url)

    def test_ssrf_rejects_no_hostname(self):
        """URLs without a hostname are blocked."""
        from app.services.security import validate_url_for_ssrf

        with pytest.raises(SSRFError):
            validate_url_for_ssrf("http:///path")


# ---------------------------------------------------------------------------
# Duplicate source detection tests (260408-iny)
# ---------------------------------------------------------------------------


_ARCGIS_BASE = "https://services6.arcgis.com/EbVsqZ18sv1kVJ3k/arcgis/rest/services/TestService/FeatureServer"
_ARCGIS_LAYER_0_URL = f"{_ARCGIS_BASE}/0"
_ARCGIS_LAYER_1_URL = f"{_ARCGIS_BASE}/1"


async def _create_arcgis_dataset(session, *, created_by, source_url, name="Test ArcGIS Dataset"):
    """Insert a Dataset simulating a previously registered ArcGIS FeatureServer layer."""
    import uuid as _uuid
    from app.datasets.models import Dataset, Record

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
        """POST /services/preview/ with same source_url+format+user returns 409."""
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
