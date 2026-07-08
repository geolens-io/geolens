"""Regression tests for SEC-021: service-preview GDAL bearer-token handling.

run_service_preview passed the auth token verbatim into GDAL_HTTP_HEADERS (the
subprocess env), leaking the bearer via /proc/<pid>/environ and allowing CRLF
header injection through the libcurl pipeline — the exact issue the ogr2ogr
commit path already fixed (SEC-FU-04 / IA-P1-06). This mirrors that fix: a
base64url-sanitized token written to a 0600 GDAL_HTTP_HEADER_FILE, plus an
API-boundary field validator that rejects control/whitespace tokens.
"""

import json
import os
import stat

import pytest
from pydantic import ValidationError

from app.modules.catalog.sources.schemas import ProbeRequest, ServicePreviewRequest


def _base_kwargs(model) -> dict:
    """Minimal VALID fields per model (everything except the token under test),
    so a ValidationError can only originate from the token validator."""
    if model is ServicePreviewRequest:
        return {
            "url": "https://example.com/wfs",
            "service_type": "WFS 2.0.0",
            "layer_name": "layer",
        }
    return {"url": "https://example.com/wfs"}


@pytest.mark.parametrize("model", [ProbeRequest, ServicePreviewRequest])
def test_token_with_crlf_rejected(model):
    """A CRLF-bearing token (the header-injection payload) is rejected at the
    schema boundary. Fails on main — no token validator existed, so a valid
    request with a CRLF token was accepted."""
    with pytest.raises(ValidationError):
        model(**_base_kwargs(model), token="abc\r\nX-Injected: evil")


@pytest.mark.parametrize("model", [ProbeRequest, ServicePreviewRequest])
def test_token_with_control_char_rejected(model):
    with pytest.raises(ValidationError):
        model(**_base_kwargs(model), token="abc\x00def")


@pytest.mark.parametrize("model", [ProbeRequest, ServicePreviewRequest])
def test_normal_token_accepted(model):
    m = model(**_base_kwargs(model), token="eyJhbGciOi.JIUzI1NiIs.in9-_=")
    assert m.token == "eyJhbGciOi.JIUzI1NiIs.in9-_="


@pytest.mark.parametrize("model", [ProbeRequest, ServicePreviewRequest])
def test_none_token_accepted(model):
    m = model(**_base_kwargs(model), token=None)
    assert m.token is None


@pytest.mark.anyio
async def test_preview_passes_bearer_via_header_file_not_env(monkeypatch, client):
    """The WFS/OAPIF bearer must travel through a 0600 GDAL_HTTP_HEADER_FILE,
    never GDAL_HTTP_HEADERS (env). Fails on main (token placed in env)."""
    import asyncio as aio

    from app.modules.catalog.sources import preview as preview_mod

    captured: dict = {}

    class _FakeProc:
        returncode = 0

        async def communicate(self):
            return (
                json.dumps(
                    {
                        "layers": [
                            {
                                "name": "l",
                                "fields": [],
                                "features": [],
                                "geometryFields": [],
                            }
                        ]
                    }
                ).encode(),
                b"",
            )

    async def _fake_exec(*cmd, **kwargs):
        env = kwargs.get("env") or {}
        captured["env"] = dict(env)
        hf = env.get("GDAL_HTTP_HEADER_FILE")
        if hf and os.path.exists(hf):
            captured["mode"] = stat.S_IMODE(os.stat(hf).st_mode)
            with open(hf) as f:
                captured["content"] = f.read()
        return _FakeProc()

    monkeypatch.setattr(aio, "create_subprocess_exec", _fake_exec)

    token = "averylongbearertoken1234567890"
    await preview_mod.run_service_preview(
        "WFS:https://example.com/wfs", "layer", token=token
    )

    env = captured["env"]
    assert "GDAL_HTTP_HEADERS" not in env, (
        "SEC-021: bearer token must not be passed via the GDAL_HTTP_HEADERS env var"
    )
    assert env.get("GDAL_HTTP_FOLLOWLOCATION") == "NO"
    assert "GDAL_HTTP_HEADER_FILE" in env, "expected the 0600 header-file pattern"
    assert captured.get("mode") == 0o600
    assert f"Authorization: Bearer {token}" in captured.get("content", "")


@pytest.mark.anyio
async def test_preview_timeout_raises_not_empty(monkeypatch):
    """An ogrinfo timeout must RAISE IngestionError, not return empty_fallback.

    Regression: a timeout previously returned a zero-column preview that the
    router treated as success, leaving the UI showing a spinner then no
    attributes. A timeout is a real failure → surface a 502 error toast.
    """
    import asyncio as aio

    from app.modules.catalog.sources import preview as preview_mod

    class _HangingProc:
        returncode = None

        async def communicate(self):
            await aio.sleep(10)  # longer than the test timeout below
            return (b"", b"")

        def kill(self):
            pass

        async def wait(self):
            return 0

    async def _fake_exec(*cmd, **kwargs):
        return _HangingProc()

    monkeypatch.setattr(aio, "create_subprocess_exec", _fake_exec)

    with pytest.raises(preview_mod.IngestionError):
        await preview_mod.run_service_preview(
            "WFS:https://example.com/wfs", "layer", timeout=0.05
        )


@pytest.mark.anyio
async def test_fetch_arcgis_layer_preview_maps_fields_crs_and_attributes():
    """fetch_arcgis_layer_preview reads ?f=json metadata + a bounded sample.

    Verifies ESRI field types map to OGR names, CRS prefers latestWkid, and
    the sample query reads ``attributes`` (ArcGIS) not ``properties``.
    """
    from unittest.mock import AsyncMock, MagicMock

    from app.modules.catalog.sources.adapters.arcgis import fetch_arcgis_layer_preview

    meta = {
        "name": "Parcels",
        "geometryType": "esriGeometryPolygon",
        "extent": {"spatialReference": {"wkid": 102100, "latestWkid": 3857}},
        "fields": [
            {"name": "OBJECTID", "type": "esriFieldTypeOID"},
            {"name": "owner", "type": "esriFieldTypeString"},
            {"name": "value", "type": "esriFieldTypeDouble"},
            {"name": "Shape", "type": "esriFieldTypeGeometry"},
        ],
    }
    sample = {
        "features": [
            {"attributes": {"OBJECTID": 1, "owner": "Smith", "value": 100.0}},
            {"attributes": {"OBJECTID": 2, "owner": "Jones", "value": 200.0}},
        ]
    }

    meta_resp = MagicMock()
    meta_resp.raise_for_status = MagicMock()
    meta_resp.json = MagicMock(return_value=meta)
    sample_resp = MagicMock()
    sample_resp.raise_for_status = MagicMock()
    sample_resp.json = MagicMock(return_value=sample)

    client = MagicMock()
    client.get = AsyncMock(side_effect=[meta_resp, sample_resp])

    result = await fetch_arcgis_layer_preview(
        "https://services.arcgis.com/x/rest/services/Parcels/FeatureServer",
        0,
        client,
    )

    assert result["srid"] == 3857  # latestWkid wins over wkid
    assert result["geometry_type"] == "Polygon"
    assert result["layer_name"] == "Parcels"
    assert result["feature_count"] is None
    # Geometry field is skipped; OID→Integer64, String→String, Double→Real.
    cols = {c["name"]: c["type"] for c in result["columns"]}
    assert cols == {"OBJECTID": "Integer64", "owner": "String", "value": "Real"}
    assert len(result["sample_rows"]) == 2
    assert result["sample_rows"][0]["owner"] == "Smith"
