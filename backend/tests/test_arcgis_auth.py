"""Tests for ArcGIS auth fixes: no Bearer header, JSON error detection, objectIdField."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.modules.catalog.sources.adapters.arcgis import (
    ArcGISTokenError,
    probe_arcgis_service,
)
from app.modules.catalog.sources.preview import build_gdal_source


def _make_mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    """Create a mock httpx.Response with the given JSON data."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    resp.request = MagicMock(spec=httpx.Request)
    return resp


@pytest.mark.asyncio
async def test_arcgis_probe_no_bearer_header():
    """Verify the ArcGIS probe sends token only as query param, not as Authorization header."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_response = _make_mock_response(
        {
            "layers": [{"id": 0, "name": "test", "geometryType": "esriGeometryPoint"}],
        }
    )
    mock_client.get.return_value = mock_response

    await probe_arcgis_service(
        "https://services.arcgis.com/svc/FeatureServer", mock_client, token="mytoken"
    )

    # The URL should include the token as a query parameter
    call_args = mock_client.get.call_args
    url_called = call_args[0][0]
    assert "token=mytoken" in url_called

    # No Authorization header should have been passed to client.get
    kwargs = call_args[1] if call_args[1] else {}
    headers = kwargs.get("headers", {})
    assert "Authorization" not in headers


@pytest.mark.asyncio
async def test_arcgis_error_498_raises():
    """ArcGIS JSON error with code 498 (invalid token) should raise ArcGISTokenError."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_response = _make_mock_response(
        {
            "error": {"code": 498, "message": "Invalid token."},
        }
    )
    mock_client.get.return_value = mock_response

    with pytest.raises(ArcGISTokenError, match="498"):
        await probe_arcgis_service(
            "https://services.arcgis.com/svc/FeatureServer",
            mock_client,
            token="badtoken",
        )


@pytest.mark.asyncio
async def test_arcgis_error_499_raises():
    """ArcGIS JSON error with code 499 (token required) should raise ArcGISTokenError."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_response = _make_mock_response(
        {
            "error": {"code": 499, "message": "Token required."},
        }
    )
    mock_client.get.return_value = mock_response

    with pytest.raises(ArcGISTokenError, match="499"):
        await probe_arcgis_service(
            "https://services.arcgis.com/svc/FeatureServer", mock_client
        )


@pytest.mark.asyncio
async def test_arcgis_object_id_field_extraction():
    """objectIdField should be read from layer metadata, falling back to service level then OBJECTID."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)

    # Layer-level objectIdField takes priority
    mock_response = _make_mock_response(
        {
            "objectIdField": "SERVICE_OID",
            "layers": [
                {
                    "id": 0,
                    "name": "layer_with_oid",
                    "geometryType": "esriGeometryPoint",
                    "objectIdField": "FID",
                },
                {
                    "id": 1,
                    "name": "layer_without_oid",
                    "geometryType": "esriGeometryPolygon",
                },
            ],
        }
    )
    mock_client.get.return_value = mock_response

    result = await probe_arcgis_service(
        "https://services.arcgis.com/svc/FeatureServer", mock_client
    )
    assert result is not None
    layers = result["layers"]

    # Layer 0 has its own objectIdField
    assert layers[0]["object_id_field"] == "FID"
    # Layer 1 falls back to service-level objectIdField
    assert layers[1]["object_id_field"] == "SERVICE_OID"


@pytest.mark.asyncio
async def test_arcgis_object_id_field_default():
    """When no objectIdField in metadata, default to OBJECTID."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_response = _make_mock_response(
        {
            "layers": [
                {"id": 0, "name": "no_oid", "geometryType": "esriGeometryPoint"},
            ],
        }
    )
    mock_client.get.return_value = mock_response

    result = await probe_arcgis_service(
        "https://services.arcgis.com/svc/FeatureServer", mock_client
    )
    assert result is not None
    assert result["layers"][0]["object_id_field"] == "OBJECTID"


def test_build_gdal_source_custom_oid():
    """build_gdal_source should use the custom OID field in orderByFields."""
    source, layer_name = build_gdal_source(
        "ArcGIS FeatureServer",
        "https://services.arcgis.com/svc/FeatureServer",
        "my_layer",
        layer_id=0,
        order_field="FID",
    )
    assert "orderByFields=FID+ASC" in source
    assert "orderByFields=OBJECTID" not in source


def test_build_gdal_source_default_oid():
    """build_gdal_source defaults to OBJECTID when order_field not specified."""
    source, _ = build_gdal_source(
        "ArcGIS FeatureServer",
        "https://services.arcgis.com/svc/FeatureServer",
        "my_layer",
        layer_id=0,
    )
    assert "orderByFields=OBJECTID+ASC" in source
