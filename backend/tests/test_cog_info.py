"""fetch_cog_info's georeferencing extraction (#1334).

Titiler's ``/cog/info`` reply already carries ``crs`` (an OGC CRS URI) and
``bounds`` (in the dataset's OWN projection, not WGS84) alongside
width/height — enough to derive ``crs_wkt``/``res_x``/``res_y``, which
nothing downstream ever read out of it before this fix. Every other test in
this codebase that touches ``fetch_cog_info`` stubs the function wholesale
(see ``test_stac_refresh_1266.py``'s ``cog_info`` fixture and
``test_stac_import.py``), which would never catch a regression in the
extraction itself — these are unit tests of that extraction, against
Titiler's actual response shape (captured live against a 2.2.1 instance,
see ``cog_info.py``'s ``_georeferencing`` docstring for the exact payload).
"""

from __future__ import annotations

import httpx
import pytest

from app.modules.catalog.sources.cog_info import fetch_cog_info

pytestmark = pytest.mark.anyio

# Captured before any monkeypatching so the factory below can build a real
# client: it replaces the module's `httpx.AsyncClient` attribute, so a
# factory that referenced `httpx.AsyncClient` itself would recurse into its
# own replacement.
_RealAsyncClient = httpx.AsyncClient

# A Titiler 2.2.1 /cog/info reply, captured live against a real COG: `crs` is
# an OGC CRS URI, and `bounds` is in the dataset's OWN projection (UTM 21N
# metres here) — the magnitude alone rules out WGS84 degrees.
_TITILER_INFO = {
    "bounds": [373185.0, 8019284.949381611, 639014.9492102272, 8286015.0],
    "crs": "http://www.opengis.net/def/crs/EPSG/0/32621",
    "band_metadata": [["b1", {}]],
    "band_descriptions": [["b1", "b1"]],
    "dtype": "uint16",
    "nodata_type": "None",
    "colorinterp": ["gray"],
    "scales": [1.0],
    "offsets": [0.0],
    "driver": "GTiff",
    "count": 1,
    "width": 2658,
    "height": 2667,
    "overviews": [2, 4, 8, 16],
}


def _install(monkeypatch, info: dict, *, stats_status: int = 200) -> None:
    """Route both COG-endpoint requests fetch_cog_info makes to one table.

    fetch_cog_info builds its own ``httpx.AsyncClient`` directly rather than
    through a factory seam (Titiler is an internal trusted service, not a
    caller-controlled origin), so the client class itself is the thing to
    replace.
    """

    def _handler(request: httpx.Request) -> httpx.Response:
        if "/cog/statistics" in str(request.url):
            return httpx.Response(
                stats_status, json={} if stats_status == 200 else None
            )
        return httpx.Response(200, json=info)

    def _factory(*args, **kwargs) -> httpx.AsyncClient:
        kwargs.pop("timeout", None)
        return _RealAsyncClient(transport=httpx.MockTransport(_handler))

    monkeypatch.setattr(
        "app.modules.catalog.sources.cog_info.httpx.AsyncClient", _factory
    )


class TestGeoreferencing:
    async def test_crs_wkt_and_resolution_come_from_titilers_own_reply(
        self, monkeypatch
    ) -> None:
        """fix(#1334): the values were retrievable all along — this shows
        fetch_cog_info actually reading them out, not just Titiler having
        sent them."""
        _install(monkeypatch, _TITILER_INFO)
        result = await fetch_cog_info("https://origin.test/scene.tif")
        assert result is not None
        assert result["crs_wkt"] is not None
        assert "32621" in result["crs_wkt"]
        # (639014.9492102272 - 373185.0) / 2658
        assert result["res_x"] == pytest.approx(100.0, rel=1e-3)
        # (8286015.0 - 8019284.949381611) / 2667
        assert result["res_y"] == pytest.approx(100.011, rel=1e-3)

    async def test_a_missing_crs_degrades_to_none_not_a_raise(
        self, monkeypatch
    ) -> None:
        info = {**_TITILER_INFO, "crs": None}
        _install(monkeypatch, info)
        result = await fetch_cog_info("https://origin.test/scene.tif")
        assert result is not None
        assert result["crs_wkt"] is None
        # bounds/width/height are untouched by the missing crs — the two
        # fields fail independently.
        assert result["res_x"] == pytest.approx(100.0, rel=1e-3)

    async def test_an_unparseable_crs_degrades_to_none_not_a_raise(
        self, monkeypatch
    ) -> None:
        info = {**_TITILER_INFO, "crs": "not a crs identifier"}
        _install(monkeypatch, info)
        result = await fetch_cog_info("https://origin.test/scene.tif")
        assert result is not None
        assert result["crs_wkt"] is None

    @pytest.mark.parametrize(
        "override",
        [
            {"bounds": None},
            {"bounds": [1.0, 2.0, 3.0]},
            {"bounds": [1.0, 2.0, "x", 4.0]},
            {"width": 0},
            {"height": 0},
            {"width": None},
        ],
    )
    async def test_unusable_bounds_or_dimensions_degrade_to_none(
        self, monkeypatch, override: dict
    ) -> None:
        info = {**_TITILER_INFO, **override}
        _install(monkeypatch, info)
        result = await fetch_cog_info("https://origin.test/scene.tif")
        assert result is not None
        assert result["res_x"] is None
        assert result["res_y"] is None
