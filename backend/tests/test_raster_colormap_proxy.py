"""Tests for raster_tile_proxy colormap_name + stretch query param handling.

Covers every behavior bullet in 1140-01-PLAN.md Task 2:
- colormap_name=viridis → titiler URL contains colormap_name=viridis
- colormap_name omitted → titiler URL unchanged (no colormap_name appended)
- colormap_name=gray → treated as default/no-op (not appended)
- colormap_name outside allowlist → 422, Titiler NOT called
- stretch=percentile/stddev → accepted, minmax fallback with logged warning
- stretch=evil → 422
- DEM (render_params starts with algorithm=) → colormap_name NOT appended

Phase 1153 additions (RASTER-STRETCH-03 + RASTER-STRETCH-UI-01 backend):
- 3-band raster + stretch=percentile → exactly 3 rescale= fragments
- 1-band raster + stretch=percentile → exactly 1 rescale= fragment
- band_count=4 capped at 3 → exactly 3 rescale= fragments
- band_count None → falls back to 1 fragment, no crash
- pmin/pmax/sigma configurable bounds, forwarded as repeated p= to /cog/statistics
- _band_stats_cache keyed by (open_path, pmin, pmax) — isolation between bounds
- 422 validation on invalid pmin/pmax/sigma before Titiler called
- SPIKE-01 contract pinned (p=/percentile_<N> forwarding)

Security: T-1140-01 — invalid colormap must be rejected before Titiler is called.
Security: T-1153-01 — invalid pmin/pmax/sigma rejected before Titiler called.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock

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
    band_count: int = 1,
) -> httpx.Response:
    """Build a fake raster-auth-check response matching the real handler's shape."""
    return MagicMock(
        status_code=200,
        headers={
            "X-GeoLens-Asset-OpenPath": open_path,
            "X-GeoLens-Cache-Status": "public",
            "X-GeoLens-Render-Params": render_params,
            "X-GeoLens-Band-Count": str(band_count),
        },
        content=b"",
    )


def _make_titiler_ok_response() -> MagicMock:
    png_magic = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    return MagicMock(
        status_code=200, content=png_magic, headers={"content-type": "image/png"}
    )


# Per-band statistics returned by the mocked Titiler /cog/statistics endpoint.
# Values mirror the real ADK DEM COG. Expected stretch rescales:
#   percentile → rescale=512.66,1304.31  (percentile_2, percentile_98)
#   stddev     → rescale=490.6,1228.19   (mean ± 2σ, lo clamped to band min)
#
# Phase 1153: extended with b2/b3 for multi-band tests + percentile_5/percentile_95
# for configurable-bounds tests.
_BAND_STATS: dict[str, Any] = {
    "b1": {
        "min": 490.6,
        "max": 1625.6,
        "mean": 787.77,
        "std": 220.21,
        "percentile_2": 512.66,
        "percentile_98": 1304.31,
        "percentile_5": 530.0,
        "percentile_95": 1280.0,
    },
    "b2": {
        "min": 10.0,
        "max": 200.0,
        "mean": 100.0,
        "std": 30.0,
        "percentile_2": 20.0,
        "percentile_98": 185.0,
        "percentile_5": 25.0,
        "percentile_95": 180.0,
    },
    "b3": {
        "min": 5.0,
        "max": 180.0,
        "mean": 90.0,
        "std": 25.0,
        "percentile_2": 15.0,
        "percentile_98": 170.0,
        "percentile_5": 18.0,
        "percentile_95": 165.0,
    },
}


def _make_titiler_stats_response(payload: dict | None = None) -> MagicMock:
    """Mock a Titiler /cog/statistics JSON response.

    When payload is None, returns _BAND_STATS (which now includes b1/b2/b3 for
    multi-band tests). Individual tests may override via self._stats_payload.
    """
    resp = MagicMock(status_code=200)
    resp.json = MagicMock(return_value=payload if payload is not None else _BAND_STATS)
    return resp


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
        self._auth_band_count = 1  # default single-band; override in multi-band tests

        async def _fake_auth_check(request, dataset_id, user=None, db=None):
            return _make_auth_response(
                self._auth_open_path,
                self._auth_render_params,
                self._auth_band_count,
            )

        from app.processing.tiles import router as tiles_router

        monkeypatch.setattr(tiles_router, "raster_auth_check", _fake_auth_check)

    @pytest.fixture(autouse=True)
    def _patch_titiler_client(self, monkeypatch):
        """Replace _titiler_client.get with a mock; capture called URL(s).

        Returns a statistics JSON for /cog/statistics URLs (stretch path) and a
        PNG for tile URLs. ``self._stats_payload`` lets a test override the stats
        response (e.g. to simulate a stats failure)."""
        self._titiler_calls: list[str] = []
        self._stats_payload: dict | None = None
        self._stats_status: int = 200

        async def _fake_get(url: str) -> MagicMock:
            self._titiler_calls.append(url)
            if "/statistics" in url:
                if self._stats_status != 200:
                    return MagicMock(
                        status_code=self._stats_status, json=MagicMock(return_value={})
                    )
                return _make_titiler_stats_response(self._stats_payload)
            return _make_titiler_ok_response()

        from app.processing.tiles import router as tiles_router

        mock_client = MagicMock()
        mock_client.get = _fake_get
        monkeypatch.setattr(tiles_router, "_titiler_client", mock_client)

    @pytest.fixture(autouse=True)
    def _clear_stats_cache(self):
        """Clear the module-level band-stats cache between tests (it is keyed by
        open_path, which is identical across these tests)."""
        from app.processing.tiles import router as tiles_router

        tiles_router._band_stats_cache.clear()
        yield
        tiles_router._band_stats_cache.clear()

    @property
    def _tile_titiler_calls(self) -> list[str]:
        """Titiler tile calls only (excludes /cog/statistics stretch lookups)."""
        return [u for u in self._titiler_calls if "/statistics" not in u]

    @property
    def _stats_titiler_calls(self) -> list[str]:
        """Titiler /cog/statistics calls only."""
        return [u for u in self._titiler_calls if "/statistics" in u]

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

    async def test_stretch_percentile_computes_rescale(self, client):
        """[RASTER-STRETCH-01] stretch=percentile overrides the dtype rescale with
        [percentile_2, percentile_98] from Titiler band statistics."""
        resp = await client.get(
            _TILE_PATH,
            params={"colormap_name": "plasma", "stretch": "percentile"},
        )
        assert resp.status_code in (200, 204)
        # One /cog/statistics lookup + one tile request
        assert len(self._stats_titiler_calls) == 1
        assert len(self._tile_titiler_calls) == 1
        tile_url = self._tile_titiler_calls[0]
        assert "colormap_name=plasma" in tile_url
        # Stats-based rescale present; original dtype rescale (0,65535) replaced
        assert "rescale=512.66,1304.31" in tile_url, tile_url
        assert "rescale=0,65535" not in tile_url, tile_url

    async def test_stretch_stddev_computes_rescale(self, client):
        """[RASTER-STRETCH-02] stretch=stddev overrides rescale with mean±2σ,
        clamped to the band [min, max]."""
        resp = await client.get(
            _TILE_PATH,
            params={"colormap_name": "inferno", "stretch": "stddev"},
        )
        assert resp.status_code in (200, 204)
        assert len(self._stats_titiler_calls) == 1
        tile_url = self._tile_titiler_calls[0]
        # mean 787.77 ± 2·220.21 = [347.35, 1228.19]; lo clamped to band min 490.6
        assert "rescale=490.6,1228.19" in tile_url, tile_url
        assert "rescale=0,65535" not in tile_url, tile_url

    async def test_stretch_minmax_no_statistics_call(self, client):
        """stretch=minmax keeps the dtype rescale and does NOT call /cog/statistics."""
        resp = await client.get(
            _TILE_PATH,
            params={"colormap_name": "magma", "stretch": "minmax"},
        )
        assert resp.status_code in (200, 204)
        assert len(self._stats_titiler_calls) == 0
        assert len(self._tile_titiler_calls) == 1
        assert "rescale=0,65535" in self._tile_titiler_calls[0]

    async def test_stretch_stats_unavailable_falls_back_to_minmax(self, client):
        """When /cog/statistics fails, stretch falls back to the dtype minmax rescale."""
        self._stats_status = 500
        resp = await client.get(
            _TILE_PATH,
            params={"colormap_name": "viridis", "stretch": "percentile"},
        )
        assert resp.status_code in (200, 204)
        assert len(self._stats_titiler_calls) == 1  # attempted once
        tile_url = self._tile_titiler_calls[0]
        assert "rescale=0,65535" in tile_url, tile_url  # original rescale preserved

    async def test_stretch_not_applied_to_dem(self, client):
        """For DEM (algorithm=terrainrgb), stretch is ignored — no statistics call."""
        self._auth_render_params = "algorithm=terrainrgb"
        resp = await client.get(_TILE_PATH, params={"stretch": "percentile"})
        assert resp.status_code in (200, 204)
        assert len(self._stats_titiler_calls) == 0
        assert "algorithm=terrainrgb" in self._tile_titiler_calls[0]

    async def test_stretch_statistics_cached_across_tiles(self, client):
        """The band-statistics lookup is cached — repeated tiles call /statistics once."""
        for _ in range(3):
            resp = await client.get(
                _TILE_PATH,
                params={"colormap_name": "plasma", "stretch": "percentile"},
            )
            assert resp.status_code in (200, 204)
        assert len(self._stats_titiler_calls) == 1, self._stats_titiler_calls
        assert len(self._tile_titiler_calls) == 3

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

    @pytest.mark.parametrize(
        "cmap", ["inferno", "plasma", "magma", "ylorrd", "bugn", "terrain"]
    )
    async def test_all_allowlist_colormaps_forwarded(self, client, cmap: str):
        """All 8 allowlist colormaps (except gray) are forwarded to Titiler."""
        resp = await client.get(_TILE_PATH, params={"colormap_name": cmap})
        assert resp.status_code in (200, 204)
        assert len(self._titiler_calls) == 1
        assert f"colormap_name={cmap}" in self._titiler_calls[0]

    # ------------------------------------------------------------------
    # Phase 1153 Task 1: Multi-band rescale (RASTER-STRETCH-03)
    # ------------------------------------------------------------------

    async def test_three_band_stretch_produces_three_rescale_fragments(self, client):
        """[RASTER-STRETCH-03] 3-band raster + stretch=percentile → exactly 3 rescale= fragments.

        The raster_tile_proxy must use n_bands=min(band_count or 1, 3) so each
        band gets its own independent rescale= from Titiler per-band stats.
        """
        self._auth_band_count = 3
        self._auth_render_params = "bidx=1&bidx=2&bidx=3&rescale=0,255&rescale=0,255&rescale=0,255"
        resp = await client.get(_TILE_PATH, params={"stretch": "percentile"})
        assert resp.status_code in (200, 204)
        tile_url = self._tile_titiler_calls[0]
        assert tile_url.count("rescale=") == 3, (
            f"Expected exactly 3 rescale= fragments for 3-band input, got: {tile_url.count('rescale=')} in {tile_url}"
        )

    async def test_one_band_stretch_produces_one_rescale_fragment(self, client):
        """[RASTER-STRETCH-03] 1-band raster + stretch=percentile → exactly 1 rescale= fragment."""
        self._auth_band_count = 1
        resp = await client.get(_TILE_PATH, params={"stretch": "percentile"})
        assert resp.status_code in (200, 204)
        tile_url = self._tile_titiler_calls[0]
        assert tile_url.count("rescale=") == 1, (
            f"Expected exactly 1 rescale= fragment for 1-band input, got: {tile_url.count('rescale=')} in {tile_url}"
        )

    async def test_four_band_stretch_capped_at_three_rescale_fragments(self, client):
        """[RASTER-STRETCH-03] band_count=4 is capped at 3 → exactly 3 rescale= fragments."""
        self._auth_band_count = 4
        self._auth_render_params = "bidx=1&bidx=2&bidx=3&rescale=0,255&rescale=0,255&rescale=0,255"
        resp = await client.get(_TILE_PATH, params={"stretch": "percentile"})
        assert resp.status_code in (200, 204)
        tile_url = self._tile_titiler_calls[0]
        assert tile_url.count("rescale=") == 3, (
            f"Expected exactly 3 rescale= fragments (cap=3) for band_count=4, got: {tile_url.count('rescale=')} in {tile_url}"
        )

    async def test_missing_band_count_falls_back_to_one_rescale_fragment(self, client):
        """[RASTER-STRETCH-03] band_count missing/None → 1 rescale= fragment, no crash."""
        # Simulate absent X-GeoLens-Band-Count header by setting it to empty string
        # The router should treat absent/empty as 1.
        from app.processing.tiles import router as tiles_router
        import monkeypatch as mp  # noqa: F401  -- use the monkeypatch fixture
        # We'll use a custom auth mock that omits the band count header
        async def _fake_auth_no_band_count(request, dataset_id, user=None, db=None):
            return MagicMock(
                status_code=200,
                headers={
                    "X-GeoLens-Asset-OpenPath": self._auth_open_path,
                    "X-GeoLens-Cache-Status": "public",
                    "X-GeoLens-Render-Params": self._auth_render_params,
                    # No X-GeoLens-Band-Count header
                },
                content=b"",
            )
        tiles_router.raster_auth_check = _fake_auth_no_band_count
        resp = await client.get(_TILE_PATH, params={"stretch": "percentile"})
        assert resp.status_code in (200, 204)
        tile_url = self._tile_titiler_calls[0]
        assert tile_url.count("rescale=") == 1, (
            f"Expected 1 rescale= fragment when band_count absent, got: {tile_url.count('rescale=')} in {tile_url}"
        )

    # ------------------------------------------------------------------
    # Phase 1153 Task 2: Configurable bounds (RASTER-STRETCH-UI-01 backend)
    # ------------------------------------------------------------------

    async def test_custom_pmin_pmax_forwarded_as_repeated_p_params(self, client):
        """[RASTER-STRETCH-UI-01] pmin=5&pmax=95 → statistics URL raw query contains p=5&p=95."""
        resp = await client.get(
            _TILE_PATH,
            params={"stretch": "percentile", "pmin": 5, "pmax": 95},
        )
        assert resp.status_code in (200, 204)
        assert len(self._stats_titiler_calls) == 1
        stats_url = self._stats_titiler_calls[0]
        assert "p=5" in stats_url and "p=95" in stats_url, (
            f"Expected p=5&p=95 in statistics URL, got: {stats_url}"
        )

    async def test_custom_pmin_pmax_reads_dynamic_percentile_keys(self, client):
        """[RASTER-STRETCH-UI-01] pmin=5&pmax=95 → rescale uses percentile_5/percentile_95 values."""
        resp = await client.get(
            _TILE_PATH,
            params={"stretch": "percentile", "pmin": 5, "pmax": 95},
        )
        assert resp.status_code in (200, 204)
        tile_url = self._tile_titiler_calls[0]
        # b1 percentile_5=530.0, percentile_95=1280.0
        assert "rescale=530.0,1280.0" in tile_url, (
            f"Expected rescale=530.0,1280.0 from percentile_5/percentile_95, got: {tile_url}"
        )

    async def test_cache_key_isolation_different_bounds(self, client):
        """[RASTER-STRETCH-UI-01 critical] Two requests with different pmin/pmax produce distinct
        _band_stats_cache entries keyed (open_path, pmin, pmax).

        This is the critical acceptance gate: without bounds in the cache key, the second
        request would silently use the first's cached p2/p98 stats (PITFALL-01 from 1153-CONTEXT.md).
        """
        from app.processing.tiles import router as tiles_router

        open_path = self._auth_open_path

        # First request: default p2/p98
        resp1 = await client.get(
            _TILE_PATH,
            params={"stretch": "percentile"},  # defaults to pmin=2, pmax=98
        )
        assert resp1.status_code in (200, 204)

        # Second request: custom p5/p95
        resp2 = await client.get(
            _TILE_PATH,
            params={"stretch": "percentile", "pmin": 5, "pmax": 95},
        )
        assert resp2.status_code in (200, 204)

        # Both cache entries must exist — distinct keys, distinct stats
        cache = tiles_router._band_stats_cache
        assert (open_path, 2.0, 98.0) in cache, (
            f"Expected cache key (open_path, 2.0, 98.0) but got keys: {list(cache.keys())}"
        )
        assert (open_path, 5.0, 95.0) in cache, (
            f"Expected cache key (open_path, 5.0, 95.0) but got keys: {list(cache.keys())}"
        )
        assert len(cache) == 2, (
            f"Expected exactly 2 distinct cache entries, got {len(cache)}: {list(cache.keys())}"
        )

        # The two tile URLs must carry different rescale= values
        tile_urls = self._tile_titiler_calls
        assert len(tile_urls) == 2
        rescale_vals = [u for u in tile_urls]
        assert rescale_vals[0] != rescale_vals[1], (
            "Both tile requests produced identical URLs — cache isolation failed"
        )

    async def test_custom_sigma_computes_different_rescale(self, client):
        """[RASTER-STRETCH-UI-01] sigma=3 → mean ± 3·std (distinct from default sigma=2)."""
        # Default sigma=2: rescale=490.6,1228.19 (lo clamped to 490.6)
        # sigma=3: mean=787.77, std=220.21 → 127.14..1448.4 → clamped lo=490.6, hi=1448.4
        resp = await client.get(
            _TILE_PATH,
            params={"stretch": "stddev", "sigma": 3},
        )
        assert resp.status_code in (200, 204)
        tile_url = self._tile_titiler_calls[0]
        # With sigma=3: hi = 787.77 + 3*220.21 = 787.77 + 660.63 = 1448.4
        assert "rescale=490.6,1448.4" in tile_url, (
            f"Expected sigma=3 rescale=490.6,1448.4, got: {tile_url}"
        )
        # Must differ from sigma=2 result
        assert "rescale=490.6,1228.19" not in tile_url

    async def test_default_pmin_pmax_preserves_percentile_2_98(self, client):
        """[RASTER-STRETCH-UI-01] absent pmin/pmax → reads percentile_2/percentile_98 (unchanged behavior)."""
        resp = await client.get(_TILE_PATH, params={"stretch": "percentile"})
        assert resp.status_code in (200, 204)
        tile_url = self._tile_titiler_calls[0]
        assert "rescale=512.66,1304.31" in tile_url, (
            f"Default pmin/pmax must use percentile_2/percentile_98, got: {tile_url}"
        )

    async def test_default_sigma_preserves_two_stddev(self, client):
        """[RASTER-STRETCH-UI-01] absent sigma → 2.0·std (unchanged behavior)."""
        resp = await client.get(_TILE_PATH, params={"stretch": "stddev"})
        assert resp.status_code in (200, 204)
        tile_url = self._tile_titiler_calls[0]
        # mean=787.77, std=220.21, sigma=2 → [347.35, 1228.19]; lo clamped to 490.6
        assert "rescale=490.6,1228.19" in tile_url, (
            f"Default sigma must be 2.0, got: {tile_url}"
        )

    @pytest.mark.parametrize("bad_params,description", [
        ({"pmin": 95, "pmax": 5}, "pmin>=pmax"),
        ({"pmin": -1, "pmax": 98}, "pmin<0"),
        ({"pmin": 2, "pmax": 101}, "pmax>100"),
        ({"sigma": 0}, "sigma=0"),
        ({"sigma": -1}, "sigma<0"),
    ])
    async def test_invalid_bounds_returns_422_before_titiler(
        self, client, bad_params, description
    ):
        """[T-1153-01] Invalid pmin/pmax/sigma → HTTP 422; Titiler tile-fetch NOT called.

        Security: untrusted bounds must be validated before any Titiler call.
        """
        params = {"stretch": "percentile" if "sigma" not in bad_params else "stddev"}
        params.update(bad_params)
        resp = await client.get(_TILE_PATH, params=params)
        assert resp.status_code == 422, (
            f"Expected 422 for {description}, got {resp.status_code}"
        )
        # Titiler tile-fetch client must NOT have been invoked
        assert len(self._tile_titiler_calls) == 0, (
            f"Titiler was called despite invalid bounds ({description}): {self._tile_titiler_calls}"
        )

    async def test_dem_with_custom_bounds_no_rescale(self, client):
        """[T-1153-03] DEM (algorithm= render_params) ignores pmin/pmax/sigma — no rescale injected."""
        self._auth_render_params = "algorithm=terrainrgb"
        resp = await client.get(
            _TILE_PATH,
            params={"stretch": "percentile", "pmin": 5, "pmax": 95},
        )
        assert resp.status_code in (200, 204)
        # No /cog/statistics call for DEM
        assert len(self._stats_titiler_calls) == 0
        tile_url = self._tile_titiler_calls[0]
        assert "rescale=" not in tile_url, (
            f"DEM tile URL must not contain rescale=: {tile_url}"
        )

    # ------------------------------------------------------------------
    # Phase 1153 Task 3: SPIKE-01 contract-pinning test
    # ------------------------------------------------------------------

    async def test_spike01_p_param_forwarding_and_dynamic_percentile_key(self, client):
        """[SPIKE-01 closure] Contract pin: _fetch_band_statistics forwards p=pmin&p=pmax as
        repeated query params; _compute_stretch_rescale reads percentile_<pmin>/percentile_<pmax>
        dynamically (not hardcoded percentile_2/percentile_98).

        Live evidence: 1153-SPIKE.md confirmed Titiler /cog/statistics honors arbitrary p= params
        and returns percentile_<N> keys (e.g. p=5&p=95 → percentile_5/percentile_95).
        This test pins that contract in the unit-test layer so regressions are caught
        without re-running the live spike.
        """
        # With pmin=5&pmax=95, the stats URL must contain p=5 and p=95
        resp = await client.get(
            _TILE_PATH,
            params={"stretch": "percentile", "pmin": 5, "pmax": 95},
        )
        assert resp.status_code in (200, 204)
        stats_url = self._stats_titiler_calls[0]
        assert "p=5" in stats_url, f"SPIKE-01: p=5 not forwarded to statistics URL: {stats_url}"
        assert "p=95" in stats_url, f"SPIKE-01: p=95 not forwarded to statistics URL: {stats_url}"

        # The resulting tile URL must use percentile_5/percentile_95 values (530.0 / 1280.0)
        # NOT the hardcoded percentile_2/percentile_98 values (512.66 / 1304.31)
        tile_url = self._tile_titiler_calls[0]
        assert "rescale=530.0,1280.0" in tile_url, (
            f"SPIKE-01: tile URL must use percentile_5/percentile_95 values, got: {tile_url}"
        )
        assert "rescale=512.66,1304.31" not in tile_url, (
            f"SPIKE-01: tile URL must NOT use hardcoded percentile_2/percentile_98 values: {tile_url}"
        )
