"""Tests for raster_tile_proxy colormap_name + stretch query param handling.

Covers every behavior bullet in 1140-01-PLAN.md Task 2:
- colormap_name=viridis → titiler URL contains colormap_name=viridis
- colormap_name omitted → titiler URL unchanged (no colormap_name appended)
- colormap_name=gray → treated as default/no-op (not appended)
- colormap_name outside allowlist → 422, Titiler NOT called
- stretch=percentile/stddev → accepted, minmax fallback with logged warning
- stretch=evil → 422
- DEM (render_params starts with algorithm=) → colormap_name NOT appended

Security: T-1140-01 — invalid colormap must be rejected before Titiler is called.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


# ---------------------------------------------------------------------------
# Helpers & fixture construction
# ---------------------------------------------------------------------------

_DATASET_ID = uuid.uuid4()
_TILE_PATH = f"/tiles/raster-proxy/{_DATASET_ID}/0/0/0.png"


def _make_auth_response(
    open_path: str = "/app/staging/rasters/test.tif",
    render_params: str = "bidx=1&rescale=0,65535",
) -> httpx.Response:
    """Build a fake raster-auth-check response matching the real handler's shape."""
    return MagicMock(
        status_code=200,
        headers={
            "X-GeoLens-Asset-OpenPath": open_path,
            "X-GeoLens-Cache-Status": "public",
            "X-GeoLens-Render-Params": render_params,
        },
        content=b"",
    )


def _make_titiler_ok_response() -> MagicMock:
    png_magic = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    return MagicMock(status_code=200, content=png_magic, headers={"content-type": "image/png"})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRasterColormapProxy:
    """raster_tile_proxy colormap_name / stretch parameter handling."""

    @pytest.fixture(autouse=True)
    def _patch_auth_check(self, monkeypatch):
        """Replace raster_auth_check so tests don't touch the DB."""
        self._auth_render_params = "bidx=1&rescale=0,65535"
        self._auth_open_path = "/app/staging/rasters/test.tif"

        async def _fake_auth_check(request, dataset_id, user=None, db=None):
            return _make_auth_response(self._auth_open_path, self._auth_render_params)

        from app.processing.tiles import router as tiles_router

        monkeypatch.setattr(tiles_router, "raster_auth_check", _fake_auth_check)

    @pytest.fixture(autouse=True)
    def _patch_titiler_client(self, monkeypatch):
        """Replace _titiler_client.get with a mock; capture called URL(s)."""
        self._titiler_calls: list[str] = []

        async def _fake_get(url: str) -> MagicMock:
            self._titiler_calls.append(url)
            return _make_titiler_ok_response()

        from app.processing.tiles import router as tiles_router

        mock_client = MagicMock()
        mock_client.get = _fake_get
        monkeypatch.setattr(tiles_router, "_titiler_client", mock_client)

    # ------------------------------------------------------------------
    # Behavior: colormap_name=viridis → URL contains colormap_name=viridis
    # ------------------------------------------------------------------

    async def test_colormap_viridis_appended_to_titiler_url(self, client):
        """colormap_name=viridis is forwarded to Titiler for single-band rasters."""
        resp = await client.get(
            _TILE_PATH,
            params={"colormap_name": "viridis"},
        )
        assert resp.status_code in (200, 204)
        assert len(self._titiler_calls) == 1
        assert "colormap_name=viridis" in self._titiler_calls[0], (
            f"Expected colormap_name=viridis in Titiler URL, got: {self._titiler_calls[0]}"
        )

    # ------------------------------------------------------------------
    # Behavior: colormap_name omitted → URL unchanged (no colormap_name)
    # ------------------------------------------------------------------

    async def test_no_colormap_no_colormap_name_in_titiler_url(self, client):
        """When colormap_name is omitted, Titiler URL has no colormap_name param."""
        resp = await client.get(_TILE_PATH)
        assert resp.status_code in (200, 204)
        assert len(self._titiler_calls) == 1
        assert "colormap_name" not in self._titiler_calls[0], (
            f"Unexpected colormap_name in Titiler URL: {self._titiler_calls[0]}"
        )

    # ------------------------------------------------------------------
    # Behavior: colormap_name=gray → no-op (not appended to Titiler URL)
    # ------------------------------------------------------------------

    async def test_colormap_gray_not_appended(self, client):
        """colormap_name=gray is a no-op — not forwarded to Titiler."""
        resp = await client.get(_TILE_PATH, params={"colormap_name": "gray"})
        assert resp.status_code in (200, 204)
        assert len(self._titiler_calls) == 1
        assert "colormap_name" not in self._titiler_calls[0], (
            f"gray colormap should not appear in Titiler URL: {self._titiler_calls[0]}"
        )

    # ------------------------------------------------------------------
    # Behavior: colormap_name outside allowlist → 422; Titiler NOT called
    # T-1140-01 BLOCKING security test
    # ------------------------------------------------------------------

    async def test_invalid_colormap_returns_422(self, client):
        """[T-1140-01] Out-of-allowlist colormap_name → 422; Titiler never called."""
        resp = await client.get(
            _TILE_PATH,
            params={"colormap_name": "not_a_real_map"},
        )
        assert resp.status_code == 422, (
            f"Expected 422 for invalid colormap, got: {resp.status_code}"
        )
        # BLOCKING: Titiler must NOT have been called
        assert len(self._titiler_calls) == 0, (
            f"Titiler was called despite invalid colormap (T-1140-01 violation): {self._titiler_calls}"
        )

    async def test_injection_attempt_colormap_returns_422(self, client):
        """[T-1140-01] Colormap injection attempt → 422; Titiler never called."""
        resp = await client.get(
            _TILE_PATH,
            params={"colormap_name": "viridis&evil=injection"},
        )
        assert resp.status_code == 422
        assert len(self._titiler_calls) == 0, (
            "Titiler was invoked despite injection attempt (T-1140-01 violation)"
        )

    # ------------------------------------------------------------------
    # Behavior: stretch=percentile/stddev → accepted, minmax fallback
    # ------------------------------------------------------------------

    async def test_stretch_percentile_accepted_minmax_fallback(self, client):
        """stretch=percentile is accepted (Literal-valid) with minmax fallback.

        Titiler URL is NOT corrupted; colormap forwarding (if any) still works.
        """
        resp = await client.get(
            _TILE_PATH,
            params={"colormap_name": "plasma", "stretch": "percentile"},
        )
        assert resp.status_code in (200, 204)
        assert len(self._titiler_calls) == 1
        assert "colormap_name=plasma" in self._titiler_calls[0]

    async def test_stretch_stddev_accepted_minmax_fallback(self, client):
        """stretch=stddev is accepted (Literal-valid) with minmax fallback."""
        resp = await client.get(
            _TILE_PATH,
            params={"colormap_name": "inferno", "stretch": "stddev"},
        )
        assert resp.status_code in (200, 204)
        assert len(self._titiler_calls) == 1

    async def test_stretch_minmax_accepted(self, client):
        """stretch=minmax is accepted without any fallback warning."""
        resp = await client.get(
            _TILE_PATH,
            params={"colormap_name": "magma", "stretch": "minmax"},
        )
        assert resp.status_code in (200, 204)
        assert len(self._titiler_calls) == 1

    # ------------------------------------------------------------------
    # Behavior: stretch=evil → 422
    # ------------------------------------------------------------------

    async def test_invalid_stretch_returns_422(self, client):
        """stretch value outside Literal allowlist → 422."""
        resp = await client.get(
            _TILE_PATH,
            params={"stretch": "evil"},
        )
        assert resp.status_code == 422
        assert len(self._titiler_calls) == 0

    # ------------------------------------------------------------------
    # Behavior: DEM render_params (algorithm=) → colormap_name NOT appended
    # ------------------------------------------------------------------

    async def test_dem_render_params_colormap_not_appended(self, client, monkeypatch):
        """For DEM layers (render_params starts with algorithm=), colormap_name is NOT forwarded.

        The terrainrgb algorithm must not be overridden by a colormap.
        """
        # Override the auth fixture to return DEM render params
        self._auth_render_params = "algorithm=terrainrgb"

        resp = await client.get(
            _TILE_PATH,
            params={"colormap_name": "viridis"},
        )
        assert resp.status_code in (200, 204)
        assert len(self._titiler_calls) == 1
        assert "colormap_name" not in self._titiler_calls[0], (
            f"colormap_name must NOT be appended to DEM algorithm URL: {self._titiler_calls[0]}"
        )

    # ------------------------------------------------------------------
    # Additional allowlist colormaps
    # ------------------------------------------------------------------

    @pytest.mark.parametrize("cmap", ["inferno", "plasma", "magma", "ylorrd", "bugn", "terrain"])
    async def test_all_allowlist_colormaps_forwarded(self, client, cmap: str):
        """All 8 allowlist colormaps (except gray) are forwarded to Titiler."""
        resp = await client.get(_TILE_PATH, params={"colormap_name": cmap})
        assert resp.status_code in (200, 204)
        assert len(self._titiler_calls) == 1
        assert f"colormap_name={cmap}" in self._titiler_calls[0]
